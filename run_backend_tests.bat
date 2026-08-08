@echo off
REM run_backend_tests.bat — run the Python backend test suite with pytest.
REM Windows counterpart of run_backend_tests.sh. The suite in server\tests\ is
REM pytest-based; pytest is a declared venv dependency (server\requirements.txt).
setlocal

cd /d "%~dp0"

REM Resolve the project venv python (root-level venv\ is the convention)
set "PY=python"
if exist "venv\Scripts\python.exe" set "PY=venv\Scripts\python.exe"

REM pytest is required (declared in server\requirements.txt)
"%PY%" -c "import pytest" >nul 2>&1
if errorlevel 1 (
    echo ERROR: pytest is required to run the backend tests but is not in this venv.
    echo        Install it with:  "%PY%" -m pip install pytest
    exit /b 1
)

"%PY%" -m pytest
exit /b %errorlevel%
