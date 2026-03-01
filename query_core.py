"""
RAG コアロジック (04_query.py と 05_webapp.py で共有)
- Embedding モデル / ChromaDB / OpenAI クライアントのシングルトン管理
- ベクトル検索、コンテキスト構築、言語検出
"""
import logging
import chromadb
from sentence_transformers import SentenceTransformer
from openai import OpenAI

from config import (
    CHROMA_DIR, COLLECTION_NAME, EMBEDDING_MODEL,
    LM_STUDIO_BASE_URL, LM_STUDIO_API_KEY,
    LM_STUDIO_MODEL_DEFAULT,
    TOP_K, MAX_CONTEXT_TOKENS, MAX_OUTPUT_TOKENS,
)

logger = logging.getLogger(__name__)

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
    cjk_count = sum(
        1 for c in text
        if "\u4e00" <= c <= "\u9fff"
        or "\u3040" <= c <= "\u30ff"
    )
    return "ja" if cjk_count / max(len(text), 1) > 0.3 else "en"


def translate_to_english(query: str) -> str:
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
    model = get_embedding_model()
    collection = get_collection()

    search_query = query
    if detect_language(query) == "ja":
        search_query = translate_to_english(query)

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
    return len(text) // CHARS_PER_TOKEN


def build_context_with_budget(hits: list[dict], query: str) -> tuple[str, list[dict]]:
    system_prompt_tokens = 120
    query_tokens = estimate_tokens(query) + 50
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
