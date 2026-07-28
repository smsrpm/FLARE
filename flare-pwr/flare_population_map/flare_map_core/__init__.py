"""Public API for the FLARE population-plume prototype."""
from .core import (
    evaluate_dose_population_bearing, find_max_population_bearing,
    find_max_dose_population_bearing, plume_polygon,
)
from .database import query_radius
from .deposition import (
    ReleaseGroup, ReleaseInterval, build_release_intervals,
    deposition_group_options, synthetic_deposition_field,
)
from .dispersion import DispersionInputs, DoseCurve, sigma_y_m, lateral_factor, half_width_m
from .flare_workbook import load_flare_output
from .map_view import make_map
from .consequence import (
    ConsequenceStep, ConsequenceResult, build_time_evolving_field,
    mask_consequence_annulus, population_above_threshold,
)
from .export_results import build_output_workbook

__all__ = [
    "evaluate_dose_population_bearing", "find_max_population_bearing",
    "find_max_dose_population_bearing", "plume_polygon",
    "query_radius", "DispersionInputs", "DoseCurve", "sigma_y_m", "lateral_factor",
    "half_width_m", "load_flare_output", "make_map", "ReleaseGroup", "ReleaseInterval",
    "build_release_intervals", "deposition_group_options", "synthetic_deposition_field",
    "ConsequenceStep", "ConsequenceResult", "build_time_evolving_field",
    "mask_consequence_annulus", "population_above_threshold", "build_output_workbook",
]
