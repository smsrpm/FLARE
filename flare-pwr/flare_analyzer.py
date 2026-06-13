"""
flare_analyzer.py  —  FLARE Real-Time Plant Analyzer
Browser-side playback version. The Streamlit app selects the working folder
and case; all frame-by-frame animation is performed in the browser so the SVG
is not torn down on every playback frame.
Run with: streamlit run flare_analyzer.py
"""

import base64
import json
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(layout="wide", page_title="FLARE Plant Analyzer", page_icon="🔥")
APP_DIR = Path(__file__).parent
WORK_DIR = APP_DIR


def _has_analyzer_outputs(folder: Path) -> bool:
    """Return True when this folder directly encloses analyzer output CSV files."""
    try:
        return any(folder.glob("*_out.csv"))
    except Exception:
        return False


def _discover_working_folders(app_dir: Path) -> list[Path]:
    """Return folders that directly contain Plant Analyzer output files.

    For the Plant Analyzer, the Working Folder selector intentionally goes all
    the way down to the run/output folder that encloses the *_out.csv files.
    This keeps large UA runs from crowding the Case selector with outputs from
    many run folders at once.
    """
    excluded = {"examples", "icons", "install", "manuals", "runtime", "__pycache__", ".git", ".streamlit"}
    candidates: list[Path] = []

    def _is_excluded(path: Path) -> bool:
        return any(part.lower() in excluded for part in path.relative_to(app_dir).parts if part)

    try:
        # Include the app folder only when it directly contains output CSV files.
        if _has_analyzer_outputs(app_dir):
            candidates.append(app_dir)

        # Search below the app folder for folders that directly contain *_out.csv.
        # The depth cap avoids walking virtual environments or unrelated large trees.
        max_depth = 4
        for csv_path in app_dir.rglob("*_out.csv"):
            folder = csv_path.parent
            try:
                rel = folder.relative_to(app_dir)
            except Exception:
                continue
            if len(rel.parts) > max_depth:
                continue
            if _is_excluded(folder):
                continue
            candidates.append(folder)
    except Exception:
        pass

    out: list[Path] = []
    seen: set[Path] = set()
    for folder in sorted(candidates, key=lambda x: str(x.relative_to(app_dir)).lower() if x != app_dir else ""):
        try:
            resolved = folder.resolve()
        except Exception:
            resolved = folder
        if resolved not in seen:
            seen.add(resolved)
            out.append(folder)

    if not out:
        out.append(app_dir)
    return out


def _working_folder_label(folder: Path) -> str:
    try:
        rel = folder.relative_to(APP_DIR)
        return "." if str(rel) == "." else str(rel)
    except Exception:
        return str(folder)


def _discover_csv_entries(folder: Path) -> list[tuple[str, Path]]:
    """Return output CSVs directly enclosed by the selected working folder."""
    entries: list[tuple[str, Path]] = []
    try:
        for p in sorted(folder.glob("*_out.csv")):
            entries.append((p.name, p))
    except Exception:
        pass
    return entries


def _load_buddy_b64() -> str | None:
    for _dir in (APP_DIR / "icons", APP_DIR / "Icons"):
        _p = _dir / "FLAREBUDDY.png"
        if _p.exists():
            try:
                return "data:image/png;base64," + base64.b64encode(_p.read_bytes()).decode()
            except Exception:
                return None
    return None


_BUDDY_B64 = _load_buddy_b64()

try:
    ua = st.context.headers.get("User-Agent", "")
except Exception:
    ua = ""
is_ios = "iPhone" in ua or "iPad" in ua
is_ios_chrome = "CriOS" in ua
is_ios_edge = "EdgiOS" in ua
is_ios_safari = is_ios and not is_ios_chrome and not is_ios_edge
if is_ios_safari:
    st.warning(
        "⚠️ **Plant diagram not available in iOS Safari.**\n\n"
        "Apple restricts all browsers on iPhone and iPad to the WebKit engine, "
        "which blocks the inline rendering this diagram requires.\n\n"
        "Please open FLARE in **Chrome** or **Microsoft Edge** on your iPhone "
        "for the full interactive plant diagram.",
        icon="📵",
    )
    st.stop()

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap');
:root{ --sidebar:#1a1f2e; --dark-surface:#0d1117; --dark-border:#30363d;
       --sid-text:#e6edf3; --sid-muted:#8b949e; }
html,body,[class*="css"]{ font-family:'IBM Plex Sans',sans-serif; }
.stApp{ background:#f5f7fa; }
header{ background:transparent !important; }
h1,h2,h3{ font-family:'IBM Plex Mono',monospace; }
#MainMenu,footer{ visibility:hidden; }
section[data-testid="stSidebar"]{ background:var(--sidebar) !important; border-right:1px solid var(--dark-border); }
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] label{ color:var(--sid-text) !important; }
section[data-testid="stSidebar"] .stCaption{ color:var(--sid-muted) !important; }
section[data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"]{
    background:var(--dark-surface); border:1px solid var(--dark-border); border-radius:6px; }
section[data-testid="stSidebar"] .stSelectbox span{ color:#fff !important; }
div[role="listbox"]{ background:var(--dark-surface) !important; }
div[role="option"] { color:#fff !important; }
div[role="option"]:hover{ background:#21262d !important; }
[data-testid="stSidebar"] button[kind="secondary"]{
    background:transparent !important; border:1px solid #e8530a !important;
    border-radius:4px !important; color:#f97316 !important;
    font-size:0.82rem !important; letter-spacing:0.08em !important; font-weight:700 !important; }
[data-testid="stSidebar"] button[kind="secondary"]:hover{
    background:rgba(232,83,10,0.18) !important;
    box-shadow:0 0 14px rgba(232,83,10,0.45) !important; color:#fff !important; }
section[data-testid="stSidebar"] button:not([kind]){
    background-color:#2a3145 !important; color:var(--sid-text) !important;
    border:1px solid #3b435c !important; border-radius:6px !important; font-size:0.85rem !important; }
section[data-testid="stSidebar"] button:not([kind]):hover{ background-color:#343c55 !important; }
section[data-testid="stSidebar"] .stTooltipHoverTarget svg.icon{ stroke:#f97316 !important; }
section[data-testid="stSidebar"] .stTooltipHoverTarget:hover svg.icon{ stroke:#fff !important; }
.stTooltipHoverTarget svg.icon{ stroke:#0969da !important; }
section[data-testid="stSidebar"] .block-container { padding-top:0.5rem !important; }
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div { gap:0.15rem !important; }
section[data-testid="stSidebar"] hr { margin:0.4rem 0 !important; }
</style>
""",
    unsafe_allow_html=True,
)

with st.sidebar:
    buddy_html = f"<img src='{_BUDDY_B64}' style='height:4.5rem;width:auto;object-fit:contain;flex-shrink:0;'/>" if _BUDDY_B64 else "🔥"
    st.markdown(
        f'''<a href="?page=home" target="_self" style="text-decoration:none;display:flex;
            align-items:center;gap:0.55rem;padding:0.35rem 0.6rem;
            border:1px solid #e8530a;border-radius:4px;
            font-family:Share Tech Mono,monospace;font-size:1.6rem;
            font-weight:700;letter-spacing:0.08em;color:#f97316;"
            onmouseover="this.style.background='rgba(232,83,10,0.18)';this.style.boxShadow='0 0 14px rgba(232,83,10,0.45)';this.style.color='#ffffff';"
            onmouseout="this.style.background='transparent';this.style.boxShadow='none';this.style.color='#f97316';">
          {buddy_html}
          FLARE Home
        </a>''',
        unsafe_allow_html=True,
    )
    st.divider()
    st.markdown("### 🏭 Plant Analyzer")

    _working_folders = _discover_working_folders(APP_DIR)
    _working_folder = st.selectbox(
        "Working Folder",
        options=_working_folders,
        index=0,
        format_func=_working_folder_label,
        key="flare_analyzer_working_folder",
        help="Select the specific run/output folder containing the *_out.csv files to replay.",
    )
    WORK_DIR = Path(_working_folder)

    _csv_entries = _discover_csv_entries(WORK_DIR)
    st.caption(f"Working folder: {WORK_DIR}")

    if not _csv_entries:
        st.error("No *_out.csv files found directly in the selected output folder.")
        st.stop()

    _labels = [e[0] for e in _csv_entries]
    _sel_label = st.selectbox("Case", _labels, help="Select a simulation output CSV to replay.")
    _sel_path = next(p for lbl, p in _csv_entries if lbl == _sel_label)
    st.divider()
    zoom = st.slider("Diagram zoom", 0.4, 1.4, 0.9, step=0.05, help="Scale the plant diagram.")
    st.caption("Playback controls are inside the main graphic and run in the browser without Streamlit reruns.")

try:
    df = pd.read_csv(_sel_path)
except Exception as exc:
    st.error(f"Could not load selected CSV: {_sel_path}\n\n{exc}")
    st.stop()

if df.empty:
    st.error(f"Selected CSV has no rows: {_sel_path}")
    st.stop()

_con_path = _sel_path.with_name(_sel_path.name.replace("_out.csv", "-CON.csv"))
try:
    df_con = pd.read_csv(_con_path) if _con_path.exists() else None
except Exception:
    df_con = None


def _range_for(col: str, default_min: float, default_max: float, transform=None) -> tuple[float, float]:
    if col not in df.columns:
        return default_min, default_max
    s = pd.to_numeric(df[col], errors="coerce")
    if transform is not None:
        s = transform(s)
    if s.dropna().empty:
        return default_min, default_max
    return float(s.min()), float(s.max())


Tmin, Tmax = _range_for("RCS Temperature (K)", 300.0, 350.0, lambda s: s - 273.15)
Pmin, Pmax = _range_for("RCS Pressure (kPa)", 0.1, 15.5, lambda s: s / 1000.0)
Tclad_min, Tclad_max = _range_for("Clad Surface Temp (K)", Tmin, Tmax, lambda s: s - 273.15)
if "Accumulator Liquid Volume (m3)" in df.columns:
    _acc = pd.to_numeric(df["Accumulator Liquid Volume (m3)"], errors="coerce")
    Lmax_acc = float(_acc.max()) if not _acc.dropna().empty else 1.0
else:
    Lmax_acc = 1.0

if df_con is not None and not df_con.empty and "Pressure [kPa]" in df_con.columns:
    _pc = pd.to_numeric(df_con["Pressure [kPa]"], errors="coerce")
    P_con_min = float(_pc.min()) if not _pc.dropna().empty else 101.0
    P_con_max = float(_pc.max()) if not _pc.dropna().empty else 101.0
else:
    P_con_min = P_con_max = 101.0

# Keep the browser payload small enough for iOS/iPadOS WebKit.
# The previous implementation sent every column from *_out.csv and every column
# from the optional FLARECON -CON.csv into the embedded JavaScript document.  That
# is workable on desktop browsers, but iPhone/iPad WebKit can terminate the iframe
# when the srcdoc/JavaScript payload becomes large.  FLARECON cases are the worst
# case because they add a second, often wide, time-history table.
#
# The animation only needs the variables below.  The "Variables — current timestep"
# table therefore shows the same compact set used by the browser animation.  This
# is intentional: it prevents FLARECON cases from crashing mobile devices while
# preserving all displayed analyzer behavior.
_JS_ROW_COLUMNS = [
    "Time (s)",
    "RCS Temperature (K)",
    "RCS Pressure (kPa)",
    "Clad Surface Temp (K)",
    "Core Power (MW)",
    "SI Pumped Total (kg/s)",
    "Break Flow (kg/s)",
    "PORV Mass Flow (kg/s)",
    "CVCS Makeup (kg/s)",
    "CVCS Letdown (kg/s)",
    "Total Mass Scaled",
    "Accumulator Liquid Volume (m3)",
    "Pump Speed (rpm)",
]
_JS_CON_COLUMNS = [
    "Pressure [kPa]",
    "Gas Temp [C]",
]

def _compact_records(frame, columns: list[str]) -> list[dict]:
    if frame is None or frame.empty:
        return []
    keep = [c for c in columns if c in frame.columns]
    if not keep:
        return []
    compact = frame.loc[:, keep]
    return compact.where(pd.notnull(compact), None).to_dict(orient="records")

records = _compact_records(df, _JS_ROW_COLUMNS)
con_records = _compact_records(df_con, _JS_CON_COLUMNS)
payload = {
    "case_name": _sel_path.name.replace("_out.csv", ""),
    "csv_name": _sel_path.name,
    "con_name": _con_path.name if df_con is not None else "",
    "has_con": bool(df_con is not None and not df_con.empty),
    "zoom": zoom,
    "rows": records,
    "con_rows": con_records,
    "ranges": {
        "Tmin": Tmin, "Tmax": Tmax, "Pmin": Pmin, "Pmax": Pmax,
        "Tclad_min": Tclad_min, "Tclad_max": Tclad_max,
        "Lmax_acc": Lmax_acc, "P_con_min": P_con_min, "P_con_max": P_con_max,
    },
}

HTML_TEMPLATE = r'''
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap');
html, body { margin:0; padding:0; background:#f5f7fa; font-family:'IBM Plex Sans',sans-serif; overflow:hidden; }
.shell { padding:0; }
.title { font-family:'IBM Plex Mono',monospace; font-weight:600; color:#1f2937; margin:0 0 0.75rem 0; font-size:1.45rem; }
.toolbar { display:flex; align-items:center; column-gap:1.05rem; row-gap:0.85rem; flex-wrap:wrap; background:#ffffff; border:1px solid #d1d9e0; border-radius:8px; padding:0.78rem 0.85rem; margin:0 0 1.0rem 0; }
.toolbar button { background:#1f2937; color:#fff; border:1px solid #374151; border-radius:6px; padding:0.42rem 0.65rem; font-weight:700; cursor:pointer; min-width:2.55rem; }
.toolbar button:hover { background:#374151; }
.toolbar label { font-size:0.85rem; color:#334155; font-weight:600; display:flex; align-items:center; gap:0.48rem; }
.toolbar input[type="range"] { width:300px; }
.toolbar input[type="number"] { width:70px; padding:0.25rem; border:1px solid #cbd5e1; border-radius:4px; }
.stat { font-family:'IBM Plex Mono',monospace; background:#0d1117; color:#e6edf3; border-radius:5px; padding:0.3rem 0.45rem; font-size:0.82rem; }
.note { color:#64748b; font-size:0.82rem; }
#svgHost { background:#f8f9fb; min-height:300px; width:100%; overflow:visible; }
#svgHost svg { display:block; max-width:100%; height:auto; }
details { margin-top:0.8rem; background:#fff; border:1px solid #d1d9e0; border-radius:8px; padding:0.5rem 0.65rem; }
summary { cursor:pointer; font-weight:700; color:#1f2937; }
.varTableWrap { margin-top:0.45rem; max-height:430px; min-height:375px; overflow-y:auto; overflow-x:auto; border:1px solid #d1d9e0; border-radius:6px; }
.varTable { border-collapse:collapse; font-size:0.78rem; width:100%; max-width:100%; }
.varTable th, .varTable td { border-bottom:1px solid #d1d9e0; padding:0.22rem 0.38rem; text-align:left; }
.varTable th { background:#f1f5f9; position:sticky; top:0; z-index:1; }
.varTable td:nth-child(2) { font-family:'IBM Plex Mono',monospace; }
</style>
</head>
<body>
<div class="shell">
  <div class="title">🏭 FLARE Plant Analyzer — <code id="caseTitle"></code></div>
  <div class="toolbar">
    <button id="firstBtn" title="First timestep">⏮</button>
    <button id="playBtn" title="Play/Pause">▶</button>
    <button id="lastBtn" title="Last timestep">⏭</button>
    <label>Speed <input id="speed" type="range" min="10" max="750" value="120" step="10"><span id="speedText">120 ms</span></label>
    <label>Step skip <input id="skip" type="number" min="1" max="1000" value="1" step="1"></label>
    <label>Timestep <input id="stepSlider" type="range" min="0" max="0" value="0" step="1"><span id="stepText">0 / 0</span></label>
    <span class="stat" id="simTime">t = 0.0 s</span>
    <span class="stat" id="csvInfo"></span>
    <span class="note">Animation is browser-side; Streamlit does not rerun during playback.</span>
  </div>
  <div id="svgHost"></div>
  <details open>
    <summary>Variables — current timestep</summary>
    <div id="varTable" class="varTableWrap"></div>
  </details>
</div>
<script>
const PAYLOAD = __PAYLOAD_JSON__;
const rows = PAYLOAD.rows || [];
const conRows = PAYLOAD.con_rows || [];
const ranges = PAYLOAD.ranges || {};
const maxStep = Math.max(0, rows.length - 1);
let step = 0;
let playing = false;
let timer = null;
const SVG_W = 902, SVG_H = 758;
const zoom = Number(PAYLOAD.zoom || 0.9);
const PRZ_Y=80, PRZ_W=149, PRZ_H=319;
const SG_X=30, SG_Y=380, SG_W=139, SG_H=299;
const RV_X=350, RV_Y=300, RV_W=219, RV_H=439;
const ACC_X=620, ACC_Y=270, ACC_W=181, ACC_H=269;
const CORE_X=390, CORE_Y=580, CORE_W=100, CORE_H=135;
const PW=16;
const SG_RIGHT=SG_X+SG_W, SG_BOT=SG_Y+SG_H, SG_CX=SG_X+Math.floor(SG_W/2);
const RV_LEFT=RV_X, RV_RIGHT=RV_X+RV_W, RV_BOT=RV_Y+RV_H;
const ACC_BOT=ACC_Y+ACC_H, ACC_CX=ACC_X+Math.floor(ACC_W/2);
const HL_Y=375;
const PRZ_CX=Math.floor((SG_RIGHT+RV_LEFT)/2), PRZ_BOT=PRZ_Y+PRZ_H;
const HL_MID_X=PRZ_CX, HL_MID_Y=HL_Y;
const PUMP_CX=Math.floor((SG_CX+RV_LEFT)/2), PUMP_CY=RV_BOT, PUMP_RX=42, PUMP_RY=28;
const SI_Y=Math.floor((550+RV_BOT)/2), SI_X_START=RV_RIGHT, SI_X_END=RV_RIGHT+300;
const BREAK_X=RV_X+Math.floor(RV_W/2), BREAK_Y_BOT=RV_Y, BREAK_STEM_H=80, BREAK_Y_TOP=BREAK_Y_BOT-BREAK_STEM_H;
const PORV_X=PRZ_CX, PORV_Y_BOT=PRZ_Y, PORV_STEM_H=80, PORV_Y_TOP=PORV_Y_BOT-PORV_STEM_H;
const CVCS_X_START=RV_LEFT, CVCS_X_END=RV_LEFT-120, CVCS_Y_MAKEUP=490, CVCS_Y_LETDOWN=520;
const ACC_INJ_Y=550;
const CON_RIGHT=ACC_X+ACC_W, CON_TOP=15, CON_W=393, CON_H=240, CON_LEFT=CON_RIGHT-CON_W, CON_BOT=CON_TOP+CON_H;
const CON_CX=Math.floor((CON_LEFT+CON_RIGHT)/2), CON_RX=Math.floor(CON_W/2), CON_RY=Math.floor(CON_H/2), CON_ARCH_CY=CON_BOT-CON_RY;
const CON_BADGE_W=116, CON_BADGE_X=CON_CX-Math.floor(CON_BADGE_W/2), CON_BADGE_Y=CON_TOP+Math.floor((CON_H-118)/2)+15;
const CON_NODATA_Y1=CON_TOP+Math.floor(CON_H/2)-13, CON_NODATA_Y2=CON_TOP+Math.floor(CON_H/2)+7, CON_NODATA_Y3=CON_TOP+Math.floor(CON_H/2)+27;

function num(obj, key, def=0.0) { const n = Number(obj && obj[key]); return Number.isFinite(n) ? n : def; }
function clamp(x) { return Math.max(0, Math.min(1, x)); }
function fmt(x, digits=1) { return Number.isFinite(x) ? x.toFixed(digits) : '0.0'; }
function fluidColor(T_C, P_MPa_val, alpha=0.82, tMin=null, tMax=null) {
  const lo = tMin === null ? ranges.Tmin : tMin;
  const hi = tMax === null ? ranges.Tmax : tMax;
  const t = clamp((T_C - lo) / ((hi - lo) + 1e-9));
  const p = clamp((P_MPa_val - ranges.Pmin) / ((ranges.Pmax - ranges.Pmin) + 1e-9));
  const hue = Math.round(240 * (1 - t));
  const light = Math.round(70 - 30 * p);
  return `hsla(${hue},85%,${light}%,${alpha})`;
}
function containmentColor(P_kPa_val, T_C_val, alpha=0.28) {
  const p = clamp((P_kPa_val - ranges.P_con_min) / ((ranges.P_con_max - ranges.P_con_min) + 1e-9));
  const t = clamp((T_C_val - 27.0) / (150.0 - 27.0));
  const hue = Math.round(210 - 210 * t);
  const sat = Math.round(60 + 25 * p);
  return `hsla(${hue},${sat}%,55%,${alpha})`;
}
function fillRect(x, y, w, h, level, color) {
  const fh = h * clamp(level);
  const fy = y + h - fh;
  return `<rect x="${x}" y="${fy.toFixed(1)}" width="${w}" height="${fh.toFixed(1)}" fill="${color}"/>`;
}
function conRowFor(i) { return conRows.length ? conRows[Math.min(i, conRows.length-1)] : null; }
let pumpMaxCache = null;
function pumpMax() {
  if (pumpMaxCache !== null) return pumpMaxCache;
  let m = 1500.0;
  for (const r of rows) m = Math.max(m, num(r, 'Pump Speed (rpm)', 0.0));
  pumpMaxCache = m;
  return m;
}

function buildSvg(i) {
  const row = rows[i] || {};
  const cr = conRowFor(i);
  const T_hot_K = num(row, 'RCS Temperature (K)', 573.15);
  const P_kPa = num(row, 'RCS Pressure (kPa)', 15500.0);
  const T_clad_K = num(row, 'Clad Surface Temp (K)', 573.15);
  const t_sim = num(row, 'Time (s)', 0.0);
  const core_pwr = num(row, 'Core Power (MW)', 0.0);
  const T_hot_C = T_hot_K - 273.15;
  const T_clad_C = T_clad_K - 273.15;
  const P_MPa = P_kPa / 1000.0;
  const P_con_kPa = cr ? num(cr, 'Pressure [kPa]', 101.325) : 101.325;
  const T_con_C = cr ? num(cr, 'Gas Temp [C]', 27.0) : 27.0;
  const si_pumped_mdot = num(row, 'SI Pumped Total (kg/s)', 0.0);
  const break_mdot = num(row, 'Break Flow (kg/s)', 0.0);
  const porv_mdot = num(row, 'PORV Mass Flow (kg/s)', 0.0);
  const cvcs_makeup = num(row, 'CVCS Makeup (kg/s)', 0.0);
  const cvcs_letdown = num(row, 'CVCS Letdown (kg/s)', 0.0);
  const lvl_rv = clamp(num(row, 'Total Mass Scaled', 1.0));
  const lvl_acc = clamp(num(row, 'Accumulator Liquid Volume (m3)', 0.0) / ((ranges.Lmax_acc || 1.0) + 1e-9));
  const pump_rpm = num(row, 'Pump Speed (rpm)', 0.0);
  const pump_hue = Math.round(120 * clamp(pump_rpm / (pumpMax() + 1e-9)));
  const col_pump = `hsla(${pump_hue},85%,45%,0.9)`;
  const col_si_pipe = si_pumped_mdot > 0.1 ? '#3b82f6' : '#d1d5db';
  const col_si_label = si_pumped_mdot > 0.1 ? '#1d4ed8' : '#9ca3af';
  const col_brk_pipe = break_mdot > 0.1 ? '#3b82f6' : '#d1d5db';
  const col_brk_label = break_mdot > 0.1 ? '#1d4ed8' : '#9ca3af';
  const col_prv_pipe = porv_mdot > 0.1 ? '#3b82f6' : '#d1d5db';
  const col_prv_label = porv_mdot > 0.1 ? '#1d4ed8' : '#9ca3af';
  const col_mkup_pipe = cvcs_makeup > 0.01 ? '#3b82f6' : '#d1d5db';
  const col_mkup_label = cvcs_makeup > 0.01 ? '#1d4ed8' : '#9ca3af';
  const col_ldwn_pipe = cvcs_letdown > 0.01 ? '#3b82f6' : '#d1d5db';
  const col_ldwn_label = cvcs_letdown > 0.01 ? '#1d4ed8' : '#9ca3af';
  const col_con = containmentColor(P_con_kPa, T_con_C);
  const col_hot = fluidColor(T_hot_C, P_MPa);
  const col_cold = fluidColor(T_hot_C - 25, P_MPa);
  const col_core = fluidColor(T_clad_C, P_MPa, 1.0, ranges.Tclad_min, ranges.Tclad_max);
  const col_acc_fluid = fluidColor(T_hot_C - 80, P_MPa * 0.5);
  const col_hl = fluidColor(T_hot_C, P_MPa, 0.9);
  const col_cl = fluidColor(T_hot_C - 25, P_MPa, 0.9);
  const prz_fill = fillRect(PRZ_CX - Math.floor(PRZ_W/2), PRZ_Y, PRZ_W, PRZ_H, lvl_rv, col_hot);
  const sg_fill = fillRect(SG_X, SG_Y, SG_W, SG_H, lvl_rv, col_cold);
  const rv_fill = fillRect(RV_X, RV_Y, RV_W, RV_H, lvl_rv, col_hot);
  const acc_fill = fillRect(ACC_X, ACC_Y, ACC_W, ACC_H, lvl_acc, col_acc_fluid);
  const badgeCx = CON_BADGE_X + Math.floor(CON_BADGE_W/2);
  const badge2Y = CON_BADGE_Y + 63;
  const conInterior = cr ? `<rect x="${CON_BADGE_X}" y="${CON_BADGE_Y}" width="${CON_BADGE_W}" height="55" rx="4" fill="#0d1117" stroke="#58697a" stroke-width="1" opacity="0.93"/>
<text x="${badgeCx}" y="${CON_BADGE_Y + 16}" font-family="IBM Plex Mono,monospace" font-size="10" fill="#cdd9e5" text-anchor="middle">CON PRESS</text>
<text x="${badgeCx}" y="${CON_BADGE_Y + 40}" font-family="IBM Plex Mono,monospace" font-size="17" font-weight="600" fill="#ffffff" text-anchor="middle">${fmt(P_con_kPa,1)} kPa</text>
<rect x="${CON_BADGE_X}" y="${badge2Y}" width="${CON_BADGE_W}" height="55" rx="4" fill="#0d1117" stroke="#58697a" stroke-width="1" opacity="0.93"/>
<text x="${badgeCx}" y="${badge2Y + 16}" font-family="IBM Plex Mono,monospace" font-size="10" fill="#cdd9e5" text-anchor="middle">CON TEMP</text>
<text x="${badgeCx}" y="${badge2Y + 40}" font-family="IBM Plex Mono,monospace" font-size="17" font-weight="600" fill="#ffffff" text-anchor="middle">${fmt(T_con_C,1)} °C</text>` : `<text x="${CON_CX}" y="${CON_NODATA_Y1}" font-family="IBM Plex Sans,sans-serif" font-size="13" font-weight="600" fill="#64748b" text-anchor="middle" opacity="0.80">no</text>
<text x="${CON_CX}" y="${CON_NODATA_Y2}" font-family="IBM Plex Sans,sans-serif" font-size="13" font-weight="600" fill="#64748b" text-anchor="middle" opacity="0.80">FLARECON</text>
<text x="${CON_CX}" y="${CON_NODATA_Y3}" font-family="IBM Plex Sans,sans-serif" font-size="13" font-weight="600" fill="#64748b" text-anchor="middle" opacity="0.80">data</text>`;

  const svgPixelWidth = Math.round(SVG_W*zoom);
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 902 758" width="${svgPixelWidth}" height="${Math.round(SVG_H*zoom)}" style="display:block;max-width:100%;height:auto;">
<defs><clipPath id="cp-prz"><rect x="${PRZ_CX - Math.floor(PRZ_W/2)}" y="${PRZ_Y}" width="${PRZ_W}" height="${PRZ_H}"/></clipPath><clipPath id="cp-sg"><rect x="${SG_X}" y="${SG_Y}" width="${SG_W}" height="${SG_H}"/></clipPath><clipPath id="cp-rv"><rect x="${RV_X}" y="${RV_Y}" width="${RV_W}" height="${RV_H}"/></clipPath><clipPath id="cp-acc"><rect x="${ACC_X}" y="${ACC_Y}" width="${ACC_W}" height="${ACC_H}"/></clipPath><clipPath id="cp-con"><path d="M ${CON_LEFT},${CON_BOT} L ${CON_LEFT},${CON_ARCH_CY} A ${CON_RX},${CON_RY} 0 0 1 ${CON_RIGHT},${CON_ARCH_CY} L ${CON_RIGHT},${CON_BOT} Z"/></clipPath></defs>
<rect width="902" height="758" fill="#f8f9fb"/>
<line x1="${SG_RIGHT}" y1="${HL_Y}" x2="${RV_LEFT}" y2="${HL_Y}" stroke="${col_hl}" stroke-width="${PW}" stroke-linecap="round"/>
<line x1="${PRZ_CX}" y1="${HL_Y}" x2="${PRZ_CX}" y2="${PRZ_BOT}" stroke="${col_hl}" stroke-width="${Math.floor(PW/3)}" stroke-linecap="round"/>
<polyline points="${RV_LEFT},${RV_BOT} ${SG_CX},${RV_BOT}" fill="none" stroke="${col_cl}" stroke-width="${PW}" stroke-linecap="round" stroke-linejoin="round"/>
<polyline points="${SG_CX},${RV_BOT} ${SG_CX},${SG_BOT}" fill="none" stroke="${col_cl}" stroke-width="${PW}" stroke-linecap="round" stroke-linejoin="round"/>
<polyline points="${ACC_CX},${ACC_BOT} ${ACC_CX},${ACC_INJ_Y} ${RV_RIGHT},${ACC_INJ_Y}" fill="none" stroke="${col_acc_fluid}" stroke-width="${PW}" stroke-linecap="round" stroke-linejoin="round"/>
<line x1="${SI_X_START}" y1="${SI_Y}" x2="${SI_X_END}" y2="${SI_Y}" stroke="${col_si_pipe}" stroke-width="${PW}" stroke-linecap="round"/><line x1="${SI_X_END}" y1="${SI_Y - PW}" x2="${SI_X_END}" y2="${SI_Y + PW}" stroke="${col_si_pipe}" stroke-width="3" stroke-linecap="round"/><text x="${SI_X_START + 14}" y="${SI_Y - Math.floor(PW/2) - 4}" font-family="IBM Plex Sans,sans-serif" font-size="13" font-weight="600" fill="${col_si_label}">SI  ${si_pumped_mdot.toFixed(0)} kg/s</text>
<line x1="${BREAK_X}" y1="${BREAK_Y_BOT}" x2="${BREAK_X}" y2="${BREAK_Y_TOP}" stroke="${col_brk_pipe}" stroke-width="${PW}" stroke-linecap="round"/><line x1="${BREAK_X - PW}" y1="${BREAK_Y_TOP}" x2="${BREAK_X + PW}" y2="${BREAK_Y_TOP}" stroke="${col_brk_pipe}" stroke-width="3" stroke-linecap="round"/><text x="${BREAK_X + PW + 5}" y="${BREAK_Y_TOP + 10}" font-family="IBM Plex Sans,sans-serif" font-size="13" font-weight="600" fill="${col_brk_label}">Break  ${break_mdot.toFixed(0)} kg/s</text>
<line x1="${PORV_X}" y1="${PORV_Y_BOT}" x2="${PORV_X}" y2="${PORV_Y_TOP}" stroke="${col_prv_pipe}" stroke-width="${PW}" stroke-linecap="round"/><line x1="${PORV_X - PW}" y1="${PORV_Y_TOP}" x2="${PORV_X + PW}" y2="${PORV_Y_TOP}" stroke="${col_prv_pipe}" stroke-width="3" stroke-linecap="round"/><text x="${PORV_X + PW + 5}" y="${PORV_Y_TOP + 10}" font-family="IBM Plex Sans,sans-serif" font-size="13" font-weight="600" fill="${col_prv_label}">PORV  ${porv_mdot.toFixed(1)} kg/s</text>
<line x1="${CVCS_X_START}" y1="${CVCS_Y_MAKEUP}" x2="${CVCS_X_END}" y2="${CVCS_Y_MAKEUP}" stroke="${col_mkup_pipe}" stroke-width="${PW}" stroke-linecap="round"/><line x1="${CVCS_X_END}" y1="${CVCS_Y_MAKEUP - PW}" x2="${CVCS_X_END}" y2="${CVCS_Y_MAKEUP + PW}" stroke="${col_mkup_pipe}" stroke-width="3" stroke-linecap="round"/><text x="${CVCS_X_END}" y="${CVCS_Y_MAKEUP - Math.floor(PW/2) - 4}" font-family="IBM Plex Sans,sans-serif" font-size="13" font-weight="600" fill="${col_mkup_label}">Makeup  ${cvcs_makeup.toFixed(2)} kg/s</text>
<line x1="${CVCS_X_START}" y1="${CVCS_Y_LETDOWN}" x2="${CVCS_X_END}" y2="${CVCS_Y_LETDOWN}" stroke="${col_ldwn_pipe}" stroke-width="${PW}" stroke-linecap="round"/><line x1="${CVCS_X_END}" y1="${CVCS_Y_LETDOWN - PW}" x2="${CVCS_X_END}" y2="${CVCS_Y_LETDOWN + PW}" stroke="${col_ldwn_pipe}" stroke-width="3" stroke-linecap="round"/><text x="${CVCS_X_END}" y="${CVCS_Y_LETDOWN + PW + 14}" font-family="IBM Plex Sans,sans-serif" font-size="13" font-weight="600" fill="${col_ldwn_label}">Letdown  ${cvcs_letdown.toFixed(2)} kg/s</text>
<g clip-path="url(#cp-con)"><rect x="${CON_LEFT}" y="${CON_TOP}" width="${CON_W}" height="${CON_H}" fill="${col_con}"/></g><path d="M ${CON_LEFT},${CON_BOT} L ${CON_LEFT},${CON_ARCH_CY} A ${CON_RX},${CON_RY} 0 0 1 ${CON_RIGHT},${CON_ARCH_CY} L ${CON_RIGHT},${CON_BOT}" fill="none" stroke="${col_con}" stroke-width="4" stroke-linejoin="round"/><text x="${CON_CX}" y="${CON_TOP + 22}" font-family="IBM Plex Sans,sans-serif" font-size="13" font-weight="600" fill="#334155" text-anchor="middle">Containment</text>${conInterior}
<rect x="${PRZ_CX - Math.floor(PRZ_W/2)}" y="${PRZ_Y}" width="${PRZ_W}" height="${PRZ_H}" fill="white" stroke="#334155" stroke-width="2"/><g clip-path="url(#cp-prz)">${prz_fill}</g><text x="${PRZ_CX + Math.floor(PRZ_W/2) + 8}" y="${PRZ_Y + Math.floor(PRZ_H/2)}" font-family="IBM Plex Sans,sans-serif" font-size="13" fill="#334155" dominant-baseline="middle">Pressurizer</text>
<rect x="${SG_X}" y="${SG_Y}" width="${SG_W}" height="${SG_H}" fill="white" stroke="#334155" stroke-width="2"/><g clip-path="url(#cp-sg)">${sg_fill}</g><text x="${SG_X + SG_W + 8}" y="${SG_Y + Math.floor(SG_H/2) - 8}" font-family="IBM Plex Sans,sans-serif" font-size="13" fill="#334155" dominant-baseline="middle">Steam</text><text x="${SG_X + SG_W + 8}" y="${SG_Y + Math.floor(SG_H/2) + 8}" font-family="IBM Plex Sans,sans-serif" font-size="13" fill="#334155" dominant-baseline="middle">Generator</text>
<rect x="${RV_X}" y="${RV_Y}" width="${RV_W}" height="${RV_H}" fill="white" stroke="#334155" stroke-width="2"/><g clip-path="url(#cp-rv)">${rv_fill}</g><rect x="${CORE_X}" y="${CORE_Y}" width="${CORE_W}" height="${CORE_H}" fill="${col_core}" stroke="#1e3a5f" stroke-width="2"/><line x1="${CORE_X+Math.floor(CORE_W/4)}" y1="${CORE_Y}" x2="${CORE_X+Math.floor(CORE_W/4)}" y2="${CORE_Y+CORE_H}" stroke="white" stroke-width="1.5" opacity="0.4"/><line x1="${CORE_X+Math.floor(CORE_W/2)}" y1="${CORE_Y}" x2="${CORE_X+Math.floor(CORE_W/2)}" y2="${CORE_Y+CORE_H}" stroke="white" stroke-width="1.5" opacity="0.4"/><line x1="${CORE_X+Math.floor(3*CORE_W/4)}" y1="${CORE_Y}" x2="${CORE_X+Math.floor(3*CORE_W/4)}" y2="${CORE_Y+CORE_H}" stroke="white" stroke-width="1.5" opacity="0.4"/>
<path d="M ${PUMP_CX - PUMP_RX} ${PUMP_CY} A ${PUMP_RX} ${PUMP_RY} 0 0 1 ${PUMP_CX + PUMP_RX} ${PUMP_CY} Z" fill="${col_pump}" stroke="#334155" stroke-width="2"/><line x1="${PUMP_CX - PUMP_RX}" y1="${PUMP_CY}" x2="${PUMP_CX + PUMP_RX}" y2="${PUMP_CY}" stroke="#334155" stroke-width="2"/><circle cx="${PUMP_CX}" cy="${PUMP_CY - Math.floor(PUMP_RY/2)}" r="5" fill="#334155"/><text x="${PUMP_CX}" y="${PUMP_CY + 18}" font-family="IBM Plex Sans,sans-serif" font-size="13" fill="#334155" text-anchor="middle">Pump</text><rect x="${PUMP_CX - 52}" y="${PUMP_CY - PUMP_RY - 58}" width="104" height="48" rx="4" fill="#0d1117" stroke="#30363d" stroke-width="1" opacity="0.88"/><text x="${PUMP_CX}" y="${PUMP_CY - PUMP_RY - 42}" font-family="IBM Plex Mono,monospace" font-size="14" fill="#8b949e" text-anchor="middle">PUMP FLOW</text><text x="${PUMP_CX}" y="${PUMP_CY - PUMP_RY - 18}" font-family="IBM Plex Mono,monospace" font-size="20" font-weight="600" fill="${col_pump}" text-anchor="middle">${pump_rpm.toFixed(0)} rpm</text>
<rect x="${ACC_X}" y="${ACC_Y}" width="${ACC_W}" height="${ACC_H}" fill="white" stroke="#334155" stroke-width="2"/><g clip-path="url(#cp-acc)">${acc_fill}</g><text x="${ACC_X + Math.floor(ACC_W/2)}" y="${ACC_Y - 14}" font-family="IBM Plex Sans,sans-serif" font-size="14" font-weight="600" fill="#334155" text-anchor="middle">Accumulator</text>
<rect x="${HL_MID_X - 62}" y="${HL_MID_Y - 26}" width="124" height="48" rx="4" fill="#0d1117" stroke="#30363d" stroke-width="1" opacity="0.88"/><text x="${HL_MID_X}" y="${HL_MID_Y - 10}" font-family="IBM Plex Mono,monospace" font-size="14" fill="#8b949e" text-anchor="middle">PRESSURE</text><text x="${HL_MID_X}" y="${HL_MID_Y + 14}" font-family="IBM Plex Mono,monospace" font-size="20" font-weight="600" fill="#ffa657" text-anchor="middle">${P_MPa.toFixed(2)} MPa</text>
<rect x="10" y="${PRZ_Y + 10}" width="150" height="48" rx="4" fill="#0d1117" stroke="#30363d" stroke-width="1" opacity="0.88"/><text x="85" y="${PRZ_Y + 26}" font-family="IBM Plex Mono,monospace" font-size="14" fill="#8b949e" text-anchor="middle">SIM TIME</text><text x="85" y="${PRZ_Y + 50}" font-family="IBM Plex Mono,monospace" font-size="20" font-weight="600" fill="#e8530a" text-anchor="middle">${t_sim.toFixed(1)} s</text><rect x="10" y="${PRZ_Y + 68}" width="150" height="48" rx="4" fill="#0d1117" stroke="#30363d" stroke-width="1" opacity="0.88"/><text x="85" y="${PRZ_Y + 84}" font-family="IBM Plex Mono,monospace" font-size="14" fill="#8b949e" text-anchor="middle">CORE PWR</text><text x="85" y="${PRZ_Y + 108}" font-family="IBM Plex Mono,monospace" font-size="20" font-weight="600" fill="#3fb950" text-anchor="middle">${core_pwr.toFixed(1)} MW</text>
<rect x="${RV_X + Math.floor(RV_W/2) - 62}" y="${RV_Y + 10}" width="124" height="48" rx="4" fill="#0d1117" stroke="#30363d" stroke-width="1" opacity="0.88"/><text x="${RV_X + Math.floor(RV_W/2)}" y="${RV_Y + 26}" font-family="IBM Plex Mono,monospace" font-size="14" fill="#8b949e" text-anchor="middle">RCS TEMP</text><text x="${RV_X + Math.floor(RV_W/2)}" y="${RV_Y + 50}" font-family="IBM Plex Mono,monospace" font-size="20" font-weight="600" fill="#58a6ff" text-anchor="middle">${T_hot_C.toFixed(1)} °C</text><rect x="${RV_X + Math.floor(RV_W/2) - 62}" y="${RV_BOT - 58}" width="124" height="48" rx="4" fill="#0d1117" stroke="#30363d" stroke-width="1" opacity="0.88"/><text x="${RV_X + Math.floor(RV_W/2)}" y="${RV_BOT - 42}" font-family="IBM Plex Mono,monospace" font-size="14" fill="#8b949e" text-anchor="middle">FUEL CLAD T</text><text x="${RV_X + Math.floor(RV_W/2)}" y="${RV_BOT - 18}" font-family="IBM Plex Mono,monospace" font-size="20" font-weight="600" fill="#58a6ff" text-anchor="middle">${T_clad_C.toFixed(1)} °C</text>
</svg>`;
}

function renderVariables(i) {
  const row = rows[i] || {};
  let html = '<table class="varTable"><thead><tr><th>Variable</th><th>Value</th></tr></thead><tbody>';
  for (const [k, v] of Object.entries(row)) {
    let val = v;
    if (typeof v === 'number' && Number.isFinite(v)) val = Math.abs(v) >= 10000 || (Math.abs(v) > 0 && Math.abs(v) < 0.001) ? v.toExponential(5) : v.toPrecision(6);
    html += `<tr><td>${k}</td><td>${val === null || val === undefined ? '' : val}</td></tr>`;
  }
  html += '</tbody></table>';
  document.getElementById('varTable').innerHTML = html;
}
function render(i) {
  step = Math.max(0, Math.min(maxStep, Number(i) || 0));
  document.getElementById('svgHost').innerHTML = buildSvg(step);
  document.getElementById('stepSlider').value = String(step);
  document.getElementById('stepText').textContent = `${step} / ${maxStep}`;
  const t = num(rows[step], 'Time (s)', 0.0);
  document.getElementById('simTime').textContent = `t = ${t.toFixed(1)} s`;
  renderVariables(step);
}
function scheduleNext() {
  if (!playing) return;
  const delay = Math.max(10, Number(document.getElementById('speed').value) || 120);
  const skip = Math.max(1, Number(document.getElementById('skip').value) || 1);
  timer = setTimeout(() => {
    if (!playing) return;
    const next = Math.min(step + skip, maxStep);
    render(next);
    if (next >= maxStep) { playing = false; document.getElementById('playBtn').textContent = '▶'; return; }
    scheduleNext();
  }, delay);
}
function setPlaying(on) {
  playing = on;
  document.getElementById('playBtn').textContent = playing ? '⏸' : '▶';
  if (timer) { clearTimeout(timer); timer = null; }
  if (playing) scheduleNext();
}
document.getElementById('caseTitle').textContent = PAYLOAD.case_name || '';
document.getElementById('csvInfo').textContent = PAYLOAD.has_con ? `CON: ${PAYLOAD.con_name} ✓` : 'CON: no -CON.csv found';
document.getElementById('stepSlider').max = String(maxStep);
document.getElementById('speed').addEventListener('input', e => { document.getElementById('speedText').textContent = `${e.target.value} ms`; });
document.getElementById('stepSlider').addEventListener('input', e => { setPlaying(false); render(Number(e.target.value)); });
document.getElementById('firstBtn').addEventListener('click', () => { setPlaying(false); render(0); });
document.getElementById('lastBtn').addEventListener('click', () => { setPlaying(false); render(maxStep); });
document.getElementById('playBtn').addEventListener('click', () => { if (step >= maxStep) render(0); setPlaying(!playing); });
render(0);
</script>
</body>
</html>
'''

html = HTML_TEMPLATE.replace("__PAYLOAD_JSON__", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
# Give the embedded browser-side analyzer enough vertical room so the iframe itself
# does not need an internal scrollbar. The Streamlit page can still scroll normally.
#
# Do not place the complete analyzer document in a base64 data URL. Large transient
# files can produce several megabytes of JSON; base64 expands that payload by another
# third and can exceed browser/iframe URL limits. components.html sends the document
# as iframe content rather than encoding it into the iframe URL, so long or densely
# sampled cases load reliably without discarding timesteps.
component_height = int(758 * zoom) + 565
components.html(html, height=component_height, scrolling=False)

with st.sidebar:
    st.divider()
    st.caption(f"Case: `{_sel_path.name}`")
    st.caption(f"Steps: {len(df)}")
    if df_con is not None:
        st.caption(f"CON: `{_con_path.name}` ✓")
    else:
        st.caption("CON: no -CON.csv found")
