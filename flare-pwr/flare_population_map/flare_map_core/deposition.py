"""Synthetic, source-term-weighted deposition footprints for FLARE maps.

This is a reduced-order visualization model, not a site-specific weather
reconstruction. It uses only information already written to a FLARE output
workbook: source-term group inventories, gap/early-in-vessel release fractions,
release durations, wind speed, and stability class. Each FLARE release interval
is independently offset about the maximum-population bearing. The dominant
interval stays on that bearing; offsets never accumulate as a random walk.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math

import numpy as np

from .dispersion import DispersionInputs, sigma_y_m


@dataclass(frozen=True)
class ReleaseGroup:
    key: str
    name: str
    core_inventory_ci: float
    gap_fraction: float
    early_fraction: float
    total_release_fraction: float


@dataclass(frozen=True)
class ReleaseInterval:
    name: str
    duration_hr: float
    activity_ci: float
    bearing_offset_deg: float


# Relative surface-retention factors. They are used only to distribute the
# existing released inventory among groups in the synthetic deposition view.
_DEPOSITION_FACTOR = {
    "Halogens": 0.35,
    "Alkali_metals": 1.00,
    "Te_group": 0.80,
    "Ba_Sr": 0.85,
    "Noble_metals": 0.90,
    "Lanthanides": 0.95,
    "Ce_group": 0.95,
    "U_actinides": 0.95,
    "NG": 0.0,
}


def deposition_group_options(groups: tuple[ReleaseGroup, ...]) -> list[str]:
    options = ["Total depositing inventory"]
    options.extend(g.name for g in groups if _DEPOSITION_FACTOR.get(g.key, 0.7) > 0 and g.total_release_fraction > 0)
    return options


def _selected_groups(groups: tuple[ReleaseGroup, ...], selection: str) -> list[ReleaseGroup]:
    if selection == "Total depositing inventory":
        return [g for g in groups if _DEPOSITION_FACTOR.get(g.key, 0.7) > 0]
    return [g for g in groups if g.name == selection]


def _stable_signed_unit(seed_text: str) -> float:
    digest = hashlib.sha256(seed_text.encode("utf-8")).digest()
    value = int.from_bytes(digest[:8], "big") / float(2**64 - 1)
    return 2.0 * value - 1.0


def directional_limit_deg(inputs: DispersionInputs) -> float:
    """Bound interval variability around the fixed predominant pathway."""
    stability = str(inputs.stability_class).strip().upper()
    stability_term = {"A": 12, "B": 11, "C": 10, "D": 9, "E": 13, "F": 18}.get(stability, 12)
    weak_wind = max(0.0, 1.0 - max(inputs.wind_speed_m_s, 0.1))
    return min(30.0, stability_term + 12.0 * weak_wind)


def build_release_intervals(
    groups: tuple[ReleaseGroup, ...],
    selection: str,
    gap_duration_hr: float,
    early_duration_hr: float,
    inputs: DispersionInputs,
    seed_text: str,
) -> tuple[ReleaseInterval, ...]:
    """Build independently perturbed intervals; the dominant interval is fixed at 0°."""
    selected = _selected_groups(groups, selection)
    gap_activity = sum(
        g.core_inventory_ci * g.gap_fraction * _DEPOSITION_FACTOR.get(g.key, 0.7)
        for g in selected
    )
    early_activity = sum(
        g.core_inventory_ci * g.early_fraction * _DEPOSITION_FACTOR.get(g.key, 0.7)
        for g in selected
    )
    raw = [
        ("Gap release", max(gap_duration_hr, 0.01), gap_activity),
        ("Early in-vessel release", max(early_duration_hr, 0.01), early_activity),
    ]
    raw = [item for item in raw if item[2] > 0]
    if not raw:
        return tuple()
    dominant = max(range(len(raw)), key=lambda i: raw[i][2])
    limit = directional_limit_deg(inputs)
    intervals: list[ReleaseInterval] = []
    for i, (name, duration, activity) in enumerate(raw):
        if i == dominant:
            offset = 0.0
        else:
            # Independent offset from the principal bearing, not from the prior interval.
            random_component = _stable_signed_unit(f"{seed_text}|{selection}|{name}")
            relative_weight = activity / max(raw[dominant][2], 1.0e-30)
            offset = random_component * limit * (0.55 + 0.45 * (1.0 - min(relative_weight, 1.0)))
        intervals.append(ReleaseInterval(name, duration, activity, offset))
    return tuple(intervals)


def synthetic_deposition_field(
    east_m: np.ndarray,
    north_m: np.ndarray,
    predominant_bearing_deg: float,
    intervals: tuple[ReleaseInterval, ...],
    inputs: DispersionInputs,
) -> np.ndarray:
    """Return a normalized, time-integrated synthetic deposition field."""
    field = np.zeros_like(east_m, dtype=float)
    if not intervals:
        return field
    total_activity = sum(i.activity_ci for i in intervals)
    for interval in intervals:
        bearing = math.radians((predominant_bearing_deg + interval.bearing_offset_deg) % 360.0)
        downwind = east_m * math.sin(bearing) + north_m * math.cos(bearing)
        crosswind = east_m * math.cos(bearing) - north_m * math.sin(bearing)
        x = np.maximum(downwind, 1.0)
        sy = sigma_y_m(x, inputs)
        lateral = np.exp(-0.5 * np.square(crosswind / np.maximum(sy, 20.0)))

        # A smooth deposition surrogate: near-source retention plus an interval-
        # transport lobe. This creates an accumulated footprint rather than a
        # single instantaneous airborne cloud.
        travel_m = max(inputs.wind_speed_m_s, 0.1) * interval.duration_hr * 3600.0
        peak_m = float(np.clip(0.35 * travel_m, 150.0, 12000.0))
        spread_m = max(0.55 * peak_m, 250.0)
        transported = np.exp(-0.5 * np.square((x - peak_m) / spread_m))
        near_source = np.exp(-x / max(peak_m, 500.0))
        longitudinal = 0.35 * near_source + 0.65 * transported
        dilution = 1.0 / np.sqrt(1.0 + x / 400.0)
        contribution = (interval.activity_ci / max(total_activity, 1.0e-30)) * lateral * longitudinal * dilution
        contribution = np.where(downwind > 0.0, contribution, 0.0)
        field += contribution
    maximum = float(np.max(field, initial=0.0))
    return field / maximum if maximum > 0.0 else field
