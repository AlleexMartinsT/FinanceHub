@echo off
setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\bootstrap_server.ps1" -RunHub
set ERR=%ERRORLEVEL%
if not "%ERR%"=="0" (
  echo [Bootstrap] Falhou com codigo %ERR%
  pause
  exit /b %ERR%
)
exit /b 0

