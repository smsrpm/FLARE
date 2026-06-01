# start_streamlit.ps1
# ─────────────────────────────────────────────────────────────────────────────
# Launches the FLARE Streamlit app.
# If flare_env is missing it is created and all required packages are installed
# before launch.  No hardcoded paths - uses $PSScriptRoot throughout.
# ─────────────────────────────────────────────────────────────────────────────

$InstallDir = $PSScriptRoot
$FlareDir   = Split-Path -Parent $InstallDir
$EnvPath   = Join-Path $InstallDir "flare_env"
$PythonExe = Join-Path $EnvPath  "Scripts\python.exe"
$PipExe    = Join-Path $EnvPath  "Scripts\pip.exe"

Set-Location $InstallDir

# ── Packages required by FLARE ───────────────────────────────────────────────
$Packages = @(
    "streamlit",
    "pandas",
    "numpy",
    "openpyxl",
    "matplotlib",
    "XSteamPython",
    "plotly",
    "python-dox",
    "reportlab"
)

# ── Helper: write coloured status lines ──────────────────────────────────────
function Write-Step  { param($msg) Write-Host "  $msg" -ForegroundColor Cyan    }
function Write-OK    { param($msg) Write-Host "  OK: $msg" -ForegroundColor Green  }
function Write-Fail  { param($msg) Write-Host "  ERROR: $msg" -ForegroundColor Red }

Write-Host ""
Write-Host "  FLARE Launcher" -ForegroundColor Yellow
Write-Host "  Working directory: $InstallDir"
Write-Host ""

# ── Check / build flare_env ───────────────────────────────────────────────────
if (Test-Path $PythonExe) {
    Write-OK "flare_env found at $EnvPath"
} else {
    Write-Host ""
    Write-Host "  flare_env not found - building virtual environment..." `
        -ForegroundColor Yellow
    Write-Host ""

    # Find a system Python 3 to bootstrap the venv with
    $SystemPython = $null
    foreach ($candidate in @("python", "python3", "py")) {
        try {
            $ver = & $candidate --version 2>&1
            if ($ver -match "Python 3") {
                $SystemPython = $candidate
                break
            }
        } catch {}
    }

    if (-not $SystemPython) {
        Write-Fail "No Python 3 installation found on PATH."
        Write-Host ""
        Write-Host "  Please install Python 3.9 or later from https://python.org" `
            -ForegroundColor White
        Write-Host "  Make sure to check 'Add Python to PATH' during installation." `
            -ForegroundColor White
        Write-Host ""
        Read-Host "Press Enter to exit"
        exit 1
    }

    Write-Step "Using system Python: $SystemPython ($ver)"
    Write-Step "Creating virtual environment..."

    & $SystemPython -m venv $EnvPath
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "venv creation failed (exit code $LASTEXITCODE)."
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-OK "Virtual environment created."

    # Upgrade pip first
    Write-Step "Upgrading pip..."
    & $PythonExe -m pip install --upgrade pip --quiet
    Write-OK "pip upgraded."

    # Install all required packages
    Write-Host ""
    Write-Host "  Installing required packages (this may take a few minutes)..." `
        -ForegroundColor Yellow
    Write-Host ""

    foreach ($pkg in $Packages) {
        Write-Step "Installing $pkg..."
        & $PipExe install $pkg --quiet
        if ($LASTEXITCODE -ne 0) {
            Write-Fail "Failed to install $pkg."
            Write-Host "  Try running manually: $PipExe install $pkg" `
                -ForegroundColor White
            Read-Host "Press Enter to exit"
            exit 1
        }
        Write-OK "$pkg installed."
    }

    Write-Host ""
    Write-Host "  All packages installed successfully." -ForegroundColor Green
    Write-Host ""
}

# ── Verify environment ────────────────────────────────────────────────────────
$PyVersion = & $PythonExe --version 2>&1
Write-Step "Python  : $PyVersion"
Write-Step "Env     : $EnvPath"
Write-Step "Dir     : $FlareDir"
Write-Host ""

# ── Launch FLARE ──────────────────────────────────────────────────────────────
Write-Host "  Starting FLARE..." -ForegroundColor Yellow
Write-Host ""

& $PythonExe -m streamlit run "$FlareDir\flare_home.py"
