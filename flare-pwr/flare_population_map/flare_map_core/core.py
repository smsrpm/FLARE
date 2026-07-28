"""Core geometry and population-search functions for a FLARE release map.

No Streamlit dependency is used here.  Coordinates are converted to a local
East/North approximation, adequate for the default 10-mile search radius.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

import numpy as np
import pandas as pd

EARTH_RADIUS_MILES = 3958.7613


@dataclass(frozen=True)
class PlumeSearchResult:
    bearing_deg: float
    population: float
    weighted_population: float
    included_cells: int
    radius_miles: float
    half_angle_deg: float


def local_xy_miles(lat: np.ndarray, lon: np.ndarray, site_lat: float, site_lon: float) -> tuple[np.ndarray, np.ndarray]:
    """Return local east (x) and north (y) distances in miles."""
    lat_r = np.radians(lat)
    lon_r = np.radians(lon)
    site_lat_r = math.radians(site_lat)
    site_lon_r = math.radians(site_lon)
    dlat = lat_r - site_lat_r
    dlon = lon_r - site_lon_r
    mean_lat = (lat_r + site_lat_r) / 2.0
    x = EARTH_RADIUS_MILES * dlon * np.cos(mean_lat)
    y = EARTH_RADIUS_MILES * dlat
    return x, y


def distance_bearing(lat: np.ndarray, lon: np.ndarray, site_lat: float, site_lon: float) -> tuple[np.ndarray, np.ndarray]:
    """Return approximate distance (mi) and compass bearing (degrees)."""
    x, y = local_xy_miles(lat, lon, site_lat, site_lon)
    distance = np.hypot(x, y)
    bearing = (np.degrees(np.arctan2(x, y)) + 360.0) % 360.0
    return distance, bearing


def angular_difference_deg(a: np.ndarray, b: float) -> np.ndarray:
    """Smallest signed angular difference a-b, in [-180, 180)."""
    return (a - b + 180.0) % 360.0 - 180.0


def radial_weight(distance: np.ndarray, radius_miles: float, mode: str = "uniform") -> np.ndarray:
    """Simple placeholder weighting until NOTBADTRAD supplies dose by distance."""
    if mode == "uniform":
        return np.ones_like(distance, dtype=float)
    if mode == "linear":
        return np.clip(1.0 - distance / radius_miles, 0.0, 1.0)
    if mode == "inverse_distance":
        return 1.0 / np.maximum(distance, 0.25)
    raise ValueError(f"Unknown radial weighting mode: {mode}")


def find_max_population_bearing(
    cells: pd.DataFrame,
    site_lat: float,
    site_lon: float,
    radius_miles: float = 10.0,
    half_angle_deg: float = 10.0,
    bearing_step_deg: float = 1.0,
    radial_weight_mode: str = "uniform",
) -> PlumeSearchResult:
    """Find the plume centerline bearing maximizing population in a wedge.

    Required columns: latitude, longitude, population.
    The wedge begins at the site, extends to radius_miles, and has the supplied
    half-angle.  A radial weighting can approximate consequence weighting.
    """
    required = {"latitude", "longitude", "population"}
    missing = required.difference(cells.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")
    if cells.empty:
        return PlumeSearchResult(0.0, 0.0, 0.0, 0, radius_miles, half_angle_deg)

    lat = cells["latitude"].to_numpy(float)
    lon = cells["longitude"].to_numpy(float)
    pop = cells["population"].to_numpy(float)
    distance, point_bearing = distance_bearing(lat, lon, site_lat, site_lon)
    radial_mask = (distance > 0.0) & (distance <= radius_miles) & (pop > 0)
    if not np.any(radial_mask):
        return PlumeSearchResult(0.0, 0.0, 0.0, 0, radius_miles, half_angle_deg)

    distance = distance[radial_mask]
    point_bearing = point_bearing[radial_mask]
    pop = pop[radial_mask]
    weights = radial_weight(distance, radius_miles, radial_weight_mode)

    best: PlumeSearchResult | None = None
    for bearing in np.arange(0.0, 360.0, bearing_step_deg):
        in_plume = np.abs(angular_difference_deg(point_bearing, bearing)) <= half_angle_deg
        population = float(pop[in_plume].sum())
        weighted = float((pop[in_plume] * weights[in_plume]).sum())
        result = PlumeSearchResult(
            bearing_deg=float(bearing),
            population=population,
            weighted_population=weighted,
            included_cells=int(in_plume.sum()),
            radius_miles=radius_miles,
            half_angle_deg=half_angle_deg,
        )
        if best is None or result.weighted_population > best.weighted_population:
            best = result
        elif result.weighted_population == best.weighted_population and weighted > 0:
            # Prefer the bearing closest to the population-weighted circular mean
            # of the cells included in the tied plume. This avoids selecting the
            # first edge of a broad plateau of equally scoring bearings.
            angles = np.radians(point_bearing[in_plume])
            masses = pop[in_plume] * weights[in_plume]
            mean_bearing = (np.degrees(np.arctan2(
                np.sum(masses * np.sin(angles)),
                np.sum(masses * np.cos(angles)),
            )) + 360.0) % 360.0
            current_delta = abs(float(angular_difference_deg(np.array([bearing]), mean_bearing)[0]))
            best_delta = abs(float(angular_difference_deg(np.array([best.bearing_deg]), mean_bearing)[0]))
            if current_delta < best_delta:
                best = result
    assert best is not None
    return best


def plume_polygon(site_lat: float, site_lon: float, bearing_deg: float, radius_miles: float, half_angle_deg: float, arc_points: int = 30) -> list[tuple[float, float]]:
    """Return a simple wedge polygon as (latitude, longitude) vertices."""
    bearings = np.linspace(bearing_deg - half_angle_deg, bearing_deg + half_angle_deg, arc_points)
    vertices = [(site_lat, site_lon)]
    for b in bearings:
        br = math.radians(b)
        north = radius_miles * math.cos(br)
        east = radius_miles * math.sin(br)
        lat = site_lat + math.degrees(north / EARTH_RADIUS_MILES)
        lon = site_lon + math.degrees(east / (EARTH_RADIUS_MILES * math.cos(math.radians(site_lat))))
        vertices.append((lat, lon))
    vertices.append((site_lat, site_lon))
    return vertices

@dataclass(frozen=True)
class DosePlumeSearchResult:
    bearing_deg: float
    population: float
    population_dose_score: float
    included_cells: int
    maximum_cell_dose_rem: float


def _plume_coordinates_miles(
    lat: np.ndarray,
    lon: np.ndarray,
    site_lat: float,
    site_lon: float,
    bearing_deg: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return downwind and signed crosswind coordinates for a bearing."""
    east, north = local_xy_miles(lat, lon, site_lat, site_lon)
    br = math.radians(bearing_deg)
    downwind = east * math.sin(br) + north * math.cos(br)
    crosswind = east * math.cos(br) - north * math.sin(br)
    return downwind, crosswind



def evaluate_dose_population_bearing(
    cells: pd.DataFrame,
    site_lat: float,
    site_lon: float,
    radius_miles: float,
    dose_curve,
    dispersion_inputs,
    bearing_deg: float,
    minimum_dose_rem: float = 0.01,
    maximum_dose_rem: float | None = None,
    minimum_radius_miles: float = 0.0,
) -> DosePlumeSearchResult:
    """Evaluate population and population-dose for one user-selected bearing."""
    from .dispersion import local_dose_rem

    required = {"latitude", "longitude", "population"}
    missing = required.difference(cells.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")

    normalized_bearing = float(bearing_deg) % 360.0
    if cells.empty:
        return DosePlumeSearchResult(normalized_bearing, 0.0, 0.0, 0, 0.0)

    lat = cells["latitude"].to_numpy(float)
    lon = cells["longitude"].to_numpy(float)
    pop = cells["population"].to_numpy(float)
    radial_distance, _ = distance_bearing(lat, lon, site_lat, site_lon)
    mask = (radial_distance >= max(float(minimum_radius_miles), 0.0)) & (radial_distance <= radius_miles) & (pop > 0)
    lat, lon, pop = lat[mask], lon[mask], pop[mask]
    if len(pop) == 0:
        return DosePlumeSearchResult(normalized_bearing, 0.0, 0.0, 0, 0.0)

    down_mi, cross_mi = _plume_coordinates_miles(
        lat, lon, site_lat, site_lon, normalized_bearing
    )
    dose = local_dose_rem(
        down_mi * 1609.344,
        cross_mi * 1609.344,
        dose_curve,
        dispersion_inputs,
    )
    included = dose >= minimum_dose_rem
    if maximum_dose_rem is not None:
        included &= dose <= maximum_dose_rem

    return DosePlumeSearchResult(
        bearing_deg=normalized_bearing,
        population=float(pop[included].sum()),
        population_dose_score=float(np.sum(pop[included] * dose[included])),
        included_cells=int(included.sum()),
        maximum_cell_dose_rem=float(dose.max(initial=0.0)),
    )

def find_max_dose_population_bearing(
    cells: pd.DataFrame,
    site_lat: float,
    site_lon: float,
    radius_miles: float,
    dose_curve,
    dispersion_inputs,
    bearing_step_deg: float = 1.0,
    minimum_dose_rem: float = 0.01,
    maximum_dose_rem: float | None = None,
    objective: str = "population_dose",
    minimum_radius_miles: float = 0.0,
) -> DosePlumeSearchResult:
    """Rotate the plume to maximize either population-dose or plume population.

    Both objectives use the same dose-defined plume footprint and dose band.
    ``population_dose`` maximizes sum(population * dose); ``population``
    maximizes the total population contained inside that footprint.
    """
    from .dispersion import local_dose_rem

    required = {"latitude", "longitude", "population"}
    missing = required.difference(cells.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")
    if cells.empty:
        return DosePlumeSearchResult(0.0, 0.0, 0.0, 0, 0.0)

    lat = cells["latitude"].to_numpy(float)
    lon = cells["longitude"].to_numpy(float)
    pop = cells["population"].to_numpy(float)
    radial_distance, _ = distance_bearing(lat, lon, site_lat, site_lon)
    mask = (radial_distance >= max(float(minimum_radius_miles), 0.0)) & (radial_distance <= radius_miles) & (pop > 0)
    lat, lon, pop = lat[mask], lon[mask], pop[mask]
    if len(pop) == 0:
        return DosePlumeSearchResult(0.0, 0.0, 0.0, 0, 0.0)

    if objective not in {"population_dose", "population"}:
        raise ValueError(f"Unknown pathway objective: {objective}")

    best = None
    for bearing in np.arange(0.0, 360.0, bearing_step_deg):
        down_mi, cross_mi = _plume_coordinates_miles(lat, lon, site_lat, site_lon, float(bearing))
        dose = local_dose_rem(
            down_mi * 1609.344,
            cross_mi * 1609.344,
            dose_curve,
            dispersion_inputs,
        )
        included = dose >= minimum_dose_rem
        if maximum_dose_rem is not None:
            included &= dose <= maximum_dose_rem
        score = float(np.sum(pop[included] * dose[included]))
        candidate = DosePlumeSearchResult(
            bearing_deg=float(bearing),
            population=float(pop[included].sum()),
            population_dose_score=score,
            included_cells=int(included.sum()),
            maximum_cell_dose_rem=float(dose.max(initial=0.0)),
        )
        candidate_value = (
            candidate.population_dose_score
            if objective == "population_dose"
            else candidate.population
        )
        best_value = (
            best.population_dose_score
            if best is not None and objective == "population_dose"
            else best.population if best is not None else None
        )
        if best is None or candidate_value > best_value:
            best = candidate
        elif candidate_value == best_value and best is not None:
            # Use the alternate measure as a deterministic, physically useful tie-breaker.
            if objective == "population" and candidate.population_dose_score > best.population_dose_score:
                best = candidate
            elif objective == "population_dose" and candidate.population > best.population:
                best = candidate
    assert best is not None
    return best
