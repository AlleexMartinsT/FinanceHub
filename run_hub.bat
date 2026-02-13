@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [Hub] Ambiente virtual nao encontrado em .venv
  echo [Hub] Execute uma vez:
  echo   python -m venv .venv
  echo   .venv\Scripts\pip install --upgrade pip
  pause
  exit /b 1
)

cls
echo [Hub] Iniciando FinanceHub...
".venv\Scripts\python.exe" "src\main.py"
set ERR=%ERRORLEVEL%
echo [Hub] Encerrado com codigo %ERR%
pause
exit /b %ERR%
