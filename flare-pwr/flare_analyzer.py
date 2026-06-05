"""
flare_analyzer.py  —  FLARE Real-Time Plant Analyzer
Layout pixel-matched to NPA_mask.png (902 × 758 canvas).
Run with:  streamlit run flare_analyzer.py
"""

import streamlit as st
import pandas as pd
import time
import base64
from pathlib import Path

st.set_page_config(layout="wide", page_title="FLARE Plant Analyzer", page_icon="🔥")
WORK_DIR = Path(__file__).parent

def _load_buddy_b64():
    """Return a base64 data URI for the FLARE Buddy icon, or None."""
    for _dir in (WORK_DIR / "icons", WORK_DIR / "Icons"):
        _p = _dir / "FLAREBUDDY.png"
        if _p.exists():
            try:
                return "data:image/png;base64," + base64.b64encode(_p.read_bytes()).decode()
            except Exception:
                return None
    return None

_BUDDY_B64 = _load_buddy_b64()

# ── Browser detection — must run before any rendering ────────────────────────
try:
    ua = st.context.headers.get("User-Agent", "")
except Exception:
    ua = ""
is_ios        = "iPhone" in ua or "iPad" in ua
is_ios_chrome = "CriOS"  in ua
is_ios_edge   = "EdgiOS" in ua
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

# ── Styling ───────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap');
:root{ --sidebar:#1a1f2e; --dark-surface:#0d1117; --dark-border:#30363d;
       --sid-text:#e6edf3; --sid-muted:#8b949e; }
html,body,[class*="css"]{ font-family:'IBM Plex Sans',sans-serif; }
.stApp{ background:#f5f7fa; }
header{ background:transparent !important; }
h1,h2,h3{ font-family:'IBM Plex Mono',monospace; }
#MainMenu,footer{ visibility:hidden; }
section[data-testid="stSidebar"]{
    background:var(--sidebar) !important; border-right:1px solid var(--dark-border); }
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
/* Tighten sidebar vertical spacing */
section[data-testid="stSidebar"] .block-container { padding-top:0.5rem !important; }
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div { gap:0.15rem !important; }
section[data-testid="stSidebar"] hr { margin:0.4rem 0 !important; }
</style>
""", unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        f'''<a href="?page=home" target="_self" style="text-decoration:none;display:flex;
            align-items:center;gap:0.55rem;padding:0.35rem 0.6rem;
            border:1px solid #e8530a;border-radius:4px;
            font-family:Share Tech Mono,monospace;font-size:1.6rem;
            font-weight:700;letter-spacing:0.08em;color:#f97316;"
            onmouseover="this.style.background='rgba(232,83,10,0.18)';this.style.boxShadow='0 0 14px rgba(232,83,10,0.45)';this.style.color='#ffffff';"
            onmouseout="this.style.background='transparent';this.style.boxShadow='none';this.style.color='#f97316';">
          {"<img src='" + _BUDDY_B64 + "' style='height:4.5rem;width:auto;object-fit:contain;flex-shrink:0;'/>" if _BUDDY_B64 else "🔥"}
          FLARE Home
        </a>''',
        unsafe_allow_html=True,
    )
    st.divider()
    st.markdown("### 🏭 Plant Analyzer")

    # Discover *_out.csv files in sim_* and risk_* subfolders only
    # Label = "sim_YYYYMMDD_HHMMSS / CaseName_out.csv"
    _csv_entries = []  # list of (label, Path)
    _run_dirs = sorted(
        [d for d in WORK_DIR.iterdir()
         if d.is_dir() and (d.name.startswith("sim_") or d.name.startswith("risk_"))],
        reverse=True,   # most recent first
    )
    for _rdir in _run_dirs:
        for p in sorted(_rdir.glob("*_out.csv")):
            _label = f"{_rdir.name}  /  {p.name}"
            _csv_entries.append((_label, p))

    if not _csv_entries:
        st.error("No *_out.csv files found in any sim_* or risk_* subfolder.")
        st.stop()

    _labels = [e[0] for e in _csv_entries]
    _sel_label = st.selectbox("Case", _labels,
                              help="Select a simulation output CSV to replay.")
    _sel_path = next(p for lbl, p in _csv_entries if lbl == _sel_label)
    file = _sel_path.name
    df = pd.read_csv(_sel_path)
    max_step = len(df) - 1
    # Load paired FLARECON output if it exists (CaseName_out.csv → CaseName_CON.csv)
    _con_path = _sel_path.with_name(_sel_path.name.replace("_out.csv", "-CON.csv"))
    df_con = pd.read_csv(_con_path) if _con_path.exists() else None
    st.divider()
    refresh_ms = st.slider("Speed (ms/step)", 0, 500, 300, step=25,
                           help="Delay between frames during playback.")
    skip = st.number_input("Step skip", min_value=1, max_value=100, value=1, step=1,
                           help="Advance this many timesteps per frame. "
                                "Increase for long slowly-changing runs.")
    zoom = st.slider("Diagram zoom", 0.4, 1.4, 0.9, step=0.05,
                     help="Scale the plant diagram.")
    st.divider()
    st.markdown("**Playback**")
    pc1, pc2, pc3 = st.columns(3)
    if "step"    not in st.session_state: st.session_state.step    = 0
    if "playing" not in st.session_state: st.session_state.playing = False
    if pc1.button("⏮", help="First timestep"):
        st.session_state.step = 0;  st.session_state.playing = False
    if pc2.button("▶" if not st.session_state.playing else "⏸", help="Play/Pause"):
        st.session_state.playing = not st.session_state.playing
    if pc3.button("⏭", help="Last timestep"):
        st.session_state.step = max_step; st.session_state.playing = False
    st.session_state.step = st.slider("Timestep", 0, max_step,
                                       st.session_state.step,
                                       help="Scrub through the simulation.")
    st.divider()
    st.caption(f"Case: `{file}`")
    st.caption(f"Steps: {max_step + 1}")
    if df_con is not None:
        st.caption(f"CON: `{_con_path.name}` ✓")
    else:
        st.caption("CON: no _CON.csv found")

# ── Data ──────────────────────────────────────────────────────────────────────
row = df.iloc[st.session_state.step]

def get(k, default=0.0):
    try:   return float(row.get(k, default))
    except: return float(default)

T_hot_K  = get("RCS Temperature (K)",           573.15)
P_kPa    = get("RCS Pressure (kPa)",            15500.0)
T_clad_K = get("Clad Surface Temp (K)",          573.15)
t_sim    = get("Time (s)",                           0.0)
core_pwr = get("Core Power (MW)",                    0.0)

T_hot_C  = T_hot_K  - 273.15
T_clad_C = T_clad_K - 273.15
P_MPa    = P_kPa / 1000.0

# Containment (FLARECON) data — loaded from paired *_CON.csv if present
if df_con is not None:
    # Interpolate CON timestep: CON csv may have different time resolution
    _con_step = min(st.session_state.step, len(df_con) - 1)
    row_con = df_con.iloc[_con_step]
    def get_con(k, default=0.0):
        try:   return float(row_con.get(k, default))
        except: return float(default)
    P_con_kPa = get_con("Pressure [kPa]",  101.325)
    T_con_C   = get_con("Gas Temp [C]",      27.0)
    P_con_min = float(df_con["Pressure [kPa]"].min()) if "Pressure [kPa]" in df_con.columns else 101.0
    P_con_max = float(df_con["Pressure [kPa]"].max()) if "Pressure [kPa]" in df_con.columns else 101.0
    T_con_min = float(df_con["Gas Temp [C]"].min())    if "Gas Temp [C]"    in df_con.columns else  27.0
    T_con_max = float(df_con["Gas Temp [C]"].max())    if "Gas Temp [C]"    in df_con.columns else  27.0
else:
    P_con_kPa, T_con_C = 101.325, 27.0
    P_con_min, P_con_max = 101.0, 101.0
    T_con_min, T_con_max =  27.0,  27.0

# SI pumped injection flow (HPSI + LPSI)
si_pumped_mdot  = get("SI Pumped Total (kg/s)", 0.0)
break_mdot      = get("Break Flow (kg/s)",       0.0)
porv_mdot       = get("PORV Mass Flow (kg/s)",   0.0)
cvcs_makeup     = get("CVCS Makeup (kg/s)",       0.0)
cvcs_letdown    = get("CVCS Letdown (kg/s)",      0.0)
cvcs_net        = cvcs_makeup - cvcs_letdown   # net CVCS flow (positive = makeup)

lvl_rv_raw  = get("Total Mass Scaled",               1.0)
lvl_acc_raw = get("Accumulator Liquid Volume (m3)",   0.0)
Lmax_acc = float(df["Accumulator Liquid Volume (m3)"].max()) if "Accumulator Liquid Volume (m3)" in df.columns else 1.0

def clamp(x): return max(0.0, min(1.0, x))
lvl_rv  = clamp(lvl_rv_raw)
lvl_acc = clamp(lvl_acc_raw / (Lmax_acc + 1e-9))

T_series = df["RCS Temperature (K)"] - 273.15
P_series = df["RCS Pressure (kPa)"]  / 1000.0
Tmin, Tmax = float(T_series.min()), float(T_series.max())
Pmin, Pmax = float(P_series.min()), float(P_series.max())

# Clad temp uses its own column range so colour is correctly normalised
CLAD_COL = "Clad Surface Temp (K)"
if CLAD_COL in df.columns:
    Tclad_min = float(df[CLAD_COL].min()) - 273.15
    Tclad_max = float(df[CLAD_COL].max()) - 273.15
else:
    Tclad_min, Tclad_max = Tmin, Tmax

def fluid_color(T_C, P_MPa_val, alpha=0.82, t_min=None, t_max=None):
    lo = Tmin if t_min is None else t_min
    hi = Tmax if t_max is None else t_max
    t = clamp((T_C       - lo)   / (hi   - lo   + 1e-9))
    p = clamp((P_MPa_val - Pmin) / (Pmax - Pmin + 1e-9))
    hue   = int(240 * (1 - t))
    light = int(70 - 30 * p)
    return f"hsla({hue},85%,{light}%,{alpha})"

# Containment colour — mapped on its own pressure range so subtle changes show
def containment_color(P_kPa_val, T_C_val, alpha=0.28):
    """
    Returns an hsla colour for the containment dome interior.
    alpha=0.28 keeps the interior semi-transparent so underlying pipes show through.

    Hue    : driven by temperature — cool blue (210°) at 27°C (ambient), shifting to
             red (0°) at 150°C (design-basis). Range 210→0°, never passes through green.
    Sat    : driven by pressure — more saturated as pressure rises (60→85%).
    Light  : fixed at 55% — mid-range so both tint and hue read clearly.
    """
    p = clamp((P_kPa_val - P_con_min) / (P_con_max - P_con_min + 1e-9))
    # Temperature uses fixed physical anchors: 27°C (ambient) → 150°C (design-basis hot)
    # This way 130°C looks orange/red regardless of where the run ends.
    t = clamp((T_C_val - 27.0) / (150.0 - 27.0))
    hue   = int(210 - 210 * t)   # 210=cool blue at ambient → 0=red at high T
    sat   = int(60  +  25 * p)   # 60% at low P, 85% at high P
    light = 55                   # fixed lightness
    return f"hsla({hue},{sat}%,{light}%,{alpha})"

col_con = containment_color(P_con_kPa, T_con_C)
col_hot       = fluid_color(T_hot_C,      P_MPa)
col_cold      = fluid_color(T_hot_C - 25, P_MPa)
col_core      = fluid_color(T_clad_C, P_MPa, alpha=1.0,
                            t_min=Tclad_min, t_max=Tclad_max)
col_acc_fluid = fluid_color(T_hot_C - 80, P_MPa * 0.5)
col_hl        = fluid_color(T_hot_C,      P_MPa, alpha=0.9)
col_cl        = fluid_color(T_hot_C - 25, P_MPa, alpha=0.9)


# ══════════════════════════════════════════════════════════════════════════════
# GEOMETRY — pixel-matched to NPA_mask.png (902 × 758)
#
# Measured by scanning blue-fill and white-interior pixels:
#
#   PRZ  white interior: x=100–249, y= 80–399   (w=149, h=319)  narrow tall
#   SG   white interior: x= 30–169, y=380–679   (w=139, h=299)  tall, far left
#   RV   white interior: x=350–569, y=300–739   (w=219, h=439)  large centre
#   ACC  white interior: x=620–879, y=270–539   (w=259, h=269)  wide, right
#   Core (dark inside RV): x=390–490, y=580–715
#   Pump D-shape:  border x=145–267, y=460–511  → cx≈206, cy≈485
#
# Piping (traced from blue-fill pixel positions):
#   Hot leg  : y≈375, x=140–380  (SG top → RV left wall)
#   Surge    : PRZ bottom (x=177,y=400) → down → joins hot leg at (x=177,y=375)
#   Cold leg : RV bottom (x=380,y=712) → left to x=99,y=712 → up to pump top
#              (x=99,y=460) → SG bottom (x=99,y=680)
#   ACC inj  : ACC bottom (x=735,y=539) → down to y=550 → left to RV right
#              wall (x=555,y=550)
# ══════════════════════════════════════════════════════════════════════════════

# Vessel corners  (x_left, y_top, width, height)
PRZ_X,  PRZ_Y,  PRZ_W,  PRZ_H  = 100, 80,  149, 319
SG_X,   SG_Y,   SG_W,   SG_H   =  30, 380, 139, 299
RV_X,   RV_Y,   RV_W,   RV_H   = 350, 300, 219, 439
ACC_X,  ACC_Y,  ACC_W,  ACC_H  = 620, 270, 181, 269
CORE_X, CORE_Y, CORE_W, CORE_H = 390, 580, 100, 135

# Pipe width
PW = 16

# Derived key points — SG and RV first, then PRZ (which depends on them)
SG_RIGHT = SG_X  + SG_W                  # 169  SG right wall x
SG_BOT   = SG_Y  + SG_H                  # 679  SG bottom y
SG_TOP   = SG_Y                           # 380  SG top y
SG_CX    = SG_X  + SG_W // 2             #  99  SG centreline x

RV_LEFT  = RV_X                           # 350  RV left wall x
RV_RIGHT = RV_X + RV_W                    # 569  RV right wall x
RV_BOT   = RV_Y + RV_H                   # 739  RV bottom y

ACC_LEFT = ACC_X                          # 620  ACC left wall x
ACC_BOT  = ACC_Y + ACC_H                  # 539  ACC bottom y
ACC_CX   = ACC_X + ACC_W // 2            # 749  ACC centreline x

# Hot leg y (horizontal pipe from SG right wall to RV left wall)
HL_Y     = 375

# PRZ centred on hot leg midpoint
PRZ_CX   = (SG_RIGHT + RV_LEFT) // 2     # x centre of PRZ = midpoint of hot leg
PRZ_X    = PRZ_CX - PRZ_W // 2           # left edge of PRZ vessel
PRZ_BOT  = PRZ_Y + PRZ_H                 # PRZ bottom y

# Pressure label also at hot leg midpoint
HL_MID_X = PRZ_CX
HL_MID_Y = HL_Y

# Pump sits at midpoint of HORIZONTAL cold leg (y=RV_BOT, x=SG_CX to RV_LEFT)
PUMP_CX = (SG_CX + RV_LEFT) // 2         # midpoint of horizontal run
PUMP_CY = RV_BOT                          # sits on the horizontal pipe
PUMP_RX = 42   # half-width
PUMP_RY = 28   # half-height (dome hangs below pipe)

# Pump colour — green=running fast, yellow=coasting, red=stopped
PUMP_COL     = "Pump Speed (rpm)"
PUMP_RPM_MAX = float(df[PUMP_COL].max()) if PUMP_COL in df.columns else 1500.0
pump_rpm     = float(row.get(PUMP_COL, 0.0)) if PUMP_COL in df.columns else 0.0
pump_frac    = clamp(pump_rpm / (PUMP_RPM_MAX + 1e-9))
pump_hue     = int(120 * pump_frac)          # 0=red, 60=yellow, 120=green
col_pump     = f"hsla({pump_hue},85%,45%,0.9)"

# SI injection pipe colour: blue when flowing, light grey when not
_si_flowing   = si_pumped_mdot > 0.1
col_si_pipe   = "#3b82f6" if _si_flowing  else "#d1d5db"
col_si_label  = "#1d4ed8" if _si_flowing  else "#9ca3af"

# Break pipe colour: blue when break flow > 0, grey when not
_break_flowing = break_mdot > 0.1
col_brk_pipe  = "#3b82f6" if _break_flowing else "#d1d5db"
col_brk_label = "#1d4ed8" if _break_flowing else "#9ca3af"

# PORV pipe colour: blue when PORV open, grey when not
_porv_flowing  = porv_mdot > 0.1
col_prv_pipe  = "#3b82f6" if _porv_flowing  else "#d1d5db"
col_prv_label = "#1d4ed8" if _porv_flowing  else "#9ca3af"

# CVCS pipe colours: blue when flowing, grey when idle
_makeup_flowing  = cvcs_makeup  > 0.01
_letdown_flowing = cvcs_letdown > 0.01
col_mkup_pipe  = "#3b82f6" if _makeup_flowing  else "#d1d5db"
col_mkup_label = "#1d4ed8" if _makeup_flowing  else "#9ca3af"
col_ldwn_pipe  = "#3b82f6" if _letdown_flowing else "#d1d5db"
col_ldwn_label = "#1d4ed8" if _letdown_flowing else "#9ca3af"

# SI pipe geometry: 300px horizontal pipe attached to RV right wall mid-height.
# Clear of accumulator injection (ACC_INJ_Y=550) and hot leg (HL_Y=375).
# ACC_INJ_Y defined below — use explicit value 550 here.
SI_Y       = (550 + RV_BOT) // 2   # 644 — midpoint between acc line and RV bottom
SI_X_START = RV_RIGHT               # 569 — flush with RV right wall
SI_X_END   = RV_RIGHT + 300         # 869 — 300 px to the right

# Break stem geometry: vertical pipe on top centre of RV
BREAK_X      = RV_X + RV_W // 2    # horizontal centre of RV
BREAK_Y_BOT  = RV_Y                 # bottom of stem = top of RV
BREAK_STEM_H = 80                   # stem height in pixels
BREAK_Y_TOP  = BREAK_Y_BOT - BREAK_STEM_H

# PORV stem geometry: vertical pipe on top centre of pressurizer
PORV_X      = PRZ_CX                # horizontal centre of PRZ
PORV_Y_BOT  = PRZ_Y                 # bottom of stem = top of PRZ
PORV_STEM_H = 80                    # stem height in pixels
PORV_Y_TOP  = PORV_Y_BOT - PORV_STEM_H

# CVCS pipe geometry: two horizontal pipes on LEFT side of RV.
# Makeup (upper) and letdown (lower), both running leftward from RV_LEFT.
# Centred at y=505, spaced 30px apart — clear of hot leg (y=375) and ACC inj (y=550).
CVCS_X_START  = RV_LEFT             # 350 — flush with RV left wall
CVCS_X_END    = RV_LEFT - 120       # 230 — 120 px left, clear of SG (right edge x=169)
CVCS_Y_MAKEUP  = 490                # upper pipe — makeup flow into vessel
CVCS_Y_LETDOWN = 520                # lower pipe — letdown flow out of vessel

# ACC injection y (drops from ACC bottom to this y, then runs left to RV right wall)
ACC_INJ_Y = 550

# ── CONTAINMENT DOME geometry ─────────────────────────────────────────────────
# Sits in the open space above the reactor vessel and accumulator.
# Elliptical arch: straight vertical sides with a rounded elliptical top,
# open at the bottom — matching the reference image.
# Containment dome — top and right edges fixed; 24% area reduction (√0.8 × √0.95)
CON_RIGHT = ACC_X + ACC_W      # 801  right edge fixed (ACC right wall)
CON_TOP   = 15                 #  15  top edge fixed
CON_W     = 393                # 393  = 451 * √0.76
CON_H     = 240                # 240  = 275 * √0.76
CON_LEFT  = CON_RIGHT - CON_W  # 408  left edge
CON_BOT   = CON_TOP   + CON_H  # 255  bottom
CON_CX    = (CON_LEFT + CON_RIGHT) // 2   # 604  horizontal centre
CON_RX    = CON_W // 2         # 196  horizontal ellipse radius
CON_RY    = CON_H // 2         # 120  vertical ellipse radius
CON_ARCH_CY = CON_BOT - CON_RY # 135  y-centre of the arch ellipse

# Badges: centred horizontally inside dome
CON_BADGE_W  = 116
CON_BADGE_X  = CON_CX - CON_BADGE_W // 2   # 546  centred on dome
CON_BADGE_Y  = CON_TOP + (CON_H - 118) // 2 + 15  # 91  vertically centred below label

# No-data text y positions — pre-computed as integers so they embed correctly
# in the SVG f-string (avoids unevaluated expressions like {CON_TOP+CON_H//2})
CON_NODATA_Y1 = CON_TOP + CON_H // 2 - 13   # 127  "no"
CON_NODATA_Y2 = CON_TOP + CON_H // 2 +  7   # 147  "FLARECON"
CON_NODATA_Y3 = CON_TOP + CON_H // 2 + 27   # 167  "data"

# ── Containment dome interior content (badges or no-data message) ────────────
# Vertically centre the content in the dome interior.
# Interior usable area: x from CON_LEFT+40 to CON_RIGHT-40, y from CON_TOP+35 to CON_BOT
# Centre point roughly (CON_CX, CON_TOP + CON_H*0.55)
_con_mid_y = 0  # filled below after geometry is defined — computed inline in SVG block

# Pre-compute badge and text positions as plain integers so they embed
# correctly into the SVG f-string without unevaluated expressions.
_badge_cx   = CON_BADGE_X + CON_BADGE_W // 2   # 604 — badge text centre x
_badge2_y   = CON_BADGE_Y + 63                  # 154 — top of second badge
_col_con_badge = col_con   # capture current colour for badge text

if df_con is not None:
    _con_interior = f"""
<!-- CONTAINMENT PRESSURE badge — inside dome -->
<rect x="{CON_BADGE_X}" y="{CON_BADGE_Y}" width="{CON_BADGE_W}" height="55" rx="4"
      fill="#0d1117" stroke="#58697a" stroke-width="1" opacity="0.93"/>
<text x="{_badge_cx}" y="{CON_BADGE_Y + 16}"
      font-family="IBM Plex Mono,monospace" font-size="10" fill="#cdd9e5"
      text-anchor="middle">CON PRESS</text>
<text x="{_badge_cx}" y="{CON_BADGE_Y + 40}"
      font-family="IBM Plex Mono,monospace" font-size="17" font-weight="600"
      fill="#ffffff" text-anchor="middle">{P_con_kPa:.1f} kPa</text>
<!-- CON TEMP badge -->
<rect x="{CON_BADGE_X}" y="{_badge2_y}" width="{CON_BADGE_W}" height="55" rx="4"
      fill="#0d1117" stroke="#58697a" stroke-width="1" opacity="0.93"/>
<text x="{_badge_cx}" y="{_badge2_y + 16}"
      font-family="IBM Plex Mono,monospace" font-size="10" fill="#cdd9e5"
      text-anchor="middle">CON TEMP</text>
<text x="{_badge_cx}" y="{_badge2_y + 40}"
      font-family="IBM Plex Mono,monospace" font-size="17" font-weight="600"
      fill="#ffffff" text-anchor="middle">{T_con_C:.1f} °C</text>"""
else:
    # Three words stacked vertically — y positions are plain ints, not expressions
    _con_interior = f"""
<!-- No FLARECON data message — stacked vertically -->
<text x="{CON_CX}" y="{CON_NODATA_Y1}"
      font-family="IBM Plex Sans,sans-serif" font-size="13" font-weight="600"
      fill="#64748b" text-anchor="middle" opacity="0.80">no</text>
<text x="{CON_CX}" y="{CON_NODATA_Y2}"
      font-family="IBM Plex Sans,sans-serif" font-size="13" font-weight="600"
      fill="#64748b" text-anchor="middle" opacity="0.80">FLARECON</text>
<text x="{CON_CX}" y="{CON_NODATA_Y3}"
      font-family="IBM Plex Sans,sans-serif" font-size="13" font-weight="600"
      fill="#64748b" text-anchor="middle" opacity="0.80">data</text>"""

# ── Fill helper ───────────────────────────────────────────────────────────────
def fill_rect(x, y, w, h, level, color):
    fh = h * clamp(level)
    fy = y + h - fh
    return (f'<rect x="{x}" y="{fy:.1f}" width="{w}" '
            f'height="{fh:.1f}" fill="{color}"/>')

prz_fill = fill_rect(PRZ_CX - PRZ_W // 2, PRZ_Y, PRZ_W, PRZ_H, lvl_rv,  col_hot)
sg_fill  = fill_rect(SG_X,  SG_Y,  SG_W,  SG_H,  lvl_rv,  col_cold)
rv_fill  = fill_rect(RV_X,  RV_Y,  RV_W,  RV_H,  lvl_rv,  col_hot)
acc_fill = fill_rect(ACC_X, ACC_Y, ACC_W, ACC_H, lvl_acc, col_acc_fluid)

# ── SVG ───────────────────────────────────────────────────────────────────────
svg = f"""
<svg xmlns="http://www.w3.org/2000/svg"
     viewBox="0 0 902 758"
     width="{int(902*zoom)}" height="{int(758*zoom)}"
     style="display:block;">
<defs>
  <clipPath id="cp-prz"><rect x="{PRZ_CX - PRZ_W//2}" y="{PRZ_Y}" width="{PRZ_W}" height="{PRZ_H}"/></clipPath>
  <clipPath id="cp-sg"> <rect x="{SG_X}"  y="{SG_Y}"  width="{SG_W}"  height="{SG_H}"/></clipPath>
  <clipPath id="cp-rv"> <rect x="{RV_X}"  y="{RV_Y}"  width="{RV_W}"  height="{RV_H}"/></clipPath>
  <clipPath id="cp-acc"><rect x="{ACC_X}" y="{ACC_Y}" width="{ACC_W}" height="{ACC_H}"/></clipPath>
  <clipPath id="cp-con">
    <path d="M {CON_LEFT},{CON_BOT}
             L {CON_LEFT},{CON_ARCH_CY}
             A {CON_RX},{CON_RY} 0 0 1 {CON_RIGHT},{CON_ARCH_CY}
             L {CON_RIGHT},{CON_BOT}
             Z"/>
  </clipPath>
</defs>

<!-- Background -->
<rect width="902" height="758" fill="#f8f9fb"/>

<!-- ════════════════════════════════════════════════════════════════
     PIPING  (drawn first, behind vessels)
     ════════════════════════════════════════════════════════════════ -->

<!-- HOT LEG: SG top-right → right → RV left wall (horizontal at HL_Y) -->
<line x1="{SG_RIGHT}" y1="{HL_Y}"
      x2="{RV_LEFT}"  y2="{HL_Y}"
      stroke="{col_hl}" stroke-width="{PW}" stroke-linecap="round"/>

<!-- SURGE LINE: narrow vertical pipe from hot leg up to PRZ bottom -->
<line x1="{PRZ_CX}" y1="{HL_Y}"
      x2="{PRZ_CX}" y2="{PRZ_BOT}"
      stroke="{col_hl}" stroke-width="{PW//3}"
      stroke-linecap="round"/>

<!-- COLD LEG: RV bottom-left → left along y=RV_BOT → up to pump →
               up to SG bottom centreline -->
<!-- Segment A: RV bottom → left to SG_CX -->
<polyline
  points="{RV_LEFT},{RV_BOT} {SG_CX},{RV_BOT}"
  fill="none" stroke="{col_cl}" stroke-width="{PW}"
  stroke-linecap="round" stroke-linejoin="round"/>
<!-- Segment B: SG_CX at RV_BOT → up through pump → up to SG bottom -->
<polyline
  points="{SG_CX},{RV_BOT} {SG_CX},{SG_BOT}"
  fill="none" stroke="{col_cl}" stroke-width="{PW}"
  stroke-linecap="round" stroke-linejoin="round"/>

<!-- ACC INJECTION: ACC bottom → down to ACC_INJ_Y → left to RV right wall -->
<polyline
  points="{ACC_CX},{ACC_BOT} {ACC_CX},{ACC_INJ_Y} {RV_RIGHT},{ACC_INJ_Y}"
  fill="none" stroke="{col_acc_fluid}" stroke-width="{PW}"
  stroke-linecap="round" stroke-linejoin="round"/>

<!-- SI INJECTION PIPE: 300px horizontal pipe attached to RV right wall.
     Blue = SI flowing (> 0.1 kg/s); grey = SI not flowing. -->
<line x1="{SI_X_START}" y1="{SI_Y}"
      x2="{SI_X_END}"   y2="{SI_Y}"
      stroke="{col_si_pipe}" stroke-width="{PW}"
      stroke-linecap="round"/>
<!-- End cap (vertical bar at pipe terminus) -->
<line x1="{SI_X_END}" y1="{SI_Y - PW}"
      x2="{SI_X_END}" y2="{SI_Y + PW}"
      stroke="{col_si_pipe}" stroke-width="3"
      stroke-linecap="round"/>
<!-- SI label above pipe, near the vessel wall -->
<text x="{SI_X_START + 14}" y="{SI_Y - PW // 2 - 4}"
      font-family="IBM Plex Sans,sans-serif" font-size="13"
      font-weight="600" fill="{col_si_label}">SI  {si_pumped_mdot:.0f} kg/s</text>

<!-- BREAK STEM: vertical pipe on top of RV — blue when break flow present -->
<line x1="{BREAK_X}" y1="{BREAK_Y_BOT}"
      x2="{BREAK_X}" y2="{BREAK_Y_TOP}"
      stroke="{col_brk_pipe}" stroke-width="{PW}"
      stroke-linecap="round"/>
<!-- End cap (horizontal bar at stem top) -->
<line x1="{BREAK_X - PW}" y1="{BREAK_Y_TOP}"
      x2="{BREAK_X + PW}" y2="{BREAK_Y_TOP}"
      stroke="{col_brk_pipe}" stroke-width="3"
      stroke-linecap="round"/>
<!-- Break label -->
<text x="{BREAK_X + PW + 5}" y="{BREAK_Y_TOP + 10}"
      font-family="IBM Plex Sans,sans-serif" font-size="13"
      font-weight="600" fill="{col_brk_label}">Break  {break_mdot:.0f} kg/s</text>

<!-- PORV STEM: vertical pipe on top of pressurizer — blue when PORV open -->
<line x1="{PORV_X}" y1="{PORV_Y_BOT}"
      x2="{PORV_X}" y2="{PORV_Y_TOP}"
      stroke="{col_prv_pipe}" stroke-width="{PW}"
      stroke-linecap="round"/>
<!-- End cap (horizontal bar at stem top) -->
<line x1="{PORV_X - PW}" y1="{PORV_Y_TOP}"
      x2="{PORV_X + PW}" y2="{PORV_Y_TOP}"
      stroke="{col_prv_pipe}" stroke-width="3"
      stroke-linecap="round"/>
<!-- PORV label -->
<text x="{PORV_X + PW + 5}" y="{PORV_Y_TOP + 10}"
      font-family="IBM Plex Sans,sans-serif" font-size="13"
      font-weight="600" fill="{col_prv_label}">PORV  {porv_mdot:.1f} kg/s</text>

<!-- CVCS MAKEUP PIPE: upper horizontal pipe on left side of RV.
     Represents flow into the vessel (makeup). Blue when makeup > 0. -->
<line x1="{CVCS_X_START}" y1="{CVCS_Y_MAKEUP}"
      x2="{CVCS_X_END}"   y2="{CVCS_Y_MAKEUP}"
      stroke="{col_mkup_pipe}" stroke-width="{PW}"
      stroke-linecap="round"/>
<line x1="{CVCS_X_END}" y1="{CVCS_Y_MAKEUP - PW}"
      x2="{CVCS_X_END}" y2="{CVCS_Y_MAKEUP + PW}"
      stroke="{col_mkup_pipe}" stroke-width="3"
      stroke-linecap="round"/>
<text x="{CVCS_X_END}" y="{CVCS_Y_MAKEUP - PW // 2 - 4}"
      font-family="IBM Plex Sans,sans-serif" font-size="13"
      font-weight="600" fill="{col_mkup_label}">Makeup  {cvcs_makeup:.2f} kg/s</text>

<!-- CVCS LETDOWN PIPE: lower horizontal pipe on left side of RV.
     Represents flow out of the vessel (letdown). Blue when letdown > 0. -->
<line x1="{CVCS_X_START}" y1="{CVCS_Y_LETDOWN}"
      x2="{CVCS_X_END}"   y2="{CVCS_Y_LETDOWN}"
      stroke="{col_ldwn_pipe}" stroke-width="{PW}"
      stroke-linecap="round"/>
<line x1="{CVCS_X_END}" y1="{CVCS_Y_LETDOWN - PW}"
      x2="{CVCS_X_END}" y2="{CVCS_Y_LETDOWN + PW}"
      stroke="{col_ldwn_pipe}" stroke-width="3"
      stroke-linecap="round"/>
<text x="{CVCS_X_END}" y="{CVCS_Y_LETDOWN + PW + 14}"
      font-family="IBM Plex Sans,sans-serif" font-size="13"
      font-weight="600" fill="{col_ldwn_label}">Letdown  {cvcs_letdown:.2f} kg/s</text>

<!-- ════════════════════════════════════════════════════════════════
     CONTAINMENT DOME
     ════════════════════════════════════════════════════════════════ -->

<!-- Dome fill — semi-transparent col_con so pipes beneath remain visible -->
<g clip-path="url(#cp-con)">
  <rect x="{CON_LEFT}" y="{CON_TOP}" width="{CON_W}" height="{CON_H}"
        fill="{col_con}"/>
</g>
<!-- Dome outline: arch outline drawn on top of fill -->
<path d="M {CON_LEFT},{CON_BOT}
         L {CON_LEFT},{CON_ARCH_CY}
         A {CON_RX},{CON_RY} 0 0 1 {CON_RIGHT},{CON_ARCH_CY}
         L {CON_RIGHT},{CON_BOT}"
      fill="none" stroke="{col_con}" stroke-width="4" stroke-linejoin="round"/>
<!-- Dome label -->
<text x="{CON_CX}" y="{CON_TOP + 22}"
      font-family="IBM Plex Sans,sans-serif" font-size="13" font-weight="600"
      fill="#334155" text-anchor="middle">Containment</text>

{_con_interior}

<!-- ════════════════════════════════════════════════════════════════
     VESSELS
     ════════════════════════════════════════════════════════════════ -->

<!-- PRESSURIZER — centred on hot leg, surge line connects from below -->
<rect x="{PRZ_CX - PRZ_W//2}" y="{PRZ_Y}" width="{PRZ_W}" height="{PRZ_H}"
      fill="white" stroke="#334155" stroke-width="2"/>
<g clip-path="url(#cp-prz)">{prz_fill}</g>
<text x="{PRZ_CX + PRZ_W//2 + 8}" y="{PRZ_Y + PRZ_H // 2}"
      font-family="IBM Plex Sans,sans-serif" font-size="13" fill="#334155"
      dominant-baseline="middle">Pressurizer</text>

<!-- STEAM GENERATOR -->
<rect x="{SG_X}" y="{SG_Y}" width="{SG_W}" height="{SG_H}"
      fill="white" stroke="#334155" stroke-width="2"/>
<g clip-path="url(#cp-sg)">{sg_fill}</g>
<text x="{SG_X + SG_W + 8}" y="{SG_Y + SG_H // 2 - 8}"
      font-family="IBM Plex Sans,sans-serif" font-size="13" fill="#334155"
      dominant-baseline="middle">Steam</text>
<text x="{SG_X + SG_W + 8}" y="{SG_Y + SG_H // 2 + 8}"
      font-family="IBM Plex Sans,sans-serif" font-size="13" fill="#334155"
      dominant-baseline="middle">Generator</text>

<!-- REACTOR VESSEL -->
<rect x="{RV_X}" y="{RV_Y}" width="{RV_W}" height="{RV_H}"
      fill="white" stroke="#334155" stroke-width="2"/>
<g clip-path="url(#cp-rv)">{rv_fill}</g>
<!-- Core -->
<rect x="{CORE_X}" y="{CORE_Y}" width="{CORE_W}" height="{CORE_H}"
      fill="{col_core}" stroke="#1e3a5f" stroke-width="2"/>
<line x1="{CORE_X+CORE_W//4}"   y1="{CORE_Y}" x2="{CORE_X+CORE_W//4}"   y2="{CORE_Y+CORE_H}"
      stroke="white" stroke-width="1.5" opacity="0.4"/>
<line x1="{CORE_X+CORE_W//2}"   y1="{CORE_Y}" x2="{CORE_X+CORE_W//2}"   y2="{CORE_Y+CORE_H}"
      stroke="white" stroke-width="1.5" opacity="0.4"/>
<line x1="{CORE_X+3*CORE_W//4}" y1="{CORE_Y}" x2="{CORE_X+3*CORE_W//4}" y2="{CORE_Y+CORE_H}"
      stroke="white" stroke-width="1.5" opacity="0.4"/>

<!-- PUMP  (D-shape on horizontal cold leg: flat base flush with pipe,
           dome rises above, colour reflects pump speed) -->
<path d="M {PUMP_CX - PUMP_RX} {PUMP_CY}
         A {PUMP_RX} {PUMP_RY} 0 0 1 {PUMP_CX + PUMP_RX} {PUMP_CY}
         Z"
      fill="{col_pump}" stroke="#334155" stroke-width="2"/>
<!-- Flat base (flush with cold leg pipe) -->
<line x1="{PUMP_CX - PUMP_RX}" y1="{PUMP_CY}"
      x2="{PUMP_CX + PUMP_RX}" y2="{PUMP_CY}"
      stroke="#334155" stroke-width="2"/>
<!-- Impeller hub -->
<circle cx="{PUMP_CX}" cy="{PUMP_CY - PUMP_RY//2}" r="5" fill="#334155"/>
<text x="{PUMP_CX}" y="{PUMP_CY + 18}"
      font-family="IBM Plex Sans,sans-serif" font-size="13" fill="#334155"
      text-anchor="middle">Pump</text>

<!-- PUMP FLOW badge — centred above the pump dome -->
<rect x="{PUMP_CX - 52}" y="{PUMP_CY - PUMP_RY - 58}" width="104" height="48" rx="4"
      fill="#0d1117" stroke="#30363d" stroke-width="1" opacity="0.88"/>
<text x="{PUMP_CX}" y="{PUMP_CY - PUMP_RY - 42}"
      font-family="IBM Plex Mono,monospace" font-size="14" fill="#8b949e"
      text-anchor="middle">PUMP FLOW</text>
<text x="{PUMP_CX}" y="{PUMP_CY - PUMP_RY - 18}"
      font-family="IBM Plex Mono,monospace" font-size="20" font-weight="600"
      fill="{col_pump}" text-anchor="middle">{pump_rpm:.0f} rpm</text>

<!-- ACCUMULATOR -->
<rect x="{ACC_X}" y="{ACC_Y}" width="{ACC_W}" height="{ACC_H}"
      fill="white" stroke="#334155" stroke-width="2"/>
<g clip-path="url(#cp-acc)">{acc_fill}</g>
<text x="{ACC_X + ACC_W // 2}" y="{ACC_Y - 14}"
      font-family="IBM Plex Sans,sans-serif" font-size="14" font-weight="600"
      fill="#334155" text-anchor="middle">Accumulator</text>

<!-- PRESSURE label — centred on hot leg pipe -->
<rect x="{HL_MID_X - 62}" y="{HL_MID_Y - 26}" width="124" height="48" rx="4"
      fill="#0d1117" stroke="#30363d" stroke-width="1" opacity="0.88"/>
<text x="{HL_MID_X}" y="{HL_MID_Y - 10}"
      font-family="IBM Plex Mono,monospace" font-size="14" fill="#8b949e"
      text-anchor="middle">PRESSURE</text>
<text x="{HL_MID_X}" y="{HL_MID_Y + 14}"
      font-family="IBM Plex Mono,monospace" font-size="20" font-weight="600"
      fill="#ffa657" text-anchor="middle">{P_MPa:.2f} MPa</text>

<!-- SIMULATION TIME — upper left, below top of pressurizer -->
<rect x="10" y="{PRZ_Y + 10}" width="90" height="48" rx="4"
      fill="#0d1117" stroke="#30363d" stroke-width="1" opacity="0.88"/>
<text x="55" y="{PRZ_Y + 26}"
      font-family="IBM Plex Mono,monospace" font-size="14" fill="#8b949e"
      text-anchor="middle">SIM TIME</text>
<text x="55" y="{PRZ_Y + 50}"
      font-family="IBM Plex Mono,monospace" font-size="20" font-weight="600"
      fill="#e8530a" text-anchor="middle">{t_sim:.1f} s</text>

<!-- CORE POWER badge — directly below the time badge -->
<rect x="10" y="{PRZ_Y + 68}" width="90" height="48" rx="4"
      fill="#0d1117" stroke="#30363d" stroke-width="1" opacity="0.88"/>
<text x="55" y="{PRZ_Y + 84}"
      font-family="IBM Plex Mono,monospace" font-size="14" fill="#8b949e"
      text-anchor="middle">CORE PWR</text>
<text x="55" y="{PRZ_Y + 108}"
      font-family="IBM Plex Mono,monospace" font-size="20" font-weight="600"
      fill="#3fb950" text-anchor="middle">{core_pwr:.1f} MW</text>

<!-- RCS TEMPERATURE badge — centred near the top of the reactor vessel -->
<rect x="{RV_X + RV_W // 2 - 62}" y="{RV_Y + 10}" width="124" height="48" rx="4"
      fill="#0d1117" stroke="#30363d" stroke-width="1" opacity="0.88"/>
<text x="{RV_X + RV_W // 2}" y="{RV_Y + 26}"
      font-family="IBM Plex Mono,monospace" font-size="14" fill="#8b949e"
      text-anchor="middle">RCS TEMP</text>
<text x="{RV_X + RV_W // 2}" y="{RV_Y + 50}"
      font-family="IBM Plex Mono,monospace" font-size="20" font-weight="600"
      fill="#58a6ff" text-anchor="middle">{T_hot_C:.1f} °C</text>

<!-- FUEL CLAD TEMPERATURE — centred at the bottom of the reactor vessel -->
<rect x="{RV_X + RV_W // 2 - 62}" y="{RV_BOT - 58}" width="124" height="48" rx="4"
      fill="#0d1117" stroke="#30363d" stroke-width="1" opacity="0.88"/>
<text x="{RV_X + RV_W // 2}" y="{RV_BOT - 42}"
      font-family="IBM Plex Mono,monospace" font-size="14" fill="#8b949e"
      text-anchor="middle">FUEL CLAD T</text>
<text x="{RV_X + RV_W // 2}" y="{RV_BOT - 18}"
      font-family="IBM Plex Mono,monospace" font-size="20" font-weight="600"
      fill="#58a6ff" text-anchor="middle">{T_clad_C:.1f} °C</text>

</svg>"""

# ── Render ────────────────────────────────────────────────────────────────────
case_label = file.replace("_out.csv", "")
st.markdown(f"## 🏭 FLARE Plant Analyzer — `{case_label}`")

# Detect iOS Safari server-side via User-Agent.
# On iOS, ALL browsers (Chrome, Firefox, Edge) use WebKit and share the same
# data:/blob: iframe restriction, so we check for "iPhone" or "iPad" + "Safari"
# but exclude cases where it's genuinely desktop Safari (which works fine).
html_page = f"""<!DOCTYPE html><html><head><meta charset="utf-8"/>
<style>body{{margin:0;padding:0;background:#f8f9fb;overflow-x:auto;overflow-y:hidden;}}</style>
</head><body>{svg}</body></html>"""

b64      = base64.b64encode(html_page.encode("utf-8")).decode("utf-8")
iframe_h = int(758 * zoom) + 10

st.markdown(
    f'<iframe src="data:text/html;base64,{b64}" '
    f'width="100%" height="{iframe_h}" '
    f'style="border:none;display:block;" scrolling="auto"></iframe>',
    unsafe_allow_html=True,
)

# ── Variable table in sidebar (placed here so row is already defined) ─────────
with st.sidebar:
    st.divider()
    st.markdown("**Variables — current timestep**")
    st.dataframe(
        row.to_frame("Value").style.format("{:.5g}"),
        width="stretch",
        height=350,
    )

# ── Playback ──────────────────────────────────────────────────────────────────
if st.session_state.playing:
    if st.session_state.step < max_step:
        time.sleep(refresh_ms / 1000.0)
        st.session_state.step = min(st.session_state.step + skip, max_step)
        st.rerun()
    else:
        st.session_state.playing = False
