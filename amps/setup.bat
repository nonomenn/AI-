@echo off
REM AMPS ローカルセットアップ（Windows用）
REM 使い方: amps フォルダで setup.bat をダブルクリック、またはコマンドプロンプトで実行

cd /d "%~dp0"

if not exist ".venv" (
  echo venvを作成しています...
  python -m venv .venv
)

echo 依存パッケージをインストールしています...
call .venv\Scripts\activate.bat
pip install --upgrade pip -q
pip install -r requirements.txt -q

if not exist ".env" (
  copy .env.example .env
  echo .env を作成しました。ANTHROPIC_API_KEY を設定してください。
)

echo DBを初期化しています...
python -c "import db; db.init_db()"

echo.
echo セットアップ完了。
echo 1^) .env を開いて ANTHROPIC_API_KEY を設定してください（Suno音源生成を使うなら SUNO_API_KEY も）
echo 2^) 次のコマンドで起動できます：
echo    .venv\Scripts\activate.bat ^&^& streamlit run dashboard.py
pause
