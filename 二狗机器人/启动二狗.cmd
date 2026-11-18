@echo off
setlocal
cd /d "%~dp0"
set "ERGOU_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%ERGOU_PY%" set "ERGOU_PY=python"
set "PYTHONUTF8=1"
if not exist "data\ergou.sqlite" (
  "%ERGOU_PY%" -m ergou init --demo
  if errorlevel 1 goto failed
)
"%ERGOU_PY%" -c "import sqlite3,sys; sys.exit(0 if sqlite3.connect('data/ergou.sqlite').execute('select count(*) from users').fetchone()[0] else 1)"
if errorlevel 1 (
  "%ERGOU_PY%" -m ergou user admin
  if errorlevel 1 goto failed
)
if not defined ERGOU_PORT set "ERGOU_PORT=8765"
"%ERGOU_PY%" -m ergou serve --port "%ERGOU_PORT%" %*
if not errorlevel 1 exit /b 0
:failed
pause
exit /b 1

