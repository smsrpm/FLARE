"""Discrete user-interface value sets for the FLARE population map."""
from __future__ import annotations

import math


def build_radius_options() -> tuple[float, ...]:
    """Return practical 0.1-100 mile radius snap points.

    Each positive option has at most two significant digits and its least
    significant digit is 0 or 5: 0.10, 0.15, ..., 0.95, 1.0, 1.5, ...,
    9.5, 10, 15, ..., 95, 100.  The zero option is retained for the inner
    radius so an ordinary disk remains available.
    """
    values: set[float] = {0.0, 100.0}
    for exponent in (-1, 0, 1):
        scale = 10.0**exponent
        for half_step in range(2, 20):
            value = (half_step / 2.0) * scale
            if 0.1 <= value <= 100.0:
                values.add(round(value, 4))
    return tuple(sorted(values))


RADIUS_OPTIONS = build_radius_options()


def nearest_radius_option(value: float) -> float:
    """Return the logarithmically nearest discrete radius option."""
    numeric = min(max(float(value), 0.0), 100.0)
    if numeric <= 0.0:
        return 0.0
    return min(
        RADIUS_OPTIONS[1:],
        key=lambda candidate: abs(math.log(candidate / numeric)),
    )


def build_dose_options() -> tuple[float, ...]:
    """Return 0.001-10,000 rem snap points with three significant digits.

    The third significant digit is always 0 or 5.  Within each decade the
    mantissa therefore advances in 0.05 increments: 1.00, 1.05, 1.10,
    1.15, ..., 9.95.  Examples across decades include 0.001, 0.00105,
    0.0100, 0.0105, 1.00, 1.05, 10.0, 10.5, 100, 105, and 10,000.
    """
    minimum = 1.0e-3
    maximum = 1.0e4
    values: set[float] = {minimum, maximum}
    for exponent in range(-3, 5):
        scale = 10.0**exponent
        # 20/20 through 199/20 gives 1.00, 1.05, ..., 9.95.
        for twentieth in range(20, 200):
            value = (twentieth / 20.0) * scale
            if minimum <= value <= maximum:
                # Twelve decimal places safely preserve all values in this range
                # while removing binary floating-point display artifacts.
                values.add(round(value, 12))
    return tuple(sorted(values))


DOSE_OPTIONS = build_dose_options()


def nearest_dose_option(value: float) -> float:
    """Return the logarithmically nearest discrete dose option."""
    numeric = min(max(float(value), DOSE_OPTIONS[0]), DOSE_OPTIONS[-1])
    return min(
        DOSE_OPTIONS,
        key=lambda candidate: abs(math.log(candidate / numeric)),
    )
