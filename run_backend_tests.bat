@echo off
REM run_backend_tests.bat — run the Python backend test suite with pytest.
REM Windows counterpart of run_backend_tests.sh. The suite in server\tests\ is
REM pytest-based; pytest is a declared venv dependency (server\requirements.txt).
setlocal

cd /d "%~dp0"

REM Resolve the project venv python. server\.venv is the canonical environment
REM (scripts\backend.sh, scripts\scan_deps.sh and CI all target it); a
REM root-level venv\ is only a legacy fallback for older checkouts.
set "PY=python"
if exist "server\.venv\Scripts\python.exe" set "PY=server\.venv\Scripts\python.exe"
if not exist "server\.venv\Scripts\python.exe" if exist "venv\Scripts\python.exe" set "PY=venv\Scripts\python.exe"

REM pytest is required (declared in server\requirements.txt)
"%PY%" -c "import pytest" >nul 2>&1
if errorlevel 1 (
    echo ERROR: pytest is required to run the backend tests but is not in this venv.
    echo        Install it with:  "%PY%" -m pip install pytest
    exit /b 1
)

"%PY%" -m pytest
exit /b %errorlevel%
