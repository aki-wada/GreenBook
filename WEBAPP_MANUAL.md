# GreenBook RAG Web アプリ マニュアル

## 概要

ブラウザからGreenBook (Radiology Review Manual 7th Edition) の内容を質問できるチャットアプリです。
LLM の回答がリアルタイムにストリーミング表示され、参照元ページも確認できます。

---

## 1. 起動

```bash
cd greenbook-rag
source .venv/bin/activate
python 05_webapp.py
```

起動ログ:
```
  GreenBook RAG Web → http://localhost:8000

Loading embedding model: BAAI/bge-base-en-v1.5
Connecting to ChromaDB: /Users/.../.greenbook-rag/vectordb
Collection loaded: 3340 chunks
Ready.
Uvicorn running on http://0.0.0.0:8000
```

`Ready.` が表示されたら準備完了です。ブラウザで **http://localhost:8000** を開きます。

### ポートを変更する場合

```bash
python 05_webapp.py --port 9000
```

### バックグラウンドで起動する場合

```bash
nohup python 05_webapp.py > webapp.log 2>&1 &
```

停止するとき:
```bash
kill $(lsof -ti :8000)
```

---

## 2. 使い方

### 画面構成

```
+--------------------------------------------------+
| GreenBook RAG  Radiology Review Manual   3340 chunks |  <-- ヘッダー + 接続状態
+--------------------------------------------------+
|                                                  |
|         GreenBook RAG                            |
|    Radiology Review Manual の内容に基づいて       |  <-- ウェルカム画面
|    回答します。                                   |
|                                                  |
|  [サンプル質問ボタン 1]                           |
|  [サンプル質問ボタン 2]                           |
|  [サンプル質問ボタン 3]                           |
|                                                  |
+--------------------------------------------------+
| [質問を入力...                        ] [送信]   |  <-- 入力エリア
+--------------------------------------------------+
```

### 質問する

1. テキストボックスに質問を入力
2. **送信** ボタンをクリック、または **Enter** キーを押す
3. 回答がリアルタイムにストリーミング表示される

> 日本語入力中 (IME変換中) の Enter は送信されません。変換確定後に Enter を押してください。

### サンプル質問を使う

ウェルカム画面のボタンをクリックすると、質問が自動入力・送信されます。

- `What are the MRI findings of hepatic hemangioma?`
- `What is the differential diagnosis of ring-enhancing brain lesions?`
- `肝血管腫のMRI所見は？`

---

## 3. 回答の見方

### 回答表示

回答は **Markdown** 形式でレンダリングされます。

| 要素 | 表示 |
|------|------|
| `**太字**` | **太字** |
| `## 見出し` | 青色の見出し |
| `- リスト` | 箇条書き |
| `\| テーブル \|` | 罫線付きテーブル |
| `` `コード` `` | コードハイライト |

### Sources (参照元)

回答の下に **Sources (N chunks)** という折りたたみセクションがあります。
クリックすると展開され、以下が表示されます:

| 項目 | 説明 |
|------|------|
| **p.XXX** | 参照元のページ番号 |
| **XX%** | 類似度スコア (高いほど質問に近い) |
| **プレビュー** | チャンクの先頭テキスト |

### メタ情報

回答の末尾に表示される情報:

```
medgemma-27b-text-it-mlx | en | 39.9s
```

| 項目 | 説明 |
|------|------|
| モデル名 | 回答に使用された LLM |
| `en` / `ja` | 検出された言語 |
| 秒数 | 回答生成にかかった時間 |

---

## 4. 対応言語

| 質問の言語 | 動作 |
|------------|------|
| 英語 | そのまま英語で検索 → 英語モデルで回答 |
| 日本語 | 英語に翻訳して検索 → 日本語モデルで回答 |

> 言語の判定は自動です。CJK文字が30%以上含まれると日本語と判定されます。

---

## 5. 設定の変更

`config.py` を編集して Web アプリの動作を調整できます。
変更後はサーバーの再起動が必要です。

### 回答品質に関わる設定

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `TOP_K` | 検索候補チャンク数 | `8` |
| `MAX_CONTEXT_TOKENS` | コンテキスト上限 (トークン数) | `12000` |
| `MAX_OUTPUT_TOKENS` | 回答の最大トークン数 | `2048` |
| `TEMPERATURE` | 生成温度 (低い=正確、高い=多様) | `0.3` |

### モデル設定

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `LM_STUDIO_MODEL_EN` | 英語回答モデル | `medgemma-27b-text-it-mlx` |
| `LM_STUDIO_MODEL_JA` | 日本語回答モデル | `gpt-oss-safeguard-120b-mlx` |
| `LM_STUDIO_BASE_URL` | LM Studio エンドポイント | `http://localhost:1234/v1` |

> `MAX_CONTEXT_TOKENS` は LM Studio 側のコンテキスト長設定と合わせてください。
> LM Studio の設定よりも大きい値を指定するとエラーになります。

---

## 6. トラブルシューティング

### ヘッダーに「LM Studio offline」と表示される

LM Studio が起動していないか、サーバーモードが無効です。

1. LM Studio を起動
2. サーバーモードを有効にする
3. モデルをロード
4. ブラウザをリロード

### 回答がエラーになる (Model not found)

LM Studio に指定モデルがロードされていません。

- LM Studio で該当モデルをロードする
- または `config.py` のモデル名を LM Studio にロード済みのモデルに変更してサーバー再起動

### 回答がエラーになる (context length exceeded)

コンテキスト長が不足しています。

- **方法 A**: LM Studio 側のコンテキスト長を増やす
- **方法 B**: `config.py` の `MAX_CONTEXT_TOKENS` を小さくする (例: `6000`)

### 起動時に「Collection not found」

VectorDB が未構築です。「8. RAG パイプライン構築」を参照してください。

### ポート 8000 が既に使われている

```bash
# 使用中のプロセスを確認
lsof -i :8000

# 別のポートで起動
python 05_webapp.py --port 9000
```

### 回答が遅い

ローカル LLM の推論速度に依存します。目安:

| モデルサイズ | 回答時間 |
|-------------|---------|
| 7B | 10〜20秒 |
| 27B | 30〜60秒 |
| 120B | 2〜5分 |

`config.py` の `TOP_K` や `MAX_CONTEXT_TOKENS` を減らすとコンテキストが小さくなり高速化できます。

---

## 7. ヘルスチェック API

```bash
curl http://localhost:8000/api/health
```

レスポンス例:
```json
{
  "status": "ok",
  "lm_studio": true,
  "models": ["medgemma-27b-text-it-mlx"],
  "vectordb_chunks": 3340
}
```

| フィールド | 説明 |
|------------|------|
| `status` | `ok` = 正常、`error` = 異常 |
| `lm_studio` | LM Studio への接続可否 |
| `models` | LM Studio にロードされているモデル一覧 |
| `vectordb_chunks` | VectorDB に格納されたチャンク数 |

ヘッダー右上の接続ステータス表示もこの API を使用しています。

---

## 8. RAG パイプライン構築 (初回セットアップ)

Web アプリを使うには、事前に以下のセットアップが完了している必要があります。
**一度構築すれば再実行は不要です。**

### LM Studio の準備

| 確認項目 | 内容 |
|----------|------|
| LM Studio が起動している | サーバーモードが有効 |
| エンドポイント | `http://localhost:1234` |
| モデルがロード済み | 英語: `medgemma-27b-text-it-mlx`、日本語: `gpt-oss-safeguard-120b-mlx` |

```bash
# LM Studio 接続確認
curl http://localhost:1234/v1/models
```

> モデルは `config.py` の `LM_STUDIO_MODEL_EN` / `LM_STUDIO_MODEL_JA` で変更できます。
> LM Studio にロード済みの任意のモデルを指定可能です。

### Python パッケージのインストール

```bash
cd greenbook-rag
source .venv/bin/activate
pip install -r requirements.txt
pip install fastapi uvicorn jinja2
```

### パイプラインの実行

```bash
# Phase 1: テキスト抽出 (数秒)
python 01_extract_text.py

# Phase 1b: OCR — 画像ページのテキスト抽出 (約90分)
python 01b_ocr_extract.py

# Phase 2: チャンク分割 (数秒)
python 02_chunk_text.py

# Phase 3: VectorDB 構築 (約1分)
python 03_build_vectordb.py
```

完了すると `~/.greenbook-rag/vectordb/` に VectorDB が作成されます。
以降は「1. 起動」からすぐに使えます。

---

## 9. API リファレンス

### POST `/api/query`

質問を送信し、SSE (Server-Sent Events) でストリーミング回答を受信します。

**リクエスト**:
```json
{
  "question": "What are the MRI findings of hepatic hemangioma?"
}
```

**レスポンス (SSE)**:

```
event: sources
data: {"sources": [...], "chunks_used": 8}

event: token
data: {"text": "Hepatic"}

event: token
data: {"text": " hemangiomas"}

...

event: done
data: {"model": "medgemma-27b-text-it-mlx", "language": "en", "elapsed": 39.9}
```

| イベント | 内容 |
|----------|------|
| `sources` | 検索結果 (参照チャンク一覧) |
| `token` | LLM が生成したトークン (逐次送信) |
| `done` | 生成完了 (モデル名・言語・所要時間) |
| `error` | エラー発生 |

### GET `/api/health`

サーバーの状態を確認します。

### GET `/`

チャット UI の HTML ページを返します。

---

## 10. ストレージ使用量

| コンポーネント | サイズ | 場所 |
|---|---|---|
| アプリ本体 (コード) | ~100KB | `greenbook-rag/*.py`, `templates/` |
| 抽出テキスト | 10MB | `data/extracted/` |
| チャンクデータ | 5.8MB | `data/chunks/` |
| VectorDB | 59MB | `~/.greenbook-rag/vectordb/` |
| Python 仮想環境 | 1.2GB | `greenbook-rag/.venv/` |
| Embedding モデルキャッシュ | 419MB | `~/.cache/huggingface/` |
| 元 PDF | 810MB | `data/raw/` (シンボリックリンク) |

### サマリー

| 区分 | サイズ |
|---|---|
| コード | ~100KB |
| 生成データ (テキスト + チャンク + VectorDB) | ~75MB |
| Python 環境 + モデルキャッシュ | ~1.6GB |
| 元 PDF | 810MB |
| **総計** | **約 2.5GB** |

> 大半は Python パッケージ (PyTorch, sentence-transformers 等) と Embedding モデルのキャッシュです。
> コードと生成データだけであれば 75MB 程度です。
