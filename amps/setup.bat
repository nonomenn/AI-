@echo off
chcp 65001 > nul
REM AMPS local setup (Windows)
REM Usage: double-click setup.bat in the amps folder, or run it from Command Prompt

cd /d "%~dp0"

if not exist ".venv" (
  echo Creating venv...
  python -m venv .venv
)

echo Installing dependencies...
call .venv\Scripts\activate.bat
pip install --upgrade pip -q
pip install -r requirements.txt -q

if not exist ".env" (
  copy .env.example .env
  echo Created .env - please set ANTHROPIC_API_KEY in it.
)

echo Initializing database...
python -c "import db; db.init_db()"

echo.
echo Setup complete.
echo Next steps:
echo   1. Open .env and set ANTHROPIC_API_KEY (and SUNO_API_KEY if using Suno)
echo   2. Run:  .venv\Scripts\activate.bat
echo   3. Run:  streamlit run dashboard.py
pause
