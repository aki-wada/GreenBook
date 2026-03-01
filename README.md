# GreenBook RAG

**Radiology Review Manual 7th Edition** (GreenBook 7) を対象としたローカル RAG (Retrieval-Augmented Generation) システム。

LM Studio 上のローカル LLM を使い、教科書の内容に基づいた質問応答を行います。すべての処理がローカルで完結し、外部 API への送信は一切ありません。

---

## 必要環境

| 項目 | 要件 |
|------|------|
| OS | macOS (Apple Silicon 推奨) / Linux |
| Python | 3.10 以上 |
| LM Studio | 0.3 以上 (localhost:1234 で起動) |
| メモリ | 32GB 以上推奨 (27B モデル使用時) |
| ストレージ | PDF (~850MB) + VectorDB (~60MB) + 中間ファイル (~15MB) |

### LM Studio に必要なモデル

| 用途 | モデル | 備考 |
|------|--------|------|
| OCR | `glm-ocr` | 画像ページのテキスト抽出 |
| 英語回答 | `medgemma-27b-text-it-mlx` | 医療特化 LLM |
| 日本語回答 | `gpt-oss-safeguard-120b-mlx` | 日本語対応 LLM |

> モデルは `config.py` で変更可能です。LM Studio にロード済みの任意のモデルを指定できます。

---

## セットアップ

### 1. リポジトリのクローン

```bash
git clone https://github.com/aki-wada/GreenBook.git
cd GreenBook
```

### 2. Python 環境の構築

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. PDF の配置

対象の PDF を以下のパスに配置します：

```
data/raw/【GreenBook 7】Radiology Review Manual 7th (2011) +31のコピー.pdf
```

> ファイル名が異なる場合は `config.py` の `PDF_PATH` を編集してください。

### 4. LM Studio の起動

LM Studio を起動し、使用するモデルをロードします。サーバーが `http://localhost:1234` で待ち受けていることを確認してください。

```bash
# 動作確認
curl http://localhost:1234/v1/models
```

---

## 使い方

### パイプライン全体の実行

初回は Phase 1 → 1b → 2 → 3 の順に実行します。一度構築すれば Phase 4 のクエリのみ繰り返し利用できます。

```bash
source .venv/bin/activate

# Phase 1: テキスト抽出 (数秒)
python 01_extract_text.py

# Phase 1b: OCR — 画像ページのテキスト抽出 (約90分)
python 01b_ocr_extract.py

# Phase 2: チャンク分割 (数秒)
python 02_chunk_text.py

# Phase 3: VectorDB 構築 (約1分)
python 03_build_vectordb.py

# Phase 4: クエリ
python 04_query.py "What are the MRI findings of hepatic hemangioma?"
```

### クエリの実行 (CLI)

```bash
# 英語で質問
python 04_query.py "What is the differential diagnosis of ring-enhancing lesions?"

# 日本語で質問 (自動翻訳 → 検索 → 日本語で回答)
python 04_query.py "肝血管腫のMRI所見は？"

# インタラクティブモード (繰り返し質問)
python 04_query.py
```

**インタラクティブモードのコマンド**:
- `quit` / `exit` / `q` — 終了
- `help` — コマンド一覧

### Web アプリで使う

```bash
# Web サーバーを起動
python 05_webapp.py
```

ブラウザで **http://localhost:8321** を開くとチャット画面が表示されます。

1. テキストボックスに質問を入力して「送信」(または Enter キー)
2. LLM の回答がリアルタイムにストリーミング表示されます
3. 回答の下にある「Sources」を開くと参照元ページと類似度を確認できます

> **前提**: Phase 1〜3 のパイプラインが完了済みであること (VectorDB が構築済み)。
> LM Studio で回答用モデルがロードされていること。

---

## 各スクリプトの詳細

### 01_extract_text.py — テキスト抽出

PyMuPDF を使って PDF からテキストを抽出します。

```bash
python 01_extract_text.py
```

- 出力: `data/extracted/greenbook7_full.md`
- テキストのないページ (スキャン画像) は空ページとして記録されます

### 01b_ocr_extract.py — OCR

LM Studio の Vision モデルで画像ページをOCR処理します。

```bash
# 全画像ページをOCR
python 01b_ocr_extract.py

# 中断からの再開
python 01b_ocr_extract.py --resume

# 並列処理 (2ワーカー推奨、それ以上はモデルクラッシュの可能性あり)
python 01b_ocr_extract.py --workers 2

# テスト実行 (最初の5ページのみ)
python 01b_ocr_extract.py --test 5

# OCR済みデータとテキストのマージのみ
python 01b_ocr_extract.py --merge-only
```

- 出力: `data/extracted/greenbook7_ocr.md`
- マージ出力: `data/extracted/greenbook7_merged.md`
- 10ページごとにチェックポイント保存 → `--resume` で再開可能
- OCR完了後、自動的にマージを実行

### 02_chunk_text.py — チャンク分割

マージ済みテキストをセクション構造を考慮して分割します。

```bash
python 02_chunk_text.py
```

- 入力: `greenbook7_merged.md` (存在しない場合は `greenbook7_full.md`)
- 出力: `data/chunks/greenbook7_chunks.jsonl`
- チャンクサイズ: 500 tokens (オーバーラップ 80 tokens)

### 03_build_vectordb.py — VectorDB 構築

チャンクを Embedding して ChromaDB に格納します。

```bash
python 03_build_vectordb.py
```

- Embedding モデル: `BAAI/bge-base-en-v1.5` (768次元)
- VectorDB 保存先: `~/.greenbook-rag/vectordb/`
- 既存のコレクションは自動的に再作成されます

### 04_query.py — RAG クエリ (CLI)

ベクトル検索 + LLM で回答を生成します。

```bash
python 04_query.py "your question here"
```

**処理フロー**:
1. 言語検出 (日本語 / 英語)
2. 日本語クエリは英語に翻訳 (Embedding 検索の精度向上のため)
3. BGE モデルで Embedding → ChromaDB からTop-K検索
4. コンテキストバジェット内でチャンクを選択
5. LLM が参照資料に基づいて回答生成 (ページ番号引用付き)

### 05_webapp.py — Web アプリ

ブラウザから質問できるチャット UI です。回答はリアルタイムにストリーミング表示されます。

```bash
# 起動
python 05_webapp.py

# ポート指定 (デフォルト: 8000)
python 05_webapp.py --port 9000
```

ブラウザで **http://localhost:8321** を開いて使用します。

**機能**:
- LLM 回答のリアルタイムストリーミング (SSE)
- Markdown レンダリング (テーブル・見出し・リスト・コードブロック対応)
- 参照元ページの一覧表示 (類似度スコア付き)
- 日本語 / 英語の自動対応
- サンプル質問ボタン

---

## config.py — 設定一覧

### パス設定

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `PDF_PATH` | 対象 PDF のパス | `data/raw/...pdf` |
| `CHROMA_DIR` | VectorDB 保存先 | `~/.greenbook-rag/vectordb/` |

### OCR 設定

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `OCR_MODEL` | OCR モデル名 | `glm-ocr` |
| `OCR_DPI` | ページレンダリング解像度 | `300` |
| `OCR_BATCH_CHECKPOINT` | チェックポイント間隔 | `10` ページ |

### チャンク設定

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `CHUNK_SIZE` | 目標トークン数 | `500` |
| `CHUNK_OVERLAP` | オーバーラップ | `80` tokens |
| `MIN_CHUNK_SIZE` | 最小チャンクサイズ | `50` tokens |

### Embedding / VectorDB 設定

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `EMBEDDING_MODEL` | Embedding モデル | `BAAI/bge-base-en-v1.5` |
| `EMBEDDING_BATCH_SIZE` | バッチサイズ | `64` |
| `COLLECTION_NAME` | ChromaDB コレクション名 | `greenbook7` |

### LLM 設定

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `LM_STUDIO_BASE_URL` | LM Studio エンドポイント | `http://localhost:1234/v1` |
| `LM_STUDIO_MODEL_EN` | 英語回答モデル | `medgemma-27b-text-it-mlx` |
| `LM_STUDIO_MODEL_JA` | 日本語回答モデル | `gpt-oss-safeguard-120b-mlx` |
| `TOP_K` | 検索候補数 | `8` |
| `MAX_CONTEXT_TOKENS` | コンテキスト上限 | `12000` |
| `TEMPERATURE` | 生成温度 | `0.3` |

---

## ディレクトリ構成

```
greenbook-rag/
├── config.py                     # 設定ファイル
├── query_core.py                 # 検索・コンテキスト構築 (共通ロジック)
├── 01_extract_text.py            # Phase 1: テキスト抽出
├── 01b_ocr_extract.py            # Phase 1b: OCR
├── 02_chunk_text.py              # Phase 2: チャンク分割
├── 03_build_vectordb.py          # Phase 3: VectorDB構築
├── 04_query.py                   # Phase 4: クエリ (CLI)
├── 05_webapp.py                  # Phase 4: Web アプリ (FastAPI)
├── templates/
│   └── index.html                # チャット UI
├── requirements.txt              # 依存パッケージ
├── DEVELOPMENT_LOG.md            # 開発プロセス記録
├── data/
│   ├── raw/                      # 元PDF
│   ├── extracted/                # 抽出テキスト
│   │   ├── greenbook7_full.md       # PyMuPDF抽出
│   │   ├── greenbook7_ocr.md        # OCR抽出
│   │   └── greenbook7_merged.md     # 統合テキスト
│   └── chunks/
│       └── greenbook7_chunks.jsonl  # チャンクデータ
├── logs/                         # ログ・レポート
│   ├── extraction_report.json
│   ├── ocr_report.json
│   └── ocr.log
└── ~/.greenbook-rag/vectordb/    # ChromaDB (Dropbox外)
```

---

## トラブルシューティング

### LM Studio に接続できない

```
Connection refused: http://localhost:1234
```

→ LM Studio が起動していて、サーバーモードが有効であることを確認してください。

### OCR でモデルがクラッシュする

```
Error code: 400 - The model has crashed
```

→ LM Studio で glm-ocr を再ロードし、`--resume` で再開してください。特定のページで繰り返しクラッシュする場合は `config.py` の `OCR_DPI` を `200` に下げると改善する場合があります。

### クエリでモデルが見つからない

```
Model not found: medgemma-27b-text-it-mlx
```

→ LM Studio で該当モデルをロードするか、`config.py` の `LM_STUDIO_MODEL_EN` / `LM_STUDIO_MODEL_JA` を変更してください。

### VectorDB が空になる

→ Phase 2 (チャンク分割) と Phase 3 (VectorDB構築) を再実行してください：

```bash
python 02_chunk_text.py
python 03_build_vectordb.py
```

---

## ライセンス

本リポジトリのコードは自由に使用できます。PDF の内容は出版社の著作権に従います。
