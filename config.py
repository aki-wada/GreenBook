"""
GreenBook RAG System - Centralized Configuration
"""
import os
from pathlib import Path

# === Paths ===
PROJECT_ROOT = Path(__file__).parent
PDF_PATH = PROJECT_ROOT / "data" / "raw" / "【GreenBook 7】Radiology Review Manual 7th (2011) +31のコピー.pdf"
EXTRACTED_MD = PROJECT_ROOT / "data" / "extracted" / "greenbook7_full.md"
CHUNKS_JSONL = PROJECT_ROOT / "data" / "chunks" / "greenbook7_chunks.jsonl"
LOG_DIR = PROJECT_ROOT / "logs"

# Dropbox外に配置 (同期干渉回避)
GREENBOOK_HOME = Path(os.path.expanduser("~/.greenbook-rag"))
CHROMA_DIR = str(GREENBOOK_HOME / "vectordb")

# === Extraction ===
EXTRACTION_ENGINE = "pymupdf"  # "pymupdf" (高速) or "pdfplumber" (テーブル対応)
EXTRACTION_LOG = LOG_DIR / "extraction.log"
EXTRACTION_REPORT = LOG_DIR / "extraction_report.json"
EXTRACTION_PROGRESS = LOG_DIR / "extraction_progress.json"
CHECKPOINT_INTERVAL = 50  # N ページ毎にチェックポイント保存

# === OCR ===
OCR_MODEL = "glm-ocr"  # glm-ocr (高速 ~11s/page) or allenai/olmocr-2-7b (高精度 ~97s/page)
OCR_MD = PROJECT_ROOT / "data" / "extracted" / "greenbook7_ocr.md"
OCR_PROGRESS = LOG_DIR / "ocr_progress.json"
OCR_REPORT = LOG_DIR / "ocr_report.json"
OCR_DPI = 300  # ページレンダリング解像度
OCR_BATCH_CHECKPOINT = 10  # N ページ毎にチェックポイント保存
MERGED_MD = PROJECT_ROOT / "data" / "extracted" / "greenbook7_merged.md"  # PyMuPDF + OCR統合

# === Chunking ===
CHUNK_SIZE = 500       # 目標トークン数 (1 token ≈ 4 chars EN)
CHUNK_OVERLAP = 80     # オーバーラップ (トークン数)
MIN_CHUNK_SIZE = 50    # これより短いチャンクは前に結合

# === Embedding ===
EMBEDDING_MODEL = "BAAI/bge-base-en-v1.5"  # 検索特化, 768次元
EMBEDDING_BATCH_SIZE = 64
COLLECTION_NAME = "greenbook7"

# === LM Studio ===
LM_STUDIO_BASE_URL = "http://localhost:1234/v1"
LM_STUDIO_API_KEY = "lm-studio"

# モデル名 (LM Studio APIが返すモデルID)
LM_STUDIO_MODEL_EN = "medgemma-27b-text-it-mlx"
LM_STUDIO_MODEL_JA = "gpt-oss-safeguard-120b-mlx"
LM_STUDIO_MODEL_DEFAULT = LM_STUDIO_MODEL_EN

# === Query ===
TOP_K = 8              # 検索候補数 (バジェットで実際の使用数を制限)
MAX_CONTEXT_TOKENS = 12000  # LM Studioのコンテキスト長に合わせる (モデルにより調整)
MAX_OUTPUT_TOKENS = 2048
TEMPERATURE = 0.3

# === Ensure directories exist ===
for d in [LOG_DIR, GREENBOOK_HOME / "vectordb",
          PROJECT_ROOT / "data" / "extracted",
          PROJECT_ROOT / "data" / "chunks"]:
    d.mkdir(parents=True, exist_ok=True)
