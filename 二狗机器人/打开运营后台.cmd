@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File "%~dp0ergou\live_start.ps1"
if not errorlevel 1 exit /b 0
pause
exit /b 1
