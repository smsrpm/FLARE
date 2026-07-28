"""Time-evolving, two-dimensional FLARE consequence-footprint surrogate.

The model uses the EAB and LPZ dose curves as cumulative anchor states and
constructs 24 internally resolved intervals between their integration times.
It requires no additional FLARE input. Conservative results remain centered on
the maximum-population pathway; better-estimate results use a deterministic,
bounded, mean-reverting directional sequence.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import math

import numpy as np

from .deposition import ReleaseGroup, _DEPOSITION_FACTOR
from .dispersion import DispersionInputs, DoseCurve, sigma_y_m


@dataclass(frozen=True)
class ConsequenceStep:
    step: int
    start_hr: float
    end_hr: float
    bearing_deg: float
    wind_speed_m_s: float
    stability_class: str
    cumulative_fraction: float
    incremental_fraction: float


@dataclass(frozen=True)
class ConsequenceResult:
    east_m: np.ndarray
    north_m: np.ndarray
    cumulative_field: np.ndarray
    incremental_field: np.ndarray
    cumulative_fields: tuple[np.ndarray, ...]
    steps: tuple[ConsequenceStep, ...]
    displayed_step: int
    maximum_value: float
    scale_maximum: float
    units: str
    title: str


def population_above_threshold(
    cells,
    site_lat: float,
    site_lon: float,
    radius_miles: float,
    consequence: ConsequenceResult,
    minimum_dose_rem: float,
    minimum_radius_miles: float = 0.0,
) -> float:
    """Sum population whose sampled cumulative airborne dose meets the threshold.

    Population-cell coordinates are converted to the same local east/north
    coordinate system used to construct the consequence raster. Bilinear
    interpolation then samples the displayed cumulative field at each cell.
    Cells outside the circular analysis radius or outside the raster are omitted.
    """
    from .core import local_xy_miles

    required = {"latitude", "longitude", "population"}
    missing = required.difference(cells.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")
    if cells.empty:
        return 0.0
    if consequence.units != "rem":
        raise ValueError("Population threshold must be evaluated from an airborne-dose field")

    lat = cells["latitude"].to_numpy(float)
    lon = cells["longitude"].to_numpy(float)
    population = cells["population"].to_numpy(float)
    east_miles, north_miles = local_xy_miles(lat, lon, site_lat, site_lon)
    east = east_miles * 1609.344
    north = north_miles * 1609.344
    radius_m = float(radius_miles) * 1609.344
    minimum_radius_m = max(float(minimum_radius_miles), 0.0) * 1609.344

    east_axis = np.asarray(consequence.east_m[0, :], dtype=float)
    north_axis = np.asarray(consequence.north_m[:, 0], dtype=float)
    field = np.asarray(consequence.cumulative_field, dtype=float)
    if east_axis.size < 2 or north_axis.size < 2 or field.shape != (north_axis.size, east_axis.size):
        return 0.0

    # np.interp requires ascending axes. The consequence north axis is normally
    # descending because row zero is the top of the map. Reverse it and the field
    # together so both axes are ascending for index calculation.
    if north_axis[0] > north_axis[-1]:
        north_axis = north_axis[::-1]
        field = field[::-1, :]

    radial_distance = np.hypot(east, north)
    radial_mask = (radial_distance >= minimum_radius_m) & (radial_distance <= radius_m) & (population > 0.0)
    bounds_mask = (
        (east >= east_axis[0]) & (east <= east_axis[-1])
        & (north >= north_axis[0]) & (north <= north_axis[-1])
    )
    valid = radial_mask & bounds_mask
    if not np.any(valid):
        return 0.0

    ex = east[valid]
    ny = north[valid]
    pop = population[valid]
    ix = np.searchsorted(east_axis, ex, side="right") - 1
    iy = np.searchsorted(north_axis, ny, side="right") - 1
    ix = np.clip(ix, 0, east_axis.size - 2)
    iy = np.clip(iy, 0, north_axis.size - 2)

    x0, x1 = east_axis[ix], east_axis[ix + 1]
    y0, y1 = north_axis[iy], north_axis[iy + 1]
    tx = np.divide(ex - x0, x1 - x0, out=np.zeros_like(ex), where=(x1 != x0))
    ty = np.divide(ny - y0, y1 - y0, out=np.zeros_like(ny), where=(y1 != y0))
    f00 = field[iy, ix]
    f10 = field[iy, ix + 1]
    f01 = field[iy + 1, ix]
    f11 = field[iy + 1, ix + 1]
    sampled = (
        (1.0 - tx) * (1.0 - ty) * f00
        + tx * (1.0 - ty) * f10
        + (1.0 - tx) * ty * f01
        + tx * ty * f11
    )
    return float(pop[sampled >= float(minimum_dose_rem)].sum())


def _unit(seed: str) -> float:
    d = hashlib.sha256(seed.encode("utf-8")).digest()
    return int.from_bytes(d[:8], "big") / float(2**64 - 1)


def _signed(seed: str) -> float:
    return 2.0 * _unit(seed) - 1.0


def _progress_fraction(s: float, shape: float = 2.4) -> float:
    """Front-loaded monotonic interpolation from 0 to 1."""
    s = float(np.clip(s, 0.0, 1.0))
    return (1.0 - math.exp(-shape * s)) / (1.0 - math.exp(-shape))


def _step_meteorology(
    nominal: DispersionInputs,
    predominant_bearing_deg: float,
    scenario: str,
    count: int,
    seed_text: str,
) -> tuple[ConsequenceStep, ...]:
    classes = ["A", "B", "C", "D", "E", "F"]
    nominal_idx = classes.index(str(nominal.stability_class).upper()) if str(nominal.stability_class).upper() in classes else 3
    steps: list[ConsequenceStep] = []
    offset = 0.0
    previous_fraction = 0.0
    eab_hr = max(float(getattr(nominal, "eab_time_hr", 0.0)), 0.0)
    lpz_hr = max(float(getattr(nominal, "lpz_time_hr", nominal.release_duration_hr)), eab_hr + 1e-6)
    dt = (lpz_hr - eab_hr) / count
    for j in range(1, count + 1):
        frac = _progress_fraction(j / count)
        inc = frac - previous_fraction
        previous_fraction = frac
        # Deterministic variations; they alter width and transport in both scenarios.
        wind_factor = 0.72 + 0.56 * _unit(f"{seed_text}|wind|{j}")
        wind = max(0.1, nominal.wind_speed_m_s * wind_factor)
        class_shift = -1 if _unit(f"{seed_text}|stab|{j}") < 0.25 else (1 if _unit(f"{seed_text}|stab2|{j}") > 0.75 else 0)
        stability = classes[int(np.clip(nominal_idx + class_shift, 0, 5))]
        if scenario.startswith("Conservative"):
            bearing = predominant_bearing_deg
        else:
            # Mean-reverting AR(1), bounded around the maximum-population pathway.
            innovation = 12.0 * _signed(f"{seed_text}|direction|{j}")
            offset = 0.62 * offset + innovation
            offset = float(np.clip(offset, -28.0, 28.0))
            bearing = (predominant_bearing_deg + offset) % 360.0
        steps.append(ConsequenceStep(
            step=j,
            start_hr=eab_hr + (j - 1) * dt,
            end_hr=eab_hr + j * dt,
            bearing_deg=bearing,
            wind_speed_m_s=wind,
            stability_class=stability,
            cumulative_fraction=frac,
            incremental_fraction=inc,
        ))
    return tuple(steps)


def _curve_values(curve: DoseCurve, radius_m: np.ndarray) -> np.ndarray:
    x = np.asarray(curve.distance_m, dtype=float)
    y = np.asarray(curve.centerline_dose_rem, dtype=float)
    order = np.argsort(x)
    x, y = x[order], y[order]
    return np.interp(radius_m, x, y, left=float(y[0]), right=float(y[-1]))


def _group_scale(groups: tuple[ReleaseGroup, ...], selection: str) -> float:
    selected = groups if selection == "Total depositing inventory" else tuple(g for g in groups if g.name == selection)
    value = sum(
        g.core_inventory_ci * max(g.total_release_fraction, g.gap_fraction + g.early_fraction)
        * _DEPOSITION_FACTOR.get(g.key, 0.7)
        for g in selected
    )
    total = sum(
        g.core_inventory_ci * max(g.total_release_fraction, g.gap_fraction + g.early_fraction)
        * _DEPOSITION_FACTOR.get(g.key, 0.7)
        for g in groups
    )
    return value / total if total > 0 else 1.0


def mask_consequence_annulus(
    consequence: ConsequenceResult,
    minimum_radius_miles: float,
    maximum_radius_miles: float,
) -> ConsequenceResult:
    """Return a consequence result screened to the selected radial annulus."""
    minimum_m = max(float(minimum_radius_miles), 0.0) * 1609.344
    maximum_m = max(float(maximum_radius_miles), 0.0) * 1609.344
    radial_distance = np.hypot(consequence.east_m, consequence.north_m)
    included = (radial_distance >= minimum_m) & (radial_distance <= maximum_m)

    def masked(field):
        return np.where(included, np.asarray(field, dtype=float), 0.0)

    cumulative_fields = tuple(masked(field) for field in consequence.cumulative_fields)
    displayed_index = min(max(int(consequence.displayed_step), 0), len(cumulative_fields) - 1)
    cumulative_field = cumulative_fields[displayed_index]
    incremental_field = masked(consequence.incremental_field)
    maximum_value = float(np.max(cumulative_field, initial=0.0))
    return replace(
        consequence,
        cumulative_field=cumulative_field,
        incremental_field=incremental_field,
        cumulative_fields=cumulative_fields,
        maximum_value=maximum_value,
    )


def build_time_evolving_field(
    site_radius_miles: float,
    predominant_bearing_deg: float,
    eab_curve: DoseCurve,
    lpz_curve: DoseCurve,
    inputs: DispersionInputs,
    eab_time_hr: float,
    lpz_time_hr: float,
    displayed_step: int,
    scenario: str,
    layer: str,
    release_groups: tuple[ReleaseGroup, ...] = (),
    deposition_group: str = "Total depositing inventory",
    seed_text: str = "FLARE",
    interval_count: int = 24,
    grid_size: int = 320,
) -> ConsequenceResult:
    """Precompute all cumulative fields and select one display frame.

    Every frame uses the final LPZ maximum for the selected scenario/layer/group.
    This preserves a fixed contour scale and makes progression visually meaningful.
    """
    radius_m = site_radius_miles * 1609.344
    east = np.linspace(-radius_m, radius_m, grid_size)
    north = np.linspace(radius_m, -radius_m, grid_size)
    east_grid, north_grid = np.meshgrid(east, north)
    radial = np.hypot(east_grid, north_grid)
    eab_centerline = _curve_values(eab_curve, radial)
    lpz_centerline = _curve_values(lpz_curve, radial)

    object.__setattr__(inputs, "eab_time_hr", eab_time_hr)
    object.__setattr__(inputs, "lpz_time_hr", lpz_time_hr)
    steps = _step_meteorology(inputs, predominant_bearing_deg, scenario, interval_count, seed_text)

    initial_inputs = DispersionInputs(
        inputs.stability_class, inputs.wind_speed_m_s, inputs.release_height_m, max(eab_time_hr, 0.01)
    )
    b0 = math.radians(predominant_bearing_deg)
    down0 = east_grid * math.sin(b0) + north_grid * math.cos(b0)
    cross0 = east_grid * math.cos(b0) - north_grid * math.sin(b0)
    sy0 = sigma_y_m(np.maximum(down0, 1.0), initial_inputs)
    cumulative = np.where(
        down0 > 0, eab_centerline * np.exp(-0.5 * (cross0 / np.maximum(sy0, 20.0)) ** 2), 0.0
    )
    cumulative = np.where(radial <= radius_m, cumulative, 0.0)
    raw_fields: list[np.ndarray] = [cumulative.copy()]
    increments: list[np.ndarray] = [np.zeros_like(cumulative)]
    previous_anchor = eab_centerline.copy()

    for step in steps:
        target_centerline = eab_centerline + step.cumulative_fraction * (lpz_centerline - eab_centerline)
        delta_centerline = np.maximum(target_centerline - previous_anchor, 0.0)
        previous_anchor = target_centerline
        bearing = math.radians(step.bearing_deg)
        down = east_grid * math.sin(bearing) + north_grid * math.cos(bearing)
        cross = east_grid * math.cos(bearing) - north_grid * math.sin(bearing)
        step_inputs = DispersionInputs(
            step.stability_class, step.wind_speed_m_s, inputs.release_height_m,
            max(step.end_hr - step.start_hr, 0.01),
        )
        sy = sigma_y_m(np.maximum(down, 1.0), step_inputs)
        lateral = np.exp(-0.5 * (cross / np.maximum(sy, 20.0)) ** 2)
        increment = np.where(down > 0, delta_centerline * lateral, 0.0)
        if layer == "Ground deposition":
            travel = max(step.wind_speed_m_s, 0.1) * max(step.end_hr - step.start_hr, 0.01) * 3600.0
            scale = max(500.0, min(12000.0, 0.7 * travel))
            retention = np.exp(-np.maximum(down, 0.0) / scale) / np.sqrt(
                1.0 + np.maximum(down, 0.0) / 500.0
            )
            increment = increment * retention * _group_scale(release_groups, deposition_group)
        increment = np.where(radial <= radius_m, increment, 0.0)
        cumulative = cumulative + increment
        raw_fields.append(cumulative.copy())
        increments.append(increment.copy())

    final_max = float(np.max(raw_fields[-1], initial=0.0))
    if layer == "Ground deposition":
        if final_max > 0.0:
            fields = tuple(field / final_max for field in raw_fields)
            normalized_increments = tuple(field / final_max for field in increments)
        else:
            fields = tuple(raw_fields)
            normalized_increments = tuple(increments)
        units = "% of final LPZ case/group maximum"
        title = f"Cumulative synthetic deposition — {deposition_group}"
        scale_maximum = 1.0
    else:
        fields = tuple(raw_fields)
        normalized_increments = tuple(increments)
        units = "rem"
        title = "Cumulative airborne TEDE"
        scale_maximum = final_max

    displayed_step = int(np.clip(displayed_step, 0, interval_count))
    selected = fields[displayed_step]
    selected_increment = normalized_increments[displayed_step]
    selected_max = float(np.max(selected, initial=0.0))
    return ConsequenceResult(
        east_grid, north_grid, selected, selected_increment, fields, steps, displayed_step,
        selected_max, scale_maximum, units, title,
    )
