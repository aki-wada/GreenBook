"""
チャンク → Embedding → ChromaDB 構築
- BAAI/bge-base-en-v1.5 (検索特化, 768次元)
- ChromaDB保存先: ~/.greenbook-rag/vectordb/ (Dropbox外)

Usage: python 03_build_vectordb.py
"""
import json
import logging
import chromadb
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

from config import (
    CHUNKS_JSONL, CHROMA_DIR, COLLECTION_NAME,
    EMBEDDING_MODEL, EMBEDDING_BATCH_SIZE,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def load_chunks(jsonl_path: str) -> list[dict]:
    """JSONLファイルからチャンクを読み込み"""
    chunks = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            chunks.append(json.loads(line))
    return chunks


def build_vectordb(chunks: list[dict]):
    """チャンクをEmbeddingしてChromaDBに格納"""
    logger.info(f"Loading embedding model: {EMBEDDING_MODEL}")
    model = SentenceTransformer(EMBEDDING_MODEL)

    logger.info(f"Initializing ChromaDB at: {CHROMA_DIR}")
    client = chromadb.PersistentClient(path=CHROMA_DIR)

    # 既存コレクションがあれば削除して再作成
    try:
        client.delete_collection(COLLECTION_NAME)
        logger.info(f"Deleted existing collection: {COLLECTION_NAME}")
    except Exception:
        pass

    collection = client.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    # バッチ処理でEmbedding & 格納
    total = len(chunks)
    for i in tqdm(range(0, total, EMBEDDING_BATCH_SIZE), desc="Indexing"):
        batch = chunks[i : i + EMBEDDING_BATCH_SIZE]
        texts = [c["text"] for c in batch]
        ids = [c["id"] for c in batch]
        metadatas = [
            {"page": c["page"], "text_preview": c["text"][:200]}
            for c in batch
        ]

        embeddings = model.encode(texts, show_progress_bar=False).tolist()

        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
        )

    logger.info(f"VectorDB built: {collection.count()} chunks indexed")
    return collection


if __name__ == "__main__":
    logger.info("=== VectorDB Build Start ===")
    chunks = load_chunks(str(CHUNKS_JSONL))
    logger.info(f"Loaded {len(chunks)} chunks")

    collection = build_vectordb(chunks)
    logger.info(f"ChromaDB location: {CHROMA_DIR}")
    logger.info("=== Done ===")
