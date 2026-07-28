"""SQLite population-grid access."""
from __future__ import annotations

import math
import sqlite3
from pathlib import Path
import pandas as pd


def initialize_database(path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS population_cells (
            cell_id INTEGER PRIMARY KEY,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            population INTEGER NOT NULL CHECK(population >= 0)
        );
        CREATE INDEX IF NOT EXISTS idx_population_lat ON population_cells(latitude);
        CREATE INDEX IF NOT EXISTS idx_population_lon ON population_cells(longitude);
        CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)


def replace_cells(path: str | Path, cells: pd.DataFrame, metadata: dict[str, str] | None = None) -> None:
    initialize_database(path)
    required = ["cell_id", "latitude", "longitude", "population"]
    if any(c not in cells.columns for c in required):
        raise ValueError(f"Cells must contain {required}")
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM population_cells")
        cells[required].to_sql("population_cells", conn, if_exists="append", index=False)
        if metadata:
            conn.executemany(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
                list(metadata.items()),
            )


def query_radius(
    path: str | Path,
    site_lat: float,
    site_lon: float,
    radius_miles: float,
    minimum_radius_miles: float = 0.0,
) -> pd.DataFrame:
    """Return populated cells inside the selected radial annulus.

    SQLite first performs an efficient outer-radius bounding-box query. The
    returned rows are then screened by exact local distance so every downstream
    calculation receives the same minimum/maximum radius population set.
    """
    lat_delta = radius_miles / 69.0
    lon_delta = radius_miles / max(69.0 * math.cos(math.radians(site_lat)), 1e-9)
    sql = """
      SELECT cell_id, latitude, longitude, population
      FROM population_cells
      WHERE latitude BETWEEN ? AND ?
        AND longitude BETWEEN ? AND ?
        AND population > 0
    """
    params = (site_lat-lat_delta, site_lat+lat_delta, site_lon-lon_delta, site_lon+lon_delta)
    with sqlite3.connect(path) as conn:
        cells = pd.read_sql_query(sql, conn, params=params)

    if cells.empty:
        return cells

    from .core import local_xy_miles

    east, north = local_xy_miles(
        cells["latitude"].to_numpy(float),
        cells["longitude"].to_numpy(float),
        float(site_lat),
        float(site_lon),
    )
    distance = (east * east + north * north) ** 0.5
    minimum = max(float(minimum_radius_miles), 0.0)
    maximum = max(float(radius_miles), minimum)
    included = (distance >= minimum) & (distance <= maximum)
    return cells.loc[included].reset_index(drop=True)
