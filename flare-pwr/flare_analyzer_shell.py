"""
flare_analyzer_shell.py  —  FLARE Plant Analyzer, multi-screen shell.

This module is the single entry point for the Plant Analyzer.  It draws a
folder-tab strip at the top of the main browser column and then executes
exactly one screen module per run:

    Tab 1  "Plant Replay"   ->  flare_analyzer.py
    Tab 2  "Dose Map"       ->  flare_population_map/flare_map.py

Design notes
------------
*   Neither screen module is modified.  Each is executed with its own
    ``__file__`` so every path anchor inside it (``APP_DIR``, ``ROOT``)
    resolves exactly as it does when that tool is run on its own.  All
    sidebar layouts, sliders, browser-side components, and playback
    controls are therefore untouched.

*   Only one screen executes per run.  ``st.tabs`` would execute both
    screens on every rerun and stack both sidebars, so tab selection is
    carried in the URL instead, matching the ``?page=`` idiom already used
    by flare_home.py.  Switching tabs costs one ordinary Streamlit rerun.

*   Existing query parameters are preserved across a tab switch, so the
    Dose Map browser-side interval, dose-range, and radius selections
    (which the map writes into the URL with ``history.replaceState``)
    survive a trip to the Plant Replay screen and back.

*   Runs both under flare_home.py routing (``?page=analyzer``) and on its
    own via ``streamlit run flare_analyzer_shell.py``.

Run with: streamlit run flare_analyzer_shell.py
"""

import os
import sys
from pathlib import Path
from types import ModuleType

import streamlit as st

# --------------------------------------------------------------------------
# Location of this shell and of the two screen modules.
# --------------------------------------------------------------------------
APP_DIR = Path(globals().get("FLARE_WORK_DIR") or Path(__file__).resolve().parent)

# flare_home.py injects FLARE_WORK_DIR into the exec globals.  Its absence
# means this shell is the Streamlit entry script.
ROUTED_FROM_HOME = "FLARE_WORK_DIR" in globals()

PLANT_MODULE = APP_DIR / "flare_analyzer.py"
POPMAP_DIR = APP_DIR / "flare_population_map"
POPMAP_MODULE = POPMAP_DIR / "flare_map.py"

TAB_QUERY_KEY = "atab"
DEFAULT_TAB = "plant"

SCREENS = {
    "plant": {
        "label": "Plant Replay",
        "module": PLANT_MODULE,
        "extra_path": None,
        "help": "Frame-by-frame plant diagram replay of a simulation output CSV.",
        "needs_sidebar_chrome": False,
    },
    "map": {
        "label": "Dose Map",
        "module": POPMAP_MODULE,
        "extra_path": POPMAP_DIR,
        "help": "Time-evolving population, airborne dose, and deposition footprint.",
        # flare_analyzer.py draws its own FLARE Home button and dark sidebar;
        # the Dose Map does not, so the shell supplies them.
        "needs_sidebar_chrome": True,
    },
}

# Session-state keys to carry across a tab switch. Empty by default: each
# screen already persists what matters (the Dose Map writes its settings to
# user_settings.json and its slider positions to the URL, both of which the
# tab links preserve), and resetting a screen's widgets on tab switch matches
# how FLARE Home already behaves when moving between tools.
#
# Only add keys belonging to widgets that allow session-state assignment.
# See _keep_session_state_alive() below for why this must not be a blanket
# sweep over st.session_state.
PRESERVE_KEYS: tuple[str, ...] = ()



# --------------------------------------------------------------------------
# Page configuration
# --------------------------------------------------------------------------
if not ROUTED_FROM_HOME:
    # Standalone launch: claim the page config before anything else renders.
    try:
        st.set_page_config(
            layout="wide",
            page_title="FLARE Plant Analyzer",
            page_icon="🔥",
            initial_sidebar_state="expanded",
        )
    except Exception:
        pass

# Both screen modules call st.set_page_config at module scope.  Only the
# first call in a Streamlit run is legal, so neutralize it before either
# module is executed.  flare_home.py already applies the same patch when it
# routes; repeating it here keeps standalone launch working identically.
st.set_page_config = lambda *args, **kwargs: None  # type: ignore[assignment]


# --------------------------------------------------------------------------
# Session-state retention
# --------------------------------------------------------------------------
def _keep_session_state_alive() -> None:
    """Re-assert selected session-state keys so they survive a tab switch.

    Streamlit discards widget state for widgets that were not drawn during a
    run, so a screen's selections reset when the other tab is shown. Writing a
    key back to itself moves it into user-set state and keeps it alive.

    This is deliberately limited to an explicit allow-list. A blanket sweep
    over every key is NOT safe: Streamlit forbids assigning values to the keys
    of st.button, st.download_button, st.file_uploader, st.form_submit_button,
    st.camera_input, and st.chat_input. Touching such a key raises
    StreamlitValueAssignmentNotAllowedError when the widget is next drawn --
    and not at the moment of assignment, so a try/except around the write does
    not help. The Dose Map's workbook uploader is exactly this case.

    Add a key here only after confirming it belongs to a widget that permits
    session-state assignment (selectbox, slider, checkbox, text/number input,
    radio, multiselect) and that a stale value cannot fall outside the
    widget's options on a later run.
    """
    for key in PRESERVE_KEYS:
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]


# --------------------------------------------------------------------------
# Tab selection
# --------------------------------------------------------------------------
def _current_tab() -> str:
    """Resolve the active screen from the URL, then from session state."""
    requested = None
    try:
        requested = st.query_params.get(TAB_QUERY_KEY)
    except Exception:
        requested = None
    if isinstance(requested, (list, tuple)):
        requested = requested[0] if requested else None

    if requested in SCREENS:
        st.session_state["flare_analyzer_tab"] = requested
        return requested

    remembered = st.session_state.get("flare_analyzer_tab")
    if remembered in SCREENS:
        return remembered

    st.session_state["flare_analyzer_tab"] = DEFAULT_TAB
    return DEFAULT_TAB


def _tab_href(tab_key: str) -> str:
    """Build a tab link that preserves every other query parameter."""
    params = {}
    try:
        for key in st.query_params.keys():
            value = st.query_params.get(key)
            if isinstance(value, (list, tuple)):
                value = value[0] if value else ""
            params[key] = "" if value is None else str(value)
    except Exception:
        params = {}

    if ROUTED_FROM_HOME:
        # Keep flare_home.py's router pointed at the Plant Analyzer.
        params["page"] = "analyzer"
    params[TAB_QUERY_KEY] = tab_key

    from urllib.parse import urlencode

    return "?" + urlencode(params)


active_tab = _current_tab()
_keep_session_state_alive()


# --------------------------------------------------------------------------
# Folder-tab strip
# --------------------------------------------------------------------------
st.markdown(
    """
<style>
/* Folder tabs for the Plant Analyzer screens.  Scoped class names so the
   stylesheet each screen module injects afterwards cannot disturb them. */
.flare-tabbar{
    position:relative;
    display:flex; align-items:flex-end; gap:0.28rem;
    margin:0 0 1.35rem 0; padding:0 0 0 0.6rem;
    /* Inherit the app's own font so the strip matches the screen it sits
       above, rather than imposing a second typeface of its own. */
    font-family:inherit;
}
/* The rail the tabs sit on: a hairline that thickens into the FLARE accent,
   so the active tab reads as part of the sheet below it. */
.flare-tabbar::after{
    content:""; position:absolute; left:0; right:0; bottom:0; height:3px;
    background:linear-gradient(90deg,#e8530a 0%,#f97316 42%,rgba(232,83,10,.18) 100%);
    border-radius:3px 3px 0 0;
}
.flare-tab{
    position:relative; z-index:1; top:1px;
    display:inline-flex; align-items:center;
    padding:0.55rem 1.5rem 0.5rem 1.5rem;
    text-decoration:none !important;
    font-size:0.94rem; font-weight:600; letter-spacing:0.012em;
    color:#5b6472 !important;
    background:linear-gradient(180deg,#eef1f6 0%,#dfe4ec 100%);
    border:1px solid #ccd3de; border-bottom:none;
    border-radius:10px 10px 0 0;
    box-shadow:inset 0 1px 0 rgba(255,255,255,.85);
    transition:background 140ms ease, color 140ms ease,
               box-shadow 140ms ease, transform 140ms ease;
}
.flare-tab:not(:first-child){ margin-left:-0.35rem; }
.flare-tab:hover{
    background:linear-gradient(180deg,#fdf1e9 0%,#f7ddcb 100%);
    color:#a8390a !important; transform:translateY(-1px);
    box-shadow:inset 0 1px 0 rgba(255,255,255,.9), 0 -3px 12px rgba(232,83,10,.18); }

.flare-tab-active{
    z-index:3; top:0;
    padding:0.68rem 1.7rem 0.62rem 1.7rem;
    color:#b8380a !important;
    background:linear-gradient(180deg,#ffffff 0%,#ffffff 62%,#fff6f0 100%);
    border-color:#e8530a; border-bottom:3px solid #ffffff;
    margin-bottom:-3px;
    box-shadow:0 -5px 16px rgba(232,83,10,.16), inset 0 2px 0 #e8530a;
    cursor:default; transform:none; }
.flare-tab-active:hover{
    background:linear-gradient(180deg,#ffffff 0%,#ffffff 62%,#fff6f0 100%);
    color:#b8380a !important; transform:none;
    box-shadow:0 -5px 16px rgba(232,83,10,.16), inset 0 2px 0 #e8530a; }

.flare-tab-missing{
    background:linear-gradient(180deg,#f4f5f7 0%,#e9ebef 100%);
    color:#a4abb6 !important; border-style:dashed; cursor:not-allowed; }
.flare-tab-missing:hover{
    background:linear-gradient(180deg,#f4f5f7 0%,#e9ebef 100%);
    color:#a4abb6 !important; transform:none; box-shadow:none; }

/* Tighten only the strip's own spacing.  No global block-container or
   sidebar padding rule is applied, so both screens keep their own layout. */
div[data-testid="stMarkdownContainer"]:has(> .flare-tabbar){ margin-top:-0.9rem; }
</style>
""",
    unsafe_allow_html=True,
)

_tab_html = ['<div class="flare-tabbar">']
for key, screen in SCREENS.items():
    if not screen["module"].exists():
        _tab_html.append(
            f'<span class="flare-tab flare-tab-missing" title="Not installed: '
            f'{screen["module"].name}">{screen["label"]}</span>'
        )
    elif key == active_tab:
        _tab_html.append(
            f'<span class="flare-tab flare-tab-active" title="{screen["help"]}">'
            f'{screen["label"]}</span>'
        )
    else:
        _tab_html.append(
            f'<a class="flare-tab" href="{_tab_href(key)}" target="_self" '
            f'title="{screen["help"]}">{screen["label"]}</a>'
        )
# The FLARE Home button lives in each screen's sidebar, so the tab strip
# stays purely a screen selector.
_tab_html.append("</div>")
st.markdown("".join(_tab_html), unsafe_allow_html=True)


def _load_buddy_b64() -> str | None:
    """Return the FLARE Buddy icon as a data URI, or None if it is absent."""
    import base64

    for icon_dir in (APP_DIR / "icons", APP_DIR / "Icons"):
        icon = icon_dir / "FLAREBUDDY.png"
        if icon.exists():
            try:
                return "data:image/png;base64," + base64.b64encode(
                    icon.read_bytes()
                ).decode()
            except Exception:
                return None
    return None


def _apply_dose_map_sidebar_chrome() -> None:
    """Give the Dose Map the standard FLARE sidebar: dark panel, light text,
    and a FLARE Home button with FLARE Buddy at the top.

    The Dose Map screen is rendered unmodified, so this styling is injected
    here rather than in flare_map.py. Only the Dose Map needs it: the Plant
    Replay screen already carries the same chrome in flare_analyzer.py, and
    adding it twice would draw two Home buttons.

    Colours and selectors are taken from flare_analyzer.py so the two screens
    match exactly. flare_map.py's own stylesheet touches the sidebar only
    inside an @media print block, so nothing here is overridden.
    """
    st.markdown(
        """
<style>
:root{ --sidebar:#1a1f2e; --dark-surface:#0d1117; --dark-border:#30363d;
       --sid-text:#e6edf3; --sid-muted:#8b949e; }

section[data-testid="stSidebar"]{
    background:var(--sidebar) !important; border-right:1px solid var(--dark-border); }

/* Text, labels, and headings */
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] li,
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3,
section[data-testid="stSidebar"] h4{ color:var(--sid-text) !important; }
section[data-testid="stSidebar"] .stCaption,
section[data-testid="stSidebar"] .stCaption p,
section[data-testid="stSidebar"] small{ color:var(--sid-muted) !important; }

/* Select boxes and their dropdowns */
section[data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"],
section[data-testid="stSidebar"] .stMultiSelect div[data-baseweb="select"]{
    background:var(--dark-surface); border:1px solid var(--dark-border); border-radius:6px; }
section[data-testid="stSidebar"] .stSelectbox span,
section[data-testid="stSidebar"] .stMultiSelect span{ color:#fff !important; }
div[role="listbox"]{ background:var(--dark-surface) !important; }
div[role="option"] { color:#fff !important; }
div[role="option"]:hover{ background:#21262d !important; }

/* Buttons */
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

/* Widgets the Dose Map uses that the Plant Replay sidebar does not:
   file uploader, number inputs, radio groups, and sliders. Without these
   the controls keep dark-on-dark text and become unreadable. */
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"]{
    background:var(--dark-surface) !important; border:1px dashed var(--dark-border) !important; }
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] span,
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] div,
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] small{
    color:var(--sid-text) !important; }
section[data-testid="stSidebar"] [data-testid="stFileUploaderFile"]{ color:var(--sid-text) !important; }
section[data-testid="stSidebar"] input{
    background:var(--dark-surface) !important; color:var(--sid-text) !important;
    border:1px solid var(--dark-border) !important; }
section[data-testid="stSidebar"] .stNumberInput div[data-baseweb="input"]{
    background:var(--dark-surface) !important; border:1px solid var(--dark-border) !important; }
section[data-testid="stSidebar"] [data-testid="stExpander"] summary,
section[data-testid="stSidebar"] [data-testid="stExpander"] p{ color:var(--sid-text) !important; }
section[data-testid="stSidebar"] [data-testid="stSliderTickBarMin"],
section[data-testid="stSidebar"] [data-testid="stSliderTickBarMax"],
section[data-testid="stSidebar"] [data-testid="stThumbValue"]{ color:var(--sid-muted) !important; }

/* Tooltips and spacing, matching Plant Replay */
section[data-testid="stSidebar"] .stTooltipHoverTarget svg.icon{ stroke:#f97316 !important; }
section[data-testid="stSidebar"] .stTooltipHoverTarget:hover svg.icon{ stroke:#fff !important; }
section[data-testid="stSidebar"] .block-container { padding-top:0.5rem !important; }
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div { gap:0.15rem !important; }
section[data-testid="stSidebar"] hr { margin:0.4rem 0 !important; }
</style>
""",
        unsafe_allow_html=True,
    )

    buddy_b64 = _load_buddy_b64()
    buddy_html = (
        f"<img src='{buddy_b64}' style='height:4.5rem;width:auto;"
        "object-fit:contain;flex-shrink:0;'/>"
        if buddy_b64
        else "🔥"
    )

    with st.sidebar:
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


# --------------------------------------------------------------------------
# Screen execution
# --------------------------------------------------------------------------
def _offer_national_database_build() -> None:
    """Add a build button to the foot of the Dose Map sidebar when the national
    Census population database is absent.

    Without that database the Dose Map falls back to synthetic demonstration
    data, which is easy to miss. The button launches
    Build_National_Population_Database.bat in its own console window, because
    the build downloads Census source files and runs far longer than a
    Streamlit callback may block for.
    """
    national_db = POPMAP_DIR / "data" / "population_2020_national.sqlite"
    builder = POPMAP_DIR / "Build_National_Population_Database.bat"

    if national_db.exists() or not builder.exists():
        return

    with st.sidebar:
        st.divider()
        st.caption(
            "National Census population database not installed - the map is "
            "using synthetic demonstration data."
        )
        if st.button(
            "Build national database",
            key="flare_build_national_db",
            use_container_width=True,
            help=(
                "Download the official 2020 Census tabulation-block files and "
                "build data\\population_2020_national.sqlite. This opens a "
                "separate console window, takes a long time, and is resumable. "
                "Reload the Dose Map when it finishes."
            ),
        ):
            if os.name != "nt":
                st.error(
                    "The builder is a Windows batch file. Run it manually:\n\n"
                    f"`{builder}`"
                )
            else:
                try:
                    import subprocess

                    subprocess.Popen(
                        ["cmd", "/c", "start", "", str(builder)],
                        cwd=str(POPMAP_DIR),
                        close_fds=True,
                    )
                    st.success(
                        "Builder started in a separate window. Reload the Dose "
                        "Map once it reports completion."
                    )
                except Exception as exc:
                    st.error(f"Could not start the builder: {exc}")


def _run_screen(screen: dict) -> None:
    """Execute one screen module with its own __file__, sys.path, and cwd."""
    module_path: Path = screen["module"]

    if not module_path.exists():
        st.error(
            f"**{module_path.name}** was not found.\n\n"
            f"Expected location: `{module_path}`\n\n"
            "This Plant Analyzer screen is not installed. "
            "Check the FLARE installation and try again."
        )
        return

    extra_path: Path | None = screen["extra_path"]

    # Draw the standard FLARE sidebar chrome before the screen runs so the
    # FLARE Home button lands at the top of the sidebar. Plant Replay supplies
    # its own, so this applies to the Dose Map only.
    if screen.get("needs_sidebar_chrome"):
        _apply_dose_map_sidebar_chrome()

    path_added = False
    if extra_path is not None:
        extra = str(extra_path)
        if extra not in sys.path:
            sys.path.insert(0, extra)
            path_added = True

    # Match the working directory each screen sees when launched on its own.
    previous_cwd = os.getcwd()
    target_cwd = str(extra_path) if extra_path is not None else str(APP_DIR)

    # Execute inside a real module object registered in sys.modules rather than
    # a bare dict.  streamlit.components.v1.declare_component resolves the
    # frontend path by walking back to the calling frame's module; a bare exec
    # dict leaves that lookup empty and the Dose Map's radius-commit component
    # aborts with "module is None". Registering the module by file path
    # reproduces what `streamlit run` does for a top-level script.
    screen_module = ModuleType(f"_flare_screen_{module_path.stem}")
    screen_module.__file__ = str(module_path)
    screen_module.__loader__ = None
    screen_module.__package__ = None
    screen_module.FLARE_WORK_DIR = str(APP_DIR)  # type: ignore[attr-defined]
    sys.modules[screen_module.__name__] = screen_module

    try:
        os.chdir(target_cwd)
        source = module_path.read_text(encoding="utf-8")
        exec(compile(source, str(module_path), "exec"), screen_module.__dict__)
    except SystemExit as exc:
        # st.stop() and st.rerun() raise StopException / RerunException, which
        # derive from BaseException and pass through this handler untouched.
        # A SystemExit here is therefore a genuine abort, not normal control
        # flow. The Dose Map raises one from its import guard when
        # streamlit-folium or streamlit-current-location are missing, which
        # happens when FLARE is started with an interpreter other than
        # flare_env. Swallowing it silently produced a blank screen with no
        # sidebar and no explanation.
        if exc.code not in (None, 0):
            st.error(
                f"**{module_path.name}** stopped before it could render:\n\n"
                f"```\n{exc.code}\n```"
            )
            # Name the packages that are actually missing from THIS
            # interpreter. The screen's own message is generic, and the useful
            # question is which environment is running and what it lacks.
            import importlib.util

            required = {
                "streamlit_folium": "streamlit-folium",
                "streamlit_current_location": "streamlit-current-location",
                "folium": "folium",
                "branca": "branca",
                "PIL": "Pillow",
            }
            missing = []
            for module_name, package in required.items():
                try:
                    if importlib.util.find_spec(module_name) is None:
                        missing.append(package)
                except (ImportError, ValueError):
                    missing.append(package)

            detail = (
                "Missing from this interpreter: **" + "**, **".join(missing) + "**\n\n"
                if missing
                else ""
            )

            # Offer to install them here, into whichever interpreter is running.
            #
            # FLARE used to run from any console that had its original eleven
            # packages, which is what most users' IDE environments already
            # provide. The Dose Map added five more, and installing them only
            # into flare_env made "python -m streamlit run flare_home.py" fail
            # for anyone working from Spyder, VS Code, or a plain prompt. Making
            # the fix available in the app keeps that from becoming a support
            # burden, and does not assume the user can or should switch
            # interpreters.
            if missing:
                st.warning(
                    "You can install the missing libraries into the interpreter "
                    "shown below without leaving FLARE. Everything else in FLARE "
                    "is unaffected either way."
                )
                if st.button(
                    f"Install {len(missing)} missing librar"
                    f"{'y' if len(missing) == 1 else 'ies'} into this interpreter",
                    key="flare_install_missing_screen_deps",
                    type="primary",
                ):
                    import subprocess

                    with st.spinner("Installing... this can take a minute."):
                        completed = subprocess.run(
                            [sys.executable, "-m", "pip", "install", *missing],
                            capture_output=True,
                            text=True,
                        )
                    if completed.returncode == 0:
                        st.success(
                            "Installed. Reload the page (F5) to open the screen."
                        )
                    else:
                        st.error("The installation did not complete.")
                        st.code(
                            (completed.stderr or completed.stdout or "")[-2000:],
                            language="text",
                        )
                        st.caption(
                            "Some environments are managed by their IDE and "
                            "disallow installs. Use flare_env instead - see below."
                        )
            st.info(
                "FLARE is running under a Python that does not have the Dose "
                "Map's libraries.\n\n"
                f"{detail}"
                f"Current interpreter:\n\n```\n{sys.executable}\n```\n\n"
                "Each Python installation and virtual environment has its own "
                "packages. `Install\\start_streamlit.ps1` installs into "
                "**flare_env** only, so an interpreter outside it is unaffected "
                "by anything the launcher does.\n\n"
                "Either use flare_env:\n\n"
                "```\n"
                "Install\\flare_env\\Scripts\\python.exe -m streamlit run flare_home.py\n"
                "```\n\n"
                "or install the libraries into the interpreter above:\n\n"
                "```\n"
                f'"{sys.executable}" -m pip install -r requirements.txt\n'
                "```"
            )
    except Exception as exc:
        st.error(
            f"**{module_path.name}** encountered an error:\n\n"
            f"```\n{type(exc).__name__}: {exc}\n```"
        )
        with st.expander("Traceback"):
            import traceback

            st.code(traceback.format_exc(), language="text")
    finally:
        os.chdir(previous_cwd)
        if path_added:
            try:
                sys.path.remove(str(extra_path))
            except ValueError:
                pass


_run_screen(SCREENS[active_tab])

# Appended after the screen renders so it sits at the foot of the sidebar.
if active_tab == "map":
    _offer_national_database_build()
