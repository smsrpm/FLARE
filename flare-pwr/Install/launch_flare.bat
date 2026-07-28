@echo off
REM -----------------------------------------------------------------
REM  FLARE Launcher
REM  Opens two PowerShell windows:
REM    1. Activates/creates flare_env and starts Streamlit on port 8501
REM    2. Starts ngrok tunnel to port 8501  (currently disabled below)
REM
REM  One environment (flare_env) serves the whole FLARE suite, including
REM  the Dose Map screen of the Plant Analyzer.  start_streamlit.ps1
REM  creates the environment if it is absent and repairs it if it is
REM  missing libraries, so an environment built by an earlier FLARE
REM  release picks up the Dose Map packages automatically.
REM
REM  Place this file and the two .ps1 files in the FLARE\Install folder.
REM  The launcher finds its own location automatically - no hardcoded
REM  paths, so the folder can be moved or renamed freely.
REM -----------------------------------------------------------------

REM %~dp0 = the directory containing this .bat file (normally FLARE\Install\)
set "INSTALL_DIR=%~dp0"

REM -- Python preflight ---------------------------------------------
REM If flare_env already exists, use its Python and do not require a global
REM python command.  If flare_env does not exist yet, the startup script must
REM be able to run "python -m venv ...", so python.exe must be installed and
REM its directory must be listed in the Windows PATH environment variable.
REM
REM Environment search order matches start_streamlit.ps1:
REM   %FLARE_ENV%  ->  Install\flare_env  ->  %USERPROFILE%\flare_env
if defined FLARE_ENV (
    if exist "%FLARE_ENV%\Scripts\python.exe" goto PYTHON_OK
)
if exist "%INSTALL_DIR%flare_env\Scripts\python.exe"    goto PYTHON_OK
if exist "%USERPROFILE%\flare_env\Scripts\python.exe"   goto PYTHON_OK

where python.exe >nul 2>nul
if errorlevel 1 (
    echo.
    echo ERROR: Python was not found.
    echo.
    echo FLARE can create its virtual environment ^(flare_env^) and install Python
    echo packages, but Python itself must already be installed first.
    echo.
    echo Please install Python 3.11 or 3.12 ^(64-bit^).  Also ensure that the folder
    echo containing python.exe is included in the PATH environment variable.
    echo.
    echo After installing Python, open a new PowerShell or Command Prompt and verify:
    echo     python --version
    echo.
    pause
    exit /b 1
)

REM Python 3.11 is the floor.  The Dose Map screen and its Streamlit
REM component stack require it, and flare_analyzer.py uses st.context.headers
REM which needs Streamlit 1.37 or newer.
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
if errorlevel 1 (
    echo.
    echo ERROR: Python was found, but it is older than Python 3.11 or could not run.
    echo.
    echo FLARE requires Python 3.11 or 3.12.  Please install a supported version and
    echo ensure that the correct python.exe directory appears before older Python
    echo installations in the PATH environment variable.
    echo.
    python --version
    echo.
    pause
    exit /b 1
)

:PYTHON_OK

REM -- Window 1: Streamlit ------------------------------------------
start "FLARE - Streamlit" powershell.exe -NoExit -ExecutionPolicy Bypass -File "%INSTALL_DIR%start_streamlit.ps1"

REM -- Brief pause so Streamlit can bind to port 8501 first ---------
timeout /t 4 /nobreak > nul

REM -- Window 2: ngrok ---------------------------------------------
REM -- start "FLARE - ngrok" powershell.exe -NoExit -ExecutionPolicy Bypass -File "%INSTALL_DIR%start_ngrok.ps1"

exit /b 0
