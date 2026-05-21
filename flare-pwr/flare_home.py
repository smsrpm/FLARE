"""
flare_home.py  —  FLARE launcher
Run with:  streamlit run flare_home.py
"""

import warnings
import logging
import asyncio

# ── Quiet benign Streamlit/Tornado websocket disconnect noise ────────────────
# When a browser tab is closed, refreshed, or temporarily disconnected while
# Streamlit is sending an update, Tornado may log WebSocketClosedError /
# StreamClosedError tracebacks. These do not indicate a FLARE calculation
# failure. Suppress only that specific noise; leave all other exceptions visible.
class _FLAREWebSocketDisconnectFilter(logging.Filter):
    _BENIGN_EXC_NAMES = {"WebSocketClosedError", "StreamClosedError"}
    _BENIGN_TEXT = (
        "WebSocketClosedError",
        "StreamClosedError",
        "Stream is closed",
        "keepalive ping failed",
    )

    def filter(self, record):
        try:
            logger_name = getattr(record, "name", "")
            msg = record.getMessage()

            if record.exc_info and record.exc_info[1] is not None:
                exc_name = record.exc_info[1].__class__.__name__
                if exc_name in self._BENIGN_EXC_NAMES:
                    return False
                # websockets can log an AssertionError during keepalive cleanup
                # after the browser/ngrok endpoint has already disconnected.
                if logger_name.startswith("websockets") and exc_name == "AssertionError":
                    return False

            if any(token in msg for token in self._BENIGN_TEXT):
                return False
        except Exception:
            pass
        return True


def _install_flare_log_filter():
    flt = _FLAREWebSocketDisconnectFilter()
    for name in ("asyncio", "tornado", "tornado.application", "tornado.general",
                 "tornado.access", "streamlit", "streamlit.runtime",
                 "websockets", "websockets.server", "websockets.client",
                 "websockets.legacy", "websockets.legacy.protocol"):
        lg = logging.getLogger(name)
        lg.addFilter(flt)
    root = logging.getLogger()
    root.addFilter(flt)
    for handler in root.handlers:
        handler.addFilter(flt)

    # Best effort: if this script thread has an event loop, give it the same
    # treatment. The Streamlit server loop may be separate, so logging filters
    # above remain the primary control.
    try:
        loop = asyncio.get_event_loop()
        default_handler = loop.default_exception_handler

        def _quiet_loop_exception_handler(loop, context):
            exc = context.get("exception")
            if exc is not None and exc.__class__.__name__ in flt._BENIGN_EXC_NAMES:
                return
            if exc is not None and exc.__class__.__name__ == "AssertionError":
                msg = str(context.get("message", ""))
                if "keepalive" in msg.lower() or "websocket" in msg.lower():
                    return
            msg = str(context.get("message", ""))
            if any(token in msg for token in flt._BENIGN_TEXT):
                return
            default_handler(context)

        loop.set_exception_handler(_quiet_loop_exception_handler)
    except Exception:
        pass


_install_flare_log_filter()

import streamlit as st
from pathlib import Path
import sys
import json
import requests

WORK_DIR = Path(__file__).parent
if str(WORK_DIR) not in sys.path:
    sys.path.insert(0, str(WORK_DIR))


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

# ── API key / config helpers ──────────────────────────────────────────────────
def _read_config(key):
    """Read a key=value entry from flare_config.txt.

    This parser is intentionally forgiving: it accepts whitespace around the
    equals sign, ignores blank/comment lines, and compares keys
    case-insensitively.
    """
    cfg = _runtime_file("flare_config.txt")
    if not cfg.exists():
        return None
    try:
        for line in cfg.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip().lower() == key.lower():
                return v.strip().strip('"').strip("'")
    except Exception:
        return None
    return None


def _write_config_value(key, value):
    """Create/update a key=value entry in flare_config.txt, preserving other lines."""
    cfg = _runtime_file("flare_config.txt")
    lines = []
    if cfg.exists():
        try:
            lines = cfg.read_text(encoding="utf-8").splitlines()
        except Exception:
            lines = []

    out = []
    replaced = False
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            k, _ = line.split("=", 1)
            if k.strip().lower() == key.lower():
                out.append(f'{key} = "{value}"')
                replaced = True
                continue
        out.append(line)
    if not replaced:
        if out and out[-1].strip():
            out.append("")
        out.append(f'{key} = "{value}"')
    cfg.write_text("\n".join(out) + "\n", encoding="utf-8")


def load_api_key():
    """Load Anthropic API key from flare_config.txt or the environment."""
    import os as _os
    return _read_config("ANTHROPIC_API_KEY") or _os.environ.get("ANTHROPIC_API_KEY")


def load_model():
    """Read ANTHROPIC_MODEL from flare_config.txt; fall back to claude-sonnet-4-5."""
    return _read_config("ANTHROPIC_MODEL") or "claude-sonnet-4-5"

_ANTHROPIC_MODEL = load_model()

st.set_page_config(
    page_title="FLARE", page_icon="🔥",
    layout="wide", initial_sidebar_state="expanded",
)

if "page" not in st.session_state:
    st.session_state.page = "home"

# Sync page from URL
if "page" in st.query_params:
    st.session_state.page = st.query_params["page"]


# ── Routing ──────────────────────────────────────────────
if st.session_state.page != "home":
    import streamlit as _st
    _st.set_page_config = lambda *a, **kw: None
    page = st.session_state.page
    if page == "simulator":
        target = "flare_ui.py"
    elif page == "ua":
        target = "flare_ua.py"
    elif page == "editor":
        target = "flare_model_editor.py"
    elif page == "analyzer":
        target = "flare_analyzer.py"
    elif page == "risk":
        target = "flare_risk.py"
    else:
        target = None

    if target:
        _globals = {
            "__file__": str(WORK_DIR / target),
            "FLARE_WORK_DIR": str(WORK_DIR),
        }
        # On Windows, Streamlit may try to write to '.' (cwd); ensure cwd
        # is the FLARE folder where the user has write access.
        import os as _os
        _prev_cwd = _os.getcwd()
        _target_path = WORK_DIR / target
        if not _target_path.exists():
            st.error(
                f"**{target}** was not found in the FLARE folder.\n\n"
                f"Expected location: `{_target_path}`\n\n"
                "This tool may not yet be installed. Please check your FLARE installation."
            )
            if st.button("← Back to Home", key="back_home_missing"):
                st.session_state.page = "home"
                st.rerun()
        else:
            try:
                _os.chdir(str(WORK_DIR))
                exec(open(_target_path, encoding="utf-8").read(), _globals)
            finally:
                _os.chdir(_prev_cwd)
    st.stop()


# ── Image data URIs (loaded from local icon subfolder) ──────
import base64

# Icons are intentionally loaded from an icon subfolder, not from the
# FLARE root directory.  Both spellings are supported for convenience on
# Windows/macOS while still preserving the requested folder organization.
ICON_DIRS = [WORK_DIR / "icons", WORK_DIR / "Icons"]

def _icon_path(filename):
    """Return the first matching icon path under icons/ or Icons/."""
    for _dir in ICON_DIRS:
        _p = _dir / filename
        if _p.exists():
            return _p
    return None

def load_image(path, fmt=None):
    """Return a data URI for an image path, or None if it is unavailable."""
    if path is None:
        return None
    try:
        _fmt = (fmt or path.suffix.lstrip(".") or "png").lower()
        if _fmt == "jpg":
            _fmt = "jpeg"
        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode()
        return f"data:image/{_fmt};base64,{encoded}"
    except FileNotFoundError:
        return None

def load_icon(filename):
    """Load a FLARE home-screen icon from icons/ or Icons/."""
    return load_image(_icon_path(filename))

IMG_SIM  = load_icon("icon_sim.jpg")
IMG_UA   = load_icon("icon_ua.jpg")
IMG_EDIT = load_icon("icon_editor.png")
IMG_PA   = load_icon("icon_analyzer.png")
IMG_TM   = load_icon("icon_theory_manual.png")
IMG_UM   = load_icon("icon_user_manual.png")
IMG_RISK = load_icon("icon_risk.png")

def _manual_path(filename):
    """Return the path to a manual stored in manuals/ or Manuals/.

    Manual downloads are intentionally loaded from a documentation subfolder
    rather than from the FLARE root directory.  Both lower- and upper-case
    folder names are supported for convenience on Windows and macOS/Linux.
    """
    for folder in ("manuals", "Manuals"):
        p = WORK_DIR / folder / filename
        if p.exists():
            return p
    return None

def load_docx(path):
    """Return manual docx bytes from manuals/ or Manuals/, or None."""
    p = _manual_path(path)
    if p is not None:
        return p.read_bytes()
    return None


# ── Home screen ───────────────────────────────────────────
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Share+Tech+Mono&display=swap');
:root {{
    --bg:#080c14; --border:#1c2d44; --accent:#e8530a;
    --glow:rgba(232,83,10,0.35); --btn-bg:#0d1a28; --btn-hover:#13253a;
}}
html,body,[class*="css"] {{ background:var(--bg) !important; margin:0 !important; padding:0 !important; }}
.stApp {{ background:var(--bg) !important; }}
#MainMenu,header,footer {{ visibility:hidden; }}
section[data-testid="stSidebar"] {{ display:none; }}
.block-container {{ padding-top:0.5rem !important; padding-bottom:0 !important; max-width:1400px !important; }}
.page-bg {{
    position:fixed; inset:0;
    background-image:
        linear-gradient(rgba(232,83,10,0.04) 1px,transparent 1px),
        linear-gradient(90deg,rgba(232,83,10,0.04) 1px,transparent 1px);
    background-size:48px 48px; pointer-events:none;
    animation:grid-drift 30s linear infinite; z-index:0;
}}
@keyframes grid-drift {{ 0%{{background-position:0 0}} 100%{{background-position:48px 48px}} }}
.page-glow {{
    position:fixed; top:30%; left:50%; transform:translate(-50%,-50%);
    width:600px; height:400px;
    background:radial-gradient(ellipse,rgba(232,83,10,0.12) 0%,transparent 70%);
    pointer-events:none; z-index:0;
}}
.hero {{
    display:flex; flex-direction:column; align-items:center;
    padding:1rem 1rem 2rem; position:relative; z-index:1;
    animation:fade-up 0.8s ease both;
}}
@keyframes fade-up {{ from{{opacity:0;transform:translateY(20px)}} to{{opacity:1;transform:translateY(0)}} }}
.flare-title {{
    font-family:'Bebas Neue',sans-serif;
    font-size:clamp(6rem,18vw,11rem);
    letter-spacing:0.12em; line-height:0.9; color:var(--accent);
    text-shadow:0 0 40px rgba(232,83,10,0.6),0 0 80px rgba(232,83,10,0.3),0 0 120px rgba(232,83,10,0.15);
    margin:0 0 0.2rem 0;
}}
.flare-sub {{
    font-family:'Share Tech Mono',monospace;
    font-size:clamp(1.1rem,3vw,1.6rem);
    letter-spacing:0.18em; text-transform:uppercase; line-height:1.6; text-align:center;
}}
.flare-sub .orange {{ color:#f97316; }}
.flare-sub .white  {{ color:#ffffff; }}
.divider {{
    width:160px; height:1px;
    background:linear-gradient(90deg,transparent,var(--accent),transparent);
    margin:1.2rem auto 2rem;
}}
.version-tag {{
    position:fixed; bottom:1rem; right:1.5rem;
    font-family:'Share Tech Mono',monospace; font-size:0.65rem;
    letter-spacing:0.1em; color:#5a7a99; opacity:0.5;
}}
/* FLARE Assistant chat */
.chat-wrap {{
    max-width:1200px; margin:1.5rem auto 0; position:relative; z-index:1;
}}
.chat-bubble-user {{
    background:#1c2d44; border-radius:12px 12px 4px 12px;
    padding:0.65rem 1rem; margin:0.5rem 0 0.5rem auto;
    max-width:80%; color:#e2e8f0;
    font-family:'Share Tech Mono',monospace; font-size:0.85rem;
    width:fit-content;
}}
.chat-bubble-assistant {{
    background:#0d1a28; border:1px solid #1c2d44;
    border-radius:12px 12px 12px 4px;
    padding:0.75rem 1rem; margin:0.5rem auto 0.5rem 0;
    max-width:85%; color:#cbd5e1;
    font-family:'IBM Plex Sans',sans-serif; font-size:0.88rem;
    line-height:1.6;
}}
.chat-label {{
    font-family:'Share Tech Mono',monospace; font-size:0.7rem;
    color:#e8530a; letter-spacing:0.1em; margin-bottom:0.5rem;
    text-transform:uppercase;
}}
/* High-contrast Streamlit buttons on the dark FLARE home page.
   Streamlit has changed button data-testid names across versions, so this
   deliberately targets all secondary button variants and the nested markdown
   containers/text. */
.stButton button,
div[data-testid="stButton"] button,
button[kind="secondary"],
button[data-testid="baseButton-secondary"],
button[data-testid="stBaseButton-secondary"] {{
    background:linear-gradient(180deg,#f97316 0%,#e8530a 100%) !important;
    background-color:#e8530a !important;
    color:#ffffff !important;
    -webkit-text-fill-color:#ffffff !important;
    border:1px solid #ffb26b !important;
    border-radius:6px !important;
    font-family:'Share Tech Mono',monospace !important;
    font-weight:800 !important;
    letter-spacing:0.04em !important;
    text-shadow:0 1px 1px rgba(0,0,0,0.55) !important;
    box-shadow:0 0 12px rgba(232,83,10,0.45), inset 0 1px 0 rgba(255,255,255,0.18) !important;
    opacity:1 !important;
}}
.stButton button *,
div[data-testid="stButton"] button *,
button[kind="secondary"] *,
button[data-testid="baseButton-secondary"] *,
button[data-testid="stBaseButton-secondary"] *,
.stButton button [data-testid="stMarkdownContainer"] p,
div[data-testid="stButton"] button [data-testid="stMarkdownContainer"] p {{
    color:#ffffff !important;
    -webkit-text-fill-color:#ffffff !important;
    opacity:1 !important;
}}
.stButton button:hover,
.stButton button:focus,
.stButton button:active,
div[data-testid="stButton"] button:hover,
div[data-testid="stButton"] button:focus,
div[data-testid="stButton"] button:active,
button[kind="secondary"]:hover,
button[kind="secondary"]:focus,
button[kind="secondary"]:active,
button[data-testid="baseButton-secondary"]:hover,
button[data-testid="baseButton-secondary"]:focus,
button[data-testid="baseButton-secondary"]:active,
button[data-testid="stBaseButton-secondary"]:hover,
button[data-testid="stBaseButton-secondary"]:focus,
button[data-testid="stBaseButton-secondary"]:active {{
    background:linear-gradient(180deg,#ffb15f 0%,#ff7a1a 55%,#e8530a 100%) !important;
    background-color:#ff7a1a !important;
    color:#ffffff !important;
    -webkit-text-fill-color:#ffffff !important;
    border-color:#ffe0bf !important;
    text-shadow:0 1px 1px rgba(0,0,0,0.65) !important;
    box-shadow:0 0 22px rgba(249,115,22,0.85), inset 0 1px 0 rgba(255,255,255,0.30) !important;
    opacity:1 !important;
}}
.stButton button:hover *,
.stButton button:focus *,
.stButton button:active *,
div[data-testid="stButton"] button:hover *,
div[data-testid="stButton"] button:focus *,
div[data-testid="stButton"] button:active *,
button[kind="secondary"]:hover *,
button[kind="secondary"]:focus *,
button[kind="secondary"]:active *,
button[data-testid="baseButton-secondary"]:hover *,
button[data-testid="baseButton-secondary"]:focus *,
button[data-testid="baseButton-secondary"]:active *,
button[data-testid="stBaseButton-secondary"]:hover *,
button[data-testid="stBaseButton-secondary"]:focus *,
button[data-testid="stBaseButton-secondary"]:active * {{
    color:#ffffff !important;
    -webkit-text-fill-color:#ffffff !important;
    opacity:1 !important;
}}
.stButton button:disabled,
div[data-testid="stButton"] button:disabled,
button[kind="secondary"]:disabled,
button[data-testid="baseButton-secondary"]:disabled,
button[data-testid="stBaseButton-secondary"]:disabled {{
    background:#374151 !important;
    background-color:#374151 !important;
    color:#f3f4f6 !important;
    -webkit-text-fill-color:#f3f4f6 !important;
    border-color:#9ca3af !important;
    opacity:1.0 !important;
    box-shadow:none !important;
}}
.stButton button:disabled *,
div[data-testid="stButton"] button:disabled *,
button[kind="secondary"]:disabled *,
button[data-testid="baseButton-secondary"]:disabled *,
button[data-testid="stBaseButton-secondary"]:disabled * {{
    color:#f3f4f6 !important;
    -webkit-text-fill-color:#f3f4f6 !important;
    opacity:1 !important;
}}

/* ── FLARE Assistant spinner ──────────────────────────────────────────────── */
div[data-testid="stSpinner"] {{
    background:#0d1a28 !important;
    border:1px solid #1c2d44 !important;
    border-radius:8px !important;
    padding:0.6rem 1rem !important;
}}
div[data-testid="stSpinner"] p,
div[data-testid="stSpinner"] span,
div[data-testid="stSpinner"] label {{
    color:#e8530a !important;
    -webkit-text-fill-color:#e8530a !important;
    font-size:0.95rem !important;
    font-weight:600 !important;
    letter-spacing:0.04em !important;
}}
div[data-testid="stSpinner"] svg {{
    stroke:#e8530a !important;
    color:#e8530a !important;
}}

/* ── Optional file-context expander ─────────────────────────────────────── */

/* Expander container and header — dark to match the page */
div[data-testid="stExpander"] {{
    background:#0d1a28 !important;
    border:1px solid #1c2d44 !important;
    border-radius:8px !important;
}}
div[data-testid="stExpander"] summary,
div[data-testid="stExpander"] > div:first-child {{
    background:#0d1a28 !important;
    color:#c8d8e8 !important;
    -webkit-text-fill-color:#c8d8e8 !important;
}}
div[data-testid="stExpander"] summary:hover {{
    background:#13253a !important;
}}
div[data-testid="stExpander"] summary svg {{
    fill:#c8d8e8 !important;
    stroke:#c8d8e8 !important;
}}

/* Widget labels inside expander — light text on dark header row */
div[data-testid="stExpander"] label,
div[data-testid="stExpander"] .stCaption,
div[data-testid="stExpander"] [data-testid="stCaptionContainer"] {{
    color:#c8d8e8 !important;
    -webkit-text-fill-color:#c8d8e8 !important;
}}
</style>
<div class="page-bg"></div>
<div class="page-glow"></div>
""", unsafe_allow_html=True)

st.markdown("""
<div class="hero">
  <div class="flare-title">FLARE</div>
  <div class="flare-sub">
    <span class="orange">Fast Licensing</span>
    <span class="white"> Accident Response Engine</span><br>
    <span class="white">by Robert P. Martin</span>
  </div>
  <div class="divider"></div>
</div>
<div class="version-tag">FLARE &middot; PWR/SMR Safety Analysis</div>
""", unsafe_allow_html=True)

# ── Clickable Image Buttons ─────────────────────────────────────────────
# Tooltips shown on hover for each tool icon
_TOOL_TIPS = {
    "simulator":  "PWR Simulator — run design-basis accident simulations",
    "ua":         "Uncertainty Analysis — Monte Carlo parameter sensitivity",
    "editor":     "Model Editor — create and edit FLARE input decks",
    "analyzer":   "Plant Analyzer — replay and compare simulation results",
    "risk":       "Risk Assessment — probabilistic safety screening",
}

def image_link(img_base64, page, label):
    if img_base64 is None:
        return ""
    tip = _TOOL_TIPS.get(page, label)
    return f"""
    <a href="?page={page}" target="_self" style="text-decoration:none;display:block;"
       title="{tip}">
        <img src="{img_base64}" style="
            width:100%;
            border-radius:12px;
            border:2px solid #1c2d44;
            transition:transform 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
        "
        onmouseover="this.style.transform='scale(1.02)';this.style.borderColor='#e8530a';this.style.boxShadow='0 0 28px rgba(232,83,10,0.45)';"
        onmouseout="this.style.transform='scale(1.0)';this.style.borderColor='#1c2d44';this.style.boxShadow='none';"
        alt="{label}"/>
    </a>
    """

# ── Home Screen Layout — five equal columns ───────────────────────────────
col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    if IMG_SIM:  st.markdown(image_link(IMG_SIM,  "simulator", "PWR Simulator"),      unsafe_allow_html=True)

with col2:
    if IMG_UA:   st.markdown(image_link(IMG_UA,   "ua",         "Uncertainty Analysis"), unsafe_allow_html=True)

with col3:
    if IMG_EDIT: st.markdown(image_link(IMG_EDIT, "editor",     "Model Editor"),       unsafe_allow_html=True)

with col4:
    if IMG_PA:   st.markdown(image_link(IMG_PA,   "analyzer",   "Plant Analyzer"),     unsafe_allow_html=True)

with col5:
    if IMG_RISK:
        st.markdown(image_link(IMG_RISK, "risk", "Risk Assessment"), unsafe_allow_html=True)
    else:
        # Text fallback if icon not yet available
        st.markdown(
            f'<a href="?page=risk" target="_self" style="text-decoration:none;display:block;">'
            f'<div style="border:2px solid #1c2d44;border-radius:12px;padding:1rem;'
            f'text-align:center;background:#0d1a28;color:#e8530a;'
            f'font-family:Share Tech Mono,monospace;font-size:0.9rem;cursor:pointer;'
            f'transition:border-color 0.15s ease,box-shadow 0.15s ease;"'
            f' onmouseover="this.style.borderColor=\'#e8530a\';'
            f'this.style.boxShadow=\'0 0 28px rgba(232,83,10,0.45)\';"'
            f' onmouseout="this.style.borderColor=\'#1c2d44\';'
            f'this.style.boxShadow=\'none\';">'
            f'⚛️<br><br>RISK<br>ASSESSMENT</div></a>',
            unsafe_allow_html=True,
        )

# ── FLARE Assistant ───────────────────────────────────────────────────────────
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []   # list of {"role": ..., "content": ...}

def _build_system_prompt():
    """Build system prompt, loading reference content from files at runtime."""
    _base = 'You are the FLARE Assistant — an expert on the FLARE (Fast Licensing \\\nAccident Response Engine) nuclear reactor safety analysis suite. FLARE is a Python/Streamlit \\\napplication for PWR and SMR design-basis accident analysis. It includes four tools: PWR \\\nSimulator (flare_ui.py), Uncertainty Analysis (flare_ua.py), Model Editor \\\n(flare_model_editor.py), and Plant Analyzer (flare_analyzer.py). The simulation engine is \\\nflare_sim.py. Input files are Excel workbooks named CaseName_in.xlsx.\n\nKey technical areas you can answer questions about:\n- Input file format: command block (key = value in column A), time-series table (columns \\\nA=Time, B=Structure Q, C=Decay Heat, D=Steam Generator, E=SI Flow, F=rho_ext)\n- All ~100 input parameters and their physical meaning (endtime, total_power, \\\npressure_kPa, diameter_break, core_flag, dnbr_flag, ria_flag, F_r, F_z, h_gap, \\\nk_sigma, nbt_* dose parameters, etc.)\n- Physical models: HEM two-phase thermal-hydraulics, ERM/Moody/Fauske critical flow, \\\npoint kinetics with Doppler and MTC feedback, Nordheim-Fuchs prompt supercritical, \\\nANS-1979 decay heat, Dittus-Boelter/Churchill-Chu HTC, Biasi/Zuber/Bowring CHF, \\\nBromley film boiling, Baker-Just oxidation, RG 1.183 source term, NOTBADTRAD dose screening\n- Four tools: how to run cases, interpret results, use the Model Editor, replay in the \\\nPlant Analyzer, run Monte Carlo uncertainty analysis\n- Installation, startup, ngrok remote access, virtual environment setup\n- Output files: _out.xlsx sheets (Sheet1, Source Term, Dose), _out.csv for Plant Analyzer\n- Common errors and troubleshooting\n\nAnswer in 1-2 paragraphs. Be specific and technical. Reference parameter names, \\\nequation numbers from the Theory Manual, or UI control names where helpful.\n\nIMPORTANT: If a question is not related to FLARE, its models, its input/output, or its \\\nuse, respond with exactly: "That question is not relevant to FLARE. I can only help with \\\nquestions about the FLARE safety analysis suite." Do not answer off-topic questions under \\\nany circumstances.\n\nREFERENCE SOURCES — use in priority order:\n1. FLARE Code Theory Manual Rev 2 and FLARE User\'s Manual Rev 2 — primary references \\\nfor all FLARE-specific questions (models, parameters, inputs, outputs, usage).\n2. "Design-Basis Accident Analysis Methods for Light-Water Nuclear Power Plants," \\\nR.P. Martin and C. Frepoli (Eds.), World Scientific Publishing, 2019 — background \\\nreference for DBA methodology, regulatory context, and underlying physics theory.\n\nWhen answering, draw on the manuals for FLARE-specific content and the book for \\\nbroader DBA context where relevant. After your answer, append a citation using \\\nthe appropriate format:\n\nFor FLARE manual references:\n  FLARE [Theory/User\'s] Manual Rev 2, [Chapter/Section] — [Title]\n\nFor book references:\n  R.P. Martin and C. Frepoli (Eds.), "Design-Basis Accident Analysis Methods for \\\nLight-Water Nuclear Power Plants," World Scientific Publishing, 2019, \\\nChapter X — Chapter Title, Section Y.Z — Section Title. \\\n(Chapter contributed by [Author(s)])\n\nThe chapter contributors are:\n  Ch.1  "Regulatory Status" — S.M. Bajorek\n  Ch.2  "The Safety Case" — S. Ergün, M. McCloskey, R.P. Martin\n  Ch.3  "Design-Basis Event Characterization" — R.P. Martin\n  Ch.4  "Analytical Requirements and Software" — R.P. Martin, D.L. Aumiller, C. Frepoli\n  Ch.5  "Verification and Validation" — K. Ohkawa, R.K. Ratnayake\n  Ch.6  "Similarity and Scaling" — J.N. Reyes Jr., C. Frepoli\n  Ch.7  "Deterministic and Best-Estimate Analysis Methods" — R.P. Martin, A. Petruzzi, C. Frepoli\n  Ch.8  "PWR LOCA/Non-LOCA Design-Basis Events" — F.X. Buschman, M.J. Meholic\n  Ch.9  "BWR LOCA/Non-LOCA Design-Basis Events" — D.R. Todd\n  Ch.10 "LWR Reactivity Transients and Accidents" — M. Avramova, K.N. Ivanov\n  Ch.11 "LWR Impact on Containment" — J.W. Lane, S.C. Franz\n  Ch.12 "Radiological Evaluations" — J.E. Metcalf, J.E. Chang\n\nYou may cite both a manual section and a book section if both are relevant. \\\nOnly cite these sources. If no section is clearly relevant, omit the citation. \\\nDo not cite sections you are not confident are relevant.'

    def _manuals_dir():
        """Return the Manuals/manuals folder if present, else None."""
        for _name in ("manuals", "Manuals"):
            _p = WORK_DIR / _name
            if _p.exists() and _p.is_dir():
                return _p
        return None

    def _load(fname):
        """Load FLARE Assistant corpus text from Manuals/manuals only."""
        _mdir = _manuals_dir()
        if _mdir is None:
            return f"[{fname} not found: Manuals/manuals folder not found]"
        p = _mdir / fname
        try:
            return p.read_text(encoding="utf-8") if p.exists() else f"[{fname} not found in {_mdir.name}/]"
        except Exception as e:
            return f"[{fname} load error from {_mdir.name}/: {e}]"

    return (
        _base
        + "\n\n=== FLARE CODE THEORY MANUAL Rev 2"
          " (primary reference for FLARE models and physics) ===\n\n"
        + _load("flare_theory_manual.txt")
        + "\n\n=== FLARE USER'S MANUAL Rev 2"
          " (primary reference for FLARE inputs, outputs and usage) ===\n\n"
        + _load("flare_users_manual.txt")
        + "\n\n=== DBA BOOK CONTENT"
          " (background reference — do not reproduce verbatim) ===\n\n"
        + _load("flare_dba_book.txt")
    )

_SYSTEM_PROMPT = _build_system_prompt()

def call_claude(history, api_key="", file_context=""):
    """Call the Anthropic API with the full conversation history."""
    if not api_key:
        return ("⚠️  No API key. Enter one above or add `ANTHROPIC_API_KEY = sk-ant-...` "
                "to runtime/flare_config.txt (or Runtime/flare_config.txt) in the FLARE folder.")
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key":         api_key,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            json={
                "model":      _ANTHROPIC_MODEL,
                "max_tokens": 1024,
                "system":     _SYSTEM_PROMPT,
                "messages":   _augment_history_with_file_context(history, file_context),
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"]
    except requests.exceptions.Timeout:
        return "⚠️  Request timed out. Please try again."
    except Exception as e:
        return f"⚠️  API error: {e}"

# ── Manual icons — second row, centred ───────────────────────────────────
# Each icon is a plain <a download> link wrapping the image so the entire
# image is the click target — no separate button needed.
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

def manual_icon_html(img_b64, docx_name, label):
    """Return HTML for a clickable icon that downloads a docx file."""
    docx_bytes = load_docx(docx_name)
    img_src = img_b64 or ""
    if docx_bytes and img_b64:
        b64_doc = base64.b64encode(docx_bytes).decode()
        href = f"data:{DOCX_MIME};base64,{b64_doc}"
        return (
            f'<a href="{href}" download="{docx_name}" target="_self"'
            f' style="text-decoration:none;display:block;">'
            f'<img src="{img_src}" alt="{label}" style="'
            f'width:100%;display:block;border-radius:12px;'
            f'border:2px solid #1c2d44;cursor:pointer;'
            f'transition:transform 0.15s ease,border-color 0.15s ease,box-shadow 0.15s ease;"'
            f' onmouseover="this.style.transform=\'scale(1.02)\';'
            f'this.style.borderColor=\'#e8530a\';'
            f'this.style.boxShadow=\'0 0 28px rgba(232,83,10,0.45)\';"'
            f' onmouseout="this.style.transform=\'scale(1.0)\';'
            f'this.style.borderColor=\'#1c2d44\';'
            f'this.style.boxShadow=\'none\';"'
            f'/></a>'
        )
    elif img_b64:
        return (
            f'<img src="{img_src}" alt="{label}" style="'
            f'width:100%;display:block;border-radius:12px;'
            f'border:2px solid #1c2d44;opacity:0.4;"/>'
            f'<p style="color:#5a7a99;font-size:0.75rem;margin-top:0.3rem;">'
            f'{docx_name} not found in manuals/ or Manuals/.</p>'
        )
    return ""

st.markdown("<div style='margin-top:1.2rem'></div>", unsafe_allow_html=True)
_, mcol1, mcol2, _ = st.columns([3, 1, 1, 3])

with mcol1:
    st.markdown(
        manual_icon_html(IMG_TM, "FLARE_Code_Theory_Manual.docx", "Theory Manual"),
        unsafe_allow_html=True,
    )

with mcol2:
    st.markdown(
        manual_icon_html(IMG_UM, "FLARE_Users_Manual.docx", "User's Manual"),
        unsafe_allow_html=True,
    )


# ── Optional FLARE file context for Assistant ────────────────────────────────
def _summarize_flare_xlsx_context(file_bytes, file_name):
    """Return a compact technical summary of a FLARE input workbook."""
    try:
        from io import BytesIO
        from openpyxl import load_workbook
        import re as _re

        wb = load_workbook(BytesIO(file_bytes), read_only=True, data_only=True)
        ws = wb.active
        ws_title = ws.title
        rows = list(ws.iter_rows(values_only=True))
        wb.close()

        # Command block: rows in column A before the time table / first numeric.
        cmd_lines = []
        time_row_idx = None
        for i, row in enumerate(rows, start=1):
            v = row[0] if row else None
            if isinstance(v, str) and v.strip().lower().startswith("time"):
                time_row_idx = i
                break
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                time_row_idx = i
                break
            if isinstance(v, str) and v.strip():
                cmd_lines.append(v.strip())

        params = []
        for line in cmd_lines:
            if line.lstrip().startswith("#"):
                continue
            m = _re.match(r"^\s*([A-Za-z_]\w*)\s*=\s*(.+?)\s*(?:#.*)?$", line)
            if m:
                params.append((m.group(1), m.group(2).strip()))

        important_names = {
            "endtime", "pressure_kPa", "temp_core_exit", "total_power",
            "diameter_break", "core_flag", "full_power_flag", "ria_flag",
            "sg_flag", "sg_table_flag", "source_term_model", "P_sec_kPa",
            "UA_sg_rated", "sg_nat_frac", "pump_flag", "pump_speed_rpm",
            "pump_orifice_area", "pump_trip_time", "PORV_setpoint_kPa",
            "PORV_reseat_kPa", "PORV_area_m2", "scram_on_PORV",
            "cvcs_kgs", "cvcs_boron_ppm", "cvcs_start_time_s",
            "hpsi_mdot_rated", "lpsi_mdot_rated", "acc_narea",
            "trip_P_hi_kPa", "trip_P_lo_kPa", "trip_power_frac",
            "trip_time_s", "trip_flow_frac", "trip_turbine_underspeed_frac",
            "coolant_activity_uci_g", "nbt_distance_eab_m",
            "nbt_containment_volume_ft3", "nbt_leak_rate_frac_per_day",
        }
        important = [(k, v) for k, v in params if k in important_names]
        other = [(k, v) for k, v in params if k not in important_names]

        lines = [
            f"Uploaded FLARE input workbook: {file_name}",
            f"Worksheet: {ws_title}",
            f"Command-block lines: {len(cmd_lines)}",
            f"Parsed parameter assignments: {len(params)}",
        ]
        if important:
            lines.append("Important parameters:")
            for k, v in important[:90]:
                lines.append(f"  - {k} = {v}")
        if other:
            lines.append("Other parsed parameters:")
            for k, v in other[:45]:
                lines.append(f"  - {k} = {v}")

        # Time table summary.  If the table header was found by first numeric row,
        # try to use the previous row as header when it looks like a Time row.
        if time_row_idx is not None:
            header_idx = time_row_idx
            if time_row_idx > 1:
                prev = rows[time_row_idx - 2]
                if prev and isinstance(prev[0], str) and "time" in prev[0].lower():
                    header_idx = time_row_idx - 1
            data_rows = rows[header_idx:] if header_idx < len(rows) else []
            numeric_rows = [
                r for r in data_rows
                if r and isinstance(r[0], (int, float)) and not isinstance(r[0], bool)
            ]
            if numeric_rows:
                times = [float(r[0]) for r in numeric_rows]
                lines.append(f"Time table rows: {len(numeric_rows)}")
                lines.append(f"Time range: {min(times):.6g} to {max(times):.6g} s")
                col_labels = [
                    "Time (s)", "Structure Q [MW]", "Decay Heat [MW]",
                    "SG Q [MW]", "CVCS/SI Flow [kg/s]", "rho_ext [pcm]"
                ]
                max_cols = min(6, max(len(r) for r in numeric_rows))
                for j in range(1, max_cols):
                    vals = []
                    for r in numeric_rows:
                        try:
                            vals.append(float(r[j] or 0.0))
                        except Exception:
                            pass
                    if vals and max(abs(x) for x in vals) > 0.0:
                        label = col_labels[j] if j < len(col_labels) else f"Column {j+1}"
                        lines.append(
                            f"Nonzero table signal: {label}; "
                            f"min={min(vals):.6g}, max={max(vals):.6g}"
                        )
        return "\n".join(lines)
    except Exception as e:
        return f"Uploaded workbook {file_name} could not be parsed: {e}"


def _summarize_flare_csv_context(file_bytes, file_name):
    """Return a compact summary of a FLARE output or diagnostic CSV file."""
    try:
        from io import BytesIO
        import pandas as _pd
        import numpy as _np

        df = _pd.read_csv(BytesIO(file_bytes))
        lines = [
            f"Uploaded FLARE CSV file: {file_name}",
            f"Rows: {len(df)}; columns: {len(df.columns)}",
            "Columns: " + ", ".join(str(c) for c in df.columns[:90]),
        ]

        if "Time (s)" in df.columns:
            t = _pd.to_numeric(df["Time (s)"], errors="coerce").dropna()
            if not t.empty:
                lines.append(f"Time range: {t.min():.6g} to {t.max():.6g} s")

        summary_specs = [
            ("RCS Pressure (kPa)", "minmax"),
            ("RCS Temperature (K)", "minmax"),
            ("RK Total Power (MW)", "max"),
            ("Core Power (MW)", "max"),
            ("SG Heat Removal (MW)", "max"),
            ("Pump Mass Flow (kg/s)", "minmax"),
            ("Break Flow (kg/s)", "max"),
            ("PORV Mass Flow (kg/s)", "max"),
            ("Accumulator Flow (kg/s)", "max"),
            ("HPSI Flow (kg/s)", "max"),
            ("LPSI Flow (kg/s)", "max"),
            ("SI Pumped Total (kg/s)", "max"),
            ("Vessel Level (m)", "minmax"),
            ("Accumulator Level (m)", "minmax"),
            ("DNBR", "min"),
            ("Clad Surface Temp (K)", "max"),
            ("Hot Pin Clad Temp (K)", "max"),
            ("Hot Pin Fuel Temp (K)", "max"),
            ("Rod Failures DNB (est.)", "max"),
            ("Rod Failures Gap (est.)", "max"),
            ("Rod Failures EarlyIV (est.)", "max"),
            ("Zr Oxidation Hot Pin ECR (%)", "max"),
            ("Zr Oxidation Mean Oxidizing Rod ECR (%)", "max"),
            ("H2 Generated (kg)", "max"),
            ("SG Flow-Capacity Limit (MW)", "minmax"),
            ("Core Power / SG Flow Capacity (-)", "max"),
            ("UA_sg_rated Used (MW/K)", "minmax"),
            ("UA_sg_dynamic Candidate (MW/K)", "minmax"),
        ]
        for col, mode in summary_specs:
            if col in df.columns:
                s = _pd.to_numeric(df[col], errors="coerce").replace(
                    [_np.inf, -_np.inf], _np.nan
                ).dropna()
                if s.empty:
                    lines.append(f"{col}: all values are blank/NaN")
                    continue
                if mode == "max":
                    idx = s.idxmax()
                    ttxt = (
                        f" at t={float(df.loc[idx, 'Time (s)']):.6g} s"
                        if "Time (s)" in df.columns else ""
                    )
                    lines.append(f"{col}: max={s.max():.6g}{ttxt}; final={s.iloc[-1]:.6g}")
                elif mode == "min":
                    idx = s.idxmin()
                    ttxt = (
                        f" at t={float(df.loc[idx, 'Time (s)']):.6g} s"
                        if "Time (s)" in df.columns else ""
                    )
                    lines.append(f"{col}: min={s.min():.6g}{ttxt}; final={s.iloc[-1]:.6g}")
                else:
                    lines.append(
                        f"{col}: initial={s.iloc[0]:.6g}; min={s.min():.6g}; "
                        f"max={s.max():.6g}; final={s.iloc[-1]:.6g}"
                    )

        for col in [
            "Break Flow (kg/s)", "PORV Mass Flow (kg/s)", "Accumulator Flow (kg/s)",
            "HPSI Flow (kg/s)", "LPSI Flow (kg/s)", "SI Pumped Total (kg/s)"
        ]:
            if col in df.columns and "Time (s)" in df.columns:
                s = _pd.to_numeric(df[col], errors="coerce").fillna(0.0)
                mask = s.abs() > 1e-6
                if bool(mask.any()):
                    lines.append(
                        f"{col} first nonzero at "
                        f"t={float(df.loc[mask, 'Time (s)'].iloc[0]):.6g} s"
                    )

        return "\n".join(lines)
    except Exception as e:
        return f"Uploaded CSV {file_name} could not be parsed: {e}"


def _summarize_flare_text_context(text, source_name="pasted text"):
    """Return a compact summary of pasted FLARE command-block or CSV text."""
    import re as _re
    raw = str(text or "")
    lines = [f"User-supplied FLARE text context: {source_name}", f"Characters: {len(raw)}"]

    params = []
    for line in raw.splitlines():
        m = _re.match(r"^\s*([A-Za-z_]\w*)\s*=\s*(.+?)\s*(?:#.*)?$", line)
        if m:
            params.append((m.group(1), m.group(2).strip()))
    if params:
        lines.append(f"Parsed parameter assignments: {len(params)}")
        for k, v in params[:120]:
            lines.append(f"  - {k} = {v}")

    excerpt = raw.strip()[:6000]
    if excerpt:
        lines.append("Text excerpt:")
        lines.append(excerpt)
    return "\n".join(lines)


def _build_uploaded_file_context(uploaded_file):
    """Classify and summarize uploaded FLARE input/output context."""
    if uploaded_file is None:
        return ""
    name = getattr(uploaded_file, "name", "uploaded file")
    suffix = Path(name).suffix.lower()
    data = uploaded_file.getvalue()
    if suffix == ".xlsx":
        return _summarize_flare_xlsx_context(data, name)
    if suffix == ".csv":
        return _summarize_flare_csv_context(data, name)
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        text = str(data[:6000])
    return _summarize_flare_text_context(text, name)


def _augment_history_with_file_context(history, file_context):
    """Attach current FLARE file context to the most recent user message."""
    if not file_context:
        return history
    msgs = [dict(m) for m in history]
    for i in range(len(msgs) - 1, -1, -1):
        if msgs[i].get("role") == "user":
            msgs[i]["content"] = (
                "USER-SUPPLIED FLARE FILE CONTEXT\n"
                "Use this context only to answer the user's current question. "
                "Do not treat it as part of the permanent manuals.\n\n"
                f"{file_context}\n\n"
                "USER QUESTION\n"
                f"{msgs[i].get('content', '')}"
            )
            return msgs
    return msgs


# Chat container
st.markdown("<div class='chat-wrap'>", unsafe_allow_html=True)
st.markdown(
    "<div class='chat-label'>⚛️  FLARE Assistant — ask a question about FLARE</div>",
    unsafe_allow_html=True,
)

# Render conversation history
for msg in st.session_state.chat_history:
    if msg["role"] == "user":
        st.markdown(
            f"<div class='chat-bubble-user'>{msg['content']}</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"<div class='chat-bubble-assistant'>{msg['content']}</div>",
            unsafe_allow_html=True,
        )

# ── API key state — rendered at bottom of page ────────────────────────────────
_cfg_key = load_api_key()   # from runtime/flare_config.txt or environment
if "user_api_key" not in st.session_state:
    # Populate from saved config/environment when available. The visible input
    # field is rendered at the bottom of the page.
    st.session_state.user_api_key = _cfg_key or ""

# Resolve active key for FAQ/send controls. The bottom API input updates this
# session state for subsequent reruns.
_active_key = st.session_state.user_api_key or _cfg_key or ""

# ── FAQ dropdown ──────────────────────────────────────────────────────────────
_FAQS = [
    "— Select a frequently asked question —",
    # FLARE tool usage
    "What is FLARE and what types of analyses does it support?",
    "How do I set up a new input case in FLARE?",
    "What is the structure of the FLARE input Excel file?",
    "How do I run a Large-Break LOCA case?",
    "How do I model a boron dilution event in FLARE?",
    "What does the core_flag parameter control?",
    "What is the difference between Core Power and RK Total Power in the output?",
    "How does FLARE calculate DNBR?",
    "How do I perform an uncertainty analysis in FLARE?",
    "What output files does FLARE produce?",
    # DBA methods (book-related)
    "What are the four Condition categories for design-basis events?",
    "What acceptance criteria apply to the PWR large-break LOCA?",
    "What is the Evaluation Model (EM) approach to safety analysis?",
    "What is the difference between deterministic and best-estimate plus uncertainty (BEPU) methods?",
    "How is two-phase critical flow modelled in PWR LOCA analysis?",
    "What reactivity feedback mechanisms are important during a PWR ATWS?",
    "How is peak cladding temperature calculated during a LOCA?",
    "What is the role of ECCS in mitigating a large-break LOCA?",
    "What is the single-failure criterion and how does it apply to safety analysis?",
    "How is decay heat modelled in design-basis accident analysis?",
]

if "faq_prev" not in st.session_state:
    st.session_state.faq_prev = _FAQS[0]

_faq_choice = st.selectbox(
    "Frequently asked questions",
    _FAQS,
    index=0,
    key="faq_dropdown",
    label_visibility="collapsed",
    help="Select a question — it will be submitted automatically",
)

# Submit the FAQ immediately when a new question is chosen
if (_faq_choice != _FAQS[0]
        and _faq_choice != st.session_state.faq_prev
        and _active_key
        and not st.session_state.get("chat_pending", False)):
    st.session_state.faq_prev = _faq_choice
    st.session_state.chat_history.append({"role": "user", "content": _faq_choice})
    with st.spinner("⚛️  FLARE Assistant is thinking…"):
        _faq_answer = call_claude(st.session_state.chat_history, api_key=_active_key, file_context=st.session_state.get('flare_file_context', ''))
    st.session_state.chat_history.append({"role": "assistant", "content": _faq_answer})
    st.rerun()


# ── Optional uploaded/pasted FLARE file context ───────────────────────────────
if "flare_context_upload_counter" not in st.session_state:
    st.session_state.flare_context_upload_counter = 0
if "flare_file_context" not in st.session_state:
    st.session_state.flare_file_context = ""

st.markdown(
    "<p style='color:#c8d8e8;font-size:0.85rem;margin-bottom:4px;'>"
    "Optional: attach a FLARE input workbook, output CSV, diagnostic CSV, or pasted "
    "command block so the Assistant can answer questions about that specific case.</p>",
    unsafe_allow_html=True,
)
with st.expander("Optional FLARE file context", expanded=False):
    _ctx_upload = st.file_uploader(
        "Upload FLARE input/output file",
        type=["xlsx", "csv", "txt"],
        key=f"flare_context_upload_{st.session_state.flare_context_upload_counter}",
        help=(
            "Drag and drop or browse for a FLARE *_in.xlsx input file, *_out.csv "
            "simulation output, *_diag.csv diagnostic file, or text export. "
            "The Assistant will use a compact technical summary of the file when "
            "answering the next question."
        ),
    )
    _pasted_ctx = st.text_area(
        "Or paste FLARE command-block / CSV text",
        height=150,
        key="flare_context_paste",
        help=(
            "Paste a command block, selected rows from an input deck, or CSV text. "
            "This is optional context for the Assistant; it does not change any FLARE files."
        ),
    )

    _ctx_parts = []
    if _ctx_upload is not None:
        _ctx_parts.append(_build_uploaded_file_context(_ctx_upload))
    if _pasted_ctx.strip():
        _ctx_parts.append(_summarize_flare_text_context(_pasted_ctx, "pasted FLARE text"))

    if _ctx_parts:
        st.session_state.flare_file_context = "\n\n---\n\n".join(_ctx_parts)
        st.markdown(
            '<div style="background:#d1e7dd;color:#0f5132;border:1px solid #badbcc;'
            'border-radius:0.375rem;padding:0.35rem 0.6rem;font-size:0.78rem;'
            'line-height:1.25;margin-top:0.25rem;">'
            'FLARE file context attached for the Assistant.</div>',
            unsafe_allow_html=True,
        )
        with st.expander("Preview parsed context", expanded=False):
            st.code(st.session_state.flare_file_context[:9000], language="text")
    elif st.session_state.flare_file_context:
        st.info("Using previously attached FLARE file context.")
        with st.expander("Preview parsed context", expanded=False):
            st.code(st.session_state.flare_file_context[:9000], language="text")
    else:
        st.caption("No file context attached.")

    if st.button("Clear attached file context", key="clear_flare_file_context"):
        st.session_state.flare_file_context = ""
        st.session_state.flare_context_upload_counter += 1
        st.rerun()


# Use a counter as the input key so we can reset it after submission
if "chat_input_counter" not in st.session_state:
    st.session_state.chat_input_counter = 0

# Input row
_qcol, _bcol = st.columns([10, 1])
with _qcol:
    user_input = st.text_input(
        label="flare_question",
        label_visibility="collapsed",
        placeholder="e.g., What is FLARE?",
        key=f"chat_input_{st.session_state.chat_input_counter}",
    )
with _bcol:
    send_btn = st.button("Ask", type="primary", key="chat_send",
                         disabled=not bool(_active_key))

# Clear history button
if st.session_state.chat_history:
    st.markdown("<div style='height:2.2rem;'></div>", unsafe_allow_html=True)
    if st.button("Clear conversation", key="chat_clear"):
        st.session_state.chat_history = []
        st.session_state.chat_input_counter += 1
        st.rerun()

st.markdown("</div>", unsafe_allow_html=True)

# Process submission — guard with a pending flag to prevent double-execution
if "chat_pending" not in st.session_state:
    st.session_state.chat_pending = False

if send_btn and user_input.strip() and not st.session_state.chat_pending:
    st.session_state.chat_pending = True
    q = user_input.strip()
    st.session_state.chat_history.append({"role": "user", "content": q})
    st.session_state.chat_input_counter += 1   # clears the text input
    with st.spinner("⚛️  FLARE Assistant is thinking…"):
        answer = call_claude(st.session_state.chat_history, api_key=_active_key, file_context=st.session_state.get('flare_file_context', ''))
    st.session_state.chat_history.append({"role": "assistant", "content": answer})
    st.session_state.chat_pending = False
    st.rerun()

# ── API key field — final page object ────────────────────────────────────────
st.markdown("<div style='height:2.4rem;'></div>", unsafe_allow_html=True)
st.markdown(
    "<p style='color:#c8d8e8;font-size:0.9rem;margin-bottom:4px;font-weight:600;'>"
    "Anthropic API Key</p>",
    unsafe_allow_html=True,
)
_key_col, _save_col, _hint_col = st.columns([3, 1.2, 2])
with _key_col:
    _typed_key = st.text_input(
        "Anthropic API key",
        value=st.session_state.user_api_key,
        label_visibility="collapsed",
        type="password",
        placeholder="sk-ant-...  (leave blank to use runtime/flare_config.txt)",
        key="api_key_input",
        help=(
            "Enter your Anthropic API key for this session. Use Save to write it "
            "to runtime/flare_config.txt so the Simulator narrative can also use it."
        ),
    )
    if _typed_key:
        st.session_state.user_api_key = _typed_key
        # Make the key visible to routed pages in the same Streamlit process.
        import os as _os
        _os.environ["ANTHROPIC_API_KEY"] = _typed_key

with _save_col:
    _key_to_save = st.session_state.user_api_key.strip()
    if st.button("💾 Save", key="save_api_key_btn", width="stretch",
                 help="Save the entered key to runtime/flare_config.txt for all FLARE tools."):
        if not _key_to_save:
            st.warning("Enter an API key before saving.")
        else:
            try:
                _write_config_value("ANTHROPIC_API_KEY", _key_to_save)
                _cfg_key = _key_to_save
                import os as _os
                _os.environ["ANTHROPIC_API_KEY"] = _key_to_save
                st.markdown(
                    '<div style="background:#d1e7dd;color:#0f5132;border:1px solid #badbcc;'
                    'border-radius:0.375rem;padding:0.35rem 0.6rem;font-size:0.78rem;'
                    'line-height:1.25;margin-top:0.25rem;">'
                    'Saved API key to runtime/flare_config.txt</div>',
                    unsafe_allow_html=True,
                )
            except Exception as _se:
                st.error(f"Could not save API key: {_se}")

with _hint_col:
    _active_key_for_hint = st.session_state.user_api_key or _cfg_key or ""
    if _active_key_for_hint:
        # Show first 10 and last 4 chars so user can confirm it's the right key
        _k = _active_key_for_hint
        _preview = f"{_k[:10]}...{_k[-4:]}" if len(_k) > 14 else _k[:6] + "..."
        _src = "entered above"
        if _cfg_key and not st.session_state.user_api_key:
            _src = "runtime/flare_config.txt / environment"
        elif _cfg_key and st.session_state.user_api_key == _cfg_key:
            _src = "runtime/flare_config.txt"
        st.markdown(
            f"<p style='color:#7ddd8a;font-size:0.85rem;margin-top:8px;'>"
            f"✅ &nbsp;{_preview}<br>"
            f"<span style='color:#8ab4cc;font-size:0.78rem;'>from {_src}</span></p>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<p style='color:#f0a050;font-size:0.85rem;margin-top:8px;'>"
            "⚠️ &nbsp;No API key<br>"
            "<span style='color:#8ab4cc;font-size:0.78rem;'>Ask button disabled</span></p>",
            unsafe_allow_html=True,
        )

