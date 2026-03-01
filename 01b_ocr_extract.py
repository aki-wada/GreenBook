"""
画像ページの OCR テキスト抽出 (LM Studio Vision Model)
- PyMuPDFでテキスト抽出できなかったページを画像化→OCRモデルで読み取り
- チェックポイント機能付き (中断→再開可能)
- 最終的にPyMuPDFテキスト + OCRテキストを統合
- 並列処理対応 (--workers N)

Usage:
  python 01b_ocr_extract.py              # 全画像ページをOCR
  python 01b_ocr_extract.py --resume     # 中断から再開
  python 01b_ocr_extract.py --workers 4  # 4並列で処理
  python 01b_ocr_extract.py --test 5     # 最初の5ページだけテスト
  python 01b_ocr_extract.py --merge-only # OCR済データと既存テキストの統合のみ
"""
import sys
import json
import logging
import base64
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import fitz
from openai import OpenAI

from config import (
    PDF_PATH, EXTRACTED_MD, LOG_DIR,
    LM_STUDIO_BASE_URL, LM_STUDIO_API_KEY,
    OCR_MODEL, OCR_MD, OCR_PROGRESS, OCR_REPORT,
    OCR_DPI, OCR_BATCH_CHECKPOINT, MERGED_MD,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "ocr.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def get_empty_pages(pdf_path: str) -> list[int]:
    """PyMuPDFでテキスト抽出できないページ番号のリストを返す (1-indexed)"""
    doc = fitz.open(pdf_path)
    empty = []
    for i in range(len(doc)):
        text = doc[i].get_text("text").strip()
        if not text:
            empty.append(i + 1)  # 1-indexed
    doc.close()
    return empty


def render_page_to_base64(pdf_path: str, page_idx: int, dpi: int = 300) -> str:
    """ページを画像化してbase64エンコード"""
    doc = fitz.open(pdf_path)
    page = doc[page_idx]
    pix = page.get_pixmap(dpi=dpi)
    img_bytes = pix.tobytes("png")
    doc.close()
    return base64.b64encode(img_bytes).decode()


def ocr_page(client: OpenAI, img_b64: str, model: str) -> str:
    """OCRモデルで画像からテキスト抽出"""
    response = client.chat.completions.create(
        model=model,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Extract all text from this medical textbook page. "
                        "Output the text exactly as written, preserving structure, "
                        "headings, bullet points, and special characters. "
                        "Do not add commentary or explanations."
                    ),
                },
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                },
            ],
        }],
        max_tokens=4096,
        temperature=0.1,
    )
    return response.choices[0].message.content


def clean_ocr_text(text: str) -> str:
    """OCR出力のクリーニング"""
    if not text:
        return ""
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" +\n", "\n", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return text.strip()


# --- チェックポイント ---

def load_progress() -> dict | None:
    if OCR_PROGRESS.exists():
        with open(OCR_PROGRESS, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_progress(completed_pages: list[int], total_target: int):
    progress = {
        "completed_pages": completed_pages,
        "total_target": total_target,
        "timestamp": datetime.now().isoformat(),
    }
    with open(OCR_PROGRESS, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=2)


def clear_progress():
    if OCR_PROGRESS.exists():
        OCR_PROGRESS.unlink()


# --- メインOCR ---

def _ocr_single_page(pdf_path_str: str, page_num: int, client: OpenAI) -> dict:
    """1ページのOCR処理 (スレッドから呼ばれる)"""
    page_idx = page_num - 1
    start = time.time()
    img_b64 = render_page_to_base64(pdf_path_str, page_idx, dpi=OCR_DPI)
    raw_text = ocr_page(client, img_b64, OCR_MODEL)
    cleaned = clean_ocr_text(raw_text)
    elapsed = time.time() - start
    return {"page_num": page_num, "text": cleaned, "elapsed": elapsed}


def run_ocr(pdf_path: str, target_pages: list[int], resume: bool = False,
            workers: int = 1) -> dict:
    """画像ページをOCR処理してMarkdownファイルに保存 (並列対応)"""
    pdf_path_str = str(pdf_path)
    client = OpenAI(base_url=LM_STUDIO_BASE_URL, api_key=LM_STUDIO_API_KEY)

    report = {
        "pdf_path": pdf_path_str,
        "ocr_model": OCR_MODEL,
        "start_time": datetime.now().isoformat(),
        "total_target": len(target_pages),
        "ocr_pages": 0,
        "errors": [],
        "timings": [],
    }

    completed = set()
    file_mode = "w"

    if resume:
        progress = load_progress()
        if progress and progress.get("completed_pages"):
            completed = set(progress["completed_pages"])
            file_mode = "a"
            logger.info(f"Resuming: {len(completed)} pages already done")
        else:
            logger.info("No checkpoint found, starting from beginning")

    remaining = [p for p in target_pages if p not in completed]
    logger.info(f"OCR Model: {OCR_MODEL}")
    logger.info(f"Workers: {workers}")
    logger.info(f"Target: {len(remaining)} pages to process ({len(completed)} already done)")

    # --- ロック (並列書き込み保護) ---
    lock = threading.Lock()
    done_count = 0
    wall_start = time.time()

    with open(OCR_MD, file_mode, encoding="utf-8") as out_f:
        if file_mode == "w":
            out_f.write(f"# Radiology Review Manual 7th Edition (OCR)\n\n")
            out_f.write(f"> OCR Model: {OCR_MODEL}\n")
            out_f.write(f"> Extracted: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            out_f.write(f"> DPI: {OCR_DPI}\n\n---\n")

        def _handle_result(result: dict):
            nonlocal done_count
            page_num = result["page_num"]
            cleaned = result["text"]
            elapsed = result["elapsed"]

            with lock:
                report["timings"].append(elapsed)
                if cleaned:
                    out_f.write(
                        f"\n\n<!-- PAGE:{page_num} -->\n"
                        f"## [Page {page_num}]\n\n"
                        f"{cleaned}"
                    )
                    report["ocr_pages"] += 1
                completed.add(page_num)
                done_count += 1

                total = len(remaining)
                wall_elapsed = time.time() - wall_start
                wall_rate = wall_elapsed / done_count if done_count else 0
                eta_min = wall_rate * (total - done_count) / 60
                logger.info(
                    f"[{done_count}/{total}] Page {page_num}: "
                    f"{elapsed:.1f}s, {len(cleaned)} chars "
                    f"(ETA: {eta_min:.0f} min)"
                )

                if done_count % OCR_BATCH_CHECKPOINT == 0:
                    save_progress(sorted(completed), len(target_pages))
                    out_f.flush()
                    logger.info(f"Checkpoint saved: {len(completed)} pages done")

        if workers <= 1:
            # 逐次処理 (従来互換)
            for page_num in remaining:
                try:
                    result = _ocr_single_page(pdf_path_str, page_num, client)
                    _handle_result(result)
                except Exception as e:
                    logger.error(f"Page {page_num}: {e}")
                    report["errors"].append({"page": page_num, "error": str(e)})
        else:
            # 並列処理
            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_to_page = {
                    executor.submit(_ocr_single_page, pdf_path_str, pn, client): pn
                    for pn in remaining
                }
                for future in as_completed(future_to_page):
                    page_num = future_to_page[future]
                    try:
                        result = future.result()
                        _handle_result(result)
                    except Exception as e:
                        logger.error(f"Page {page_num}: {e}")
                        report["errors"].append({"page": page_num, "error": str(e)})

        # 最終チェックポイント保存
        save_progress(sorted(completed), len(target_pages))
        out_f.flush()

    # 完了処理
    clear_progress()

    report["end_time"] = datetime.now().isoformat()
    report["output_path"] = str(OCR_MD)
    if report["timings"]:
        report["avg_seconds_per_page"] = round(sum(report["timings"]) / len(report["timings"]), 1)
        report["total_minutes"] = round(sum(report["timings"]) / 60, 1)
        wall_total = time.time() - wall_start
        report["wall_minutes"] = round(wall_total / 60, 1)
        report["effective_pages_per_sec"] = round(len(report["timings"]) / wall_total, 2)

    logger.info(f"OCR complete: {report['ocr_pages']}/{len(target_pages)} pages")
    if report["errors"]:
        logger.warning(f"Errors: {len(report['errors'])} pages")
    if report["timings"]:
        logger.info(
            f"Avg: {report['avg_seconds_per_page']}s/page, "
            f"Wall: {report.get('wall_minutes', '?')} min, "
            f"Effective: {report.get('effective_pages_per_sec', '?')} pages/s"
        )

    return report


# --- マージ ---

def merge_texts():
    """PyMuPDFテキスト + OCRテキストを統合して1つのMarkdownに"""
    logger.info("Merging PyMuPDF text + OCR text...")

    # PyMuPDFテキストを読み込み
    pymupdf_pages = {}
    if EXTRACTED_MD.exists():
        with open(EXTRACTED_MD, "r", encoding="utf-8") as f:
            content = f.read()
        pattern = r"<!-- PAGE:(\d+) -->"
        parts = re.split(pattern, content)
        for i in range(1, len(parts), 2):
            page_num = int(parts[i])
            text = parts[i + 1].strip() if i + 1 < len(parts) else ""
            text = re.sub(r"^## \[Page \d+\]\s*", "", text)
            if text:
                pymupdf_pages[page_num] = text
        logger.info(f"PyMuPDF: {len(pymupdf_pages)} pages")

    # OCRテキストを読み込み
    ocr_pages = {}
    if OCR_MD.exists():
        with open(OCR_MD, "r", encoding="utf-8") as f:
            content = f.read()
        pattern = r"<!-- PAGE:(\d+) -->"
        parts = re.split(pattern, content)
        for i in range(1, len(parts), 2):
            page_num = int(parts[i])
            text = parts[i + 1].strip() if i + 1 < len(parts) else ""
            text = re.sub(r"^## \[Page \d+\]\s*", "", text)
            if text:
                ocr_pages[page_num] = text
        logger.info(f"OCR: {len(ocr_pages)} pages")

    # 統合 (PyMuPDF優先、画像ページはOCR)
    all_pages = sorted(set(pymupdf_pages.keys()) | set(ocr_pages.keys()))
    logger.info(f"Merged: {len(all_pages)} total pages")

    with open(MERGED_MD, "w", encoding="utf-8") as f:
        f.write("# Radiology Review Manual 7th Edition (Merged)\n\n")
        f.write(f"> Merged: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"> PyMuPDF pages: {len(pymupdf_pages)}\n")
        f.write(f"> OCR pages: {len(ocr_pages)}\n")
        f.write(f"> Total pages: {len(all_pages)}\n\n---\n")

        for page_num in all_pages:
            # PyMuPDFテキストがあればそちらを優先
            if page_num in pymupdf_pages:
                text = pymupdf_pages[page_num]
                source = "pymupdf"
            else:
                text = ocr_pages[page_num]
                source = "ocr"

            f.write(
                f"\n\n<!-- PAGE:{page_num} -->\n"
                f"## [Page {page_num}]\n\n"
                f"{text}"
            )

    logger.info(f"Output: {MERGED_MD}")
    return len(all_pages)


if __name__ == "__main__":
    args = sys.argv[1:]
    resume_mode = "--resume" in args
    merge_only = "--merge-only" in args
    test_limit = None
    num_workers = 1

    for i, arg in enumerate(args):
        if arg == "--test" and i + 1 < len(args):
            test_limit = int(args[i + 1])
        if arg == "--workers" and i + 1 < len(args):
            num_workers = int(args[i + 1])

    if merge_only:
        merge_texts()
        logger.info("=== Merge Done ===")
        sys.exit(0)

    logger.info("=== OCR Extraction Start ===")

    # 画像ページを特定
    empty_pages = get_empty_pages(str(PDF_PATH))
    logger.info(f"Found {len(empty_pages)} image-only pages")

    if test_limit:
        empty_pages = empty_pages[:test_limit]
        logger.info(f"Test mode: processing first {test_limit} pages")

    # OCR実行
    report = run_ocr(str(PDF_PATH), empty_pages, resume=resume_mode,
                     workers=num_workers)

    # レポート保存
    with open(OCR_REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    logger.info(f"Report saved: {OCR_REPORT}")

    # マージ
    total = merge_texts()
    logger.info(f"=== Done ({total} pages merged) ===")
