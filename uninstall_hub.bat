@echo off
setlocal
cd /d "%~dp0"
rem -NoExit mantem o terminal aberto para leitura das mensagens finais
powershell -NoExit -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\uninstall_server.ps1" %*
set ERR=%ERRORLEVEL%
echo [Uninstall] Encerrado com codigo %ERR%
exit /b %ERR%
