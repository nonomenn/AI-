#!/usr/bin/env bash
# AMPS ローカルセットアップ（Mac/Linux用）
# 使い方: cd amps && ./setup.sh
set -e

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "venvを作成しています..."
  python3 -m venv .venv
fi

echo "依存パッケージをインストールしています..."
source .venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo ".env を作成しました。ANTHROPIC_API_KEY を設定してください。"
fi

echo "DBを初期化しています..."
python -c "import db; db.init_db()"

echo ""
echo "セットアップ完了。"
echo "1) .env を開いて ANTHROPIC_API_KEY を設定してください（Suno音源生成を使うなら SUNO_API_KEY も）"
echo "2) 次のコマンドで起動できます："
echo "   source .venv/bin/activate && streamlit run dashboard.py"
