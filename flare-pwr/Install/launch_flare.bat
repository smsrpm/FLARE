@echo off
REM ─────────────────────────────────────────────────────────────────
REM  FLARE Launcher
REM  Opens two PowerShell windows:
REM    1. Activates/creates flare_env and starts Streamlit on port 8501
REM    2. Starts ngrok tunnel to port 8501
REM
REM  Place this file and the two .ps1 files in the FLARE\Install folder.
REM  The launcher finds its own location automatically — no hardcoded
REM  paths, so the folder can be moved or renamed freely.
REM ─────────────────────────────────────────────────────────────────

REM %~dp0 = the directory containing this .bat file (normally FLARE\Install\)
set "INSTALL_DIR=%~dp0"

REM ── Python preflight ─────────────────────────────────────────────
REM If flare_env already exists, use its Python and do not require a global
REM python command.  If flare_env does not exist yet, the startup script must
REM be able to run "python -m venv ...", so python.exe must be installed and
REM its directory must be listed in the Windows PATH environment variable.
set "FLARE_ENV_PY=%INSTALL_DIR%flare_env\Scripts\python.exe"

if exist "%FLARE_ENV_PY%" goto PYTHON_OK

where python.exe >nul 2>nul
if errorlevel 1 (
    echo.
    echo ERROR: Python was not found.
    echo.
    echo FLARE can create its virtual environment ^(flare_env^) and install Python
    echo packages, but Python itself must already be installed first.
    echo.
    echo Please install Python 3.10 or newer.  Also ensure that the folder
    echo containing python.exe is included in the PATH environment variable.
    echo.
    echo After installing Python, open a new PowerShell or Command Prompt and verify:
    echo     python --version
    echo.
    pause
    exit /b 1
)

python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if errorlevel 1 (
    echo.
    echo ERROR: Python was found, but it is older than Python 3.10 or could not run.
    echo.
    echo Please install Python 3.10 or newer and ensure that the correct python.exe
    echo directory appears before older Python installations in the PATH environment
    echo variable.
    echo.
    python --version
    echo.
    pause
    exit /b 1
)

:PYTHON_OK

REM ── Window 1: Streamlit ──────────────────────────────────────────
start "FLARE - Streamlit" powershell.exe -NoExit -ExecutionPolicy Bypass -File "%INSTALL_DIR%start_streamlit.ps1"

REM ── Brief pause so Streamlit can bind to port 8501 first ─────────
timeout /t 4 /nobreak > nul

REM ── Window 2: ngrok ─────────────────────────────────────────────
REM ── start "FLARE - ngrok" powershell.exe -NoExit -ExecutionPolicy Bypass -File "%INSTALL_DIR%start_ngrok.ps1"

exit /b 0
