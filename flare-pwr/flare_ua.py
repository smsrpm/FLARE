"""
flare_ua.py   -   Streamlit uncertainty analysis UI for flare_sim.py
===============================================================================
Run with:
    streamlit run flare_ua.py
"""

import io
import os
import re
import sys
import csv
import json
import subprocess
import requests
import time as _time
import shutil as _shutil
from datetime import datetime
from datetime import datetime
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from pathlib import Path
from openpyxl import load_workbook

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="FLARE · Uncertainty Analysis",
    page_icon="⚛",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Styling (matches flare_ui.py) ─────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap');

:root {
    --bg:       #f5f7fa;
    --surface:  #ffffff;
    --sidebar:  #1a1f2e;
    --border:   #d0d7de;
    --accent:   #0969da;
    --accent2:  #1a7f37;
    --warn:     #9a6700;
    --danger:   #cf222e;
    --text:     #1f2328;
    --muted:    #57606a;
    --sid-text: #e6edf3;
    --sid-muted:#8b949e;
    --dark-surface: #0d1117;
    --dark-border:  #30363d;
}

html, body, [class*="css"] {
    font-family: 'IBM Plex Sans', sans-serif;
    color: var(--text);
}
.stApp { background: var(--bg); }
header { background: transparent !important; }

section[data-testid="stSidebar"] {
    background: var(--sidebar) !important;
    border-right: 1px solid var(--dark-border);
    color: var(--sid-text);
}
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] label {
    color: var(--sid-text) !important;
}
section[data-testid="stSidebar"] .stCaption {
    color: var(--sid-muted) !important;
}
/* Keep expander header dark when expanded so label stays visible */
section[data-testid="stSidebar"] details,
section[data-testid="stSidebar"] details[open],
section[data-testid="stSidebar"] [data-testid="stExpander"],
section[data-testid="stSidebar"] [data-testid="stExpander"] > details {
    background: var(--dark-surface) !important;
    border: 1px solid var(--dark-border) !important;
    border-radius: 4px;
}
section[data-testid="stSidebar"] details summary,
section[data-testid="stSidebar"] details[open] summary,
section[data-testid="stSidebar"] [data-testid="stExpander"] summary {
    background: var(--dark-surface) !important;
    color: var(--sid-text) !important;
}
section[data-testid="stSidebar"] details summary p,
section[data-testid="stSidebar"] details summary span,
section[data-testid="stSidebar"] details[open] summary p,
section[data-testid="stSidebar"] details[open] summary span {
    color: var(--sid-text) !important;
}
section[data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"] {
    background: var(--dark-surface);
    border: 1px solid var(--dark-border);
    border-radius: 6px;
}
section[data-testid="stSidebar"] .stSelectbox span { color: #ffffff !important; }
div[role="listbox"] { background: var(--dark-surface) !important; }
div[role="option"] { color: #ffffff !important; }
div[role="option"]:hover { background: #21262d !important; }
section[data-testid="stSidebar"] input {
    background: var(--dark-surface) !important;
    color: #ffffff !important;
    border: 1px solid var(--dark-border) !important;
}
section[data-testid="stSidebar"] button[kind="primary"] {
    background: var(--danger) !important;
    color: white !important;
}
section[data-testid="stSidebar"] button[kind="primary"]:hover {
    background: #a40e26 !important;
}
section[data-testid="stSidebar"] code {
    color: #ffffff !important;
    background: var(--dark-border) !important;
    padding: 2px 6px; border-radius: 4px;
}
h1, h2, h3 { font-family: 'IBM Plex Mono', monospace; }
button[role="tab"] { color: var(--muted); }
button[role="tab"][aria-selected="true"] {
    color: var(--accent);
    border-bottom: 2px solid var(--accent);
}
.console {
    background: #0d1117;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 1rem;
    color: #7ee787;
    font-family: 'IBM Plex Mono', monospace;
    white-space: pre-wrap;
    font-size: 0.85rem;
}
.hdiv { border-top: 1px solid var(--border); margin: 1.5rem 0; }
.metric-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:0.75rem; }
.metric-tile {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 1rem;
    text-align: center;
}
.metric-tile .val {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 1.4rem;
    color: var(--accent);
}
.metric-tile.ok  .val { color: var(--accent2); }
.metric-tile.warn .val { color: var(--warn); }
.metric-tile.danger .val { color: var(--danger); }
/* ── Tooltip (?) icon — targets the actual SVG stroke ── */
section[data-testid="stSidebar"] .stTooltipHoverTarget svg.icon {
    stroke: #f97316 !important;
}
section[data-testid="stSidebar"] .stTooltipHoverTarget:hover svg.icon {
    stroke: #ffffff !important;
}
.stTooltipHoverTarget svg.icon {
    stroke: #0969da !important;
}
</style>
""", unsafe_allow_html=True)

# ── Constants ─────────────────────────────────────────────────────────────────

WORK_DIR = Path(__file__).parent


def _runtime_dir(base_dir: Path | None = None) -> Path:
    """Return the FLARE runtime folder, preferring runtime/ then Runtime/."""
    base = Path(base_dir) if base_dir is not None else WORK_DIR
    lower = base / "runtime"
    upper = base / "Runtime"
    if lower.exists():
        rt = lower
    elif upper.exists():
        rt = upper
    else:
        rt = lower
        rt.mkdir(parents=True, exist_ok=True)
    return rt


def _runtime_file(name: str, base_dir: Path | None = None) -> Path:
    return _runtime_dir(base_dir) / name



# ── AI narrative helpers ─────────────────────────────────────────────────────
def _read_config(key):
    """Read KEY=value from runtime/flare_config.txt (or Runtime/flare_config.txt)."""
    cfg = _runtime_file("flare_config.txt")
    if cfg.exists():
        for line in cfg.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip().upper() == key.upper():
                return v.strip().strip('"').strip("'")
    return None

def _load_api_key():
    return (st.session_state.get("user_api_key")
            or _read_config("ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY"))

def _load_model():
    return (_read_config("ANTHROPIC_MODEL")
            or os.environ.get("ANTHROPIC_MODEL")
            or "claude-sonnet-4-5")

def _anthropic_text(system_prompt, user_prompt, max_tokens=1800):
    api_key = _load_api_key()
    if not api_key:
        raise RuntimeError("No API key found. Add ANTHROPIC_API_KEY to runtime/flare_config.txt (or Runtime/flare_config.txt) or save it on the FLARE Home page.")
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": _load_model(),
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        },
        timeout=90,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Anthropic API error {resp.status_code}: {resp.text[:600]}")
    data = resp.json()
    return "\n".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text").strip()

# Hardwired variable catalogue: {var_name: (label, default_dist, base, p1, p2, help)}
DEFAULT_UA_VARIABLES = {
    "F_r":           ("Radial peaking F_r",          "uniform",   1.30,    1.20,    1.45,
                      "Radial hot-channel factor: ratio of peak-to-average pin power. "
                      "Drives hot-pin clad temperature and DNBR. Typical range 1.2–1.45."),
    "F_z":           ("Axial peaking F_z",            "uniform",   1.55,    1.45,    1.65,
                      "Axial peaking factor (chopped cosine). Combined with F_r for "
                      "hot-pin heat flux. Typical fresh-core range 1.45–1.65."),
    "total_power":   ("Rated power [MW]",             "normal",  575.0,  575.0,    10.0,
                      "Rated thermal power. Uncertainty reflects calorimetric measurement "
                      "error (~1–2% of rated). Modelled as normal."),
    "temp_core_exit":("Core-exit temp [°C]",          "normal",  312.8,  312.8,     3.0,
                      "Initial bulk coolant temperature at core exit. Affects initial "
                      "enthalpy and moderator reactivity feedback. Uncertainty reflects "
                      "thermocouple calibration and flow mixing (~±3°C)."),
    "diameter_break":("Break diameter [m]",           "uniform",   0.20,    0.15,    0.25,
                      "Equivalent break diameter. Drives blowdown rate and peak clad "
                      "temperature. Use a uniform distribution to represent break spectrum "
                      "uncertainty."),
    "Cd_sub":        ("Break Cd (subcooled)",         "uniform",   0.93,    0.85,    1.00,
                      "Discharge coefficient for subcooled critical flow at the break. "
                      "Accounts for vena contracta and non-equilibrium effects. "
                      "Range 0.85–1.0 per NUREG validation studies."),
    "k_fuel":        ("Fuel conductivity [W/m·K]",   "uniform",   3.0,     2.5,     3.5,
                      "UO₂ thermal conductivity. Decreases with burnup and temperature. "
                      "Controls fuel centreline temperature and stored energy. "
                      "Typical BOL ~3 W/m·K; EOL ~2.5 W/m·K."),
    "h_gap":         ("Gap conductance [W/m²·K]",    "uniform", 6000.0, 3000.0,  9000.0,
                      "Fuel-clad gap conductance — the largest single contributor to fuel "
                      "temperature uncertainty. Depends on gap size, fill gas, and contact "
                      "pressure. Wide uniform range reflects as-fabricated variation."),
    "r_fuel_m":      ("Fuel radius [m]",              "uniform", 0.00418, 0.00390, 0.00440,
                      "Fuel pellet outer radius. Manufacturing tolerance ~±0.025 mm. "
                      "Affects fuel heat capacity, stored energy, and gap conductance area."),
    "rho_fuel":      ("Fuel density [kg/m³]",         "uniform", 10400.0, 10000.0, 10800.0,
                      "UO₂ pellet density (theoretical ~10 960 kg/m³). "
                      "Affects fuel heat capacity and total stored energy in the core."),
    "cp_fuel":       ("Fuel Cp [J/kg·K]",             "uniform",   330.0,   300.0,   360.0,
                      "UO₂ specific heat capacity. Increases with temperature. "
                      "Controls the rate of fuel temperature rise during a transient."),
    "delta_clad":    ("Clad thickness [m]",           "uniform", 0.00057, 0.00050, 0.00065,
                      "Zircaloy cladding wall thickness. Manufacturing tolerance ~±0.05 mm. "
                      "Affects conduction resistance between fuel and coolant."),
    "lambda_clad":   ("Clad conductivity [W/m·K]",   "uniform",   13.0,    11.0,    15.0,
                      "Zircaloy-4 thermal conductivity. Relatively insensitive to "
                      "temperature in the operating range. Uncertainty ~±15%."),
    "htc_post_chf":  ("Bromley HTC cap [W/m²·K]",   "uniform",   450.0,   300.0,   600.0,
                      "Upper limit on the Bromley film-boiling HTC after CHF. "
                      "Represents uncertainty in the inverted-annular flow regime at "
                      "high pressure. Lower values give more conservative PCT."),
    "htc_core_mult": ("Core HTC multiplier",          "uniform",   1.0,     0.8,     1.2,
                      "Multiplicative factor on the forced-convection (Dittus-Boelter / "
                      "Churchill-Chu) core HTC during normal pre-CHF operation. "
                      "Values < 1 reduce cladding-to-coolant heat transfer, raising clad "
                      "temperature and advancing DNB onset. Conservative direction: < 1. "
                      "Typical UA range ±20% (0.8–1.2)."),
    "htc_fb_mult":   ("Film boiling HTC multiplier",  "uniform",   1.0,     0.5,     2.0,
                      "Multiplicative factor on the post-CHF film boiling HTC — applied "
                      "to both the Bromley (inverted-annular) result and the steam "
                      "Dittus-Boelter (reflood / uncovery) result before the htc_post_chf "
                      "cap is enforced. Values < 1 worsen post-CHF cooling and raise PCT. "
                      "Conservative direction: < 1. "
                      "Wide range reflects factor-of-2 scatter in film boiling data."),
    "rewet_dT_K":    ("Leidenfrost ΔT [K]",          "uniform",   200.0,   150.0,   300.0,
                      "Maximum cladding superheat above T_sat at which rewetting "
                      "(return to nucleate boiling) is permitted. "
                      "Higher values delay rewetting and produce higher PCT."),
}

DIST_OPTIONS = ["uniform", "normal", "lognormal", "triangular"]

DIST_PARAM_LABELS = {
    "uniform":    ("Lower bound",  "Upper bound"),
    "normal":     ("Mean",         "Std deviation"),
    "lognormal":  ("ln(mean)",     "ln(std)"),
    "triangular": ("Lower bound",  "Upper bound"),
}

UA_VARIABLES_FILE = _runtime_file("flare_ua_variables.json")

def _normalize_ua_variable_catalog(raw):
    """Return UA variable catalogue in the internal tuple format.

    JSON format expected:
      {
        "parameter_name": {
          "label": "Display label",
          "distribution": "uniform|normal|lognormal|triangular",
          "base": 1.0,
          "p1": 0.8,
          "p2": 1.2,
          "help": "Sidebar help text"
        }
      }

    Keys beginning with '_' are ignored so the JSON file may contain comments
    such as "_note" without becoming a model parameter.
    """
    if isinstance(raw, list):
        items = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name") or entry.get("variable") or entry.get("var")
            if name:
                items.append((str(name), entry))
    elif isinstance(raw, dict):
        items = [(str(k), v) for k, v in raw.items()
                 if not str(k).startswith("_")]
    else:
        raise ValueError("UA variable catalogue must be a JSON object or list.")

    catalog = {}
    for var, cfg in items:
        if not isinstance(cfg, dict):
            raise ValueError(f"UA variable '{var}' must be a JSON object.")
        label = str(cfg.get("label", var))
        dist  = str(cfg.get("distribution", cfg.get("dist", "uniform"))).lower()
        if dist not in DIST_OPTIONS:
            raise ValueError(
                f"UA variable '{var}' has invalid distribution '{dist}'. "
                f"Allowed: {', '.join(DIST_OPTIONS)}"
            )
        try:
            base = float(cfg.get("base"))
            p1   = float(cfg.get("p1", cfg.get("param1")))
            p2   = float(cfg.get("p2", cfg.get("param2")))
        except Exception as exc:
            raise ValueError(
                f"UA variable '{var}' must define numeric base, p1, and p2 values."
            ) from exc
        help_text = str(cfg.get("help", cfg.get("description", "")))
        catalog[var] = (label, dist, base, p1, p2, help_text)

    if not catalog:
        raise ValueError("UA variable catalogue contains no usable variables.")
    return catalog

def _write_default_ua_variables_file(path: Path):
    """Create an editable JSON catalogue from the built-in defaults."""
    raw = {}
    for var, (label, dist, base, p1, p2, help_text) in DEFAULT_UA_VARIABLES.items():
        raw[var] = {
            "label": label,
            "distribution": dist,
            "base": base,
            "p1": p1,
            "p2": p2,
            "help": help_text,
        }
    path.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")

def load_ua_variables():
    """Load sidebar UA parameter catalogue from runtime/flare_ua_variables.json.

    If the file is absent, it is created from the built-in defaults. If the
    file is malformed, the UI continues with the built-in defaults and shows a
    warning rather than preventing FLARE from loading.
    """
    try:
        if not UA_VARIABLES_FILE.exists():
            _write_default_ua_variables_file(UA_VARIABLES_FILE)
        raw = json.loads(UA_VARIABLES_FILE.read_text(encoding="utf-8"))
        return _normalize_ua_variable_catalog(raw)
    except Exception as exc:
        st.warning(
            f"Could not load `{UA_VARIABLES_FILE.name}`; using built-in UA variable defaults. "
            f"Reason: {exc}"
        )
        return DEFAULT_UA_VARIABLES.copy()

UA_VARIABLES = load_ua_variables()

PLOT_BG    = "#ffffff"
PLOT_PAPER = "#f5f7fa"
PLOT_GRID  = "#d0d7de"
PLOT_TEXT  = "#1f2328"
C = ["#0969da","#cf222e","#1a7f37","#9a6700","#6e40c9","#bc4c00"]


# Time-series variables offered in the UA overlay selector.
# This list intentionally mirrors the variables plotted by the PWR Simulator
# Results tab (flare_ui.py / flare_sim.py), so the UA plot selector stays
# focused on quantities that are already meaningful in normal FLARE review.
UA_PLOTTED_TS_COLUMNS = [
    # Fig 1-5: primary response, inventory, and discharge
    "RCS Pressure (kPa)",
    "Equilibrium Quality (-)",
    "Void Fraction (-)",
    "Total Mass Scaled",
    "Vessel Level (m)",
    "Break Flow (kg/s)",
    "PORV Mass Flow (kg/s)",

    # Fig 6-9: accumulator and injection / letdown flows
    "Accumulator Pressure (kPa)",
    "Accumulator Temperature (K)",
    "Accumulator Level (m)",
    "Accumulator Flow (kg/s)",
    "CVCS Makeup (kg/s)",
    "CVCS Letdown (kg/s)",
    "HPSI Flow (kg/s)",
    "LPSI Flow (kg/s)",
    "SI Pumped Total (kg/s)",

    # Fig 10-13: power, pump, and SG response
    "RK Total Power (MW)",
    "Core Power (MW)",
    "Pump Speed (rpm)",
    "Pump Velocity (m/s)",
    "SG Heat Removal (MW)",

    # Fig 14-16: core temperatures, HTC, and DNBR
    "Clad Surface Temp (K)",
    "RCS Temperature (K)",
    "Fuel Avg Temp (K)",
    "Hot Pin Clad Temp (K)",
    "Hot Pin Fuel Temp (K)",
    "Clad HTC (W/m2-K)",
    "DNBR",

    # Fig 17: reactivity components
    "Reactivity scram (pcm)",
    "Reactivity ext (pcm)",
    "Reactivity Boron (pcm)",
    "Reactivity Doppler (pcm)",
    "Reactivity Moderator (pcm)",
    "Reactivity net (pcm)",

    # Supplemental PWR Simulator plots
    "Pressurizer Level (m)",
    "Pressurizer Level (norm)",
    "Zr Oxidation Hot Pin ECR (%)",
    "Zr Oxidation Mean Oxidizing Rod ECR (%)",
    "H2 Generated (kg)",
    "H2 Full Core Cladding Reaction (kg)",
    "Zr Oxidizing Rods (est.)",
]

# Maps scalar output variable names to (TS CSV column, offset, unit label)
TS_MAP = {
    "hot_pin_clad_peak_K":  ("Hot Pin Clad Temp (K)",       -273.15, "°C"),
    "hot_pin_clad_final_K": ("Hot Pin Clad Temp (K)",       -273.15, "°C"),
    "avg_clad_peak_K":      ("Clad Surface Temp (K)",       -273.15, "°C"),
    "avg_clad_final_K":     ("Clad Surface Temp (K)",       -273.15, "°C"),
    "hot_pin_fuel_peak_K":  ("Hot Pin Fuel Temp (K)",       -273.15, "°C"),
    "P_min_kPa":            ("RCS Pressure (kPa)",           0,      "kPa"),
    "P_max_kPa":            ("RCS Pressure (kPa)",           0,      "kPa"),
    "T_max_K":              ("RCS Temperature (K)",         -273.15, "°C"),
    "DNBR_min":             ("DNBR",                         0,      ""),
    "N_fail_DNB":           ("Rod Failures DNB (est.)",      0,      "rods"),
    "N_fail_gap":           ("Rod Failures Gap (est.)",      0,      "rods"),
    "N_fail_eiv":           ("Rod Failures EarlyIV (est.)",  0,      "rods"),
    "P_peak_MW":            ("RK Total Power (MW)",          0,      "MW"),
}

# Unit conversion: each entry is (si_label, eng_label, si_to_eng_fn)
# Keyed by column name suffix patterns
# UNIT_CONV: suffix → (si_label, eng_label, si_fn, eng_fn, eng_scale)
# eng_scale is the multiplicative factor only (no offset)  -  used for std dev.
UNIT_CONV = {
    # Temperature columns (stored in K)
    "(K)":    ("°C",   "°F",   lambda v: v - 273.15, lambda v: (v - 273.15)*9/5 + 32, 9/5),
    # Pressure
    "(kPa)":  ("kPa",  "psia", lambda v: v,          lambda v: v * 0.145038,           0.145038),
    # Mass flow
    "(kg/s)": ("kg/s", "lb/s", lambda v: v,          lambda v: v * 2.20462,            2.20462),
    # Power  -  keep MW in both
    "(MW)":   ("MW",   "MW",   lambda v: v,          lambda v: v,                      1.0),
    # Dimensionless / other  -  no conversion
    "[-]":    ("",     "",     lambda v: v,          lambda v: v,                      1.0),
}

# Scalar result column name → unit suffix for lookup in UNIT_CONV
SCALAR_UNIT = {
    "hot_pin_clad_peak_K":  "(K)",
    "hot_pin_clad_final_K": "(K)",
    "avg_clad_peak_K":      "(K)",
    "avg_clad_final_K":     "(K)",
    "hot_pin_fuel_peak_K":  "(K)",
    "T_max_K":              "(K)",
    "P_min_kPa":            "(kPa)",
    "P_max_kPa":            "(kPa)",
    "P_peak_MW":            "(MW)",
}


def _safe_plot_token(text, max_len=48):
    """Return a filesystem-safe token for UA plot filenames."""
    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(text)).strip("_")
    return (token[:max_len] or "plot")


def _ua_convert_series_for_plot(values, col_name, use_english=False):
    arr = pd.to_numeric(pd.Series(values), errors="coerce").to_numpy(dtype=float)
    for suffix, conv in UNIT_CONV.items():
        if str(col_name).endswith(suffix):
            si_lbl, eng_lbl, si_fn, eng_fn = conv[:4]
            fn = eng_fn if use_english else si_fn
            return fn(arr), (eng_lbl if use_english else si_lbl)
    return arr, ""


def _ua_convert_scalar_for_plot(values, col_name, use_english=False):
    arr = pd.to_numeric(pd.Series(values), errors="coerce").to_numpy(dtype=float)
    suffix = SCALAR_UNIT.get(str(col_name))
    if suffix and suffix in UNIT_CONV:
        si_lbl, eng_lbl, si_fn, eng_fn, _scale = UNIT_CONV[suffix]
        fn = eng_fn if use_english else si_fn
        return fn(arr), (eng_lbl if use_english else si_lbl)
    return arr, ""


def _make_ua_plot_set(df_results, ts_list, run_dir: Path, base_case: str,
                      selected_ts: str, selected_out: str, use_english=False,
                      tag="current"):
    """Create PNG files and a multipage PDF for the selected UA plot set.

    The set mirrors the visible UA Results page for the current selections:
    time-series overlay, CDF, input-vs-output scatter plots, and Pearson ranking.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    run_dir = Path(run_dir or WORK_DIR)
    out_dir = run_dir / "ua_plots"
    out_dir.mkdir(parents=True, exist_ok=True)

    df = _restore_input_columns_for_stats(df_results, st.session_state.get("ua_samples"))
    if df is None or len(df) == 0 or "status" not in df.columns:
        raise ValueError("No UA results are available for plotting.")
    df_ok = df[df["status"] == "OK"].copy()
    if len(df_ok) == 0:
        raise ValueError("No successful UA samples are available for plotting.")
    if selected_out not in df_ok.columns:
        raise ValueError(f"Selected scalar output is not available: {selected_out}")

    in_cols = [c for c in df_ok.columns if str(c).startswith("in_")]
    y_raw = pd.to_numeric(df_ok[selected_out], errors="coerce")
    y_vals, y_unit = _ua_convert_scalar_for_plot(y_raw, selected_out, use_english)
    y_label = selected_out.replace("_", " ") + (f" [{y_unit}]" if y_unit else "")

    pngs = []
    pdf_path = out_dir / f"ua_{_safe_plot_token(base_case)}_{_safe_plot_token(tag)}_plots.pdf"

    def _save_current(fig, name):
        png = out_dir / f"ua_{_safe_plot_token(base_case)}_{_safe_plot_token(tag)}_{name}.png"
        fig.tight_layout()
        fig.savefig(png, dpi=180, bbox_inches="tight")
        pngs.append(png)
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

    with PdfPages(pdf_path) as pdf:
        # 1. Time-series overlay
        if ts_list and selected_ts and selected_ts not in ("(no data yet)", "(no plotted variables available)"):
            fig, ax = plt.subplots(figsize=(9.5, 5.2))
            n = len(ts_list)
            plotted = 0
            for j, entry in enumerate(ts_list):
                try:
                    ts_df = entry["df"]
                    if selected_ts not in ts_df.columns or "Time (s)" not in ts_df.columns:
                        continue
                    x = pd.to_numeric(ts_df["Time (s)"], errors="coerce")
                    y, unit = _ua_convert_series_for_plot(ts_df[selected_ts], selected_ts, use_english)
                    ax.plot(x, y, linewidth=1.0, alpha=0.55, label=f"S{entry.get('sample', j+1)}")
                    plotted += 1
                except Exception:
                    continue
            if plotted:
                base_label = selected_ts
                for sfx in UNIT_CONV:
                    if selected_ts.endswith(sfx):
                        base_label = selected_ts[:-len(sfx)].rstrip()
                        break
                ax.set_title(f"UA Time-Series Overlay — {selected_ts}")
                ax.set_xlabel("Time [s]")
                ax.set_ylabel(f"{base_label} [{unit}]" if unit else base_label)
                ax.grid(True, alpha=0.35)
                if plotted <= 20:
                    ax.legend(fontsize=7, ncol=2)
                _save_current(fig, "fig01_timeseries")
            else:
                plt.close(fig)

        # 2. CDF
        valid = np.isfinite(y_vals)
        if valid.any():
            ys = np.sort(y_vals[valid])
            cdf = np.arange(1, len(ys) + 1) / len(ys)
            fig, ax = plt.subplots(figsize=(8, 5))
            ax.plot(ys, cdf, linewidth=2.0)
            ax.set_title(f"UA CDF — {selected_out}")
            ax.set_xlabel(y_label)
            ax.set_ylabel("Cumulative probability")
            ax.set_ylim(0, 1)
            ax.grid(True, alpha=0.35)
            _save_current(fig, "fig02_cdf")

        # 3. Scatter plots for each sampled input
        corr_pairs = []
        fig_no = 3
        for in_col in in_cols:
            x = pd.to_numeric(df_ok[in_col], errors="coerce").to_numpy(dtype=float)
            y = y_vals
            mask = np.isfinite(x) & np.isfinite(y)
            if mask.sum() < 2:
                continue
            r = np.corrcoef(x[mask], y[mask])[0, 1] if mask.sum() > 2 else np.nan
            if np.isfinite(r):
                corr_pairs.append((in_col.replace("in_", ""), r))
            fig, ax = plt.subplots(figsize=(7.5, 5))
            ax.scatter(x[mask], y[mask], s=24, alpha=0.7)
            title = f"{in_col.replace('in_', '')} vs {selected_out}"
            if np.isfinite(r):
                title += f"  (r={r:.3f})"
            ax.set_title(title)
            ax.set_xlabel(in_col.replace("in_", ""))
            ax.set_ylabel(y_label)
            ax.grid(True, alpha=0.35)
            _save_current(fig, f"fig{fig_no:02d}_scatter_{_safe_plot_token(in_col.replace('in_', ''))}")
            fig_no += 1

        # 4. Pearson ranking / tornado
        if corr_pairs:
            corr_pairs = sorted(corr_pairs, key=lambda p: abs(p[1]), reverse=True)
            labels = [p[0] for p in corr_pairs]
            vals = [p[1] for p in corr_pairs]
            fig_h = max(4.5, 0.35 * len(labels) + 1.5)
            fig, ax = plt.subplots(figsize=(8, fig_h))
            ax.barh(labels[::-1], vals[::-1])
            ax.axvline(0.0, linewidth=1.0)
            ax.set_xlim(-1, 1)
            ax.set_xlabel("Pearson correlation coefficient, r")
            ax.set_title(f"Pearson Ranking — {selected_out}")
            ax.grid(True, axis="x", alpha=0.35)
            _save_current(fig, f"fig{fig_no:02d}_pearson_ranking")

    if not pngs:
        raise ValueError("No plots could be generated for the current selections.")
    return {"pdf": pdf_path, "pngs": pngs, "out_dir": out_dir}


# ── Helpers ───────────────────────────────────────────────────────────────────

_EXCLUDED_INPUT_DIR_PREFIXES = ("sim_", "risk_", "ua_", ".sim_all_", "__pycache__")

def _is_generated_input_dir(path: Path) -> bool:
    try:
        rel_parts = path.relative_to(WORK_DIR).parts
    except Exception:
        rel_parts = path.parts
    return any(part.startswith(_EXCLUDED_INPUT_DIR_PREFIXES) or part.startswith(".")
               for part in rel_parts)

def discover_input_cases():
    entries = []
    for p in WORK_DIR.rglob("*_in.xlsx"):
        if p.parent == WORK_DIR:
            continue
        if p.stem.startswith(".~") or p.stem.startswith("ua_"):
            continue
        if _is_generated_input_dir(p.parent):
            continue
        case = p.stem[:-3] if p.stem.endswith("_in") else p.stem.replace("_in", "")
        rel = p.parent.relative_to(WORK_DIR).as_posix()
        entries.append({"case": case, "path": p, "rel": rel, "label": f"{case}  —  {rel}"})
    entries.sort(key=lambda e: (e["case"].lower(), e["rel"].lower()))
    return entries

def find_cases():
    return [e["label"] for e in discover_input_cases()]


def sample_values(dist, p1, p2, base, n, rng):
    """Sample n values from the specified distribution.
    Raises ValueError with a descriptive message if parameters are invalid.
    """
    if dist == "uniform":
        if p1 >= p2:
            raise ValueError(
                f"Uniform distribution requires Lower < Upper, got {p1} >= {p2}")
        return rng.uniform(p1, p2, n)
    elif dist == "normal":
        if p2 <= 0:
            raise ValueError(
                f"Normal distribution requires Std deviation > 0, got {p2}")
        raw = rng.normal(p1, p2, n)
        return np.clip(raw, p1 - 4*p2, p1 + 4*p2)
    elif dist == "lognormal":
        if p2 <= 0:
            raise ValueError(
                f"Lognormal distribution requires ln(std) > 0, got {p2}")
        return np.exp(rng.normal(p1, p2, n))
    elif dist == "triangular":
        if p1 >= p2:
            raise ValueError(
                f"Triangular distribution requires Lower < Upper, got {p1} >= {p2}")
        if not (p1 <= base <= p2):
            raise ValueError(
                f"Triangular mode (base={base:.4g}) must be between Lower={p1} and Upper={p2}")
        return rng.triangular(p1, base, p2, n)
    return np.full(n, base)


def build_ua_input(base_case, overrides: dict, sample_id: int, run_dir: Path = None, input_path=None):
    """
    Copy base _in.xlsx to a temp UA input file.
    Appends override assignments just before the Time (s) data table header,
    so last-assignment-wins semantics apply without touching existing rows.
    Returns temp case name.
    """
    src      = Path(input_path) if input_path is not None else WORK_DIR / f"{base_case}_in.xlsx"
    tmp_name = f"ua_{base_case}_{sample_id}"
    # Always write input to WORK_DIR so simulation finds it;
    # outputs are moved to run_dir after the run completes.
    dst      = WORK_DIR / f"{tmp_name}_in.xlsx"

    wb = load_workbook(src)
    ws = wb[f"{base_case}_in"]
    if f"{base_case}_out" in wb.sheetnames:
        wb[f"{base_case}_out"].title = f"{tmp_name}_out"
    ws.title = f"{tmp_name}_in"

    # Find the Time (s) header row  -  insert overrides just before it.
    time_row = None
    for row in ws.iter_rows(max_col=1):
        v = row[0].value
        if isinstance(v, str) and v.strip().startswith("Time"):
            time_row = row[0].row
            break

    if time_row is None:
        time_row = ws.max_row  # fallback

    n_ins = len(overrides) + 1  # +1 comment
    ws.insert_rows(time_row, amount=n_ins)

    ws.cell(row=time_row, column=1).value = "# UA overrides (last-assignment-wins)"
    for i, (var, val) in enumerate(overrides.items(), start=1):
        ws.cell(row=time_row + i, column=1).value = f"{var} = {val:.8g}"

    wb.save(dst)
    wb.close()
    return tmp_name


def extract_scalars(base_case, sample_id, run_dir: Path = None):
    """Extract key scalar results from sample output CSV."""
    _dir     = run_dir if run_dir is not None else WORK_DIR
    csv_path = _dir / f"ua_{base_case}_{sample_id}_out.csv"
    if not csv_path.exists():
        return {}
    try:
        df = pd.read_csv(csv_path)
        r  = {}
        if "RCS Pressure (kPa)" in df.columns:
            r["P_min_kPa"] = df["RCS Pressure (kPa)"].min()
        if "DNBR" in df.columns:
            dn = df["DNBR"].replace(0, np.nan)
            r["DNBR_min"]  = dn.min()
        if "Clad Surface Temp (K)" in df.columns:
            tw = df["Clad Surface Temp (K)"]
            r["avg_clad_peak_K"]  = tw.max()
            r["avg_clad_final_K"] = tw.dropna().iloc[-1]
        if "Hot Pin Clad Temp (K)" in df.columns:
            thc = df["Hot Pin Clad Temp (K)"]
            r["hot_pin_clad_peak_K"]  = thc.max()
            r["hot_pin_clad_final_K"] = thc.dropna().iloc[-1]
        if "Rod Failures DNB (est.)" in df.columns:
            r["N_fail_DNB"]  = int(df["Rod Failures DNB (est.)"].max())
        if "Rod Failures Gap (est.)" in df.columns:
            r["N_fail_gap"]  = int(df["Rod Failures Gap (est.)"].max())
        if "Rod Failures EarlyIV (est.)" in df.columns:
            r["N_fail_eiv"]  = int(df["Rod Failures EarlyIV (est.)"].max())
        return r
    except Exception as e:
        return {"error": str(e)}


def cleanup_sample(base_case, sample_id):
    for suffix in ("_in.xlsx", "_out.xlsx", "_out.csv", "_fail.csv"):
        p = WORK_DIR / f"ua_{base_case}_{sample_id}{suffix}"
        try:
            p.unlink()
        except Exception:
            pass


# ── Worker-process helpers ───────────────────────────────────────────────────
_UA_STATUS_FILE = "ua_status.json"
_UA_CONFIG_FILE = "ua_worker_config.json"
_UA_ABORT_FILE  = "ua_abort_requested.json"

def _json_read(path: Path, default=None):
    try:
        if path and path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default

def _tail_text(path: Path, max_chars=12000):
    try:
        if path and path.exists():
            txt = path.read_text(encoding="utf-8", errors="replace")
            return txt[-max_chars:]
    except Exception as e:
        return f"(Could not read log: {e})"
    return ""

def _restore_input_columns_for_stats(results_df, samples_df=None):
    """Ensure UA result tables contain in_<var> columns for statistics plots.

    The worker writes clean CSV headers for user-facing output, but the
    Results tab historically expects sampled inputs to be named in_<var>.
    Reconstruct those columns from the samples table when needed, so scatter
    plots and Pearson/tornado rankings remain available for old and new runs.
    """
    if results_df is None:
        return results_df
    df = results_df.copy()

    # Already in the historical/internal format.
    if any(str(c).startswith("in_") for c in df.columns):
        return df

    if samples_df is None or len(samples_df) == 0 or "sample" not in samples_df.columns:
        return df

    try:
        samp = samples_df.copy()
        input_cols = [c for c in samp.columns if c != "sample"]
        if not input_cols or "sample" not in df.columns:
            return df

        add_cols = samp[["sample"] + input_cols].copy()
        add_cols = add_cols.rename(columns={c: f"in_{c}" for c in input_cols})

        # Drop any accidental duplicate unprefixed input columns from the result
        # frame before merge; otherwise they appear as output choices.
        drop_unprefixed = [c for c in input_cols if c in df.columns]
        if drop_unprefixed:
            df = df.drop(columns=drop_unprefixed)

        df = df.merge(add_cols, on="sample", how="left")
    except Exception:
        return results_df
    return df


def _format_elapsed_from_status(status: dict) -> str:
    """Return total elapsed run time from ua_status.json as H:MM:SS.

    The worker keeps its PID in the status file for abort handling, but the UI
    displays elapsed time instead because that is more useful to the user.
    """
    try:
        started = status.get("started")
        if started:
            # Worker timestamps are local ISO strings from datetime.now().isoformat().
            t0 = datetime.fromisoformat(str(started))
            secs = max(0, int((datetime.now() - t0).total_seconds()))
        else:
            # Fallback: current-sample elapsed if a legacy worker/status file lacks
            # the total-run start timestamp.
            secs = max(0, int(float(status.get("elapsed_current_s", 0) or 0)))
        h, rem = divmod(secs, 3600)
        m, sec = divmod(rem, 60)
        return f"{h:d}:{m:02d}:{sec:02d}" if h else f"{m:d}:{sec:02d}"
    except Exception:
        return "—"

def _load_ua_run_from_dir(run_dir: Path, base_case: str):
    """Load worker-produced UA results, samples, and time-series into session state."""
    res_csv  = run_dir / f"ua_{base_case}_results.csv"
    samp_csv = run_dir / f"ua_{base_case}_samples.csv"
    _res_df = pd.read_csv(res_csv) if res_csv.exists() else None
    _samp_df = pd.read_csv(samp_csv) if samp_csv.exists() else None
    if _samp_df is not None:
        st.session_state.ua_samples = _samp_df
    if _res_df is not None:
        st.session_state.ua_results = _restore_input_columns_for_stats(_res_df, _samp_df)
    _ts_list = []
    import re as _re
    for _ts_f in sorted(run_dir.glob(f"ua_{base_case}_*_out.csv")):
        _m = _re.search(r"_(\d+)_out\.csv$", _ts_f.name)
        if _m:
            try:
                _ts_list.append({"sample": int(_m.group(1)), "df": pd.read_csv(_ts_f)})
            except Exception:
                pass
    st.session_state.ua_ts = _ts_list
    st.session_state.ua_run_dir = run_dir
    st.session_state.ua_case = base_case

def _find_recent_active_ua_run():
    """Return most recent UA run folder whose status is running/starting."""
    runs = sorted(
        [d for d in WORK_DIR.iterdir()
         if d.is_dir() and d.name.startswith("ua_") and (d / _UA_STATUS_FILE).exists()],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    for d in runs:
        s = _json_read(d / _UA_STATUS_FILE, {})
        if s.get("status") in ("starting", "running"):
            return d
    return None

def _start_ua_worker(base_case, active_vars, n_samples, fast_mode, input_path=None):
    """Create a UA run folder, write config, and launch detached worker."""
    _run_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = WORK_DIR / f"ua_{base_case}_{_run_tag}"
    run_dir.mkdir(exist_ok=True)

    cfg = {
        "work_dir": str(WORK_DIR),
        "run_dir": str(run_dir),
        "base_case": base_case,
        "base_input_path": str(input_path) if input_path is not None else str(WORK_DIR / f"{base_case}_in.xlsx"),
        "active_vars": active_vars,
        "n_samples": int(n_samples),
        "fast_mode": bool(fast_mode),
        "timeout_s": 600,
    }
    cfg_path = run_dir / _UA_CONFIG_FILE
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    stdout_path = run_dir / "ua_worker_stdout.log"
    stderr_path = run_dir / "ua_worker_stderr.log"

    worker = WORK_DIR / "flare_ua_worker.py"
    if not worker.exists():
        raise FileNotFoundError(
            f"{worker.name} was not found in the FLARE folder. "
            "Place flare_ua_worker.py beside flare_ua.py."
        )

    # Use unbuffered Python so status/log output is available promptly.
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["MPLBACKEND"] = "Agg"
    flags = 0
    try:
        flags = subprocess.CREATE_NEW_PROCESS_GROUP  # Windows
    except AttributeError:
        flags = 0

    with open(stdout_path, "w", encoding="utf-8", errors="replace") as out, \
         open(stderr_path, "w", encoding="utf-8", errors="replace") as err:
        proc = subprocess.Popen(
            [sys.executable, "-u", str(worker), str(cfg_path)],
            cwd=str(WORK_DIR),
            stdout=out,
            stderr=err,
            env=env,
            creationflags=flags,
        )

    st.session_state.ua_run_dir = run_dir
    st.session_state.ua_case = base_case
    st.session_state.ua_status = "running"
    st.session_state.ua_results = None
    st.session_state.ua_samples = None
    st.session_state.ua_ts = []
    return proc.pid, run_dir

def _request_ua_abort(run_dir: Path):
    """Ask worker to abort and, if available, kill the worker/child process tree."""
    abort_path = run_dir / _UA_ABORT_FILE
    abort_path.write_text(json.dumps({
        "abort_requested": True,
        "requested_at": datetime.now().isoformat(timespec="seconds"),
        "reason": "User clicked Abort UA Run in the FLARE UI.",
    }, indent=2), encoding="utf-8")

    status = _json_read(run_dir / _UA_STATUS_FILE, {})
    pids = [status.get("current_pid"), status.get("worker_pid")]
    for pid in [p for p in pids if p]:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                               capture_output=True, text=True, timeout=10)
            else:
                os.kill(int(pid), 15)
        except Exception:
            pass


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    # ── Return to FLARE home ──────────────────────────────────────────────────
    st.markdown("""
        <style>
        [data-testid="stSidebar"] button[kind="secondary"] {
            background: transparent !important;
            border: 1px solid #e8530a !important;
            border-radius: 4px !important;
            color: #f97316 !important;
            font-size: 0.82rem !important;
            letter-spacing: 0.08em !important;
            font-weight: 700 !important;
        }
        [data-testid="stSidebar"] button[kind="secondary"]:hover {
            background: rgba(232,83,10,0.18) !important;
            box-shadow: 0 0 14px rgba(232,83,10,0.45) !important;
            color: #ffffff !important;
        }
        </style>""", unsafe_allow_html=True)
    if st.button("\U0001f525  FLARE Home", key="home_btn", width="stretch"):
        st.session_state.page = "home"
        st.query_params.clear()
        st.rerun()
    st.divider()
    # ─────────────────────────────────────────────────────────────────────────
    st.markdown('<div style="font-family:IBM Plex Mono;font-size:1.4rem;'
                'color:#e6edf3;font-weight:600;margin-bottom:2px">⚛ FLARE UA</div>',
                unsafe_allow_html=True)
    st.markdown('<div style="font-size:0.8rem;color:#8b949e;'
                'margin-bottom:1rem">Uncertainty Analysis</div>',
                unsafe_allow_html=True)

    # Number of samples  -  first and most prominent
    n_samples = st.number_input("Number of samples", min_value=1,
                                max_value=5000, value=50, step=10,
                                help=(
                                    "Number of Monte Carlo simulation runs. "
                                    "50–100 samples is sufficient to estimate the mean and "
                                    "standard deviation of most outputs. "
                                    "200+ samples are needed for reliable 95th-percentile "
                                    "estimates (Wilks' formula requires 59 for one-sided 95/95). "
                                    "Runtime scales linearly — allow ~1 min per sample."
                                ))

    st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

    # Case selector
    _case_entries = discover_input_cases()
    if not _case_entries:
        st.error("No *_in.xlsx files found in FLARE subfolders. Root-level input files are intentionally ignored.")
        st.stop()
    _case_labels = [e["label"] for e in _case_entries]
    _selected_label = st.selectbox("Base case", _case_labels,
                             help=(
                                 "The nominal input case to perturb. Input decks are discovered recursively in "
                                 "subfolders below the FLARE root; root-level inputs and generated output folders are ignored. "
                                 "All sampled parameters are varied around their base-case values; unselected parameters "
                                 "keep their base-case value exactly."
                             ))
    _selected_entry = next(e for e in _case_entries if e["label"] == _selected_label)
    selected = _selected_entry["case"]
    selected_input_path = _selected_entry["path"]
    st.caption(f"Input file: `{selected_input_path.relative_to(WORK_DIR)}`")

    st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

    # Per-variable distribution editor
    active_vars = {}
    st.caption(
        "Enable each variable you want to treat as uncertain and set its "
        "probability distribution. Variables left unchecked are held at "
        "their base-case value for every sample. "
        "Hover over any variable name for its physical description and typical range."
    )
    with st.expander("Edit variable distributions", expanded=True):
        for var, (label, def_dist, base, def_p1, def_p2, var_help) in UA_VARIABLES.items():
            enabled = st.checkbox(label, value=False, key=f"en_{var}",
                                  help=var_help)
            if enabled:
                c1, c2, c3 = st.columns([2, 1.5, 1.5])
                with c1:
                    dist = st.selectbox("Distribution", DIST_OPTIONS,
                                        index=DIST_OPTIONS.index(def_dist),
                                        key=f"dist_{var}", label_visibility="collapsed",
                                        help=(
                                            "uniform — equal probability between lower and upper bound.\n"
                                            "normal — Gaussian; sampled values clipped to ±4σ.\n"
                                            "lognormal — log-space normal; use for strictly positive "
                                            "quantities with multiplicative uncertainty.\n"
                                            "triangular — peaked at the base-case value with "
                                            "user-specified lower and upper bounds."
                                        ))
                lbl1, lbl2 = DIST_PARAM_LABELS[dist]
                with c2:
                    p1 = st.number_input(lbl1, value=float(def_p1),
                                         format="%.6g",
                                         key=f"p1_{var}", label_visibility="collapsed",
                                         help=lbl1)
                with c3:
                    p2 = st.number_input(lbl2, value=float(def_p2),
                                         format="%.6g",
                                         key=f"p2_{var}", label_visibility="collapsed",
                                         help=lbl2)
                active_vars[var] = {"dist": dist, "base": base,
                                    "p1": p1, "p2": p2, "label": label}

    st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

    # ── Previous-run selector ─────────────────────────────────────────────
    import re as _re2
    _prev_runs = sorted(
        [d for d in WORK_DIR.iterdir()
         if d.is_dir()
         and d.name.startswith("ua_")
         and any(d.glob("*_results.csv"))],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    if _prev_runs:
        _run_labels = ["— current session —"] + [d.name for d in _prev_runs]
        _sel_run = st.selectbox(
            "Load previous run",
            _run_labels,
            key="ua_prev_run_sel",
            help="Select a completed UA run folder to review its results.",
        )
        if _sel_run != "— current session —":
            _sel_dir = WORK_DIR / _sel_run
            _case_from_dir = _re2.sub(r"_\d{8}_\d{6}$", "", _sel_run[3:])
            _res_csv  = _sel_dir / f"ua_{_case_from_dir}_results.csv"
            _samp_csv = _sel_dir / f"ua_{_case_from_dir}_samples.csv"
            if st.session_state.get("_ua_loaded_run") != _sel_run:
                if st.button("📥  Load", key="ua_load_prev"):
                    try:
                        _res_df = pd.read_csv(_res_csv)
                        _samp_df = pd.read_csv(_samp_csv) if _samp_csv.exists() else None
                        st.session_state.ua_results  = _restore_input_columns_for_stats(_res_df, _samp_df)
                        st.session_state.ua_run_dir  = _sel_dir
                        st.session_state.ua_case     = _case_from_dir
                        if _samp_df is not None:
                            st.session_state.ua_samples = _samp_df
                        _ts_list = []
                        for _ts_f in sorted(_sel_dir.glob(
                                f"ua_{_case_from_dir}_*_out.csv")):
                            _m = _re2.search(r"_(\d+)_out\.csv$", _ts_f.name)
                            if _m:
                                try:
                                    _ts_list.append({"sample": int(_m.group(1)),
                                                     "df": pd.read_csv(_ts_f)})
                                except Exception:
                                    pass
                        st.session_state.ua_ts = _ts_list
                        st.session_state._ua_loaded_run = _sel_run
                        st.rerun()
                    except Exception as _le:
                        st.error(f"Could not load run: {_le}")

    st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)
    _fast_mode = st.checkbox(
        "Fast mode (no figures)",
        value=True,
        key="ua_fast_mode",
        help="Skip figure generation for each sample run. Only CSV and XLSX are written. Recommended for UA batch runs.",
    )
    run_btn = st.button("▶  Run UA", type="primary",
                        width="stretch",
                        disabled=len(active_vars) == 0)
    if len(active_vars) == 0:
        st.caption("Enable at least one variable above.")

    st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)
    st.caption("flare_sim.py")
    st.caption(f"Working dir: `{WORK_DIR}`")


# ── Main panel ────────────────────────────────────────────────────────────────

st.markdown(f"## Uncertainty Analysis &mdash; {selected}")

tab_run, tab_results, tab_samples = st.tabs(
    ["▶  Run", "📊  Results", "📋  Samples"]
)

# ── Session state ─────────────────────────────────────────────────────────────
if "ua_log"     not in st.session_state: st.session_state.ua_log     = ""
if "ua_status"  not in st.session_state: st.session_state.ua_status  = "idle"
if "ua_results" not in st.session_state: st.session_state.ua_results = None
if "ua_samples" not in st.session_state: st.session_state.ua_samples = None
if "ua_case"    not in st.session_state: st.session_state.ua_case    = None
if "ua_ts"      not in st.session_state: st.session_state.ua_ts      = []   # time-series per sample
if "ua_run_dir" not in st.session_state: st.session_state.ua_run_dir = None # output subfolder


# ── Run tab ───────────────────────────────────────────────────────────────────
with tab_run:
    # Recover an active worker run after browser refresh/reconnect.
    if st.session_state.ua_status in ("idle", "running") and st.session_state.ua_run_dir is None:
        _active = _find_recent_active_ua_run()
        if _active is not None:
            _st = _json_read(_active / _UA_STATUS_FILE, {})
            st.session_state.ua_run_dir = _active
            st.session_state.ua_case = _st.get("base_case") or selected
            st.session_state.ua_status = "running"

    _run_dir = st.session_state.get("ua_run_dir")
    _status_json = _json_read(_run_dir / _UA_STATUS_FILE, {}) if _run_dir else {}
    status = _status_json.get("status", st.session_state.ua_status)

    # Keep session status synchronized with worker status.
    if status in ("starting", "running"):
        st.session_state.ua_status = "running"
    elif status in ("complete", "done"):
        st.session_state.ua_status = "done"
    elif status in ("failed", "error"):
        st.session_state.ua_status = "error"
    elif status == "aborted":
        st.session_state.ua_status = "aborted"

    badge_map = {
        "idle":     '<span style="background:#9a6700;color:white;padding:2px 10px;border-radius:4px;font-family:IBM Plex Mono;font-size:0.8rem">IDLE</span>',
        "starting": '<span style="background:#0969da;color:white;padding:2px 10px;border-radius:4px;font-family:IBM Plex Mono;font-size:0.8rem">STARTING</span>',
        "running":  '<span style="background:#0969da;color:white;padding:2px 10px;border-radius:4px;font-family:IBM Plex Mono;font-size:0.8rem">RUNNING</span>',
        "complete": '<span style="background:#1a7f37;color:white;padding:2px 10px;border-radius:4px;font-family:IBM Plex Mono;font-size:0.8rem">COMPLETE</span>',
        "done":     '<span style="background:#1a7f37;color:white;padding:2px 10px;border-radius:4px;font-family:IBM Plex Mono;font-size:0.8rem">COMPLETE</span>',
        "failed":   '<span style="background:#cf222e;color:white;padding:2px 10px;border-radius:4px;font-family:IBM Plex Mono;font-size:0.8rem">FAILED</span>',
        "error":    '<span style="background:#cf222e;color:white;padding:2px 10px;border-radius:4px;font-family:IBM Plex Mono;font-size:0.8rem">FAILED</span>',
        "aborted":  '<span style="background:#cf222e;color:white;padding:2px 10px;border-radius:4px;font-family:IBM Plex Mono;font-size:0.8rem">ABORTED</span>',
    }
    st.markdown(badge_map.get(status, badge_map["idle"]), unsafe_allow_html=True)

    if run_btn and status not in ("starting", "running") and active_vars:
        try:
            _pid, _rd = _start_ua_worker(selected, active_vars, int(n_samples), _fast_mode)
            st.success(f"Started UA run in `{_rd.name}`.")
            st.rerun()
        except Exception as _e:
            st.session_state.ua_status = "error"
            st.session_state.ua_log = f"Could not start UA worker: {_e}"
            st.error(st.session_state.ua_log)

    # Active worker status / progress display.
    _run_dir = st.session_state.get("ua_run_dir")
    _status_json = _json_read(_run_dir / _UA_STATUS_FILE, {}) if _run_dir else {}
    _status = _status_json.get("status", st.session_state.ua_status)

    if _run_dir:
        st.caption(f"Run folder: `{_run_dir.name}`")

    if _status in ("starting", "running"):
        total = int(_status_json.get("total_samples", n_samples) or n_samples or 1)
        done  = int(_status_json.get("completed_samples", 0) or 0)
        failed = int(_status_json.get("failed_samples", 0) or 0)
        current = _status_json.get("current_sample", "")
        frac = min(1.0, max(0.0, done / max(total, 1)))

        st.progress(frac, text=f"Completed {done}/{total} samples · Failed {failed} · Current sample {current}")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Completed", f"{done}/{total}")
        m2.metric("Failed", f"{failed}")
        m3.metric("Current sample", str(current or "—"))
        m4.metric("Elapsed", _format_elapsed_from_status(_status_json))

        if st.button("⛔ Abort UA Run", type="primary", width="content"):
            _request_ua_abort(_run_dir)
            st.warning("Abort requested. The current simulation process will be stopped.")
            _time.sleep(1.0)
            st.rerun()

        log_path = Path(_status_json.get("current_log", "")) if _status_json.get("current_log") else None
        if log_path:
            with st.expander("Current sample console log", expanded=True):
                st.code(_tail_text(log_path, max_chars=12000), language="text")

        # Poll while browser remains connected. If browser disconnects, worker continues.
        _time.sleep(2.0)
        st.rerun()

    elif _status in ("complete", "done", "failed", "error", "aborted"):
        base_case = _status_json.get("base_case") or st.session_state.get("ua_case") or selected
        if _run_dir and (st.session_state.ua_results is None or st.session_state.get("_ua_loaded_worker_run") != str(_run_dir)):
            try:
                _load_ua_run_from_dir(_run_dir, base_case)
                st.session_state._ua_loaded_worker_run = str(_run_dir)
            except Exception as _le:
                st.warning(f"Could not load worker output yet: {_le}")

        total = int(_status_json.get("total_samples", 0) or 0)
        done  = int(_status_json.get("completed_samples", 0) or 0)
        failed = int(_status_json.get("failed_samples", 0) or 0)
        msg = _status_json.get("message", "")

        if _status in ("complete", "done"):
            st.success(msg or f"UA complete: {done}/{total} samples completed.")
        elif _status == "aborted":
            st.warning(msg or f"UA aborted: {done}/{total} samples completed before abort.")
        else:
            st.error(msg or f"UA failed: {done}/{total} samples completed; {failed} failed.")

        if _run_dir:
            worker_log = _run_dir / "ua_worker_stdout.log"
            if worker_log.exists():
                with st.expander("Worker log", expanded=False):
                    st.code(_tail_text(worker_log, max_chars=16000), language="text")

        if st.session_state.ua_results is not None:
            st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)
            col1, col2 = st.columns(2)
            with col1:
                _res_path = (_run_dir / f"ua_{base_case}_results.csv"
                             if _run_dir else None)
                if _res_path and _res_path.exists():
                    with open(_res_path, "rb") as _f:
                        st.download_button("⬇  Download results CSV",
                                           data=_f.read(),
                                           file_name=_res_path.name,
                                           mime="text/csv", width="stretch")
            with col2:
                _samp_path = (_run_dir / f"ua_{base_case}_samples.csv"
                              if _run_dir else None)
                if _samp_path and _samp_path.exists():
                    with open(_samp_path, "rb") as _f:
                        st.download_button("⬇  Download samples CSV",
                                           data=_f.read(),
                                           file_name=_samp_path.name,
                                           mime="text/csv", width="stretch")

    elif st.session_state.ua_log:
        st.markdown("**Console output**")
        st.markdown(f'<div class="console">{st.session_state.ua_log}</div>', unsafe_allow_html=True)
    else:
        st.info("Configure uncertain variables in the sidebar and click **Run UA**.")
        st.caption("Long UA runs now execute in a separate worker process. If the browser disconnects, the worker continues and the run can be reloaded from its output folder.")


# ── Results tab ───────────────────────────────────────────────────────────────
with tab_results:
    st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

    df = _restore_input_columns_for_stats(
        st.session_state.ua_results,
        st.session_state.get("ua_samples"),
    )
    # Keep the normalized form in session state so downstream selectors and
    # downloads behave consistently after reconnecting to worker-produced runs.
    if df is not None:
        st.session_state.ua_results = df

    if df is None or len(df) == 0:
        st.info("No results yet. Run the uncertainty analysis first.")
    else:
        df_ok = df[df["status"] == "OK"].copy()
        if len(df_ok) == 0:
            st.error("All samples failed.")
        else:
            # ── Unit system selector ─────────────────────────────────────────
            unit_sys = st.radio(
                "Units",
                ["Metric  (°C, kPa, kg/s)", "English  (°F, psia, lb/s)"],
                horizontal=True, key="unit_sys",
            )
            _use_english = unit_sys.startswith("English")

            def convert_col(values, col_name):
                """Convert a numpy array using the column name's unit suffix."""
                for suffix, conv in UNIT_CONV.items():
                    if col_name.endswith(suffix):
                        si_lbl, eng_lbl, si_fn, eng_fn = conv[:4]
                        fn = eng_fn if _use_english else si_fn
                        return fn(values), (eng_lbl if _use_english else si_lbl)
                return values, ""

            def convert_scalar(val, col_name):
                """Convert a scalar result value by scalar column name."""
                suffix = SCALAR_UNIT.get(col_name)
                if suffix and suffix in UNIT_CONV:
                    si_lbl, eng_lbl, si_fn, eng_fn, eng_scale = UNIT_CONV[suffix]
                    fn  = eng_fn if _use_english else si_fn
                    lbl = eng_lbl if _use_english else si_lbl
                    return fn(val), lbl
                return val, ""

            def convert_std(val, col_name):
                """Convert a std deviation  -  scale only, no offset."""
                suffix = SCALAR_UNIT.get(col_name)
                if suffix and suffix in UNIT_CONV:
                    si_lbl, eng_lbl, si_fn, eng_fn, eng_scale = UNIT_CONV[suffix]
                    scale = eng_scale if _use_english else 1.0
                    lbl   = eng_lbl if _use_english else si_lbl
                    return val * scale, lbl
                return val, ""

            # ── Helper: general number format (no scientific notation) ────────
            def fmt_general(v):
                """Format a number cleanly without scientific notation."""
                try:
                    v = float(v)
                    if v == int(v) and abs(v) < 1e9:
                        return f"{int(v):,}"
                    elif abs(v) >= 1000:
                        return f"{v:,.2f}"
                    elif abs(v) >= 1:
                        return f"{v:.4f}"
                    elif abs(v) >= 0.001:
                        return f"{v:.6f}"
                    else:
                        return f"{v:.6f}"
                except Exception:
                    return str(v)

            # ── Blue→red gradient helper ──────────────────────────────────────
            def sample_color(i, n):
                t = i / max(n - 1, 1)
                r = int(9   + t * (207 -   9))
                g = int(105 - t *  80)
                b = int(218 - t * 218)
                return f"rgba({r},{g},{b},0.6)"

            # ── Output variable selector  -  at the top ─────────────────────────
            out_cols = [c for c in df_ok.columns
                        if not c.startswith("in_")
                        and c not in ("sample", "status", "error")]
            ts_out_cols     = [c for c in out_cols if c in TS_MAP]
            scalar_out_cols = out_cols

            if not out_cols:
                st.warning("No output columns found in results.")
            else:
                in_cols = [c for c in df_ok.columns if c.startswith("in_")]

                # ── Two independent selectors side by side ────────────────
                # Time-series: restrict the selector to variables that are
                # also plotted in the PWR Simulator Results tab.  This keeps the
                # UA overlay list focused and avoids exposing every raw CSV
                # diagnostic column as a plot option.
                ts_list_now = st.session_state.ua_ts
                if ts_list_now:
                    _available_ts_cols = set()
                    for _entry in ts_list_now:
                        try:
                            _available_ts_cols.update(
                                c for c in _entry["df"].columns if c != "Time (s)"
                            )
                        except Exception:
                            pass
                    ts_csv_cols = [
                        c for c in UA_PLOTTED_TS_COLUMNS
                        if c in _available_ts_cols
                    ]
                else:
                    ts_csv_cols = []

                sel_col1, sel_col2 = st.columns(2)
                with sel_col1:
                    default_ts = next(
                        (c for c in [
                            "Clad Surface Temp (K)",
                            "Hot Pin Clad Temp (K)",
                            "RCS Pressure (kPa)",
                        ] if c in ts_csv_cols),
                        ts_csv_cols[0] if ts_csv_cols else None,
                    )
                    selected_ts = st.selectbox(
                        "Time-series variable",
                        ts_csv_cols if ts_csv_cols else ["(no plotted variables available)"],
                        index=ts_csv_cols.index(default_ts)
                              if default_ts in ts_csv_cols else 0,
                        key="sel_ts",
                        help=(
                            "Limited to the same time-series quantities plotted in "
                            "the PWR Simulator Results tab."
                        ),
                    ) if ts_csv_cols else None

                with sel_col2:
                    default_sc = ("hot_pin_clad_peak_K"
                                  if "hot_pin_clad_peak_K" in scalar_out_cols
                                  else scalar_out_cols[0] if scalar_out_cols else None)
                    selected_out = st.selectbox(
                        "Scalar / CDF / scatter variable",
                        scalar_out_cols,
                        index=scalar_out_cols.index(default_sc)
                              if default_sc in scalar_out_cols else 0,
                        key="sel_sc",
                    )

                y = df_ok[selected_out].dropna()

                # ── Time-series overlay for selected TS variable ──────────
                ts_list = st.session_state.ua_ts

                # Small offset lookup: K columns displayed in °C
                _K_TO_C = {c for c in (ts_csv_cols or []) if c.endswith("(K)")}

                if ts_list_now and selected_ts and selected_ts not in ("(no data yet)", "(no plotted variables available)"):
                    n_ts = len(ts_list_now)
                    fig_ts = go.Figure()
                    for j, entry in enumerate(ts_list_now):
                        df_ts = entry["df"]
                        if selected_ts in df_ts.columns:
                            _yvals, _unit = convert_col(
                                df_ts[selected_ts].values, selected_ts)
                            fig_ts.add_trace(go.Scatter(
                                x=df_ts["Time (s)"],
                                y=_yvals,
                                mode="lines",
                                line=dict(color=sample_color(j, n_ts), width=1.5),
                                name=f"S{entry['sample']}",
                                showlegend=(n_ts <= 20),
                            ))
                    # Build clean ylabel: strip original unit suffix, add converted unit
                    _, _unit = convert_col(
                        __import__("numpy").array([0.0]), selected_ts)
                    _base_label = selected_ts
                    for _sfx in UNIT_CONV:
                        if selected_ts.endswith(_sfx):
                            _base_label = selected_ts[:-len(_sfx)].rstrip()
                            break
                    _ylabel = f"{_base_label} [{_unit}]" if _unit else _base_label
                    fig_ts.update_layout(
                        title=dict(text=f"Time-series  -  {selected_ts}  (n={n_ts} samples)",
                                   font=dict(family="IBM Plex Mono", size=12, color=PLOT_TEXT)),
                        plot_bgcolor=PLOT_BG, paper_bgcolor=PLOT_PAPER,
                        font=dict(family="IBM Plex Sans", size=11, color=PLOT_TEXT),
                        xaxis=dict(title="Time [s]", gridcolor=PLOT_GRID),
                        yaxis=dict(title=_ylabel, gridcolor=PLOT_GRID),
                        margin=dict(l=60, r=20, t=45, b=45),
                        height=380,
                        legend=dict(bgcolor="rgba(255,255,255,0.8)",
                                    font=dict(size=9)),
                    )
                    st.plotly_chart(fig_ts, width="stretch",
                                    config={"displayModeBar": False})
                    st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

                # ── Scalar summary ────────────────────────────────────────────
                if len(y) > 0:
                    _vc = lambda v: convert_scalar(v, selected_out)[0]
                    _, _su = convert_scalar(y.iloc[0], selected_out)
                    _su_tag = f" [{_su}]" if _su else ""
                    tiles = [
                        (fmt_general(_vc(y.min())),  f"Min{_su_tag}",     "ok"),
                        (fmt_general(_vc(y.mean())), f"Mean{_su_tag}",    "ok"),
                        (fmt_general(_vc(y.max())),  f"Max{_su_tag}",
                         "danger" if "clad" in selected_out.lower() else "ok"),
                        (fmt_general(convert_std(y.std(), selected_out)[0]),
                         "Std Dev", "ok"),
                    ]
                    html = '<div class="metric-grid">'
                    for val, lbl, cls in tiles:
                        html += (f'<div class="metric-tile {cls}">'
                                 f'<div class="val">{val}</div>'
                                 f'<div class="lbl">{lbl}</div>'
                                 f'</div>')
                    html += '</div>'
                    st.markdown(html, unsafe_allow_html=True)

                st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

                # ── CDF ───────────────────────────────────────────────────────
                fig_cdf = go.Figure()
                y_sorted = np.sort(y)
                cdf      = np.arange(1, len(y_sorted)+1) / len(y_sorted)
                fig_cdf.add_trace(go.Scatter(
                    x=y_sorted, y=cdf,
                    line=dict(color=C[0], width=2), name="CDF"
                ))
                fig_cdf.update_layout(
                    title=dict(text=f"CDF  -  {selected_out}",
                               font=dict(family="IBM Plex Mono", size=12, color=PLOT_TEXT)),
                    plot_bgcolor=PLOT_BG, paper_bgcolor=PLOT_PAPER,
                    font=dict(family="IBM Plex Sans", size=11, color=PLOT_TEXT),
                    xaxis=dict(title=selected_out.replace("_", " "),
                               gridcolor=PLOT_GRID),
                    yaxis=dict(title="Cumulative probability",
                               gridcolor=PLOT_GRID, range=[0, 1]),
                    margin=dict(l=55, r=20, t=40, b=45), height=300,
                )
                st.plotly_chart(fig_cdf, width="stretch",
                                config={"displayModeBar": False})

                st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)

                # ── Scatter plots: each input vs selected output  -  stacked ─────
                if in_cols:
                    st.markdown(f"**Scatter plots &mdash; inputs vs {selected_out}**")
                    for in_var in in_cols:
                        common = df_ok[[in_var, selected_out]].dropna()
                        if len(common) < 2:
                            continue
                        cc = (np.corrcoef(common[in_var], common[selected_out])[0, 1]
                              if len(common) > 2 else float("nan"))
                        ann = f"r = {cc:.3f}" if not np.isnan(cc) else ""
                        var_label = in_var.replace("in_", "")
                        fig_s = go.Figure()
                        fig_s.add_trace(go.Scatter(
                            x=common[in_var], y=common[selected_out],
                            mode="markers",
                            marker=dict(color=C[0], size=7, opacity=0.7),
                            showlegend=False,
                        ))
                        fig_s.update_layout(
                            title=dict(
                                text=f"{var_label}   {ann}",
                                font=dict(family="IBM Plex Mono",
                                          size=12, color=PLOT_TEXT)
                            ),
                            plot_bgcolor=PLOT_BG, paper_bgcolor=PLOT_PAPER,
                            font=dict(size=11, color=PLOT_TEXT),
                            xaxis=dict(title=var_label, gridcolor=PLOT_GRID),
                            yaxis=dict(title=selected_out.replace("_", " "),
                                       gridcolor=PLOT_GRID),
                            margin=dict(l=60, r=20, t=45, b=50),
                            height=280,
                        )
                        st.plotly_chart(fig_s, width="stretch",
                                        config={"displayModeBar": False})

                    # ── Tornado (|r| ranking) ─────────────────────────────────
                    st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)
                    st.markdown(f"**Tornado &mdash; Pearson |r| with {selected_out}**")
                    corrs = {}
                    for iv in in_cols:
                        common = df_ok[[iv, selected_out]].dropna()
                        if len(common) > 2:
                            cc = np.corrcoef(common[iv],
                                             common[selected_out])[0, 1]
                            if not np.isnan(cc):
                                corrs[iv.replace("in_", "")] = cc

                    if corrs:
                        sorted_vars = sorted(corrs, key=lambda k: abs(corrs[k]),
                                             reverse=True)
                        vals   = [corrs[v] for v in sorted_vars]
                        colors = [C[1] if v < 0 else C[0] for v in vals]
                        fig_t = go.Figure(go.Bar(
                            x=vals, y=sorted_vars,
                            orientation="h",
                            marker_color=colors,
                        ))
                        fig_t.update_layout(
                            title=dict(text="Pearson correlation coefficients",
                                       font=dict(family="IBM Plex Mono",
                                                 size=12, color=PLOT_TEXT)),
                            plot_bgcolor=PLOT_BG, paper_bgcolor=PLOT_PAPER,
                            font=dict(family="IBM Plex Sans", size=11,
                                      color=PLOT_TEXT),
                            xaxis=dict(title="r", gridcolor=PLOT_GRID,
                                       range=[-1, 1]),
                            yaxis=dict(gridcolor=PLOT_GRID),
                            margin=dict(l=120, r=20, t=40, b=45),
                            height=max(300, 30 * len(sorted_vars) + 80),
                        )
                        fig_t.add_vline(x=0, line=dict(color="grey", width=1))
                        st.plotly_chart(fig_t, width="stretch",
                                        config={"displayModeBar": False})


                # ── Export current UA plot set ────────────────────────────────
                st.markdown('<div class="hdiv"></div>', unsafe_allow_html=True)
                st.markdown("**Plot export**")
                st.caption(
                    "Create PNG files and a multipage PDF for the currently selected "
                    "time-series variable and scalar/CDF/scatter variable."
                )
                if st.button("📈  Create Plots", key="ua_create_current_plots"):
                    try:
                        _run_dir_plot = Path(st.session_state.get("ua_run_dir") or WORK_DIR)
                        _plot_tag = (
                            f"current_{_safe_plot_token(selected_ts)}_"
                            f"{_safe_plot_token(selected_out)}_"
                            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                        )
                        _created = _make_ua_plot_set(
                            df_ok,
                            ts_list_now,
                            _run_dir_plot,
                            st.session_state.get("ua_case") or selected,
                            selected_ts,
                            selected_out,
                            use_english=_use_english,
                            tag=_plot_tag,
                        )
                        st.success(
                            f"Created {len(_created['pngs'])} PNG file(s) and one PDF in "
                            f"`{_created['out_dir'].name}`."
                        )
                        with open(_created["pdf"], "rb") as _pf:
                            st.download_button(
                                "⬇  Download plot PDF",
                                data=_pf.read(),
                                file_name=_created["pdf"].name,
                                mime="application/pdf",
                                key="ua_download_current_plot_pdf",
                            )
                    except Exception as _plot_e:
                        st.error(f"Could not create UA plots: {_plot_e}")


    # ── AI Uncertainty Narrative ──────────────────────────────────────────────
    if df is not None and len(df) > 0 and "status" in df.columns:
        with st.expander("🤖  AI Uncertainty Narrative", expanded=True):
            st.caption(
                "Generate a technical narrative of the uncertainty-analysis results, "
                "including key output distributions, sensitivity rankings, and interpretation."
            )
            _ua_detail = st.slider(
                "Narrative detail", 0.0, 1.0, 0.55, 0.05,
                key="ua_ai_detail",
                help="Lower values produce a short executive summary; higher values produce a more detailed technical discussion.",
            )
            _ua_cols = st.columns([1, 1, 3])
            with _ua_cols[0]:
                _gen_ua_ai = st.button("Generate narrative", key="ua_ai_generate")
            with _ua_cols[1]:
                if st.button("Clear", key="ua_ai_clear"):
                    st.session_state.pop("ua_ai_narrative", None)
                    st.rerun()

            if _gen_ua_ai:
                try:
                    _df_ai = _restore_input_columns_for_stats(
                        st.session_state.ua_results,
                        st.session_state.get("ua_samples"),
                    )
                    _df_ok_ai = _df_ai[_df_ai["status"] == "OK"].copy()
                    _in_cols_ai = [c for c in _df_ok_ai.columns if c.startswith("in_")]
                    _out_cols_ai = [c for c in _df_ok_ai.columns
                                    if not c.startswith("in_") and c not in ("sample", "status", "error")]
                    _numeric_out = [c for c in _out_cols_ai if pd.api.types.is_numeric_dtype(_df_ok_ai[c])]
                    _summary = []
                    for _c in _numeric_out[:20]:
                        _s = pd.to_numeric(_df_ok_ai[_c], errors="coerce").dropna()
                        if len(_s):
                            _summary.append({
                                "output": _c,
                                "n": int(len(_s)),
                                "min": float(_s.min()),
                                "mean": float(_s.mean()),
                                "max": float(_s.max()),
                                "std": float(_s.std()) if len(_s) > 1 else 0.0,
                                "p95": float(_s.quantile(0.95)),
                            })
                    _corr_rows = []
                    for _out in _numeric_out[:20]:
                        for _iv in _in_cols_ai:
                            _common = _df_ok_ai[[_iv, _out]].apply(pd.to_numeric, errors="coerce").dropna()
                            if len(_common) > 2:
                                _r = float(np.corrcoef(_common[_iv], _common[_out])[0, 1])
                                if np.isfinite(_r):
                                    _corr_rows.append({"output": _out, "input": _iv.replace("in_", ""), "r": _r, "abs_r": abs(_r)})
                    _corr_rows = sorted(_corr_rows, key=lambda x: x["abs_r"], reverse=True)[:20]
                    _samples_csv = ""
                    try:
                        _samples_csv = st.session_state.ua_samples.head(20).to_csv(index=False) if st.session_state.get("ua_samples") is not None else ""
                    except Exception:
                        _samples_csv = ""
                    _system = (
                        "You are FLARE's uncertainty-analysis narrative assistant. Write in a concise, "
                        "technically defensible nuclear safety analysis style. Do not invent data. "
                        "Use only the supplied summaries and correlations. Distinguish statistical "
                        "association from causation."
                    )
                    _length = "brief, about 3 paragraphs" if _ua_detail < 0.34 else ("moderate, about 5 paragraphs" if _ua_detail < 0.67 else "detailed, with concise bullets plus narrative")
                    _user = f"""
Prepare a {_length} AI Uncertainty Narrative for this FLARE UA run.

Case: {st.session_state.get('ua_case') or selected}
Samples requested/available: {len(_df_ai)} total rows; {len(_df_ok_ai)} successful rows.
Input variables sampled: {[c.replace('in_', '') for c in _in_cols_ai]}

Output summary statistics:
{json.dumps(_summary, indent=2)}

Top Pearson correlations by absolute value:
{json.dumps(_corr_rows, indent=2)}

First rows of sample matrix, if available:
{_samples_csv}

Discuss: adequacy of successful sample count, dominant uncertain inputs, important output distributions, tails/95th percentile behavior, and cautions about failed samples, correlation interpretation, and model-form limitations.
"""
                    with st.spinner("Generating AI uncertainty narrative…"):
                        st.session_state.ua_ai_narrative = _anthropic_text(_system, _user, max_tokens=2400)
                except Exception as _ai_e:
                    st.error(f"AI narrative failed: {_ai_e}")

            if st.session_state.get("ua_ai_narrative"):
                st.markdown(st.session_state.ua_ai_narrative)
                st.download_button(
                    "⬇  Download narrative (Markdown)",
                    data=st.session_state.ua_ai_narrative.encode("utf-8"),
                    file_name=f"ua_{st.session_state.get('ua_case') or selected}_narrative.md",
                    mime="text/markdown",
                    key="ua_ai_download",
                )


# ── Samples tab ───────────────────────────────────────────────────────────────
with tab_samples:
    if st.session_state.ua_samples is not None:
        st.markdown("**Sample input values**")
        st.dataframe(st.session_state.ua_samples, width="stretch",
                     hide_index=True)
    else:
        st.info("No samples generated yet.")
