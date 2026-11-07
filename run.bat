@echo off
cd /d "%~dp0"
python -c "import gem" 2>nul
if errorlevel 1 (
  echo Installing replay parser dependencies...
  python -m pip install -r requirements.txt
)
start "" /b python server.py 8765
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:8765
