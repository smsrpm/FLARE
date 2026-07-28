@echo off
setlocal EnableExtensions

cd /d "%~dp0"
title FLARE National Population Database Builder

echo.
echo ================================================================
echo   FLARE National Population Database Builder
echo ================================================================
echo.

rem ----------------------------------------------------------------
rem Environment search order. FLARE now uses one environment
rem (flare_env) for the whole suite, including this builder:
rem   %FLARE_ENV%  ->  ..\Install\flare_env  ->  %USERPROFILE%\flare_env
rem A private .venv is created only when this package is used on its
rem own, outside a FLARE installation.
rem ----------------------------------------------------------------
set "FLARE_ROOT=%CD%\.."
set "VENV_DIR="
rem The Dose Map no longer keeps its own requirements file; its packages are
rem part of the merged list at the FLARE root.
set "REQ_FILE=%FLARE_ROOT%\requirements.txt"

if defined FLARE_ENV (
    if exist "%FLARE_ENV%\Scripts\python.exe" set "VENV_DIR=%FLARE_ENV%"
)
if not defined VENV_DIR (
    if exist "%FLARE_ROOT%\Install\flare_env\Scripts\python.exe" set "VENV_DIR=%FLARE_ROOT%\Install\flare_env"
)
if not defined VENV_DIR (
    if exist "%USERPROFILE%\flare_env\Scripts\python.exe" set "VENV_DIR=%USERPROFILE%\flare_env"
)
if defined VENV_DIR (
    echo Using the shared FLARE environment:
    echo   %VENV_DIR%
    if exist "%FLARE_ROOT%\requirements.txt" set "REQ_FILE=%FLARE_ROOT%\requirements.txt"
    if not exist "%FLARE_ROOT%\requirements.txt" (
        if exist "%FLARE_ROOT%\requirements-flare.txt" set "REQ_FILE=%FLARE_ROOT%\requirements-flare.txt"
    )
) else (
    echo No flare_env found. Using a private .venv for standalone use.
    set "VENV_DIR=%CD%\.venv"
    if not exist "%REQ_FILE%" (
        if exist "%FLARE_ROOT%\requirements-flare.txt" set "REQ_FILE=%FLARE_ROOT%\requirements-flare.txt"
    )
)

set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "BUILDER=%CD%\tools\build_national_census.py"
set "OUTPUT=%CD%\data\population_2020_national.sqlite"
set "WORK_DIR=%CD%\build\population_2020"
set "STAGING=%WORK_DIR%\national_staging.duckdb"

if not exist "%REQ_FILE%" goto :missing_files
if not exist "%BUILDER%" goto :missing_files

call :ensure_python
if errorlevel 1 goto :failed_pause

echo.
echo This operation downloads official 2020 Census source files and creates:
echo   data\population_2020_national.sqlite
echo.
echo The process is resumable. Running it again continues an interrupted build.
echo Existing completed source areas are not downloaded or processed again.
echo.

if exist "%OUTPUT%" (
    echo An existing national database was found:
    echo   %OUTPUT%
    echo.
    choice /C RCF /N /M "Choose [R]ebuild from scratch, [C]ontinue/resume staging, or [F]inalize existing staging: "
    if errorlevel 3 goto :finalize
    if errorlevel 2 goto :build
    if errorlevel 1 goto :rebuild
) else (
    choice /C YN /N /M "Begin the national Census database build now? [Y/N]: "
    if errorlevel 2 goto :cancelled
)

:build
echo.
echo Building/resuming the national database...
"%VENV_PYTHON%" "%BUILDER%" --scope all --grid-km 1.0 --output "%OUTPUT%" --work-dir "%WORK_DIR%"
if errorlevel 1 goto :build_failed
goto :success

:rebuild
echo.
echo Removing the current runtime database and national staging database...
del /q "%OUTPUT%" >nul 2>&1
del /q "%STAGING%" >nul 2>&1
goto :build

:finalize
echo.
echo Recreating the SQLite runtime database from existing staging data...
"%VENV_PYTHON%" "%BUILDER%" --scope all --grid-km 1.0 --output "%OUTPUT%" --work-dir "%WORK_DIR%" --finalize-only
if errorlevel 1 goto :build_failed
goto :success

:ensure_python
if exist "%VENV_PYTHON%" goto :install_requirements

set "BOOTSTRAP_PYTHON="
where py >nul 2>&1
if not errorlevel 1 (
    py -3.11 -c "import sys; assert sys.version_info >= (3,11)" >nul 2>&1
    if not errorlevel 1 set "BOOTSTRAP_PYTHON=py -3.11"
)
if not defined BOOTSTRAP_PYTHON (
    where python >nul 2>&1
    if not errorlevel 1 (
        python -c "import sys; assert sys.version_info >= (3,11)" >nul 2>&1
        if not errorlevel 1 set "BOOTSTRAP_PYTHON=python"
    )
)
if not defined BOOTSTRAP_PYTHON (
    echo ERROR: Python 3.11 or newer was not found.
    echo Install 64-bit Python from https://www.python.org/downloads/windows/
    exit /b 1
)

echo Creating private Python environment in .venv ...
%BOOTSTRAP_PYTHON% -m venv "%VENV_DIR%"
if errorlevel 1 exit /b 1

:install_requirements
echo Checking builder libraries...
rem The builder needs duckdb and dbfread. When the shared flare_env already
rem has them, skip installation so an ordinary build does not disturb the
rem environment the rest of FLARE is running on.
"%VENV_PYTHON%" -c "import duckdb, dbfread" >nul 2>&1
if not errorlevel 1 (
    echo Builder libraries already present.
    exit /b 0
)
"%VENV_PYTHON%" -m ensurepip --upgrade >nul 2>&1
"%VENV_PYTHON%" -m pip install --disable-pip-version-check --quiet -r "%REQ_FILE%"
if errorlevel 1 (
    echo Initial package installation failed. Retrying after upgrading pip...
    "%VENV_PYTHON%" -m pip install --upgrade pip setuptools wheel
    if errorlevel 1 exit /b 1
    "%VENV_PYTHON%" -m pip install -r "%REQ_FILE%"
    if errorlevel 1 exit /b 1
)
exit /b 0

:success
echo.
echo ================================================================
echo National population database completed successfully.
echo Output:
echo   %OUTPUT%
echo ================================================================
echo.
pause
exit /b 0

:cancelled
echo Build cancelled.
exit /b 0

:missing_files
echo ERROR: Required builder files are missing.
echo Keep this BAT file in the project folder with:
echo   ..\requirements.txt  ^(at the FLARE root^)
echo   tools\build_national_census.py
goto :failed_pause

:build_failed
echo.
echo ERROR: The national population database build did not complete.
echo The build is resumable; run this file again after correcting the issue.
goto :failed_pause

:failed_pause
echo.
pause
exit /b 1
