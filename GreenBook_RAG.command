#!/bin/bash
# ============================================
# GreenBook RAG Web アプリ ランチャー
# ダブルクリックで起動 → ブラウザが自動で開きます
# ============================================

cd "$(dirname "$0")"

PORT=8321

# 既に起動中なら、ブラウザだけ開いて終了
if lsof -ti :$PORT > /dev/null 2>&1; then
    echo ""
    echo "  GreenBook RAG は既に起動中です"
    echo "  → http://localhost:$PORT"
    echo ""
    open "http://localhost:$PORT"
    echo "  ブラウザを開きました。このウィンドウは閉じて OK です。"
    echo ""
    read -p "  Enter で閉じる..."
    exit 0
fi

echo ""
echo "  ========================================="
echo "  GreenBook RAG を起動しています..."
echo "  ========================================="
echo ""

# 仮想環境を有効化
source .venv/bin/activate

# サーバーをバックグラウンドで起動
python 05_webapp.py &
SERVER_PID=$!

# サーバーが起動するまで待つ
echo "  モデルを読み込み中..."
for i in $(seq 1 30); do
    sleep 1
    if curl -s "http://localhost:$PORT/api/health" > /dev/null 2>&1; then
        echo ""
        echo "  ========================================="
        echo "  起動完了!"
        echo "  → http://localhost:$PORT"
        echo "  ========================================="
        echo ""
        open "http://localhost:$PORT"
        echo "  ブラウザを開きました。"
        echo ""
        echo "  ─────────────────────────────────────────"
        echo "  終了するには: このウィンドウを閉じる"
        echo "              または Ctrl+C を押す"
        echo "  ─────────────────────────────────────────"
        echo ""
        wait $SERVER_PID
        exit 0
    fi
done

echo ""
echo "  エラー: サーバーの起動に失敗しました。"
echo "  LM Studio が起動しているか確認してください。"
echo ""
read -p "  Enter で閉じる..."
kill $SERVER_PID 2>/dev/null
exit 1
