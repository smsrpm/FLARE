"""Fast national 2020 Census population-grid builder for FLARE.

Pipeline
--------
1. Download one TIGER/Line TABBLOCK20 ZIP at a time.
2. Extract only the DBF member (polygon geometry is never extracted or read).
3. Stream POP20, INTPTLAT20, and INTPTLON20 from the DBF.
4. Aggregate occupied blocks into nominal-kilometer cells in memory per source area.
5. Append those already-aggregated rows to a resumable DuckDB staging database.
6. Perform one national GROUP BY and write the compact SQLite runtime database.

State and territory files are only Census download partitions. The final grid is
national and seam-free because all source areas use the same deterministic grid
indices and are merged before export.
"""
from __future__ import annotations

import argparse
import hashlib
import math
import sqlite3
import tempfile
import time
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Iterator

TIGER_URL = (
    "https://www2.census.gov/geo/tiger/TIGER2020/TABBLOCK20/"
    "tl_2020_{fips}_tabblock20.zip"
)

ALL_FIPS = (
    "01 02 04 05 06 08 09 10 11 12 13 15 16 17 18 19 20 21 22 23 24 25 "
    "26 27 28 29 30 31 32 33 34 35 36 37 38 39 40 41 42 44 45 46 47 48 "
    "49 50 51 53 54 55 56 60 66 69 72 78"
).split()
CORE_FIPS = [f for f in ALL_FIPS if f not in {"60", "66", "69", "78"}]


def _require_build_dependencies():
    try:
        import duckdb  # type: ignore
        from dbfread import DBF  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "National database generation requires duckdb and dbfread. "
            "Install the project requirements first."
        ) from exc
    return duckdb, DBF


def download(url: str, destination: Path, retries: int = 4) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    if destination.exists() and destination.stat().st_size > 0:
        return
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "FLARE-population-builder/2.0"}
            )
            with urllib.request.urlopen(request, timeout=180) as response, partial.open("wb") as out:
                while True:
                    chunk = response.read(8 * 1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
            partial.replace(destination)
            return
        except Exception:
            partial.unlink(missing_ok=True)
            if attempt == retries:
                raise
            time.sleep(2**attempt)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(8 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def grid_index(latitude: float, longitude: float, grid_km: float) -> tuple[int, int]:
    """Return deterministic national grid indices for one coordinate."""
    lat_step = grid_km / 111.32
    lat_idx = math.floor((latitude + 90.0) / lat_step)
    band_lat = -90.0 + (lat_idx + 0.5) * lat_step
    cos_lat = max(math.cos(math.radians(band_lat)), 0.05)
    lon_step = grid_km / (111.32 * cos_lat)
    lon_idx = math.floor((longitude + 180.0) / lon_step)
    return lat_idx, lon_idx


def grid_indices(latitude, longitude, grid_km: float):
    """Vector-compatible helper retained for tests and analysis utilities."""
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("NumPy is required for vector grid calculations") from exc
    latitude = np.asarray(latitude, dtype="float64")
    longitude = np.asarray(longitude, dtype="float64")
    lat_step = grid_km / 111.32
    lat_idx = np.floor((latitude + 90.0) / lat_step).astype("int64")
    band_lat = -90.0 + (lat_idx + 0.5) * lat_step
    cos_lat = np.clip(np.cos(np.radians(band_lat)), 0.05, None)
    lon_step = grid_km / (111.32 * cos_lat)
    lon_idx = np.floor((longitude + 180.0) / lon_step).astype("int64")
    return lat_idx, lon_idx


def aggregate_blocks(blocks, grid_km: float):
    """Compatibility helper for DataFrame-based tests; production uses DBF streaming."""
    import pandas as pd

    lat_idx, lon_idx = grid_indices(blocks.latitude, blocks.longitude, grid_km)
    pop = blocks.population.astype("int64")
    work = pd.DataFrame(
        {
            "lat_idx": lat_idx,
            "lon_idx": lon_idx,
            "population": pop,
            "lat_pop": blocks.latitude.astype(float) * pop,
            "lon_pop": blocks.longitude.astype(float) * pop,
        }
    )
    return work.groupby(["lat_idx", "lon_idx"], as_index=False, sort=False).agg(
        population=("population", "sum"),
        lat_pop=("lat_pop", "sum"),
        lon_pop=("lon_pop", "sum"),
    )


def find_dbf_member(zip_path: Path) -> str:
    with zipfile.ZipFile(zip_path) as archive:
        members = [n for n in archive.namelist() if n.lower().endswith(".dbf")]
    if len(members) != 1:
        raise RuntimeError(f"Expected one DBF in {zip_path}; found {len(members)}")
    return members[0]


def stream_occupied_blocks(zip_path: Path) -> Iterator[tuple[float, float, int]]:
    """Yield occupied block internal points while extracting only the DBF member."""
    _, DBF = _require_build_dependencies()
    member = find_dbf_member(zip_path)
    with tempfile.TemporaryDirectory(prefix="flare_census_dbf_") as temp_dir:
        dbf_path = Path(temp_dir) / Path(member).name
        with zipfile.ZipFile(zip_path) as archive, archive.open(member) as source, dbf_path.open("wb") as out:
            while True:
                chunk = source.read(8 * 1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        table = DBF(
            dbf_path,
            load=False,
            lowernames=False,
            char_decode_errors="ignore",
            ignore_missing_memofile=True,
        )
        required = {"POP20", "INTPTLAT20", "INTPTLON20"}
        missing = required.difference(table.field_names)
        if missing:
            raise RuntimeError(f"Missing required DBF fields in {zip_path.name}: {sorted(missing)}")
        for record in table:
            try:
                population = int(record["POP20"] or 0)
                if population <= 0:
                    continue
                latitude = float(record["INTPTLAT20"])
                longitude = float(record["INTPTLON20"])
            except (TypeError, ValueError):
                continue
            yield latitude, longitude, population


def aggregate_source(zip_path: Path, grid_km: float) -> tuple[dict[tuple[int, int], list[float]], int]:
    """Aggregate one Census source area without retaining block records."""
    cells: dict[tuple[int, int], list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    occupied_blocks = 0
    for latitude, longitude, population in stream_occupied_blocks(zip_path):
        occupied_blocks += 1
        key = grid_index(latitude, longitude, grid_km)
        values = cells[key]
        values[0] += population
        values[1] += latitude * population
        values[2] += longitude * population
    return cells, occupied_blocks


def initialize_staging(path: Path, grid_km: float) -> None:
    duckdb, _ = _require_build_dependencies()
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(path)) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS source_cells(
                   fips VARCHAR, lat_idx BIGINT, lon_idx BIGINT,
                   population BIGINT, lat_pop DOUBLE, lon_pop DOUBLE
               )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS build_progress(
                   fips VARCHAR PRIMARY KEY, source_file VARCHAR,
                   source_sha256 VARCHAR, occupied_blocks BIGINT,
                   occupied_cells BIGINT, processed_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP
               )"""
        )
        conn.execute("CREATE TABLE IF NOT EXISTS metadata(key VARCHAR PRIMARY KEY, value VARCHAR)")
        rows = [
            ("source", "U.S. Census Bureau 2020 TIGER/Line TABBLOCK20 POP20"),
            ("source_year", "2020"),
            ("grid_km", str(grid_km)),
            ("builder_version", "3-direct-dbf-duckdb"),
        ]
        conn.executemany("INSERT OR REPLACE INTO metadata VALUES (?, ?)", rows)


def completed_fips(staging_path: Path) -> set[str]:
    duckdb, _ = _require_build_dependencies()
    with duckdb.connect(str(staging_path), read_only=True) as conn:
        return {row[0] for row in conn.execute("SELECT fips FROM build_progress").fetchall()}


def stage_source(staging_path: Path, fips: str, zip_path: Path, grid_km: float) -> tuple[int, int]:
    duckdb, _ = _require_build_dependencies()
    cells, occupied_blocks = aggregate_source(zip_path, grid_km)
    records = [
        (fips, lat_idx, lon_idx, int(v[0]), v[1], v[2])
        for (lat_idx, lon_idx), v in cells.items()
    ]
    with duckdb.connect(str(staging_path)) as conn:
        conn.execute("BEGIN TRANSACTION")
        conn.execute("DELETE FROM source_cells WHERE fips = ?", [fips])
        if records:
            conn.executemany("INSERT INTO source_cells VALUES (?, ?, ?, ?, ?, ?)", records)
        conn.execute(
            "INSERT OR REPLACE INTO build_progress(fips,source_file,source_sha256,occupied_blocks,occupied_cells) "
            "VALUES (?, ?, ?, ?, ?)",
            [fips, zip_path.name, sha256(zip_path), occupied_blocks, len(records)],
        )
        conn.execute("COMMIT")
    return occupied_blocks, len(records)


def finalize_database(staging_path: Path, output_path: Path) -> None:
    duckdb, _ = _require_build_dependencies()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)

    with duckdb.connect(str(staging_path), read_only=True) as source:
        metadata = dict(source.execute("SELECT key,value FROM metadata").fetchall())
        source_areas = source.execute("SELECT COUNT(*) FROM build_progress").fetchone()[0]
        cursor = source.execute(
            """SELECT lat_idx, lon_idx,
                      SUM(population)::BIGINT AS population,
                      SUM(lat_pop) AS lat_pop,
                      SUM(lon_pop) AS lon_pop
               FROM source_cells
               GROUP BY lat_idx, lon_idx
               ORDER BY lat_idx, lon_idx"""
        )

        with sqlite3.connect(output_path) as out:
            out.executescript(
                """PRAGMA page_size=4096;
                   PRAGMA journal_mode=OFF;
                   PRAGMA synchronous=OFF;
                   PRAGMA temp_store=MEMORY;
                   CREATE TABLE population_cells(
                       cell_id INTEGER PRIMARY KEY,
                       latitude REAL NOT NULL,
                       longitude REAL NOT NULL,
                       population INTEGER NOT NULL CHECK(population > 0)
                   );
                   CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);"""
            )
            cell_id = 0
            total_population = 0
            while True:
                rows = cursor.fetchmany(100_000)
                if not rows:
                    break
                batch = []
                for _lat_idx, _lon_idx, population, lat_pop, lon_pop in rows:
                    cell_id += 1
                    population = int(population)
                    total_population += population
                    batch.append((cell_id, lat_pop / population, lon_pop / population, population))
                out.executemany("INSERT INTO population_cells VALUES (?, ?, ?, ?)", batch)

            metadata.update(
                {
                    "occupied_cells": str(cell_id),
                    "total_population": str(total_population),
                    "source_areas": str(source_areas),
                    "geographic_scope": "50 states, DC, Puerto Rico, American Samoa, Guam, CNMI, USVI",
                }
            )
            out.executemany("INSERT INTO metadata VALUES (?, ?)", metadata.items())
            out.execute("CREATE INDEX idx_population_lat_lon ON population_cells(latitude, longitude)")
            out.commit()
            out.execute("ANALYZE")
            out.execute("VACUUM")


def validate(output_path: Path) -> dict[str, int | float]:
    with sqlite3.connect(output_path) as conn:
        row = conn.execute(
            """SELECT COUNT(*), SUM(population), MIN(latitude), MAX(latitude),
                      MIN(longitude), MAX(longitude) FROM population_cells"""
        ).fetchone()
    cells, population, min_lat, max_lat, min_lon, max_lon = row
    if not cells or not population:
        raise RuntimeError("Generated database is empty")
    if not (-90 <= min_lat <= max_lat <= 90 and -180 <= min_lon <= max_lon <= 180):
        raise RuntimeError("Generated database contains invalid coordinates")
    return {
        "cells": int(cells),
        "population": int(population),
        "min_latitude": float(min_lat),
        "max_latitude": float(max_lat),
        "min_longitude": float(min_lon),
        "max_longitude": float(max_lon),
        "bytes": output_path.stat().st_size,
    }


def resolve_scope(scope: str, states: Iterable[str] | None) -> list[str]:
    if states:
        selected = [str(s).zfill(2) for s in states]
    elif scope == "core":
        selected = CORE_FIPS
    else:
        selected = ALL_FIPS
    unknown = sorted(set(selected).difference(ALL_FIPS))
    if unknown:
        raise ValueError(f"Unsupported Census FIPS codes: {unknown}")
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=["core", "all"], default="all")
    parser.add_argument("--states", nargs="*", help="Optional two-digit FIPS subset")
    parser.add_argument("--grid-km", type=float, default=1.0)
    parser.add_argument("--output", type=Path, default=Path("data/population_2020_national.sqlite"))
    parser.add_argument("--work-dir", type=Path, default=Path("build/population_2020"))
    parser.add_argument("--keep-zips", action="store_true")
    parser.add_argument("--finalize-only", action="store_true")
    args = parser.parse_args()
    if args.grid_km <= 0:
        parser.error("--grid-km must be positive")

    staging_path = args.work_dir / "national_staging.duckdb"
    download_dir = args.work_dir / "downloads"
    initialize_staging(staging_path, args.grid_km)

    if not args.finalize_only:
        selected = resolve_scope(args.scope, args.states)
        done = completed_fips(staging_path)
        for position, fips in enumerate(selected, start=1):
            if fips in done:
                print(f"[{position}/{len(selected)}] {fips}: already complete")
                continue
            zip_path = download_dir / f"tl_2020_{fips}_tabblock20.zip"
            url = TIGER_URL.format(fips=fips)
            print(f"[{position}/{len(selected)}] {fips}: downloading")
            download(url, zip_path)
            print(f"[{position}/{len(selected)}] {fips}: streaming DBF and aggregating")
            blocks, cells = stage_source(staging_path, fips, zip_path, args.grid_km)
            print(f"[{position}/{len(selected)}] {fips}: {blocks:,} occupied blocks -> {cells:,} cells")
            if not args.keep_zips:
                zip_path.unlink(missing_ok=True)

    print("Finalizing national SQLite database")
    finalize_database(staging_path, args.output)
    stats = validate(args.output)
    print("Build complete")
    for key, value in stats.items():
        print(f"  {key}: {value:,}" if isinstance(value, int) else f"  {key}: {value}")


if __name__ == "__main__":
    main()
