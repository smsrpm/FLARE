"""
verify_flare_environment.py - FLARE installation and environment check.

Verifies that one environment (flare_env) can serve the whole FLARE suite,
including the Dose Map screen of the Plant Analyzer.

Run it with the environment's own interpreter, for example:

    Install\\flare_env\\Scripts\\python.exe verify_flare_environment.py

Exit code 0 means FLARE can start.  Exit code 1 means something required is
missing; the report says what and how to fix it.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
POPMAP = ROOT / "flare_population_map"

# --------------------------------------------------------------------------
# What must be present
# --------------------------------------------------------------------------

# (module name as imported, pip name, what breaks without it, required?)
PACKAGES = [
    ("streamlit", "streamlit>=1.37", "the entire user interface", True),
    ("pandas", "pandas", "all data handling", True),
    ("numpy", "numpy", "all numerical work", True),
    ("scipy", "scipy", "statistical functions", True),
    ("openpyxl", "openpyxl", "reading and writing .xlsx decks", True),
    ("matplotlib", "matplotlib", "figure generation", True),
    ("plotly", "plotly", "interactive charts", True),
    ("docx", "python-docx", "Word report generation", True),
    ("reportlab", "reportlab", "PDF report generation", True),
    ("XSteamPython", "XSteamPython", "steam properties (simulator)", True),
    ("anthropic", "anthropic", "the FLARE Assistant narrative", False),
    ("folium", "folium", "the Dose Map basemap", True),
    ("streamlit_folium", "streamlit-folium>=0.15.1", "the Dose Map viewport", True),
    ("branca", "branca", "Dose Map overlays and legends", True),
    ("PIL", "Pillow", "Dose Map raster overlays", True),
    (
        "streamlit_current_location",
        "streamlit-current-location",
        "Dose Map browser geolocation",
        True,
    ),
    ("duckdb", "duckdb", "the national population database builder", False),
    ("dbfread", "dbfread", "the national population database builder", False),
]

# (path, what it provides, required?)
FILES = [
    (ROOT / "flare_home.py", "FLARE Home screen and tool router", True),
    (ROOT / "flare_sim.py", "simulation engine", True),
    (ROOT / "flare_analyzer.py", "Plant Analyzer - Plant Replay screen", True),
    (
        ROOT / "flare_analyzer_shell.py",
        "Plant Analyzer tab shell (Plant Replay + Dose Map)",
        False,
    ),
    (POPMAP / "flare_map.py", "Plant Analyzer - Dose Map screen", False),
    (POPMAP / "flare_map_core" / "__init__.py", "Dose Map calculation package", False),
    (
        POPMAP / "flare_map_components" / "radius_commit" / "index.html",
        "Dose Map radius-commit component",
        False,
    ),
]

NATIONAL_DB = POPMAP / "data" / "population_2020_national.sqlite"
DEMO_DB = POPMAP / "data" / "demo_population.sqlite"


def check_python() -> list[str]:
    problems: list[str] = []
    major, minor = sys.version_info[:2]
    print(f"  Python {major}.{minor} at {sys.executable}")
    if (major, minor) < (3, 11):
        problems.append(
            f"Python {major}.{minor} is too old. FLARE requires Python 3.11 or 3.12."
        )
    return problems


def check_packages() -> tuple[list[str], list[str]]:
    problems: list[str] = []
    warnings: list[str] = []
    for module, pip_name, purpose, required in PACKAGES:
        try:
            found = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            found = False
        if found:
            print(f"  ok       {module}")
        elif required:
            print(f"  MISSING  {module}  ({purpose})")
            problems.append(f"pip install {pip_name}          # needed for {purpose}")
        else:
            print(f"  absent   {module}  (optional - {purpose})")
            warnings.append(f"pip install {pip_name}          # optional: {purpose}")
    return problems, warnings


def check_files() -> tuple[list[str], list[str]]:
    problems: list[str] = []
    warnings: list[str] = []
    for path, purpose, required in FILES:
        try:
            rel = path.relative_to(ROOT)
        except ValueError:
            rel = path
        if path.exists():
            print(f"  ok       {rel}")
        elif required:
            print(f"  MISSING  {rel}  ({purpose})")
            problems.append(f"{rel} is missing - {purpose}")
        else:
            print(f"  absent   {rel}  (optional - {purpose})")
            warnings.append(f"{rel} is absent - {purpose} will be unavailable")
    return problems, warnings


def validate_population_db(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "file is missing"
    try:
        with sqlite3.connect(path) as conn:
            check = conn.execute("PRAGMA quick_check").fetchone()
            if not check or check[0] != "ok":
                return False, f"SQLite quick_check returned {check}"
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(population_cells)")
            }
            required = {"cell_id", "latitude", "longitude", "population"}
            if not required.issubset(columns):
                return False, "population_cells schema is incomplete"
            count = conn.execute("SELECT COUNT(*) FROM population_cells").fetchone()[0]
            if count <= 0:
                return False, "population_cells is empty"
        return True, f"{count:,} occupied cells"
    except sqlite3.Error as exc:
        return False, f"SQLite error: {exc}"


def check_databases() -> list[str]:
    warnings: list[str] = []
    if not POPMAP.exists():
        print("  absent   flare_population_map  (Dose Map not installed)")
        return warnings

    national_ok, national_msg = validate_population_db(NATIONAL_DB)
    demo_ok, demo_msg = validate_population_db(DEMO_DB)

    if national_ok:
        print(f"  ok       national population database  ({national_msg})")
    else:
        print(f"  absent   national population database  ({national_msg})")
        warnings.append(
            "The national Census database is not installed. The Dose Map will open "
            "with the synthetic demonstration data. Build the national "
            "database with flare_population_map\\Build_National_Population_Database.bat"
        )

    if demo_ok:
        print(f"  ok       demo population database  ({demo_msg})")
    elif not national_ok:
        print(f"  MISSING  demo population database  ({demo_msg})")
        warnings.append(
            "Neither population database is usable. Regenerate the demonstration "
            "database with: python flare_population_map\\tools\\make_demo_database.py"
        )
    return warnings


def main() -> int:
    print()
    print("=" * 68)
    print("  FLARE environment verification")
    print("=" * 68)

    print("\nInterpreter")
    problems = check_python()

    print("\nLibraries")
    pkg_problems, pkg_warnings = check_packages()
    problems += pkg_problems

    print("\nProject files")
    file_problems, file_warnings = check_files()
    problems += file_problems

    print("\nPopulation data")
    db_warnings = check_databases()

    warnings = pkg_warnings + file_warnings + db_warnings

    print()
    print("=" * 68)
    if problems:
        print("  RESULT: FLARE cannot start yet.")
        print("=" * 68)
        print("\nRequired fixes:\n")
        for item in problems:
            print(f"  - {item}")
        if warnings:
            print("\nAlso note:\n")
            for item in warnings:
                print(f"  - {item}")
        print()
        return 1

    print("  RESULT: environment OK - FLARE can start.")
    print("=" * 68)
    if warnings:
        print("\nOptional items:\n")
        for item in warnings:
            print(f"  - {item}")
    print("\nLaunch with:  Install\\launch_flare.bat")
    print("The Plant Analyzer opens with two tabs: Plant Replay and Dose Map.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
