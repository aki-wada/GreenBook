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

from config import (
    LM_STUDIO_MODEL_EN, LM_STUDIO_MODEL_JA, LM_STUDIO_MODEL_DEFAULT,
    TEMPERATURE, MAX_OUTPUT_TOKENS,
)
from query_core import (
    search, build_context_with_budget, detect_language, estimate_tokens,
    get_embedding_model, get_collection, get_openai_client,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# --- 回答生成 ---

def generate_answer(query: str, hits: list[dict]) -> str:
    """LM Studio LLMでRAG回答を生成"""
    lang = detect_language(query)
    model_name = LM_STUDIO_MODEL_JA if lang == "ja" else LM_STUDIO_MODEL_EN

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

    hits = search(question)
    logger.info(f"Found {len(hits)} candidate chunks")

    answer = generate_answer(question, hits)

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
