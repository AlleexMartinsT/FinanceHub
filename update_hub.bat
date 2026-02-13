@echo off
setlocal
cd /d "%~dp0"

echo [Hub] Atualizando codigo via Git...
git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
  echo [Hub] Esta pasta nao e um repositorio Git valido.
  pause
  exit /b 1
)

git pull --ff-only
set ERR=%ERRORLEVEL%
if not "%ERR%"=="0" (
  echo [Hub] Falha no git pull.
  pause
  exit /b %ERR%
)

echo [Hub] Atualizacao concluida.
pause
exit /b 0

