@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\uninstall_server.ps1" -Force %*
set ERR=%ERRORLEVEL%
echo [Uninstall] Encerrado com codigo %ERR%
pause
exit /b %ERR%
