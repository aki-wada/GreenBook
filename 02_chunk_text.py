"""
抽出Markdown → 意味単位チャンク分割
- セクション構造を考慮した分割
- 巨大チャンクの再帰的フォールバック分割
- チャンクサイズ500トークン (検索精度重視)

Usage: python 02_chunk_text.py
"""
import json
import re
import logging

from config import (
    EXTRACTED_MD, MERGED_MD, CHUNKS_JSONL,
    CHUNK_SIZE, CHUNK_OVERLAP, MIN_CHUNK_SIZE,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# 文字数換算 (1 token ≈ 4 chars for English)
CHARS_PER_TOKEN = 4


def parse_pages(md_text: str) -> list[dict]:
    """Markdownをページ単位で分割"""
    pattern = r"<!-- PAGE:(\d+) -->"
    parts = re.split(pattern, md_text)

    pages = []
    for i in range(1, len(parts), 2):
        page_num = int(parts[i])
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""
        content = re.sub(r"^## \[Page \d+\]\s*", "", content)
        if content:
            pages.append({"page": page_num, "text": content})
    return pages


def split_by_sections(text: str) -> list[str]:
    """見出し・セクション区切りで分割 (改善版)"""
    section_patterns = [
        r"\n(?=[A-Z][A-Z\s/\-]{5,}\n)",         # ALL-CAPS headings
        r"\n(?=[Mm]nemonic[:\s])",                # mnemonic (case-insensitive)
        r"\n(?=[A-Z]\.\s+[A-Z][a-z])",           # A. Section Name
        r"\n(?=\d+\.\s+[A-Z])",                  # Numbered major items
        r"\n(?=[Dd]ifferential [Dd]iagnos)",      # Differential diagnosis sections
        r"\n(?=(?:Imaging |Clinical |Key |Most ))",  # Domain-specific section starts
        r"\n---\n",                               # Horizontal rules
    ]
    combined = "|".join(section_patterns)
    sections = re.split(combined, text)
    return [s.strip() for s in sections if s.strip()]


def fallback_split(text: str, max_chars: int) -> list[str]:
    """巨大テキストを再帰的に分割 (paragraph → line → sentence → space)"""
    if len(text) <= max_chars:
        return [text]

    separators = ["\n\n", "\n", ". ", " "]
    for sep in separators:
        parts = text.split(sep)
        if len(parts) <= 1:
            continue

        chunks = []
        current = ""
        for part in parts:
            candidate = current + sep + part if current else part
            if len(candidate) > max_chars and current:
                chunks.append(current.strip())
                current = part
            else:
                current = candidate

        if current.strip():
            chunks.append(current.strip())

        if len(chunks) > 1:
            # 再帰: まだ大きいチャンクがあれば再分割
            result = []
            for c in chunks:
                if len(c) > max_chars:
                    result.extend(fallback_split(c, max_chars))
                else:
                    result.append(c)
            return result

    # 全セパレータで分割できなかった場合、そのまま返す
    return [text]


def create_chunks(pages: list[dict]) -> list[dict]:
    """ページとセクション構造を考慮してチャンク分割"""
    max_chars = CHUNK_SIZE * CHARS_PER_TOKEN
    overlap_chars = CHUNK_OVERLAP * CHARS_PER_TOKEN
    min_chars = MIN_CHUNK_SIZE * CHARS_PER_TOKEN
    chunks = []
    chunk_id = 0

    for page_data in pages:
        page_num = page_data["page"]
        sections = split_by_sections(page_data["text"])

        current_chunk = ""
        current_start_page = page_num

        for section in sections:
            # セクションが大きすぎる場合はフォールバック分割
            if len(section) > max_chars * 2:
                # 現在のバッファをフラッシュ
                if current_chunk:
                    chunks.append({
                        "id": f"chunk_{chunk_id:05d}",
                        "page": current_start_page,
                        "text": current_chunk.strip(),
                    })
                    chunk_id += 1
                    current_chunk = ""

                # フォールバック分割
                sub_chunks = fallback_split(section, max_chars)
                for j, sc in enumerate(sub_chunks):
                    if j == len(sub_chunks) - 1:
                        # 最後のサブチャンクはバッファに入れる
                        current_chunk = sc
                        current_start_page = page_num
                    else:
                        chunks.append({
                            "id": f"chunk_{chunk_id:05d}",
                            "page": page_num,
                            "text": sc.strip(),
                        })
                        chunk_id += 1
                continue

            # 通常のセクション: バッファに追加
            if len(current_chunk) + len(section) > max_chars:
                if current_chunk:
                    chunks.append({
                        "id": f"chunk_{chunk_id:05d}",
                        "page": current_start_page,
                        "text": current_chunk.strip(),
                    })
                    chunk_id += 1
                    # オーバーラップ: 末尾の一部を次のチャンクに引き継ぐ
                    if overlap_chars > 0 and len(current_chunk) > overlap_chars:
                        current_chunk = current_chunk[-overlap_chars:] + "\n\n" + section
                    else:
                        current_chunk = section
                    current_start_page = page_num
                else:
                    current_chunk = section
                    current_start_page = page_num
            else:
                current_chunk += "\n\n" + section

        # ページ終了時の残りバッファ
        if current_chunk.strip():
            if len(current_chunk.strip()) < min_chars and chunks:
                chunks[-1]["text"] += "\n\n" + current_chunk.strip()
            else:
                chunks.append({
                    "id": f"chunk_{chunk_id:05d}",
                    "page": current_start_page,
                    "text": current_chunk.strip(),
                })
                chunk_id += 1
            current_chunk = ""

    return chunks


if __name__ == "__main__":
    logger.info("=== Chunk Splitting Start ===")

    # マージ済みファイルがあればそちらを優先
    input_path = MERGED_MD if MERGED_MD.exists() else EXTRACTED_MD
    with open(input_path, "r", encoding="utf-8") as f:
        md_text = f.read()
    logger.info(f"Input: {input_path} ({len(md_text):,} chars)")

    pages = parse_pages(md_text)
    logger.info(f"Parsed {len(pages)} pages")

    chunks = create_chunks(pages)
    logger.info(f"Created {len(chunks)} chunks")

    # JSONL保存
    with open(CHUNKS_JSONL, "w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    # 統計
    lengths = [len(c["text"]) for c in chunks]
    logger.info(
        f"Chunk stats: min={min(lengths)}, max={max(lengths)}, "
        f"avg={sum(lengths) // len(lengths)}, total={sum(lengths):,} chars"
    )
    logger.info(f"Output: {CHUNKS_JSONL}")
    logger.info("=== Done ===")
