# GreenBook RAG System — 開発プロセス記録

## プロジェクト概要

**目的**: Radiology Review Manual 7th Edition (GreenBook 7) のPDFから、ローカルLLMで質問応答できるRAGシステムを構築する。

**環境**:
- macOS (Apple Silicon M4 Max)
- Python 3.12 (Homebrew) + venv
- LM Studio (localhost:1234) — ローカルLLM推論サーバー
- Dropbox 同期フォルダ上で開発

**対象PDF**: 1,257ページ / ~849MB (画像ベースのスキャンページが大半)

---

## アーキテクチャ

```
PDF (1,257 pages)
  │
  ├─ Phase 1: PyMuPDF テキスト抽出 → 155 テキストページ
  │
  ├─ Phase 1b: LM Studio OCR (glm-ocr) → 1,102 画像ページ
  │
  ├─ Phase 1c: マージ → 1,257 ページ統合 Markdown
  │
  ├─ Phase 2: セクション構造考慮チャンク分割 → 3,340 チャンク
  │
  ├─ Phase 3: Embedding (BGE) + ChromaDB → ベクトルDB (60MB)
  │
  └─ Phase 4: クエリ → 検索 + LLM回答生成
```

---

## ファイル構成

```
greenbook-rag/
├── config.py                  # 全体設定 (パス, モデル名, パラメータ)
├── 01_extract_text.py         # Phase 1: PyMuPDFテキスト抽出
├── 01b_ocr_extract.py         # Phase 1b: LM Studio Vision OCR
├── 02_chunk_text.py           # Phase 2: チャンク分割
├── 03_build_vectordb.py       # Phase 3: ChromaDB構築
├── 04_query.py                # Phase 4: RAGクエリ
├── requirements.txt           # 依存パッケージ
├── .venv/                     # Python仮想環境
├── data/
│   ├── raw/                   # 元PDF
│   ├── extracted/
│   │   ├── greenbook7_full.md    # PyMuPDFテキスト (491KB)
│   │   ├── greenbook7_ocr.md     # OCRテキスト (4.5MB)
│   │   └── greenbook7_merged.md  # 統合テキスト (5.0MB)
│   └── chunks/
│       └── greenbook7_chunks.jsonl  # チャンクデータ (5.8MB)
├── logs/
│   ├── extraction_report.json
│   ├── ocr_report.json
│   ├── ocr_progress.json      # チェックポイント (実行中のみ)
│   └── ocr.log
└── ~/.greenbook-rag/vectordb/ # ChromaDB (60MB, Dropbox外)
```

---

## Phase 1: テキスト抽出 (01_extract_text.py)

**日時**: 2026-03-01 12:51

**手法**: PyMuPDF (`fitz`) でPDF全ページからテキスト抽出。

**結果**:
- 155 ページにテキストあり (目次, 索引, 一部の章)
- 1,102 ページはテキストなし (スキャン画像)
- 出力: `greenbook7_full.md` (491KB)
- 処理時間: ~6秒

**設計判断**:
- `<!-- PAGE:N -->` マーカーで各ページを区切る形式を採用
- 後続のOCRテキストと統合しやすい構造

---

## Phase 1b: OCR抽出 (01b_ocr_extract.py)

**日時**: 2026-03-01 13:37〜19:22 (複数セッション)

**手法**: LM Studio の Vision Model (glm-ocr) を使い、画像ページをOCR処理。

### モデル選定

| モデル | 速度 | 精度 |
|--------|------|------|
| glm-ocr | ~12s/page | 十分 |
| allenai/olmocr-2-7b | ~97s/page | 高精度 |

→ **glm-ocr を採用** (速度重視、精度も実用十分)

### チェックポイント機能

長時間処理 (推定3〜4時間) に対応するため:
- 10ページごとにチェックポイント保存 (`ocr_progress.json`)
- `--resume` フラグで中断→再開可能
- OCR結果は `ocr.md` にインクリメンタル追記

### 並列処理の実装と検証

`ThreadPoolExecutor` による並列OCRを実装:

```python
with ThreadPoolExecutor(max_workers=workers) as executor:
    future_to_page = {
        executor.submit(_ocr_single_page, pdf_path_str, pn, client): pn
        for pn in remaining
    }
```

**検証結果**:
- **4 workers**: LM Studio のモデルがクラッシュ (Error 400)
- **2 workers**: 安定動作するがGPU推論のシリアル化により実質的な速度向上なし
- **1 worker**: 最も安定、~12s/page

→ **2 workers で実行** (安定性と微小な改善のバランス)

**LM Studio の並列処理制限**:
Vision モデルはGPU推論がシリアル化されるため、並列リクエストを送っても実際の処理速度は向上しない。テキストのみのモデルでは `--parallel` オプションで効果あり。

### OCR結果

- **成功**: 1,094 / 1,102 ページ (初回実行)
- **エラー**: 8 ページ (モデルクラッシュ)
  - Pages: 837, 838, 1001, 1002, 1059, 1060, 1134, 1135
  - 原因: 2-worker並列処理時に散発的にモデルがクラッシュ
- **リトライ**: 全8ページ回復成功
  - Page 837, 1134: DPI 200に下げて成功 (300ではクラッシュ)
  - 他6ページ: 単独再実行で成功
- **処理時間**: 88.2分 (wall clock), 平均23.7s/page

### 障害と復旧

**OCRファイル上書き事故**:
- 原因: OCR完了後に `clear_progress()` でチェックポイント削除される設計
- `--resume` を再実行 → チェックポイントなしで全ページ再処理開始 → ファイルが "w" モードで上書き
- 復旧: Dropbox バージョン履歴 (17:37 / 4.48MB版) から復元
- 教訓: **完了後のチェックポイント削除は危険。完了マーカーを別途設けるべき。**

---

## Phase 1c: テキストマージ

**手法**: PyMuPDF テキスト (155 pages) + OCR テキスト (1,102 pages) を統合。

```
--merge-only フラグで実行
PyMuPDFテキストがあるページはそちらを優先
画像ページはOCRテキストを使用
```

**結果**: 1,257 ページ統合 → `greenbook7_merged.md` (5.0MB)

---

## Phase 2: チャンク分割 (02_chunk_text.py)

**日時**: 2026-03-01 19:27

**手法**: セクション構造を考慮した意味単位分割。

**分割戦略**:
1. `<!-- PAGE:N -->` でページ単位に分割
2. セクション見出しパターン (ALL-CAPS, 番号付き見出し, mnemonic, Differential Diagnosis 等) で分割
3. 巨大セクションは再帰的フォールバック分割 (paragraph → line → sentence → space)
4. 小さすぎるチャンクは前のチャンクに結合

**パラメータ**:
- チャンクサイズ: 500 tokens (≈ 2,000 chars)
- オーバーラップ: 80 tokens (≈ 320 chars)
- 最小チャンクサイズ: 50 tokens (≈ 200 chars)

**コード変更**:
- `EXTRACTED_MD` → `MERGED_MD` を優先的に読み込むよう変更

**結果**: 3,340 チャンク, min=1 / max=4,296 / avg=1,665 chars

---

## Phase 3: VectorDB構築 (03_build_vectordb.py)

**日時**: 2026-03-01 19:28

**手法**: Sentence-Transformers でEmbedding → ChromaDB に格納。

**Embeddingモデル**: `BAAI/bge-base-en-v1.5`
- 768次元, コサイン類似度
- 検索タスクに特化したモデル
- デバイス: MPS (Apple Silicon GPU)

**VectorDB**: ChromaDB (Persistent)
- 保存先: `~/.greenbook-rag/vectordb/` (Dropbox外に配置)
  - Dropbox同期による競合を回避
- HNSW空間: cosine
- バッチサイズ: 64

**結果**: 3,340 チャンク indexed, 60MB, 48秒

---

## Phase 4: クエリシステム (04_query.py)

**機能**:
1. **言語自動検出**: CJK文字比率30%以上で日本語と判定
2. **日本語→英語翻訳**: 日本語クエリはLLMで英語に翻訳してからEmbedding検索
3. **BGEクエリプレフィックス**: `"Represent this sentence for searching relevant passages: "` を自動付与
4. **コンテキストバジェット**: トークン上限内でチャンクを選択
5. **モデル自動切替**:
   - 英語: `medgemma-27b-text-it-mlx`
   - 日本語: `gpt-oss-safeguard-120b-mlx`
6. **フォールバック**: 指定モデルが利用不可の場合、デフォルトモデルにフォールバック
7. **インタラクティブREPL**: 引数なしで起動するとREPLモード

**テスト結果**:
```
Q: What are the MRI findings of hepatic hemangioma?
A: Hepatic hemangiomas are typically hypointense on T1WI and
   hyperintense on T2WI. On CEMR, they exhibit peripheral nodular
   enhancement... [Page 711, 766 を引用]
```

---

## 技術的な知見・教訓

### LM Studio OCR
- Vision モデルの並列処理はGPUシリアル化により効果限定的
- 一部ページで DPI 300 → モデルクラッシュ。DPI 200 にフォールバックで解決
- モデルクラッシュは散発的で再実行すれば多くの場合成功する

### チェックポイント設計
- 完了後にチェックポイントを削除する設計は危険
- `--resume` の安全性: ファイルモード ("w" vs "a") の切り替えに注意
- **改善案**: 完了フラグを別ファイルで管理し、progress.json は保持する

### Dropbox上での開発
- VectorDB は Dropbox 外に配置 (同期競合回避)
- Dropbox バージョン履歴が緊急復旧に有効 (30日間)

### チャンク分割
- 医学テキストのセクション構造 (ALL-CAPS見出し, mnemonic, DDx) を考慮したパターンマッチが有効
- OCRテキストは構造が不完全なため、フォールバック分割の重要性が高い

---

## 実行コマンド一覧

```bash
cd greenbook-rag

# 環境構築
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Phase 1: テキスト抽出
python 01_extract_text.py

# Phase 1b: OCR (LM Studio の glm-ocr を事前にロード)
python 01b_ocr_extract.py                      # 全ページOCR
python 01b_ocr_extract.py --resume             # 中断再開
python 01b_ocr_extract.py --resume --workers 2 # 2並列で再開
python 01b_ocr_extract.py --test 5             # テスト (5ページ)
python 01b_ocr_extract.py --merge-only         # マージのみ

# Phase 2: チャンク分割
python 02_chunk_text.py

# Phase 3: VectorDB構築
python 03_build_vectordb.py

# Phase 4: クエリ
python 04_query.py "What are the MRI findings of hepatic hemangioma?"
python 04_query.py "肝血管腫のMRI所見は？"
python 04_query.py  # インタラクティブモード
```

---

## 処理時間サマリー

| Phase | 処理時間 | 備考 |
|-------|----------|------|
| テキスト抽出 | ~6秒 | PyMuPDF |
| OCR | 88分 | 1,102ページ, glm-ocr |
| マージ | <1秒 | |
| チャンク分割 | <1秒 | |
| VectorDB構築 | 48秒 | BGE embedding on MPS |
| クエリ | ~30秒 | 検索 + LLM生成 |

**合計**: 約90分 (OCRが大半)

---

## 依存パッケージ

```
PyMuPDF>=1.24.0          # PDF処理
pdfplumber>=0.10.0       # (代替PDF処理)
sentence-transformers>=2.2.0  # Embedding
chromadb>=0.4.0          # VectorDB
openai>=1.0.0            # LM Studio API client
tqdm>=4.60.0             # プログレスバー
```

---

*記録日: 2026-03-01*
*開発環境: macOS / Apple Silicon M4 Max / Python 3.12 / LM Studio*
