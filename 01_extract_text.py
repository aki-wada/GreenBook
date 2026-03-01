"""
GreenBook PDF → Markdown テキスト抽出
- PyMuPDF (高速) / pdfplumber (テーブル対応) 切替可能
- 50ページ毎のチェックポイントによるレジューム機能付き

Usage: python 01_extract_text.py [--resume]
"""
import re
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from config import (
    PDF_PATH, EXTRACTED_MD, EXTRACTION_ENGINE,
    EXTRACTION_LOG, EXTRACTION_REPORT, EXTRACTION_PROGRESS,
    CHECKPOINT_INTERVAL, LOG_DIR,
)

# --- ログ設定 ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(EXTRACTION_LOG, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def clean_text(text: str) -> str:
    """抽出テキストの基本クリーニング"""
    if not text:
        return ""
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" +\n", "\n", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return text.strip()


# --- 抽出バックエンド ---

def extract_page_pymupdf(pdf_path: str, page_idx: int) -> str:
    """PyMuPDF (fitz) で1ページ抽出"""
    import fitz
    doc = fitz.open(pdf_path)
    page = doc[page_idx]
    text = page.get_text("text")
    doc.close()
    return text


def extract_page_pdfplumber(pdf_path: str, page_idx: int, _pdf_cache: dict = {}) -> str:
    """pdfplumber で1ページ抽出 (PDFオブジェクトはキャッシュ)"""
    import pdfplumber
    if "pdf" not in _pdf_cache:
        _pdf_cache["pdf"] = pdfplumber.open(pdf_path)
    return _pdf_cache["pdf"].pages[page_idx].extract_text()


def get_total_pages(pdf_path: str, engine: str) -> int:
    """PDF総ページ数を取得"""
    if engine == "pymupdf":
        import fitz
        doc = fitz.open(pdf_path)
        total = len(doc)
        doc.close()
        return total
    else:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            return len(pdf.pages)


def extract_page(pdf_path: str, page_idx: int, engine: str) -> str:
    """エンジンに応じてページを抽出"""
    if engine == "pymupdf":
        return extract_page_pymupdf(pdf_path, page_idx)
    else:
        return extract_page_pdfplumber(pdf_path, page_idx)


# --- チェックポイント ---

def load_progress() -> dict | None:
    """保存済みの進捗を読み込み"""
    if EXTRACTION_PROGRESS.exists():
        with open(EXTRACTION_PROGRESS, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_progress(last_page: int, total: int):
    """進捗をチェックポイントに保存"""
    progress = {
        "last_completed_page": last_page,
        "total_pages": total,
        "timestamp": datetime.now().isoformat(),
    }
    with open(EXTRACTION_PROGRESS, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=2)


def clear_progress():
    """完了後にチェックポイントファイルを削除"""
    if EXTRACTION_PROGRESS.exists():
        EXTRACTION_PROGRESS.unlink()


# --- メイン抽出 ---

def extract_pdf(pdf_path: str, output_path: str, resume: bool = False) -> dict:
    """PDFからテキストを抽出しMarkdownファイルに保存"""
    pdf_path_str = str(pdf_path)
    total = get_total_pages(pdf_path_str, EXTRACTION_ENGINE)

    report = {
        "pdf_path": pdf_path_str,
        "engine": EXTRACTION_ENGINE,
        "start_time": datetime.now().isoformat(),
        "total_pages": total,
        "extracted_pages": 0,
        "empty_pages": [],
        "errors": [],
    }

    start_page = 0
    file_mode = "w"

    # レジューム判定
    if resume:
        progress = load_progress()
        if progress and progress.get("last_completed_page", 0) > 0:
            start_page = progress["last_completed_page"]
            file_mode = "a"
            logger.info(f"Resuming from page {start_page + 1}")
        else:
            logger.info("No checkpoint found, starting from beginning")

    logger.info(f"PDF: {Path(pdf_path_str).name} ({total} pages)")
    logger.info(f"Engine: {EXTRACTION_ENGINE}")
    logger.info(f"Processing pages {start_page + 1} to {total}")

    with open(output_path, file_mode, encoding="utf-8") as out_f:
        # ヘッダー (新規開始時のみ)
        if file_mode == "w":
            out_f.write(f"# Radiology Review Manual 7th Edition\n\n")
            out_f.write(f"> Extracted: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            out_f.write(f"> Source: {Path(pdf_path_str).name}\n")
            out_f.write(f"> Engine: {EXTRACTION_ENGINE}\n")
            out_f.write(f"> Total pages: {total}\n\n---\n")

        for i in range(start_page, total):
            page_num = i + 1
            try:
                text = extract_page(pdf_path_str, i, EXTRACTION_ENGINE)
                if text and text.strip():
                    cleaned = clean_text(text)
                    out_f.write(
                        f"\n\n<!-- PAGE:{page_num} -->\n"
                        f"## [Page {page_num}]\n\n"
                        f"{cleaned}"
                    )
                    report["extracted_pages"] += 1
                else:
                    report["empty_pages"].append(page_num)
            except Exception as e:
                logger.error(f"Page {page_num}: {e}")
                report["errors"].append({"page": page_num, "error": str(e)})

            # 進捗表示 + チェックポイント
            if page_num % CHECKPOINT_INTERVAL == 0:
                pct = page_num / total * 100
                logger.info(f"Progress: {page_num}/{total} ({pct:.1f}%)")
                save_progress(page_num, total)
                out_f.flush()

    # 完了処理
    clear_progress()

    import os
    report["end_time"] = datetime.now().isoformat()
    report["output_path"] = str(output_path)
    report["output_size_mb"] = round(os.path.getsize(output_path) / 1024 / 1024, 2)

    logger.info(f"Extraction complete: {report['extracted_pages']}/{total} pages")
    logger.info(f"Empty pages: {len(report['empty_pages'])}")
    if report["errors"]:
        logger.warning(f"Errors: {len(report['errors'])} pages")
    logger.info(f"Output: {output_path} ({report['output_size_mb']} MB)")

    return report


if __name__ == "__main__":
    resume_mode = "--resume" in sys.argv

    logger.info("=== GreenBook Text Extraction Start ===")
    report = extract_pdf(PDF_PATH, EXTRACTED_MD, resume=resume_mode)

    with open(EXTRACTION_REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    logger.info(f"Report saved: {EXTRACTION_REPORT}")
    logger.info("=== Done ===")
