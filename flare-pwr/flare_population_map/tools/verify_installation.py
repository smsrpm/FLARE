"""Validate and repair the local FLARE Population Map installation.

Invoked by Launch_FLARE_Population_Map.bat after the virtual environment and
requirements have been prepared. Returns a nonzero exit code on an unrecoverable
problem so the launcher can stop without opening a broken Streamlit session.
"""
from __future__ import annotations

import importlib
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = [
    ROOT / "flare_map.py",
    ROOT / "flare_map_core" / "__init__.py",
    ROOT / "flare_map_core" / "core.py",
    ROOT / "flare_map_core" / "database.py",
    ROOT / "flare_map_core" / "map_view.py",
    ROOT / "tools" / "make_demo_database.py",
    ROOT / "tools" / "build_national_census.py",
    ROOT / "Build_National_Population_Database.bat",
]
IMPORTS = [
    "streamlit",
    "streamlit_folium",
    "folium",
    "pandas",
    "numpy",
    "duckdb",
    "dbfread",
]
NATIONAL_DB = ROOT / "data" / "population_2020_national.sqlite"
DEMO_DB = ROOT / "data" / "demo_population.sqlite"


def fail(message: str) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return 1


def validate_database(path: Path) -> tuple[bool, str]:
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
    except sqlite3.Error as exc:
        return False, str(exc)
    return True, "ok"


def main() -> int:
    print("Checking project files...")
    missing = [str(path.relative_to(ROOT)) for path in REQUIRED_FILES if not path.exists()]
    if missing:
        return fail("Required project files are missing: " + ", ".join(missing))

    print("Checking Python imports...")
    failed_imports: list[str] = []
    for name in IMPORTS:
        try:
            importlib.import_module(name)
        except Exception as exc:  # report broken binary installs as well as ImportError
            failed_imports.append(f"{name} ({exc})")
    if failed_imports:
        return fail("Required libraries could not be imported: " + "; ".join(failed_imports))

    print("Checking application syntax...")
    compile_result = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", str(ROOT / "flare_map.py"), str(ROOT / "flare_map_core")],
        cwd=ROOT,
        check=False,
    )
    if compile_result.returncode != 0:
        return fail("One or more application files failed Python compilation.")

    data_dir = ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    national_ok, national_reason = validate_database(NATIONAL_DB)
    if national_ok:
        print(f"National population database verified: {NATIONAL_DB.name}")
    else:
        print(f"National population database not available ({national_reason}).")
        print("The launcher will use the bundled synthetic demonstration database.")

    demo_ok, demo_reason = validate_database(DEMO_DB)
    if not demo_ok:
        print(f"Demo database needs repair ({demo_reason}); regenerating it...")
        try:
            DEMO_DB.unlink(missing_ok=True)
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "make_demo_database.py")],
                cwd=ROOT,
                check=False,
                # make_demo_database.py imports flare_map_core, which is not on
                # sys.path when it runs as a script: Python puts the script's own
                # folder (tools/) there, not the package root. Without this the
                # rebuild always failed with ModuleNotFoundError.
                env={**os.environ, "PYTHONPATH": os.pathsep.join(
                    [str(ROOT), os.environ.get("PYTHONPATH", "")]).strip(os.pathsep)},
            )
        except OSError as exc:
            return fail(f"Could not regenerate the demo database: {exc}")
        if result.returncode != 0:
            return fail("The demo database generator failed.")
        demo_ok, demo_reason = validate_database(DEMO_DB)
        if not demo_ok:
            return fail(f"The regenerated demo database is invalid: {demo_reason}")
    print(f"Demo database verified: {DEMO_DB.name}")

    print("Installation verification completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
