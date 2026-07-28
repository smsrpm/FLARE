# start_streamlit.ps1
# -----------------------------------------------------------------------------
# Launches the FLARE Streamlit app.
#
# One environment (flare_env) serves the whole FLARE suite, including the
# Dose Map screen of the Plant Analyzer.  The Dose Map's former private .venv
# is no longer used.
#
# If flare_env is missing it is created and all required packages installed.
# If flare_env already exists it is CHECKED and REPAIRED before launch, so an
# environment built by an earlier FLARE release picks up the Dose Map
# libraries without being rebuilt from scratch.
#
# No hardcoded paths - uses $PSScriptRoot throughout.
# -----------------------------------------------------------------------------

$InstallDir = $PSScriptRoot
$FlareDir   = Split-Path -Parent $InstallDir

# -- Helper: coloured status lines --------------------------------------------
function Write-Step { param($msg) Write-Host "  $msg"        -ForegroundColor Cyan   }
function Write-OK   { param($msg) Write-Host "  OK: $msg"     -ForegroundColor Green  }
function Write-Warn { param($msg) Write-Host "  NOTE: $msg"   -ForegroundColor Yellow }
function Write-Fail { param($msg) Write-Host "  ERROR: $msg"  -ForegroundColor Red    }

Write-Host ""
Write-Host "  FLARE Launcher" -ForegroundColor Yellow
Write-Host "  Working directory: $InstallDir"
Write-Host ""

# -- Resolve the environment location -----------------------------------------
# Order: %FLARE_ENV%, then Install\flare_env (standard), then the legacy
# %USERPROFILE%\flare_env described in older revisions of the README.
if ($env:FLARE_ENV) {
    $EnvPath = $env:FLARE_ENV
}
elseif (Test-Path (Join-Path $InstallDir "flare_env\Scripts\python.exe")) {
    $EnvPath = Join-Path $InstallDir "flare_env"
}
elseif (Test-Path (Join-Path $env:USERPROFILE "flare_env\Scripts\python.exe")) {
    $EnvPath = Join-Path $env:USERPROFILE "flare_env"
    Write-Warn "Using legacy environment at $EnvPath"
}
else {
    $EnvPath = Join-Path $InstallDir "flare_env"
}

$PythonExe = Join-Path $EnvPath "Scripts\python.exe"
# The merged requirements live in requirements.txt at the FLARE root; it is
# named that way so Streamlit Community Cloud recognises it. The former
# requirements-flare.txt name is still accepted so a partly updated
# installation keeps working.
$ReqFile = Join-Path $FlareDir "requirements.txt"
if (-not (Test-Path $ReqFile)) {
    $LegacyReqFile = Join-Path $FlareDir "requirements-flare.txt"
    if (Test-Path $LegacyReqFile) { $ReqFile = $LegacyReqFile }
}

Set-Location $InstallDir

# -- Fallback package list, used only if the requirements file is absent ------
$Packages = @(
    # Core FLARE suite
    "numpy", "scipy", "pandas", "openpyxl", "matplotlib",
    "XSteamPython", "plotly", "reportlab", "python-docx", "anthropic",
    # Streamlit UI (>=1.37: flare_analyzer.py reads st.context.headers)
    "streamlit>=1.37",
    # Dose Map screen
    "folium", "streamlit-folium>=0.15.1", "branca", "Pillow",
    "streamlit-current-location",
    # National population database builder
    "duckdb", "dbfread"
)

# -- Import name -> pip name, used for the health check ------------------------
# Keys are module names as imported; values are what pip installs.
$ImportMap = [ordered]@{
    "streamlit"                  = "streamlit>=1.37"
    "pandas"                     = "pandas"
    "numpy"                      = "numpy"
    "scipy"                      = "scipy"
    "openpyxl"                   = "openpyxl"
    "matplotlib"                 = "matplotlib"
    "plotly"                     = "plotly"
    "docx"                       = "python-docx"
    "reportlab"                  = "reportlab"
    "anthropic"                  = "anthropic"
    "XSteamPython"               = "XSteamPython"
    "folium"                     = "folium"
    "streamlit_folium"           = "streamlit-folium>=0.15.1"
    "branca"                     = "branca"
    "PIL"                        = "Pillow"
    "streamlit_current_location" = "streamlit-current-location"
    "duckdb"                     = "duckdb"
    "dbfread"                    = "dbfread"
}

# -----------------------------------------------------------------------------
# Create flare_env if it does not exist
# -----------------------------------------------------------------------------
$FreshBuild = $false

if (Test-Path $PythonExe) {
    Write-OK "flare_env found at $EnvPath"
}
else {
    Write-Host ""
    Write-Host "  flare_env not found - building virtual environment..." -ForegroundColor Yellow
    Write-Host ""

    # Find a system Python 3.11+ to bootstrap the venv with.
    # Each candidate is an explicit executable plus argument list; do not build
    # these by splitting a string, because PowerShell treats 1..0 as a
    # descending range and would silently produce the wrong command line.
    $SystemPython = $null
    $SystemArgs   = @()
    $ver          = $null

    $Candidates = @(
        @{ Exe = "py";      Args = @("-3.12") },
        @{ Exe = "py";      Args = @("-3.11") },
        @{ Exe = "python";  Args = @()        },
        @{ Exe = "python3"; Args = @()        },
        @{ Exe = "py";      Args = @()        }
    )

    foreach ($candidate in $Candidates) {
        try {
            $exe   = $candidate.Exe
            $extra = $candidate.Args
            $ver   = & $exe @extra --version 2>&1
            if ($ver -match "Python 3\.(1[1-9]|[2-9][0-9])") {
                $SystemPython = $exe
                $SystemArgs   = $extra
                break
            }
        } catch {}
    }

    if (-not $SystemPython) {
        Write-Fail "No Python 3.11 or newer installation found on PATH."
        Write-Host ""
        Write-Host "  Install Python 3.11 or 3.12 (64-bit) from https://python.org" -ForegroundColor White
        Write-Host "  and check 'Add Python to PATH' during installation." -ForegroundColor White
        Write-Host ""
        Read-Host "Press Enter to exit"
        exit 1
    }

    Write-Step "Using system Python: $SystemPython ($ver)"
    Write-Step "Creating virtual environment..."

    & $SystemPython @SystemArgs -m venv $EnvPath
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "venv creation failed (exit code $LASTEXITCODE)."
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-OK "Virtual environment created."

    Write-Step "Upgrading pip..."
    & $PythonExe -m pip install --upgrade pip setuptools wheel --quiet
    Write-OK "pip upgraded."

    $FreshBuild = $true
}

# -----------------------------------------------------------------------------
# Check which packages are missing, and install only those
#
# This runs on EVERY launch, not just on a fresh build.  An environment created
# by an earlier FLARE release will not contain the Dose Map libraries, and this
# is what adds them without a rebuild.
# -----------------------------------------------------------------------------
Write-Step "Checking required libraries..."

$ProbeScript = @'
import importlib.util, sys
missing = []
for name in sys.argv[1:]:
    try:
        if importlib.util.find_spec(name) is None:
            missing.append(name)
    except (ImportError, ValueError, AttributeError):
        # A broken or partially removed distribution counts as missing.
        missing.append(name)
print(";".join(missing))
'@

$ProbeFile = Join-Path $env:TEMP "flare_probe_imports.py"
Set-Content -Path $ProbeFile -Value $ProbeScript -Encoding ASCII

$ImportNames = @($ImportMap.Keys)
$MissingRaw  = & $PythonExe $ProbeFile @ImportNames 2>&1
Remove-Item $ProbeFile -ErrorAction SilentlyContinue

$Missing = @()
if ($MissingRaw) {
    $Missing = @(($MissingRaw | Out-String).Trim() -split ";" | Where-Object { $_ })
}

if ($Missing.Count -eq 0) {
    Write-OK "All required libraries present."
}
else {
    Write-Host ""
    Write-Warn "$($Missing.Count) package(s) missing or outdated: $($Missing -join ', ')"
    Write-Host "  Installing (this may take a few minutes)..." -ForegroundColor Yellow
    Write-Host ""

    $Installed = $true

    if (Test-Path $ReqFile) {
        # Preferred path: single source of truth at the FLARE root.
        Write-Step "Installing from $(Split-Path -Leaf $ReqFile) ..."
        & $PythonExe -m pip install -r $ReqFile --quiet
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "Bulk install reported a problem; retrying package by package."
            $Installed = $false
        }
    }
    else {
        Write-Warn "No requirements file found; using the built-in list."
        $Installed = $false
    }

    if (-not $Installed) {
        # Fall back to one-at-a-time so a single bad package cannot block the rest.
        $Failed = @()
        foreach ($mod in $Missing) {
            $pkg = $ImportMap[$mod]
            if (-not $pkg) { $pkg = $mod }
            Write-Step "Installing $pkg ..."
            & $PythonExe -m pip install $pkg --quiet
            if ($LASTEXITCODE -ne 0) {
                Write-Fail "Failed to install $pkg."
                $Failed += $pkg
            }
            else {
                Write-OK "$pkg installed."
            }
        }

        if ($Failed.Count -gt 0) {
            Write-Host ""
            Write-Fail "These packages could not be installed: $($Failed -join ', ')"
            Write-Host "  Install them manually with:" -ForegroundColor White
            Write-Host "    `"$PythonExe`" -m pip install <package>" -ForegroundColor White
            Write-Host ""
            if ($Failed -contains "XSteamPython") {
                Write-Warn "XSteamPython sometimes needs a C compiler on Windows."
                Write-Warn "Without it the simulator will not run, but the Plant"
                Write-Warn "Analyzer Dose Map screen still works."
            }
            Write-Host ""
            $answer = Read-Host "  Continue launching anyway? (Y/N)"
            if ($answer -notmatch "^[Yy]") { exit 1 }
        }
        else {
            Write-Host ""
            Write-OK "All packages installed successfully."
        }
    }
    else {
        Write-Host ""
        Write-OK "All packages installed successfully."
    }
}

# -----------------------------------------------------------------------------
# Dose Map population data
#
# Moved here from Launch_FLARE_Population_Map.bat, which used to be the only
# thing that checked it. The Dose Map needs a valid population database: the
# national Census build if present, otherwise the bundled synthetic
# demonstration database. If the demo database is missing or damaged and no
# national build exists, the Dose Map fails at runtime with no warning at
# launch. Validate it here and rebuild it if necessary.
# -----------------------------------------------------------------------------
$MapDir = Join-Path $FlareDir "flare_population_map"

if (Test-Path (Join-Path $MapDir "flare_map.py")) {
    Write-Step "Checking Dose Map population data..."

    $DataProbe = @'
import os, subprocess, sqlite3, sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
demo = root / "data" / "demo_population.sqlite"
national = root / "data" / "population_2020_national.sqlite"
builder = root / "tools" / "make_demo_database.py"


def validate(path):
    if not path.exists():
        return False, "file is missing"
    try:
        with sqlite3.connect(path) as conn:
            check = conn.execute("PRAGMA quick_check").fetchone()
            if not check or check[0] != "ok":
                return False, "integrity check failed"
            cols = {r[1] for r in conn.execute("PRAGMA table_info(population_cells)")}
            if not {"cell_id", "latitude", "longitude", "population"} <= cols:
                return False, "schema is incomplete"
            n = conn.execute("SELECT COUNT(*) FROM population_cells").fetchone()[0]
            if n <= 0:
                return False, "table is empty"
        return True, f"{n:,} cells"
    except sqlite3.Error as exc:
        return False, str(exc)


(root / "data").mkdir(parents=True, exist_ok=True)

nat_ok, nat_msg = validate(national)
print("NATIONAL|%s|%s" % ("ok" if nat_ok else "absent", nat_msg))

demo_ok, demo_msg = validate(demo)
if not demo_ok:
    if not builder.exists():
        print("DEMO|failed|generator missing: %s" % builder)
        raise SystemExit(1)
    print("DEMO|rebuilding|%s" % demo_msg)
    try:
        demo.unlink(missing_ok=True)
    except OSError as exc:
        print("DEMO|failed|could not remove damaged file: %s" % exc)
        raise SystemExit(1)
    # make_demo_database.py imports flare_map_core, which is not on
    # sys.path when it runs as a script: Python puts the script's own
    # folder (tools/) there, not the package root. Pass the root through
    # PYTHONPATH so the import resolves.
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(root), env.get("PYTHONPATH", "")]).strip(os.pathsep)
    result = subprocess.run([sys.executable, str(builder)], cwd=str(root), env=env)
    if result.returncode != 0:
        print("DEMO|failed|generator returned %d" % result.returncode)
        raise SystemExit(1)
    demo_ok, demo_msg = validate(demo)
    if not demo_ok:
        print("DEMO|failed|rebuilt file is still invalid: %s" % demo_msg)
        raise SystemExit(1)
print("DEMO|ok|%s" % demo_msg)
'@

    $DataProbeFile = Join-Path $env:TEMP "flare_probe_popdata.py"
    Set-Content -Path $DataProbeFile -Value $DataProbe -Encoding UTF8
    $DataLines = & $PythonExe $DataProbeFile $MapDir 2>&1
    $DataExit = $LASTEXITCODE
    Remove-Item $DataProbeFile -ErrorAction SilentlyContinue

    foreach ($line in $DataLines) {
        $parts = ("$line" -split "\|")
        if ($parts.Count -lt 3) { continue }
        switch ($parts[0]) {
            "NATIONAL" {
                if ($parts[1] -eq "ok") { Write-OK "National population database ($($parts[2]))" }
                else { Write-Warn "National database not installed - using synthetic demo data." }
            }
            "DEMO" {
                switch ($parts[1]) {
                    "ok"        { Write-OK   "Demonstration population database ($($parts[2]))" }
                    "rebuilding"{ Write-Warn "Demo database $($parts[2]); rebuilding it..." }
                    "failed"    { Write-Fail "Demo database problem: $($parts[2])" }
                }
            }
        }
    }

    if ($DataExit -ne 0) {
        Write-Host ""
        Write-Fail "The Dose Map has no usable population database."
        Write-Host "  Rebuild it manually with:" -ForegroundColor White
        Write-Host "    `"$PythonExe`" flare_population_map\tools\make_demo_database.py" -ForegroundColor White
        Write-Host "  The other FLARE tools are unaffected." -ForegroundColor White
        Write-Host ""
        $answer = Read-Host "  Continue launching anyway? (Y/N)"
        if ($answer -notmatch "^[Yy]") { exit 1 }
    }
}

# -----------------------------------------------------------------------------
# Report the environment and launch
# -----------------------------------------------------------------------------
$PyVersion = & $PythonExe --version 2>&1
Write-Host ""
Write-Step "Python  : $PyVersion"
Write-Step "Env     : $EnvPath"
Write-Step "Dir     : $FlareDir"

$MapModule = Join-Path $FlareDir "flare_population_map\flare_map.py"
if (Test-Path $MapModule) {
    Write-Step "Screens : Plant Replay + Dose Map"
}
else {
    Write-Warn "flare_population_map not found - Dose Map tab will be unavailable."
}
Write-Host ""

# Leave the console in the FLARE folder, not Install, so the restart command
# below needs no "cd ..". Streamlit is given an absolute script path, so this
# does not change what is launched.
Set-Location $FlareDir

# Put the restart command into the history PSReadLine actually reads.
#
# PowerShell records what the user types, not what a script runs, so the
# launcher's own command never reaches history. After Ctrl-C, pressing Up
# recalls whatever the user last typed - commonly a bare
# "python -m streamlit run flare_home.py", which resolves through PATH and can
# land on an IDE's Python (Spyder, VS Code) that lacks the Dose Map libraries.
#
# Calling AddToHistory from here does not survive: with -File the script runs
# before PSReadLine initialises, and PSReadLine then loads history from its save
# file, discarding anything added in memory beforehand. Appending to that file
# is what makes the entry present when the prompt appears. Both are attempted.
$RestartCommand = '& "' + $PythonExe + '" -m streamlit run flare_home.py'

$HistoryPath = $null
try {
    if (Get-Command Get-PSReadLineOption -ErrorAction SilentlyContinue) {
        $HistoryPath = (Get-PSReadLineOption).HistorySavePath
    }
} catch { }
if (-not $HistoryPath) {
    $HistoryPath = Join-Path $env:APPDATA "Microsoft\Windows\PowerShell\PSReadLine\ConsoleHost_history.txt"
}

$RestartHistoryAdded = $false
try {
    $HistoryDir = Split-Path -Parent $HistoryPath
    if ($HistoryDir -and -not (Test-Path $HistoryDir)) {
        New-Item -ItemType Directory -Path $HistoryDir -Force | Out-Null
    }
    # Skip if it is already the most recent entry, so repeated launches do not
    # accumulate duplicates in the user's history file.
    $LastEntry = $null
    if (Test-Path $HistoryPath) {
        $LastEntry = Get-Content $HistoryPath -Tail 1 -ErrorAction SilentlyContinue
    }
    if ($LastEntry -ne $RestartCommand) {
        Add-Content -Path $HistoryPath -Value $RestartCommand -Encoding UTF8
    }
    $RestartHistoryAdded = $true
} catch {
    # Read-only or redirected profile: the printed command below still works.
}

try {
    if (-not (Get-Module PSReadLine)) {
        Import-Module PSReadLine -ErrorAction SilentlyContinue
    }
    [Microsoft.PowerShell.PSConsoleReadLine]::AddToHistory($RestartCommand)
} catch { }

Write-Host "  Starting FLARE..." -ForegroundColor Yellow
if ($RestartHistoryAdded) {
    Write-Host "  After Ctrl-C, press the Up arrow to restart." -ForegroundColor DarkGray
}
Write-Host "  Restart command: $RestartCommand" -ForegroundColor DarkGray
Write-Host ""

& $PythonExe -m streamlit run "$FlareDir\flare_home.py"
