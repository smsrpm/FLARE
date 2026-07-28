"""Build FLARE's compact grid from official 2020 Census products.

Workflow per state:
  1. Download 2020 TIGER/Line tabulation-block shapefile.  Its attributes include
     GEOID20 and Census internal-point latitude/longitude.
  2. Query P.L. 94-171 total population (P1_001N) by county and block.
  3. Join by GEOID20, discard zero-population blocks, and aggregate to a regular
     latitude/longitude grid.

This utility is a development-time builder; end users only need the resulting
SQLite database. Network access is required.
"""
from __future__ import annotations

import argparse
import io
import sqlite3
import urllib.request
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from flare_map_core.database import initialize_database

CENSUS_API = "https://api.census.gov/data/2020/dec/pl"
TIGER_URL = "https://www2.census.gov/geo/tiger/TIGER2020PL/STATE/{fips}/tl_2020_{fips}_tabblock20.zip"


def json_get(url: str):
    with urllib.request.urlopen(url, timeout=120) as response:
        import json
        return json.load(response)


def county_codes(state_fips: str) -> list[str]:
    rows = json_get(f"{CENSUS_API}?get=NAME&for=county:*&in=state:{state_fips}")
    header = rows[0]
    return [dict(zip(header, row))["county"] for row in rows[1:]]


def block_population(state_fips: str) -> pd.DataFrame:
    frames = []
    for county in county_codes(state_fips):
        url = f"{CENSUS_API}?get=P1_001N&for=block:*&in=state:{state_fips}%20county:{county}"
        rows = json_get(url)
        frame = pd.DataFrame(rows[1:], columns=rows[0])
        frame["GEOID20"] = frame["state"] + frame["county"] + frame["tract"] + frame["block"]
        frame["population"] = pd.to_numeric(frame["P1_001N"], errors="coerce").fillna(0).astype("int64")
        frames.append(frame[["GEOID20", "population"]])
    return pd.concat(frames, ignore_index=True)


def tiger_points(state_fips: str, cache_dir: Path) -> pd.DataFrame:
    cache_dir.mkdir(parents=True, exist_ok=True)
    zip_path = cache_dir / f"tl_2020_{state_fips}_tabblock20.zip"
    if not zip_path.exists():
        urllib.request.urlretrieve(TIGER_URL.format(fips=state_fips), zip_path)
    gdf = gpd.read_file(f"zip://{zip_path}")
    lat_col = "INTPTLAT20" if "INTPTLAT20" in gdf.columns else "INTPTLAT"
    lon_col = "INTPTLON20" if "INTPTLON20" in gdf.columns else "INTPTLON"
    return pd.DataFrame({
        "GEOID20": gdf["GEOID20"].astype(str),
        "latitude": pd.to_numeric(gdf[lat_col]),
        "longitude": pd.to_numeric(gdf[lon_col]),
    })


def aggregate_grid(points: pd.DataFrame, grid_km: float) -> pd.DataFrame:
    # Approximately equal cell dimensions; longitude index corrected by latitude.
    lat_step = grid_km / 111.32
    lat_idx = np.floor((points["latitude"] + 90.0) / lat_step).astype("int64")
    # Use latitude bands and a local longitude step for each point.
    lon_step = grid_km / (111.32 * np.cos(np.radians(points["latitude"])).clip(0.1))
    lon_idx = np.floor((points["longitude"] + 180.0) / lon_step).astype("int64")
    tmp = points.assign(lat_idx=lat_idx, lon_idx=lon_idx)
    grouped = tmp.groupby(["lat_idx", "lon_idx"], as_index=False).agg(
        population=("population", "sum"),
        latitude=("latitude", "mean"),
        longitude=("longitude", "mean"),
    )
    return grouped[grouped.population > 0].copy()


def append_state(db_path: Path, state_fips: str, grid_km: float, cache_dir: Path) -> int:
    population = block_population(state_fips)
    points = tiger_points(state_fips, cache_dir)
    merged = points.merge(population, on="GEOID20", how="inner")
    merged = merged[merged.population > 0]
    grid = aggregate_grid(merged, grid_km)
    # Deterministic global-ish integer ID from rounded coordinates.
    grid["cell_id"] = ((grid.latitude + 90) * 1_000_000).round().astype("int64") * 1_000_000_000 + ((grid.longitude + 180) * 1_000_000).round().astype("int64")
    with sqlite3.connect(db_path) as conn:
        grid[["cell_id", "latitude", "longitude", "population"]].to_sql(
            "population_cells", conn, if_exists="append", index=False
        )
    return len(grid)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--states", nargs="+", required=True, help="Two-digit state FIPS codes, e.g. 51 37")
    parser.add_argument("--output", type=Path, default=Path("population_2020.sqlite"))
    parser.add_argument("--grid-km", type=float, default=1.0)
    parser.add_argument("--cache", type=Path, default=Path("census_cache"))
    args = parser.parse_args()

    initialize_database(args.output)
    with sqlite3.connect(args.output) as conn:
        conn.execute("DELETE FROM population_cells")
        conn.execute("INSERT OR REPLACE INTO metadata VALUES (?, ?)", ("source", "2020 Census P.L. 94-171 + TIGER/Line 2020"))
        conn.execute("INSERT OR REPLACE INTO metadata VALUES (?, ?)", ("grid_km", str(args.grid_km)))
    total = 0
    for state in args.states:
        count = append_state(args.output, state.zfill(2), args.grid_km, args.cache)
        total += count
        print(f"State {state}: {count:,} occupied cells")
    print(f"Wrote {total:,} cells to {args.output}")

if __name__ == "__main__":
    main()
