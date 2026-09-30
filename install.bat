@echo off
rem Shorts Maker - one-time setup. Double-click this file.
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
title Shorts Maker - install

where python >nul 2>nul
if errorlevel 1 (
  echo [!] Python was not found. Install Python 3.11+ from python.org
  echo     and check "Add python.exe to PATH" on the first screen. Then run this again.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Creating virtual environment...
  python -m venv .venv
  if errorlevel 1 ( echo [!] Failed to create .venv & pause & exit /b 1 )
)

echo [2/3] Installing packages (a few minutes the first time)...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 ( echo [!] Package install failed. Copy the error above and ask for help. & pause & exit /b 1 )

if not exist ".env" (
  echo [3/3] Creating .env from .env.example
  copy /y ".env.example" ".env" >nul
  echo.
  echo Notepad will open. Fill in these two lines, then save with Ctrl+S:
  echo     SHORTSMAKER_ACCESS_CODE=your-password ^(letters and digits^)
  echo     GEMINI_API_KEY=your-key
  echo Do NOT paste keys in chat. They stay only in this .env file.
  pause
  notepad ".env"
) else (
  echo [3/3] .env already exists - left unchanged.
)

echo.
echo Done. Double-click start.bat to run.
pause
