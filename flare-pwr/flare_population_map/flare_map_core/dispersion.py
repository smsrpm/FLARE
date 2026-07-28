"""Reduced-order lateral atmospheric-dispersion model for FLARE plume maps.

The model preserves NOTBADTRAD's centerline dose-versus-distance calculation and
adds a transparent Gaussian crosswind profile. Horizontal dispersion follows a
standard rural Pasquill-Gifford/Turner correlation by stability class. A bounded
low-wind, duration-dependent meander multiplier broadens sigma_y for persistent
releases under weak winds.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

import numpy as np


@dataclass(frozen=True)
class DispersionInputs:
    stability_class: str = "F"
    wind_speed_m_s: float = 1.0
    release_height_m: float = 0.0
    release_duration_hr: float = 2.0


# Rural Pasquill-Gifford/Turner horizontal dispersion coefficients:
# sigma_y = a*x / sqrt(1 + b*x), x and sigma_y in metres.
_PG_Y = {
    "A": (0.22, 0.0001),
    "B": (0.16, 0.0001),
    "C": (0.11, 0.0001),
    "D": (0.08, 0.0001),
    "E": (0.06, 0.0001),
    "F": (0.04, 0.0001),
}


def meander_multiplier(wind_speed_m_s: float, release_duration_hr: float) -> float:
    """Return a bounded weak-wind plume-meander broadening multiplier.

    The correction is deliberately modest and transparent. It is zero at and
    above 1 m/s, increases as wind decreases, increases logarithmically with
    duration, and is capped at 2.5 so it cannot dominate the base correlation.
    """
    u = max(float(wind_speed_m_s), 0.1)
    duration = max(float(release_duration_hr), 0.0)
    weak_wind = max(0.0, 1.0 - u)  # 0 at 1 m/s and above
    duration_factor = min(1.0, math.log1p(duration) / math.log(25.0))
    return min(2.5, 1.0 + 1.5 * weak_wind * duration_factor)


def sigma_y_m(distance_m: np.ndarray | float, inputs: DispersionInputs) -> np.ndarray:
    """Effective horizontal plume standard deviation in metres."""
    stability = str(inputs.stability_class).strip().upper()
    if stability not in _PG_Y:
        raise ValueError(f"Stability class must be A-F; received {inputs.stability_class!r}")
    x = np.maximum(np.asarray(distance_m, dtype=float), 1.0)
    a, b = _PG_Y[stability]
    base = a * x / np.sqrt(1.0 + b * x)
    return base * meander_multiplier(inputs.wind_speed_m_s, inputs.release_duration_hr)


def lateral_factor(crosswind_m: np.ndarray | float, distance_m: np.ndarray | float, inputs: DispersionInputs) -> np.ndarray:
    """Gaussian crosswind concentration/dose fraction relative to centerline."""
    sy = sigma_y_m(distance_m, inputs)
    y = np.asarray(crosswind_m, dtype=float)
    return np.exp(-0.5 * np.square(y / np.maximum(sy, 1.0e-9)))


def half_width_m(distance_m: np.ndarray | float, inputs: DispersionInputs, edge_fraction: float = 0.01) -> np.ndarray:
    """Crosswind half-width where the Gaussian profile reaches edge_fraction."""
    if not 0.0 < edge_fraction < 1.0:
        raise ValueError("edge_fraction must be between 0 and 1")
    return sigma_y_m(distance_m, inputs) * math.sqrt(2.0 * math.log(1.0 / edge_fraction))


@dataclass(frozen=True)
class DoseCurve:
    distance_m: np.ndarray
    centerline_dose_rem: np.ndarray
    label: str = "TEDE"

    def dose_at(self, distance_m: np.ndarray | float) -> np.ndarray:
        """Log-log interpolation with power-law extrapolation at both ends."""
        xq = np.maximum(np.asarray(distance_m, dtype=float), 1.0)
        x = np.asarray(self.distance_m, dtype=float)
        y = np.asarray(self.centerline_dose_rem, dtype=float)
        valid = (x > 0) & (y > 0) & np.isfinite(x) & np.isfinite(y)
        x, y = x[valid], y[valid]
        order = np.argsort(x)
        x, y = x[order], y[order]
        if len(x) < 2:
            raise ValueError("Dose curve requires at least two positive points")
        lx, ly, lq = np.log(x), np.log(y), np.log(xq)
        result = np.interp(lq, lx, ly)
        low_slope = (ly[1] - ly[0]) / (lx[1] - lx[0])
        high_slope = (ly[-1] - ly[-2]) / (lx[-1] - lx[-2])
        result = np.where(lq < lx[0], ly[0] + low_slope * (lq - lx[0]), result)
        result = np.where(lq > lx[-1], ly[-1] + high_slope * (lq - lx[-1]), result)
        return np.exp(result)


def local_dose_rem(
    downwind_m: np.ndarray,
    crosswind_m: np.ndarray,
    curve: DoseCurve,
    inputs: DispersionInputs,
) -> np.ndarray:
    """Two-dimensional TEDE field from centerline dose and lateral spreading."""
    centerline = curve.dose_at(np.maximum(downwind_m, 1.0))
    dose = centerline * lateral_factor(crosswind_m, np.maximum(downwind_m, 1.0), inputs)
    return np.where(downwind_m > 0.0, dose, 0.0)
