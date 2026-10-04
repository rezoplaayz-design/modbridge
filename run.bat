@echo off
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel% neq 0 (
  echo Python was not found.
  echo Install Python 3.11+ and enable Add Python to PATH.
  pause
  exit /b 1
)
set OPEN_BROWSER=1
python server.py
pause
