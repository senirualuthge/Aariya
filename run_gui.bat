@echo off
setlocal
REM AI Girl - Full System Launcher (DEV or PROD)
REM
REM Usage:
REM   run_gui.bat           Start in development mode (vite dev server, auto-reload brain)
REM   run_gui.bat --prod    Build the UI and run in production mode (vite preview,
REM                         brain without auto-reload) - same as `npm run dev -- --prod`
REM
REM The dev launcher (scripts\dev.mjs) owns BOTH servers - brain (:8000) and
REM UI (:5173) - so they always start and stop together: no orphaned processes
REM and no "address already in use" collisions (uvicorn must NOT also be started
REM directly here, or the launcher's own brain would crash on the busy port).

set PROD=0
if /i "%~1"=="--prod" set PROD=1
if /i "%~1"=="-p" set PROD=1

echo ========================================
echo   AI Girl - Full System Launcher
echo ========================================
if %PROD%==1 (echo   Mode: PRODUCTION - build + preview) else (echo   Mode: DEVELOPMENT - dev server)
echo ========================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Please install Python 3.10+
    pause
    exit /b 1
)

REM Check Node
npm --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js/npm not found. Please install Node.js
    pause
    exit /b 1
)

echo [1/3] Starting servers...
REM --clean makes the launcher kill any stale listeners on :8000/:5173 first,
REM so a crashed previous session can't break this launch.
if %PROD%==1 (
    echo   Building UI for production (first run may take a minute)...
    start "AI Girl - Servers (PROD)" cmd /k "cd /d "%~dp0" && npm run dev -- --clean --prod"
) else (
    echo   Starting dev servers...
    start "AI Girl - Servers (DEV)" cmd /k "cd /d "%~dp0" && npm run dev -- --clean"
)

echo [2/3] Waiting for servers to be ready...
REM Poll until both ports accept TCP connections (up to ~2 minutes - the prod
REM build alone takes ~30s). Uses a raw TCP connect so an HTTP 404 on the brain
REM root still counts as "up".
set /a TRIES=0
:waitloop
set /a TRIES+=1
if %TRIES% gtr 120 (
    echo   WARNING: servers did not respond within 2 minutes - launching anyway.
    goto launch
)
timeout /t 1 /nobreak >nul
powershell -NoProfile -Command "$b=$false; $u=$false; try { $c=New-Object System.Net.Sockets.TcpClient; $c.Connect('127.0.0.1',8000); $c.Close(); $b=$true } catch {}; try { $c=New-Object System.Net.Sockets.TcpClient; $c.Connect('127.0.0.1',5173); $c.Close(); $u=$true } catch {}; if ($b -and $u) { exit 0 } else { exit 1 }" >nul 2>&1
if errorlevel 1 goto waitloop

:launch
echo   Servers are ready.
echo.
echo [3/3] Launching Electron GUI...
echo.
cd /d "%~dp0"
npm run gui

echo.
echo ========================================
echo   AI Girl has been closed
echo ========================================
pause
