"""
RAG検索 + LM Studio LLMで回答生成
- コンテキストバジェットシステム (トークン上限を超えないようチャンクを選択)
- BGEクエリプレフィックス対応
- 言語自動検出 → medgemma (英語) / Qwen3.5 (日本語) 切替
- シングルトンローディング (モデル・DB接続の初回のみ読み込み)
- インタラクティブREPLモード対応

Usage:
  python 04_query.py "What are the MRI findings of hepatic hemangioma?"
  python 04_query.py "肝血管腫のMRI所見は？"
  python 04_query.py                      # インタラクティブモード
"""
import sys
import logging
import chromadb
from sentence_transformers import SentenceTransformer
from openai import OpenAI

from config import (
    CHROMA_DIR, COLLECTION_NAME, EMBEDDING_MODEL,
    LM_STUDIO_BASE_URL, LM_STUDIO_API_KEY,
    LM_STUDIO_MODEL_EN, LM_STUDIO_MODEL_JA, LM_STUDIO_MODEL_DEFAULT,
    TOP_K, MAX_CONTEXT_TOKENS, MAX_OUTPUT_TOKENS, TEMPERATURE,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# 文字数でトークン数を近似 (1 token ≈ 4 chars for English)
CHARS_PER_TOKEN = 4

# --- シングルトン ---

_embedding_model = None
_chroma_collection = None
_openai_client = None


def get_embedding_model() -> SentenceTransformer:
    global _embedding_model
    if _embedding_model is None:
        logger.info(f"Loading embedding model: {EMBEDDING_MODEL}")
        _embedding_model = SentenceTransformer(EMBEDDING_MODEL)
    return _embedding_model


def get_collection():
    global _chroma_collection
    if _chroma_collection is None:
        logger.info(f"Connecting to ChromaDB: {CHROMA_DIR}")
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        _chroma_collection = client.get_collection(COLLECTION_NAME)
        logger.info(f"Collection loaded: {_chroma_collection.count()} chunks")
    return _chroma_collection


def get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(
            base_url=LM_STUDIO_BASE_URL,
            api_key=LM_STUDIO_API_KEY,
        )
    return _openai_client


# --- 言語検出・翻訳 ---

def detect_language(text: str) -> str:
    """簡易言語検出: CJK文字が30%以上なら日本語と判定"""
    cjk_count = sum(
        1 for c in text
        if "\u4e00" <= c <= "\u9fff"    # CJK統合漢字
        or "\u3040" <= c <= "\u30ff"    # ひらがな・カタカナ
    )
    return "ja" if cjk_count / max(len(text), 1) > 0.3 else "en"


def translate_to_english(query: str) -> str:
    """日本語クエリをLM Studio経由で英語に翻訳 (Embedding検索用)"""
    client = get_openai_client()
    try:
        response = client.chat.completions.create(
            model=LM_STUDIO_MODEL_DEFAULT,
            messages=[
                {"role": "system", "content": "Translate the following Japanese radiology query to English. Output ONLY the English translation, nothing else."},
                {"role": "user", "content": query},
            ],
            temperature=0.1,
            max_tokens=200,
        )
        translated = response.choices[0].message.content.strip()
        logger.info(f"Translated: {query} -> {translated}")
        return translated
    except Exception as e:
        logger.warning(f"Translation failed: {e}, using original query")
        return query


# --- 検索 ---

def search(query: str, top_k: int = TOP_K) -> list[dict]:
    """ベクトルDBから関連チャンクを検索 (日本語は英語に翻訳してから検索)"""
    model = get_embedding_model()
    collection = get_collection()

    # 日本語クエリは英語に翻訳してからEmbedding (英語コンテンツとのマッチング向上)
    search_query = query
    if detect_language(query) == "ja":
        search_query = translate_to_english(query)

    # BGEモデルは検索用プレフィックスが推奨
    if "bge" in EMBEDDING_MODEL.lower():
        query_for_embedding = f"Represent this sentence for searching relevant passages: {search_query}"
    else:
        query_for_embedding = search_query

    query_embedding = model.encode([query_for_embedding]).tolist()

    results = collection.query(
        query_embeddings=query_embedding,
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    hits = []
    for i in range(len(results["ids"][0])):
        hits.append({
            "id": results["ids"][0][i],
            "page": results["metadatas"][0][i]["page"],
            "text": results["documents"][0][i],
            "distance": results["distances"][0][i],
        })
    return hits


# --- コンテキストバジェット ---

def estimate_tokens(text: str) -> int:
    """文字数からトークン数を推定"""
    return len(text) // CHARS_PER_TOKEN


def build_context_with_budget(hits: list[dict], query: str) -> tuple[str, list[dict]]:
    """トークンバジェット内でコンテキストを構築。使用したチャンクのリストも返す。"""
    system_prompt_tokens = 120  # システムプロンプトの推定トークン数
    query_tokens = estimate_tokens(query) + 50  # 質問 + フォーマットオーバーヘッド
    available = MAX_CONTEXT_TOKENS - system_prompt_tokens - MAX_OUTPUT_TOKENS - query_tokens

    used_hits = []
    context_parts = []
    total_tokens = 0

    for i, hit in enumerate(hits):
        chunk_text = f"[Reference {i + 1} - Page {hit['page']}]\n{hit['text']}"
        chunk_tokens = estimate_tokens(chunk_text)

        if total_tokens + chunk_tokens > available:
            logger.info(f"Budget reached: using {len(used_hits)}/{len(hits)} chunks "
                        f"({total_tokens}/{available} tokens)")
            break

        context_parts.append(chunk_text)
        used_hits.append(hit)
        total_tokens += chunk_tokens

    context = "\n\n---\n\n".join(context_parts)
    return context, used_hits


# --- 回答生成 ---

def generate_answer(query: str, hits: list[dict]) -> str:
    """LM Studio LLMでRAG回答を生成"""
    # 言語に応じてモデルを選択
    lang = detect_language(query)
    model_name = LM_STUDIO_MODEL_JA if lang == "ja" else LM_STUDIO_MODEL_EN

    # コンテキストをバジェット内で構築
    context, used_hits = build_context_with_budget(hits, query)

    if not context:
        return "Error: No context could be included within the token budget."

    system_prompt = (
        "You are a radiology assistant specializing in the content of "
        "Radiology Review Manual (GreenBook 7th Edition). "
        "Answer questions based ONLY on the provided reference material. "
        "Always cite page numbers in your answer. "
        "If the reference does not contain relevant information, say so clearly. "
        "Answer in the same language as the question. "
        "When answering in Japanese, use standard radiology terminology "
        "(e.g., 肝血管腫, T2強調画像, 造影パターン) while keeping "
        "English technical terms where conventionally used in Japanese radiology."
    )

    user_prompt = (
        f"## Reference Material\n\n{context}\n\n"
        f"---\n\n"
        f"## Question\n{query}\n\n"
        f"Please answer based on the reference material above, citing page numbers."
    )

    client = get_openai_client()

    logger.info(f"Model: {model_name} | Language: {lang} | "
                f"Chunks: {len(used_hits)} | Context: ~{estimate_tokens(context)} tokens")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=TEMPERATURE,
            max_tokens=MAX_OUTPUT_TOKENS,
        )
    except Exception as e:
        if model_name != LM_STUDIO_MODEL_DEFAULT:
            logger.warning(f"{model_name} failed ({e}), falling back to {LM_STUDIO_MODEL_DEFAULT}")
            response = client.chat.completions.create(
                model=LM_STUDIO_MODEL_DEFAULT,
                messages=messages,
                temperature=TEMPERATURE,
                max_tokens=MAX_OUTPUT_TOKENS,
            )
        else:
            raise

    return response.choices[0].message.content


# --- メイン ---

def query_rag(question: str):
    """RAGパイプライン実行"""
    logger.info(f"Question: {question}")

    # 1. 検索
    hits = search(question)
    logger.info(f"Found {len(hits)} candidate chunks")

    # 2. LLM回答生成
    answer = generate_answer(question, hits)

    # 3. 結果出力
    print("\n" + "=" * 60)
    print(f"Q: {question}")
    print("=" * 60)
    print(f"\n{answer}")
    print("\n" + "-" * 60)
    print("Sources:")
    for h in hits:
        preview = h["text"][:80].replace("\n", " ")
        print(f"  - Page {h['page']} (score: {1 - h['distance']:.3f}): {preview}...")
    print()


def interactive_mode():
    """インタラクティブREPLモード"""
    print("=" * 60)
    print("GreenBook RAG - Interactive Mode")
    print("=" * 60)
    print("Commands:")
    print("  quit / exit / q  - 終了")
    print("  help             - コマンド一覧")
    print("=" * 60)
    print()

    # モデルを事前ロード
    get_embedding_model()
    get_collection()

    while True:
        try:
            question = input("Q: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not question:
            continue
        if question.lower() in ("quit", "exit", "q"):
            print("Bye!")
            break
        if question.lower() == "help":
            print("  quit    - 終了")
            print("  help    - このヘルプ")
            print()
            continue

        query_rag(question)


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        question = " ".join(sys.argv[1:])
        query_rag(question)
    else:
        interactive_mode()
