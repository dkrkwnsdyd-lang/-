@echo off
rem Shorts Maker - start the server. Double-click this file.
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
title Shorts Maker - server (keep this window open)

if not exist ".venv\Scripts\python.exe" (
  echo [!] Not installed yet. Run install.bat first.
  pause
  exit /b 1
)

rem Port 8000 already in use? An old server is probably still running.
netstat -ano | findstr /r /c:":8000 .*LISTENING" >nul
if not errorlevel 1 (
  echo [!] Port 8000 is already in use. Close the other Shorts Maker window,
  echo     or find it with:  netstat -ano ^| findstr :8000   then  taskkill /PID ^<number^> /F
  pause
  exit /b 1
)

rem Update code if git is available (ignore failures, e.g. local edits).
where git >nul 2>nul
if not errorlevel 1 (
  echo Checking for updates...
  git pull --ff-only 2>nul
)

rem Access code: use .env if it has one, otherwise ask now.
findstr /r /c:"^SHORTSMAKER_ACCESS_CODE=." ".env" >nul 2>nul
if errorlevel 1 (
  if not defined SHORTSMAKER_ACCESS_CODE (
    echo No access code in .env. Anyone on your Tailscale network could open the app.
    set /p SHORTSMAKER_ACCESS_CODE=Type an access code ^(letters and digits^), then Enter: 
  )
)

rem HTTPS link for the phone (Tailscale must be installed and logged in).
where tailscale >nul 2>nul
if not errorlevel 1 (
  tailscale serve --bg 8000 >nul 2>nul
  echo Phone address: run  tailscale serve status  to see your https://...ts.net link
) else (
  echo Tailscale not found - phone access needs it. This PC can still use http://127.0.0.1:8000
)

rem Open the browser a few seconds after the server starts.
start "" cmd /c "timeout /t 4 /nobreak >nul & start http://127.0.0.1:8000"

echo.
echo Starting server... Close this window to stop it.
".venv\Scripts\python.exe" -m shortsmaker web --host 127.0.0.1 --port 8000
echo.
echo Server stopped.
pause
