"""FLARE maximum-population, time-evolving consequence-footprint prototype."""
from pathlib import Path
from dataclasses import replace
import json
import math
import tempfile

try:
    import streamlit as st
    import streamlit.components.v1 as components
    from streamlit_folium import st_folium
    from streamlit_current_location import current_position
except ImportError as exc:
    raise SystemExit("Install streamlit, streamlit-folium, and streamlit-current-location to run the GUI.") from exc

from flare_map_core import (
    build_output_workbook,
    build_time_evolving_field,
    deposition_group_options,
    evaluate_dose_population_bearing,
    find_max_dose_population_bearing,
    find_max_population_bearing,
    load_flare_output,
    make_map,
    population_above_threshold,
    query_radius,
)
from flare_map_core.map_view import consequence_legend_data
from flare_map_core.ui_options import (
    DOSE_OPTIONS,
    RADIUS_OPTIONS,
    nearest_dose_option,
    nearest_radius_option,
)

ROOT = Path(__file__).resolve().parent
NATIONAL_DB = ROOT / "data" / "population_2020_national.sqlite"
DEMO_DB = ROOT / "data" / "demo_population.sqlite"
DEFAULT_DB = NATIONAL_DB if NATIONAL_DB.exists() else DEMO_DB
INTERVAL_COUNT = 24
SITE_LOCATION_FILE = ROOT / "data" / "site_location.json"
# Outer analysis radius applied when a workbook is loaded. Ten miles is the
# conventional plume-exposure EPZ radius and matches the documented default
# for the circular map viewport.
# Root of the FLARE installation. flare_analyzer_shell.py injects FLARE_WORK_DIR
# when the Dose Map runs as a Plant Analyzer screen; standalone, the Dose Map
# package sits one level below the FLARE folder.
FLARE_APP_DIR = Path(globals().get("FLARE_WORK_DIR") or ROOT.parent).resolve()

DEFAULT_RADIUS_MILES = 10.0
DEFAULT_SITE_LAT = 37.4138
DEFAULT_SITE_LON = -79.1422
USER_SETTINGS_FILE = ROOT / "data" / "user_settings.json"
# The active workbook is stored under the name it was uploaded with, inside a
# folder that holds only that one file. The stored file name is therefore the
# case name, and nothing has to be recorded separately to remember it.
#
# It used to be written to a fixed data/active_flare_workbook.xlsx, which meant
# the name had to be carried alongside it in the settings file. That copy could
# go missing or hold the storage name itself, and reports were then named after
# the storage file rather than the case. Deriving the name from the file removes
# that possibility rather than guarding against it.
SAVED_WORKBOOK_DIR = ROOT / "data" / "active_workbook"
# Retained only to adopt workbooks stored by earlier versions.
LEGACY_SAVED_WORKBOOK_FILE = ROOT / "data" / "active_flare_workbook.xlsx"
RADIUS_COMMIT_COMPONENT_DIR = ROOT / "flare_map_components" / "radius_commit"
RADIUS_COMMIT_COMPONENT = components.declare_component(
    "flare_radius_commit",
    path=str(RADIUS_COMMIT_COMPONENT_DIR),
)

def _normalized_dose_range(raw_value):
    """Normalize saved/query dose limits to the discrete logarithmic scale."""
    requested = None
    if not isinstance(raw_value, (str, bytes, int, float)):
        try:
            candidate = tuple(raw_value)
            if len(candidate) == 2:
                requested = candidate
        except (TypeError, ValueError):
            requested = None
    if requested is None and isinstance(raw_value, (int, float)):
        requested = (0.01, float(raw_value))
    if requested is None:
        requested = (0.01, 25.0)
    try:
        requested_minimum = float(requested[0])
        requested_maximum = float(requested[1])
    except (TypeError, ValueError, IndexError):
        requested_minimum, requested_maximum = 0.01, 25.0
    requested_minimum = min(max(requested_minimum, DOSE_OPTIONS[0]), DOSE_OPTIONS[-1])
    requested_maximum = min(max(requested_maximum, requested_minimum), DOSE_OPTIONS[-1])
    normalized_minimum = nearest_dose_option(requested_minimum)
    normalized_maximum = nearest_dose_option(requested_maximum)
    return (normalized_minimum, max(normalized_minimum, normalized_maximum))

def _normalized_radius_range(raw_value):
    if not isinstance(raw_value, (list, tuple)) or len(raw_value) != 2:
        raw_value = (0.0, 10.0)
    minimum = nearest_radius_option(raw_value[0])
    maximum = nearest_radius_option(raw_value[1])
    if maximum <= minimum:
        maximum = nearest_radius_option(max(0.1, minimum * 1.01 if minimum > 0 else 0.1))
    return (minimum, max(minimum, maximum))

def _query_float(name):
    raw = st.query_params.get(name)
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None

SETTINGS_KEYS = (
    "radiological_layer",
    "pathway_objective_label",
    "custom_bearing_deg",
    "scenario",
    "dose_range",
    "deposition_group",
    "population_database",
    "site_lat",
    "site_lon",
    "radius_range",
    "show_population",
    "show_plume",
    "show_radius",
    "cumulative_interval",
)


def _atomic_write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)


def load_user_settings():
    """Read the stored GUI settings without changing session state."""
    if not USER_SETTINGS_FILE.exists():
        return None
    try:
        payload = json.loads(USER_SETTINGS_FILE.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except Exception as exc:
        st.warning(f"Could not read saved user settings {USER_SETTINGS_FILE}: {exc}")
        return None


def discover_workbook_folders(app_dir: Path) -> list[Path]:
    """Return folders that directly contain FLARE output workbooks.

    Mirrors the Working Folder selector used by the other FLARE tools. The Plant
    Analyzer discovers folders holding *_out.csv; the Dose Map needs the
    *_out.xlsx workbooks, which carry the Input Echo and Dose sheets it reads.

    The selector descends to the run/output folder itself, so a large UA run does
    not crowd the case list with outputs from every other run at once.
    """
    excluded = {
        "examples", "icons", "install", "manuals", "runtime",
        "__pycache__", ".git", ".streamlit", "flare_env", "build",
    }
    candidates: list[Path] = []

    def _is_excluded(path: Path) -> bool:
        try:
            parts = path.relative_to(app_dir).parts
        except Exception:
            return True
        return any(part.lower() in excluded for part in parts if part)

    try:
        if any(app_dir.glob("*_out.xlsx")):
            candidates.append(app_dir)
        for workbook in app_dir.rglob("*_out.xlsx"):
            folder = workbook.parent
            try:
                rel = folder.relative_to(app_dir)
            except Exception:
                continue
            if len(rel.parts) > 4 or _is_excluded(folder):
                continue
            candidates.append(folder)
    except Exception:
        pass

    out: list[Path] = []
    seen: set[Path] = set()
    for folder in sorted(candidates, key=lambda x: str(x).lower()):
        try:
            resolved = folder.resolve()
        except Exception:
            resolved = folder
        if resolved not in seen:
            seen.add(resolved)
            out.append(folder)
    return out


def working_folder_label(folder: Path) -> str:
    """Path relative to the FLARE folder, matching the other tools' selectors."""
    try:
        rel = folder.resolve().relative_to(FLARE_APP_DIR)
        return "." if str(rel) == "." else str(rel)
    except Exception:
        return str(folder)


def safe_workbook_filename(name) -> str:
    """Reduce an uploaded name to a plain file name that is safe to store."""
    candidate = Path(str(name or "")).name.strip()
    candidate = "".join(c for c in candidate if c not in '<>:"/\\|?*').strip()
    if not candidate:
        candidate = "workbook.xlsx"
    if not candidate.lower().endswith(".xlsx"):
        candidate += ".xlsx"
    return candidate


def find_saved_workbook():
    """Return the stored active workbook, or None.

    The folder holds at most one workbook, so its file name is the case name.
    A workbook saved by an earlier version, under the old fixed name, is adopted
    on first sight so existing installations keep working.
    """
    try:
        if SAVED_WORKBOOK_DIR.is_dir():
            for candidate in sorted(SAVED_WORKBOOK_DIR.glob("*.xlsx")):
                if candidate.is_file():
                    return candidate.resolve()
    except OSError:
        pass
    try:
        if LEGACY_SAVED_WORKBOOK_FILE.is_file():
            return LEGACY_SAVED_WORKBOOK_FILE.resolve()
    except OSError:
        pass
    return None


def save_uploaded_workbook(uploaded_file):
    """Persist the active FLARE workbook so it can be restored on a later run."""
    SAVED_WORKBOOK_DIR.mkdir(parents=True, exist_ok=True)
    # Only one workbook is active at a time; clear any previous one so the
    # folder's single file always identifies the current case.
    for stale in SAVED_WORKBOOK_DIR.glob("*.xlsx"):
        try:
            stale.unlink()
        except OSError:
            pass
    target = SAVED_WORKBOOK_DIR / safe_workbook_filename(uploaded_file.name)
    temp_path = target.with_suffix(".xlsx.tmp")
    temp_path.write_bytes(uploaded_file.getbuffer())
    temp_path.replace(target)
    try:
        LEGACY_SAVED_WORKBOOK_FILE.unlink(missing_ok=True)
    except OSError:
        pass
    st.session_state.active_workbook_path = str(target.resolve())
    st.session_state.active_workbook_saved = True


def current_settings_payload():
    """Return all persisted user-selectable GUI values."""
    settings = {key: st.session_state.get(key) for key in SETTINGS_KEYS}
    # The workbook name and location are properties of the stored file, not
    # user preferences, so they are not written here. Only whether a workbook
    # was stored is recorded; the file itself supplies the rest.
    settings["active_workbook_saved"] = bool(find_saved_workbook() is not None)
    return {"version": 1, "settings": settings}


def save_user_settings():
    """Persist all current GUI options to the package data folder."""
    _atomic_write_json(USER_SETTINGS_FILE, current_settings_payload())


def autosave_user_settings():
    """Write settings only when the current GUI state differs from the stored state."""
    payload = current_settings_payload()
    try:
        existing = json.loads(USER_SETTINGS_FILE.read_text(encoding="utf-8")) if USER_SETTINGS_FILE.exists() else None
    except Exception:
        existing = None
    if existing != payload:
        _atomic_write_json(USER_SETTINGS_FILE, payload)


def apply_user_settings(payload):
    """Stage saved GUI options before Streamlit constructs the keyed widgets."""
    settings = payload.get("settings", {}) if isinstance(payload, dict) else {}
    if not isinstance(settings, dict):
        raise ValueError("saved settings payload is invalid")
    # Backward compatibility: earlier settings files stored only the upper
    # airborne-dose scale limit as ``maximum_dose``.  Promote that value into
    # the new two-ended dose range while retaining the historical 0.01-rem
    # lower threshold.
    if "radius_range" not in settings:
        legacy_radius = float(settings.get("radius_miles", 10.0) or 10.0)
        settings = dict(settings)
        settings["radius_range"] = [0.0, legacy_radius]
    if "dose_range" not in settings:
        legacy_minimum = float(settings.get("minimum_dose", 0.01) or 0.01)
        legacy_maximum = float(settings.get("maximum_dose", 25.0) or 25.0)
        settings = dict(settings)
        settings["dose_range"] = [legacy_minimum, legacy_maximum]
    for key in SETTINGS_KEYS:
        if key in settings and settings[key] is not None:
            st.session_state[key] = settings[key]
    # Locate the stored workbook from disk. Older settings files may still
    # carry active_workbook_path / active_workbook_name; both are ignored, since
    # the stored file is authoritative for its own name and location.
    workbook_path = find_saved_workbook()
    workbook_requested = bool(
        settings.get("active_workbook_saved")
        or settings.get("active_workbook_name")
        or settings.get("active_workbook_path")
    )
    if workbook_requested and workbook_path is not None:
        st.session_state.active_workbook_saved = True
        st.session_state.active_workbook_path = str(workbook_path)
        st.session_state.restored_workbook_path = str(workbook_path)
    else:
        st.session_state.active_workbook_saved = False
        st.session_state.pop("active_workbook_path", None)
        st.session_state.pop("restored_workbook_path", None)
    # Reconstruct the uploader under a fresh key.  Streamlit upload widgets cannot
    # be populated from Session State, and an earlier upload must not override the
    # explicitly restored package copy.
    st.session_state["workbook_uploader_revision"] = int(
        st.session_state.get("workbook_uploader_revision", 0)
    ) + 1
    st.session_state.pop("export_bytes", None)
    st.session_state.pop("radius_case_signature", None)
    st.session_state.pop("radius_range_widget_v1", None)
    st.session_state["map_revision"] = int(st.session_state.get("map_revision", 0)) + 1
    if "site_lat" in st.session_state and "site_lon" in st.session_state:
        save_site_location(st.session_state.site_lat, st.session_state.site_lon, source="stored_settings")


def load_saved_site_location():
    """Return the saved site payload, or None when no valid file exists."""
    if not SITE_LOCATION_FILE.exists():
        return None
    try:
        payload = json.loads(SITE_LOCATION_FILE.read_text(encoding="utf-8"))
        lat = float(payload["latitude"])
        lon = float(payload["longitude"])
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            raise ValueError("coordinates are outside valid latitude/longitude limits")
        return {
            "latitude": lat,
            "longitude": lon,
            "source": str(payload.get("source", "saved")),
        }
    except Exception as exc:
        st.warning(f"Could not read saved site location {SITE_LOCATION_FILE}: {exc}")
        return None


def save_site_location(latitude, longitude, source="user"):

    """Atomically persist the accepted site coordinates in the package data folder."""
    lat = float(latitude)
    lon = float(longitude)
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        raise ValueError("site coordinates are outside valid latitude/longitude limits")
    SITE_LOCATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"latitude": lat, "longitude": lon, "source": str(source)}
    temp_path = SITE_LOCATION_FILE.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(SITE_LOCATION_FILE)


def persist_widget_site_location():
    """Widget callback used for manually entered latitude/longitude values."""
    try:
        save_site_location(st.session_state.site_lat, st.session_state.site_lon, source="manual_entry")
        st.session_state.pop("export_bytes", None)
        st.session_state.pop("site_location_save_error", None)
    except Exception as exc:
        st.session_state.site_location_save_error = str(exc)


st.set_page_config(page_title="FLARE Population Plume", layout="wide")
st.title("FLARE Time-Evolving Consequences")
st.markdown(
    """
    <style>
    h1 {font-size:2.55rem !important;}
    div[data-testid="stCustomComponentV1"]:has(iframe[title*="streamlit_folium"]) {
        display:flex; justify-content:center; position:relative;
    }
    div[data-testid="stCustomComponentV1"]:has(iframe[title*="streamlit_folium"])::after {
        /* The Leaflet content box is 16 px narrower than the iframe border box
           because of the iframe scrollbar gutter. Shift the circular crop by
           half that gutter so its center matches Leaflet's true map center. */
        content:""; position:absolute; left:calc(50% - 8px); top:0; transform:translateX(-50%);
        width:min(620px, 100%); aspect-ratio:1/1; border-radius:50%;
        border:3px solid rgba(90,90,90,.55); box-sizing:border-box;
        pointer-events:none; z-index:10;
    }
    iframe[title*="streamlit_folium"] {
        /* Keep the circular viewport, but add a small upper-left mask island so
           Leaflet's native zoom buttons remain in their standard position. */
        border:0; aspect-ratio:1/1; max-width:640px; max-height:640px;
        -webkit-mask-image:
          radial-gradient(circle at calc(50% - 8px) 50%, #000 0 49.85%, transparent 50.15%),
          linear-gradient(#000 0 0);
        -webkit-mask-size:100% 100%, 58px 86px;
        -webkit-mask-position:0 0, 0 0;
        -webkit-mask-repeat:no-repeat, no-repeat;
        -webkit-mask-composite:source-over;
        mask-image:
          radial-gradient(circle at calc(50% - 8px) 50%, #000 0 49.85%, transparent 50.15%),
          linear-gradient(#000 0 0);
        mask-size:100% 100%, 58px 86px;
        mask-position:0 0, 0 0;
        mask-repeat:no-repeat, no-repeat;
        mask-composite:add;
    }
    .flare-external-legend, .flare-analysis-panel {
      border:1px solid #777; border-radius:7px; padding:10px 12px;
      background:rgba(255,255,255,.98); font-size:13px; line-height:1.25;
    }
    .flare-analysis-panel {margin-top:0;}
    .flare-legend-title, .flare-analysis-title {font-weight:700; font-size:15px; margin-bottom:7px;}
    .flare-legend-row {display:flex; align-items:center; gap:7px; margin:4px 0;}
    .flare-legend-swatch {width:22px; height:14px; border:1px solid #666; display:inline-block; flex:0 0 auto;}
    .flare-legend-note {margin-top:7px; color:#444;}
    /* Collapse to a single column when the panel is too narrow for two, so
       long values wrap instead of being clipped at the panel edge. */
    .flare-analysis-grid {display:grid; grid-template-columns:repeat(auto-fit,minmax(232px,1fr)); column-gap:18px;}
    .flare-analysis-item {display:flex; justify-content:space-between; align-items:baseline;
      gap:10px; padding:3px 0; border-bottom:1px solid #ddd; min-width:0;}
    .flare-analysis-item span {text-align:right; overflow-wrap:anywhere; min-width:0;}
    .flare-analysis-source {padding-top:7px; overflow-wrap:anywhere;}
    .flare-legend-note {overflow-wrap:anywhere;}
    @media print {
      @page {size: portrait; margin: 0.30in;}
      [data-testid="stSidebar"], [data-testid="stHeader"],
      [data-testid="stToolbar"], [data-testid="stDecoration"],
      [data-testid="stStatusWidget"], .flare-no-print {display:none !important;}
      .main .block-container {padding:0 !important; max-width:none !important;}
      h1 {font-size:18pt !important; margin:0 0 5pt 0 !important; text-align:center;}
      div[data-testid="stCustomComponentV1"]:has(iframe[title*="streamlit_folium"]) {
        display:flex !important; justify-content:center !important; break-inside:avoid;
      }
      iframe[title*="streamlit_folium"] {
        width:5.45in !important; height:5.45in !important;
        max-width:5.45in !important; max-height:5.45in !important;
      }
      div[data-testid="stCustomComponentV1"]:has(iframe[title*="streamlit_folium"])::after {
        width:5.45in !important; height:5.45in !important;
      }
      div[data-testid="stHorizontalBlock"]:has(.flare-external-legend) {
        display:flex !important; flex-direction:row !important; flex-wrap:nowrap !important;
        align-items:stretch !important; gap:0.16in !important; margin-top:0.10in !important;
        break-inside:avoid;
      }
      div[data-testid="stHorizontalBlock"]:has(.flare-external-legend) > div:first-child {
        flex:0 0 2.15in !important; width:2.15in !important;
      }
      div[data-testid="stHorizontalBlock"]:has(.flare-external-legend) > div:last-child {
        flex:1 1 auto !important; min-width:0 !important;
      }
      .flare-external-legend, .flare-analysis-panel {
        break-inside:avoid; font-size:7.8pt; line-height:1.14; padding:5pt 6pt; border-radius:4pt;
        height:100%; box-sizing:border-box;
      }
      .flare-legend-title, .flare-analysis-title {font-size:9.5pt; margin-bottom:3pt;}
      .flare-legend-row {margin:1.4pt 0; gap:4pt;}
      .flare-legend-swatch {width:12pt; height:7pt;}
      .flare-legend-note {margin-top:4pt;}
      .flare-analysis-grid {grid-template-columns:1fr 1fr; column-gap:10pt;}
      .flare-analysis-item {padding:1.1pt 0; gap:4pt;}
      .flare-analysis-source {padding-top:4pt;}
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ``st.iframe`` is intentionally used for the visible fast controls, but
# that helper cannot return a value to Python.  This zero-height custom component
# is a narrow bridge used only when the outer radius must expand beyond the data
# currently loaded in the Leaflet iframe.  Its component value triggers one
# ordinary Streamlit rerun with the requested discrete radius range.
radius_commit_event = RADIUS_COMMIT_COMPONENT(
    key="flare_radius_commit_bridge_v1",
    default=None,
)
pending_radius_commit = None
if isinstance(radius_commit_event, dict):
    commit_id = str(radius_commit_event.get("requestId", ""))
    try:
        commit_minimum = float(radius_commit_event["minimum"])
        commit_maximum = float(radius_commit_event["maximum"])
    except (KeyError, TypeError, ValueError):
        commit_minimum = commit_maximum = None
    if (
        commit_id
        and commit_id != st.session_state.get("last_radius_commit_id")
        and commit_minimum is not None
        and commit_maximum is not None
    ):
        pending_radius_commit = (commit_minimum, commit_maximum)
        st.session_state["last_radius_commit_id"] = commit_id
        st.session_state["map_revision"] = int(st.session_state.get("map_revision", 0)) + 1
        if radius_commit_event.get("fitView") is True:
            st.session_state.pending_fit_view_to_radius = True

saved_site_location = load_saved_site_location()

# On a true first run, do not construct the sidebar widgets or map until the
# browser has returned a location.  
if saved_site_location is None:
    st.info(
        "Requesting your current location. Allow location access in the browser "
        "to initialize the FLARE map."
    )

    try:
        browser_position = current_position()
    except Exception as exc:
        browser_position = None
        st.warning(f"The browser location request could not be started: {exc}")

    browser_lat = browser_position.get("latitude") if isinstance(browser_position, dict) else None
    browser_lon = browser_position.get("longitude") if isinstance(browser_position, dict) else None

    if browser_lat is not None and browser_lon is not None:
        try:
            browser_lat = float(browser_lat)
            browser_lon = float(browser_lon)
            save_site_location(browser_lat, browser_lon, source="browser_current_location")
        except Exception as exc:
            st.error(f"Could not save the browser location to {SITE_LOCATION_FILE}: {exc}")
            st.stop()

        # Start the next run from the newly created file.  This also ensures the
        # coordinate widgets are never instantiated with stale fallback values.
        st.rerun()

    st.caption(
        "The map will open after the browser returns your location. If location "
        "permission was denied or location services are unavailable, use the "
        "fallback button below."
    )
    if st.button("Use fallback location", type="secondary"):
        try:
            save_site_location(DEFAULT_SITE_LAT, DEFAULT_SITE_LON, source="explicit_fallback")
        except Exception as exc:
            st.error(f"Could not create the fallback site-location file at {SITE_LOCATION_FILE}: {exc}")
            st.stop()
        st.rerun()

    # Crucially, do not continue to the coordinate widgets, population query, or
    # map while browser geolocation is still pending.
    st.stop()


if "site_lat" not in st.session_state or "site_lon" not in st.session_state:
    st.session_state.site_lat = float(saved_site_location["latitude"])
    st.session_state.site_lon = float(saved_site_location["longitude"])

# A map click cannot directly overwrite widget-backed keys after those widgets have
# been instantiated.  Apply any pending coordinates at the start of the next run,
# before the sidebar number inputs are created.
if "pending_site_lat" in st.session_state and "pending_site_lon" in st.session_state:
    st.session_state.site_lat = float(st.session_state.pop("pending_site_lat"))
    st.session_state.site_lon = float(st.session_state.pop("pending_site_lon"))
    st.session_state.pop("export_bytes", None)

# A map-side "Fit view to radius" action stages a one-run fractional-zoom fit.
# The user-selected analysis radius is never modified by this action.
fit_view_to_radius = bool(st.session_state.pop("pending_fit_view_to_radius", False))
view_bounds_override = None

if st.session_state.get("site_location_save_error"):
    st.error(
        f"The selected site could not be saved to {SITE_LOCATION_FILE}: "
        f"{st.session_state.site_location_save_error}"
    )

if DEFAULT_DB != NATIONAL_DB:
    # Highlighted rather than a caption: every population count, dose-weighted
    # pathway, and exported report on this screen is derived from synthetic
    # data until the national Census database is built, so it must not read as
    # an incidental note. The Build national database control referred to here
    # is added at the foot of the sidebar by flare_analyzer_shell.py, and is
    # shown under exactly this condition.
    st.warning(
        "**The national population database is not installed.** Synthetic "
        "population data are being used, so population counts and the "
        "maximum-population pathway are illustrative only.\n\n"
        "Use **Build national database** at the bottom of the sidebar to "
        "download the official 2020 Census data and build it.",
        icon=":material/warning:",
    )

case = None
uploaded = None
tmp_path = None
with st.sidebar:
    st.header("Saved setup")
    saved_settings = load_user_settings()
    if st.button(
        "Apply stored settings",
        use_container_width=True,
        disabled=saved_settings is None,
        help=f"Restore the controls and active workbook stored in {USER_SETTINGS_FILE.name}.",
    ):
        try:
            apply_user_settings(saved_settings)
            for query_key in (
                "flare_interval", "flare_dose_min", "flare_dose_max",
                "flare_radius_min", "flare_radius_max",
            ):
                if query_key in st.query_params:
                    del st.query_params[query_key]
            st.session_state.settings_notice = "Stored settings applied."
            st.rerun()
        except Exception as exc:
            st.error(f"Could not apply the stored settings: {exc}")
    settings_notice = st.session_state.pop("settings_notice", None)
    if settings_notice:
        st.success(settings_notice)

    st.divider()
    st.header("FLARE radiological case")

    # Working Folder / Case selection, matching the other FLARE tools. The
    # Dose Map previously accepted a workbook only by upload, which meant
    # browsing the filesystem for a file the FLARE run had just written into
    # the case folder alongside it.
    selected_workbook = None
    _workbook_folders = discover_workbook_folders(FLARE_APP_DIR)
    if _workbook_folders:
        _selected_folder = st.selectbox(
            "Working Folder",
            options=_workbook_folders,
            index=0,
            format_func=working_folder_label,
            key="flare_map_working_folder",
            help="Run/output folder holding the FLARE *_out.xlsx workbooks.",
        )
        _folder_workbooks = sorted(Path(_selected_folder).glob("*_out.xlsx"))
        if _folder_workbooks:
            _case_labels = ["(none - use upload below)"] + [w.name for w in _folder_workbooks]
            _selected_case = st.selectbox(
                "Case",
                _case_labels,
                key="flare_map_working_case",
                help="Select a FLARE output workbook from the working folder.",
            )
            if _selected_case != _case_labels[0]:
                selected_workbook = next(
                    w for w in _folder_workbooks if w.name == _selected_case
                )
        else:
            st.caption("No *_out.xlsx workbooks in this folder.")
    else:
        st.caption(
            "No FLARE output workbooks found under the FLARE folder. "
            "Run a case, or upload a workbook below."
        )

    uploader_key = f"flare_workbook_upload_{int(st.session_state.get('workbook_uploader_revision', 0))}"
    uploaded = st.file_uploader("Or upload a workbook", type=["xlsx"], key=uploader_key)
    st.caption("Select a case above, or upload a FLARE output workbook, to calculate the time-evolving footprint. A geometric preview is shown.")
    active_workbook_name = None
    restored_workbook_path = st.session_state.pop("restored_workbook_path", None)
    # A case chosen from the working folder takes precedence: it is an explicit
    # selection made this run, unlike a restored or previously stored workbook.
    if selected_workbook is not None:
        try:
            case = load_flare_output(selected_workbook)
            active_workbook_name = selected_workbook.name
            tmp_path = selected_workbook
            st.session_state.active_workbook_name = selected_workbook.name
            st.session_state.active_workbook_path = str(selected_workbook)
            st.session_state.active_workbook_saved = False
            st.caption(f"Working folder case: {selected_workbook.name}")
            # Same first-load framing as an upload: open on the off-site annulus.
            _case_signature = f"{selected_workbook}:{selected_workbook.stat().st_mtime}"
            if st.session_state.get("radius_case_signature") != _case_signature:
                _eab_miles = case.eab_distance_m / 1609.344
                _inner_miles = (
                    _eab_miles if 0.0 < _eab_miles < DEFAULT_RADIUS_MILES else 0.0
                )
                st.session_state["radius_range"] = (_inner_miles, DEFAULT_RADIUS_MILES)
                st.session_state.pop("radius_range_widget_v1", None)
                st.session_state["radius_case_signature"] = _case_signature
                st.session_state.pop("export_bytes", None)
        except Exception as exc:
            st.error(f"Could not read {selected_workbook.name}: {exc}")
    elif restored_workbook_path:
        try:
            saved_path = Path(restored_workbook_path).expanduser().resolve()
            if not saved_path.exists():
                located = find_saved_workbook()
                if located is None:
                    raise FileNotFoundError(saved_path)
                saved_path = located
            tmp_path = saved_path
            case = load_flare_output(tmp_path)
            active_workbook_name = saved_path.name
            st.session_state.active_workbook_saved = True
            st.session_state.active_workbook_path = str(saved_path)
            st.caption(f"Stored active workbook loaded: {active_workbook_name}")
        except Exception as exc:
            st.session_state.active_workbook_saved = False
            st.error(f"Could not read the stored active workbook: {exc}")
    elif uploaded is not None:
        try:
            save_uploaded_workbook(uploaded)
            active_workbook_name = uploaded.name
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                tmp.write(uploaded.getbuffer())
                tmp_path = Path(tmp.name)
            case = load_flare_output(tmp_path)
            upload_signature = f"{uploaded.name}:{uploaded.size}"
            if st.session_state.get("radius_case_signature") != upload_signature:
                # A newly loaded workbook opens on the off-site annulus: the
                # exclusion-area boundary as the inner radius, the standard
                # 10-mile plume-exposure EPZ radius as the outer.
                #
                # nbt_distance_eab_m used to set the OUTER radius, which zoomed
                # the map to a few hundred metres. As an inner radius it is the
                # right quantity: there is no resident population inside the
                # EAB, so it is off-site dose beyond that boundary that the
                # population figures on this screen are about.
                #
                # flare_workbook.py substitutes 16093.44 m (10 miles) when a
                # workbook carries no readable EAB distance. Taken literally
                # that would place the inner radius on top of the outer and
                # collapse the annulus, so anything not strictly inside the
                # outer radius falls back to no inner cut.
                _eab_miles = case.eab_distance_m / 1609.344
                _inner_miles = (
                    _eab_miles if 0.0 < _eab_miles < DEFAULT_RADIUS_MILES else 0.0
                )
                st.session_state["radius_range"] = (_inner_miles, DEFAULT_RADIUS_MILES)
                st.session_state.pop("radius_range_widget_v1", None)
                st.session_state["radius_case_signature"] = upload_signature
                st.session_state.pop("export_bytes", None)
        except Exception as exc:
            st.error(f"Could not read the FLARE workbook: {exc}")
    elif st.session_state.get("active_workbook_saved", False):
        try:
            saved_path_text = st.session_state.get("active_workbook_path", str(find_saved_workbook() or ""))
            saved_path = Path(saved_path_text).expanduser()
            if not saved_path.is_absolute():
                saved_path = (ROOT / saved_path).resolve()
            if not saved_path.exists():
                located = find_saved_workbook()
                if located is None:
                    raise FileNotFoundError(saved_path)
                saved_path = located
            tmp_path = saved_path
            case = load_flare_output(tmp_path)
            active_workbook_name = saved_path.name
            st.session_state.active_workbook_path = str(saved_path)
            st.caption(f"Stored active workbook: {active_workbook_name}")
        except Exception as exc:
            st.error(f"Could not read the stored active workbook: {exc}")

    radiological_layer = st.radio(
        "Radiological layer", ["Airborne dose", "Ground deposition"], key="radiological_layer"
    )
    # The two maximization criteria search for the bearing that maximizes a
    # population quantity, so they are only meaningful against real population
    # data. With the synthetic demonstration database they would return a
    # confident bearing derived from invented people. Offer only Custom
    # direction until the national Census database is installed.
    #
    # NATIONAL_DB.exists() is the test rather than the selected database,
    # because this control is built before the database selector further down
    # the sidebar. It matches the condition used for the banner on the main
    # panel and the status message below.
    _national_installed = NATIONAL_DB.exists()
    _pathway_options = [
        "Maximum population × dose",
        "Maximum population inside plume",
        "Custom direction",
    ]
    if not _national_installed:
        _pathway_options = ["Custom direction"]
        # Streamlit raises if a keyed widget's stored value is not among its
        # options, so clear a maximization choice left by a previous session or
        # restored from the settings file.
        if st.session_state.get("pathway_objective_label") not in _pathway_options:
            st.session_state["pathway_objective_label"] = "Custom direction"

    pathway_objective_label = st.radio(
        "Maximum-population pathway criterion",
        _pathway_options,
        key="pathway_objective_label",
        help=(
            "The first two options rotate the same dose-defined plume through 360°. The first "
            "maximizes the sum of population × dose; the second maximizes total population within "
            "the plume footprint above the minimum dose threshold. Custom direction uses the "
            "bearing selected below without performing a maximization search."
        ),
    )
    if not _national_installed:
        st.caption(
            "Maximum-population criteria need the national Census database. "
            "Until it is installed, only Custom direction is available."
        )
    custom_bearing_deg = None
    if pathway_objective_label == "Custom direction":
        if "custom_bearing_deg" not in st.session_state:
            st.session_state.custom_bearing_deg = 0
        custom_bearing_deg = st.slider(
            "Custom direction (degrees)",
            min_value=0,
            max_value=360,
            step=1,
            key="custom_bearing_deg",
            help="Meteorological bearing measured clockwise from north. 0° and 360° are north.",
        )
    pathway_objective = {
        "Maximum population × dose": "population_dose",
        "Maximum population inside plume": "population",
        "Custom direction": "custom",
    }[pathway_objective_label]
    scenario_labels = {
        "Conservative maximum-population pathway": "Unidirectional",
        "Better-estimate synthetic meteorology": "Constrained Variability",
    }
    scenario = st.radio(
        "Meteorological scenario",
        list(scenario_labels),
        key="scenario",
        format_func=scenario_labels.get,
        help=(
            "Unidirectional keeps every interval centered on the selected pathway. "
            "Constrained Variability uses a reproducible, bounded, mean-reverting direction sequence."
        ),
    )
    scenario_display_label = scenario_labels.get(scenario, scenario)
    # Slider-based controls are rendered in the persistent map-side interface.
    # Query parameters carry their most recent browser-local values into Python
    # on startup or on the next ordinary Streamlit rerun.
    query_dose_minimum = _query_float("flare_dose_min")
    query_dose_maximum = _query_float("flare_dose_max")
    requested_dose_range = (
        (query_dose_minimum, query_dose_maximum)
        if query_dose_minimum is not None and query_dose_maximum is not None
        else st.session_state.get("dose_range")
    )
    minimum_dose, maximum_dose = _normalized_dose_range(requested_dose_range)
    st.session_state["dose_range"] = (minimum_dose, maximum_dose)

    deposition_group = "Total depositing inventory"
    if radiological_layer == "Ground deposition":
        options = deposition_group_options(case.release_groups) if case is not None else [deposition_group]
        deposition_group = st.selectbox("Deposition release group", options, key="deposition_group")
        st.caption("Synthetic relative deposition; no additional FLARE or weather input is required.")

    query_radius_minimum = _query_float("flare_radius_min")
    query_radius_maximum = _query_float("flare_radius_max")
    requested_radius_range = (
        pending_radius_commit
        if pending_radius_commit is not None
        else (
            (query_radius_minimum, query_radius_maximum)
            if query_radius_minimum is not None and query_radius_maximum is not None
            else st.session_state.get(
                "radius_range", (0.0, st.session_state.get("radius_miles", 10.0))
            )
        )
    )
    minimum_radius, radius = _normalized_radius_range(requested_radius_range)
    st.session_state["radius_range"] = (minimum_radius, radius)
    bearing_step = 1.0

    query_interval_raw = st.query_params.get("flare_interval")
    try:
        query_interval = int(query_interval_raw) if query_interval_raw is not None else None
    except (TypeError, ValueError):
        query_interval = None
    if query_interval is None:
        query_interval = int(st.session_state.get("cumulative_interval", 0) or 0)
    step = max(0, min(INTERVAL_COUNT, int(query_interval)))
    st.session_state["cumulative_interval"] = step

    st.header("Map layers")
    if "show_population" not in st.session_state:
        st.session_state.show_population = False
    if "show_plume" not in st.session_state:
        st.session_state.show_plume = True
    if "show_radius" not in st.session_state:
        st.session_state.show_radius = True
    show_population = st.checkbox("Show population density", key="show_population")
    show_plume = st.checkbox("Show radiological layer", key="show_plume")
    show_radius = st.checkbox("Show analysis-radius boundary", key="show_radius")

    st.header("Site and population")
    if NATIONAL_DB.exists():
        st.success("National Census database installed")
    else:
        st.warning("Run Build_National_Population_Database.bat to create the national database.")
    def _resolve_population_database(raw_path):
        """Resolve a saved/user path and recover safely from moved package folders."""
        candidate = Path(str(raw_path or DEFAULT_DB)).expanduser()
        if not candidate.is_absolute():
            candidate = (ROOT / candidate).resolve()
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()
        # Settings commonly retain an absolute path from an earlier extracted
        # package. Recover the same filename from this package's data folder.
        packaged_candidate = (ROOT / "data" / candidate.name).resolve()
        if packaged_candidate.exists() and packaged_candidate.is_file():
            return packaged_candidate
        if DEFAULT_DB.exists() and DEFAULT_DB.is_file():
            return DEFAULT_DB.resolve()
        return candidate

    resolved_saved_db = _resolve_population_database(
        st.session_state.get("population_database", DEFAULT_DB)
    )
    st.session_state["population_database"] = str(resolved_saved_db)
    if "population_database_widget_v2" not in st.session_state:
        st.session_state["population_database_widget_v2"] = str(resolved_saved_db)
    database_text = st.text_input(
        "Population database", key="population_database_widget_v2"
    )
    requested_db = _resolve_population_database(database_text)
    if requested_db.exists() and requested_db.is_file():
        db_path = requested_db
        st.session_state["population_database"] = str(db_path)
    else:
        db_path = _resolve_population_database(DEFAULT_DB)
        st.warning(
            f"Could not open the selected database path. Using {db_path.name} from this package."
        )

    # Coordinates are display-only.  Site changes are made by arming the map
    # selector and clicking the desired location, which updates Session State
    # and the persisted site/settings files on the subsequent rerun.
    st.caption(
        f"Site latitude: {float(st.session_state.site_lat):.3f}    "
        f"Longitude: {float(st.session_state.site_lon):.3f}"
    )

    if st.button(
        "Select new location on map",
        type="primary" if not st.session_state.get("location_pick_armed", False) else "secondary",
        use_container_width=True,
    ):
        st.session_state.location_pick_armed = True
        st.session_state.pop("last_consumed_map_click", None)
    if st.session_state.get("location_pick_armed", False):
        st.warning("Location selection is armed. Pan as needed, then click the desired site once.")
    else:
        st.caption("Pan normally. Use the button above before clicking to select a new site.")
    # Every widget interaction causes a Streamlit rerun.  At the end of widget
    # construction, persist the complete state only when it differs from disk.
    # This captures radio buttons, checkboxes, direct-entry values, sliders,
    # the selected database, and the active copied FLARE workbook without a
    # separate save action.
    # Do not overwrite the persisted setup merely because the application was
    # opened.  The first completed render establishes the in-memory baseline;
    # subsequent widget reruns are genuine user changes and are autosaved.
    current_payload = current_settings_payload()
    if not st.session_state.get("settings_autosave_ready", False):
        st.session_state.settings_autosave_ready = True
        st.session_state.settings_last_payload = current_payload
    elif current_payload != st.session_state.get("settings_last_payload"):
        try:
            _atomic_write_json(USER_SETTINGS_FILE, current_payload)
            st.session_state.settings_last_payload = current_payload
        except Exception as exc:
            st.warning(f"Could not automatically save settings to {USER_SETTINGS_FILE.name}: {exc}")

site_lat = float(st.session_state.site_lat)
site_lon = float(st.session_state.site_lon)
if not db_path.exists():
    st.error(f"Database not found: {db_path}")
    st.stop()

cells = query_radius(
    db_path, site_lat, site_lon, radius, minimum_radius_miles=0.0
)
consequence = None

if case is not None:
    # Use the LPZ curve for pathway optimization because it represents the complete modeled interval.
    if pathway_objective == "custom":
        result = evaluate_dose_population_bearing(
            cells, site_lat, site_lon, radius, case.lpz_curve, case.dispersion,
            bearing_deg=float(custom_bearing_deg), minimum_dose_rem=minimum_dose,
            minimum_radius_miles=minimum_radius,
        )
    else:
        result = find_max_dose_population_bearing(
            cells, site_lat, site_lon, radius, case.lpz_curve, case.dispersion,
            bearing_step_deg=bearing_step, minimum_dose_rem=minimum_dose,
            objective=pathway_objective, minimum_radius_miles=minimum_radius,
        )
    consequence = build_time_evolving_field(
        radius, result.bearing_deg, case.eab_curve, case.lpz_curve, case.dispersion,
        case.eab_integration_hr, case.lpz_integration_hr, INTERVAL_COUNT, scenario,
        radiological_layer, case.release_groups, deposition_group,
        seed_text=active_workbook_name or case.source_path.name,
        interval_count=INTERVAL_COUNT,
    )
    # Population above threshold is a consequence-field metric, not the
    # population used to choose the predominant pathway. Always evaluate it
    # against the active cumulative airborne-dose field for the selected
    # meteorological scenario and cumulative interval.
    if radiological_layer == "Airborne dose":
        population_dose_consequence = consequence
    else:
        population_dose_consequence = build_time_evolving_field(
            radius, result.bearing_deg, case.eab_curve, case.lpz_curve, case.dispersion,
            case.eab_integration_hr, case.lpz_integration_hr, INTERVAL_COUNT, scenario,
            "Airborne dose", case.release_groups, deposition_group,
            seed_text=active_workbook_name or case.source_path.name,
            interval_count=INTERVAL_COUNT,
        )
    elapsed_hours = [float(case.eab_integration_hr)] + [
        float(interval.end_hr) for interval in consequence.steps
    ]
    scenario_population_by_interval = [
        population_above_threshold(
            cells,
            site_lat,
            site_lon,
            radius,
            replace(
                population_dose_consequence,
                cumulative_field=population_dose_consequence.cumulative_fields[interval_index],
                displayed_step=interval_index,
            ),
            minimum_dose,
            minimum_radius_miles=minimum_radius,
        )
        for interval_index in range(len(population_dose_consequence.cumulative_fields))
    ]
    scenario_population_above_threshold = scenario_population_by_interval[step]
    current_elapsed_hr = elapsed_hours[step]
    map_maximum_text = (
        f"{maximum_dose:.3g} rem display maximum"
        if radiological_layer == "Airborne dose"
        else "100% of final LPZ"
    )
    workbook_display = active_workbook_name or case.source_path.name
    report_scale_maximum = (
        maximum_dose
        if radiological_layer == "Airborne dose"
        else consequence.scale_maximum
    )
    report_payload = {
        "filename": f"{Path(workbook_display).stem}_dose_map.pdf",
        "legend": consequence_legend_data(
            consequence.title,
            consequence.units,
            minimum_dose if consequence.units == "rem" else 0.005,
            report_scale_maximum,
        ),
        "summary": [],
        "summary_by_interval": [
            [
                {"label": "Selected pathway", "value": f"{result.bearing_deg:.1f}°"},
                {"label": "Current elapsed time", "value": f"{elapsed_hours[interval_index]:.3g} hr"},
                {"label": "Cumulative interval", "value": f"{interval_index}/{INTERVAL_COUNT}"},
                {"label": "Population above threshold", "value": f"{scenario_population_by_interval[interval_index]:,.0f}"},
                {"label": "Map maximum", "value": map_maximum_text},
                {"label": "Dose threshold", "value": f"{minimum_dose:.3g} rem"},
                {"label": "Radiological layer", "value": radiological_layer},
                {"label": "Pathway criterion", "value": pathway_objective_label},
                {"label": "Meteorological scenario", "value": scenario_display_label},
                {"label": "Site coordinates", "value": f"{site_lat:.6f}, {site_lon:.6f}"},
                {"label": "Analysis radius range", "value": f"{minimum_radius:.3f}-{radius:.3f} miles"},
            ]
            for interval_index in range(len(consequence.cumulative_fields))
        ],
        "source_workbook": workbook_display,
        "selected_bearing_deg": float(result.bearing_deg),
        "minimum_analysis_radius_miles": float(minimum_radius),
    }
    pathway_points = sorted(
        (
            float(distance_m),
            float(dose_rem),
        )
        for distance_m, dose_rem in zip(
            case.lpz_curve.distance_m,
            case.lpz_curve.centerline_dose_rem,
        )
        if math.isfinite(float(distance_m))
        and math.isfinite(float(dose_rem))
        and float(distance_m) > 0.0
        and float(dose_rem) > 0.0
    )
    pathway_control_payload = {
        "objective": pathway_objective,
        "bearing_step_deg": float(bearing_step),
        "distance_m": [point[0] for point in pathway_points],
        "dose_rem": [point[1] for point in pathway_points],
        "stability_class": str(case.dispersion.stability_class),
        "wind_speed_m_s": float(case.dispersion.wind_speed_m_s),
        "release_duration_hr": float(case.dispersion.release_duration_hr),
    }
    m = make_map(
        site_lat, site_lon, cells, result.bearing_deg, radius,
        minimum_radius_miles=minimum_radius,
        dispersion_inputs=case.dispersion,
        dose_curve=case.lpz_curve,
        minimum_dose_rem=minimum_dose,
        show_population=show_population,
        show_plume=show_plume,
        show_radius=show_radius,
        radiological_layer=radiological_layer,
        consequence_fields=tuple(consequence.cumulative_fields),
        population_consequence_fields=tuple(population_dose_consequence.cumulative_fields),
        consequence_title=consequence.title,
        consequence_units=consequence.units,
        consequence_scale_maximum=(
            maximum_dose
            if radiological_layer == "Airborne dose" else consequence.scale_maximum
        ),
        consequence_elapsed_hours=tuple(elapsed_hours),
        consequence_initial_step=int(step),
        consequence_display_step=int(step),
        consequence_total_steps=INTERVAL_COUNT,
        embedded_legend=False,
        view_bounds=view_bounds_override,
        fit_view_to_radius=fit_view_to_radius,
        report_export_payload=report_payload,
        pathway_control_payload=pathway_control_payload,
    )

    with st.sidebar:
        st.header("Capture result")
        if st.button("Prepare updated FLARE output workbook", use_container_width=True):
            with st.spinner("Writing interval and radial/azimuthal results..."):
                try:
                    st.session_state.export_bytes = build_output_workbook(
                        tmp_path, case, site_lat, site_lon, minimum_radius, radius, result.bearing_deg,
                        scenario, deposition_group, pathway_objective_label,
                        active_workbook_name or case.source_path.name,
                        INTERVAL_COUNT,
                    )
                    st.session_state.export_name = f"{Path(active_workbook_name or case.source_path.name).stem}_footprint.xlsx"
                except Exception as exc:
                    st.error(f"Could not prepare the output workbook: {exc}")
        if st.session_state.get("export_bytes"):
            st.download_button(
                "Download updated output workbook",
                data=st.session_state.export_bytes,
                file_name=st.session_state.get("export_name", "FLARE_footprint_output.xlsx"),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
else:
    result = find_max_population_bearing(cells, site_lat, site_lon, radius, 10.0, bearing_step, "uniform")
    m = make_map(
        site_lat, site_lon, cells, result.bearing_deg, radius, minimum_radius_miles=minimum_radius, half_angle_deg=10.0,
        show_population=show_population, show_plume=show_plume, show_radius=show_radius,
        view_bounds=view_bounds_override,
        fit_view_to_radius=fit_view_to_radius,
    )

# The three frequently adjusted slider controls live beside the persistent map.
# Interval and dose changes are handled entirely in the browser.  Radius changes
# are also browser-local while the selected outer radius remains within the loaded
# numerical domain; expanding beyond that domain performs one deliberate reload so
# Python can build the larger consequence and population extent.
reset_button_column, map_controls_column = st.columns([1.55, 8.45], gap="medium")
with reset_button_column:
    # Keep reset in the browser with the fast radius controls. A Streamlit
    # button rerun can only see the older server-side radius, not a local edit.
    st.iframe(
        """
        <style>
          html,body {margin:0;font:14px system-ui,sans-serif;}
          button {width:100%;min-height:38px;background:white;color:#222;
            border:1px solid #aaa;border-radius:8px;cursor:pointer;}
          button:hover {border-color:#d16b3d;color:#a44320;}
          button:focus-visible {outline:2px solid #d16b3d;outline-offset:-3px;}
        </style>
        <button id="flare-reset-view" type="button"
          title="Center the release site and fit the selected maximum analysis radius to the opening.">
          Reset View
        </button>
        <script>
          document.getElementById('flare-reset-view').addEventListener('click', function() {
            window.parent.document.querySelectorAll('iframe').forEach(function(frame) {
              if (frame.contentWindow) frame.contentWindow.postMessage(
                {type:'flare-reset-view-request'}, '*');
            });
          });
        </script>
        """,
        height=44,
    )
with map_controls_column:
    dose_options_json = json.dumps(DOSE_OPTIONS, separators=(",", ":"))
    radius_options_json = json.dumps(RADIUS_OPTIONS, separators=(",", ":"))
    dose_disabled = "true" if radiological_layer != "Airborne dose" else "false"
    st.iframe(
        f"""
        <style>
          .flare-controls {{font:13px/1.25 system-ui,sans-serif;color:#222;border:1px solid #bbb;
            border-radius:8px;padding:8px 11px;background:white;}}
          .flare-row {{display:grid;grid-template-columns:145px minmax(230px,1fr) 126px;
            align-items:center;gap:10px;min-height:38px;}}
          .flare-label {{font-weight:650;white-space:nowrap;}}
          .flare-value {{font-variant-numeric:tabular-nums;text-align:right;color:#444;white-space:nowrap;}}
          .flare-single, .flare-dual {{position:relative;height:28px;display:flex;align-items:center;}}
          .flare-single input[type=range] {{width:100%;accent-color:#d16b3d;}}
          .flare-dual .track {{position:absolute;left:0;right:0;height:5px;border-radius:4px;background:#d6d6d6;}}
          .flare-dual input[type=range] {{position:absolute;left:0;width:100%;height:28px;margin:0;
            appearance:none;-webkit-appearance:none;background:transparent;pointer-events:none;}}
          .flare-dual input[type=range]::-webkit-slider-thumb {{appearance:none;-webkit-appearance:none;
            width:16px;height:16px;border-radius:50%;border:1px solid #666;background:white;
            pointer-events:auto;cursor:pointer;}}
          .flare-dual input[type=range]::-moz-range-thumb {{width:16px;height:16px;border-radius:50%;
            border:1px solid #666;background:white;pointer-events:auto;cursor:pointer;}}
          .flare-dual input:disabled::-webkit-slider-thumb {{opacity:.4;cursor:default;}}
          .flare-status {{font-size:11px;color:#666;min-height:14px;text-align:right;}}
        </style>
        <div class="flare-controls">
          <div class="flare-row">
            <div class="flare-label">Cumulative interval</div>
            <div class="flare-single"><input id="flare-interval" type="range" min="0" max="{INTERVAL_COUNT}" step="1" value="{int(step)}"></div>
            <div id="flare-interval-value" class="flare-value">{int(step)}/{INTERVAL_COUNT}</div>
          </div>
          <div class="flare-row">
            <div class="flare-label">Dose range (rem)</div>
            <div class="flare-dual">
              <div id="flare-dose-track" class="track"></div>
              <input id="flare-dose-min" type="range" min="0" max="{len(DOSE_OPTIONS)-1}" step="1" aria-label="Minimum dose threshold">
              <input id="flare-dose-max" type="range" min="0" max="{len(DOSE_OPTIONS)-1}" step="1" aria-label="Maximum dose display value">
            </div>
            <div id="flare-dose-value" class="flare-value"></div>
          </div>
          <div class="flare-row">
            <div class="flare-label">Map/analysis radius (mi)</div>
            <div class="flare-dual">
              <div id="flare-radius-track" class="track"></div>
              <input id="flare-radius-min" type="range" min="0" max="{len(RADIUS_OPTIONS)-1}" step="1" aria-label="Minimum analysis radius">
              <input id="flare-radius-max" type="range" min="0" max="{len(RADIUS_OPTIONS)-1}" step="1" aria-label="Maximum analysis radius">
            </div>
            <div>
              <div id="flare-radius-value" class="flare-value"></div>
              <div id="flare-radius-status" class="flare-status"></div>
            </div>
          </div>
        </div>
        <script>
          (function () {{
            const totalIntervals = {INTERVAL_COUNT};
            const loadedRadius = {float(radius):.12g};
            const doseOptions = {dose_options_json};
            const radiusOptions = {radius_options_json};
            const doseDisabled = {dose_disabled};
            const interval = document.getElementById('flare-interval');
            const doseMin = document.getElementById('flare-dose-min');
            const doseMax = document.getElementById('flare-dose-max');
            const radiusMin = document.getElementById('flare-radius-min');
            const radiusMax = document.getElementById('flare-radius-max');
            const intervalValue = document.getElementById('flare-interval-value');
            const doseValue = document.getElementById('flare-dose-value');
            const radiusValue = document.getElementById('flare-radius-value');
            const radiusStatus = document.getElementById('flare-radius-status');
            let intervalTimer = null, doseTimer = null, radiusTimer = null;
            let radiusExpansionRequestId = null;
            let radiusExpansionTimeout = null;

            function nearestIndex(options, value) {{
              let best = 0, distance = Infinity;
              for (let i = 0; i < options.length; i += 1) {{
                const d = options[i] > 0 && value > 0
                  ? Math.abs(Math.log(options[i] / value)) : Math.abs(options[i] - value);
                if (d < distance) {{ best = i; distance = d; }}
              }}
              return best;
            }}
            function formatValue(value) {{
              const numeric = Number(value);
              if (!Number.isFinite(numeric)) return '';
              if (numeric === 0) return '0';
              const rounded = Number(numeric.toPrecision(3));
              if (Math.abs(rounded) >= 1000) {{
                return rounded.toLocaleString(undefined, {{maximumFractionDigits:0}});
              }}
              return rounded.toPrecision(3)
                .replace(/(\\.\\d*?[1-9])0+$/, '$1')
                .replace(/\\.0+$/, '');
            }}
            function setTrack(track, lower, upper, maximum) {{
              const left = 100 * lower / maximum, right = 100 * upper / maximum;
              track.style.background = 'linear-gradient(to right,#d6d6d6 0%,#d6d6d6 ' + left + '%,#d16b3d ' + left + '%,#d16b3d ' + right + '%,#d6d6d6 ' + right + '%,#d6d6d6 100%)';
            }}
            function constrainPair(lower, upper) {{
              let lo = Number(lower.value), hi = Number(upper.value);
              if (lo >= hi) {{
                if (document.activeElement === lower) lo = Math.max(0, hi - 1);
                else hi = Math.min(Number(upper.max), lo + 1);
                lower.value = String(lo); upper.value = String(hi);
              }}
              return [lo, hi];
            }}
            function post(message) {{
              try {{
                window.parent.document.querySelectorAll('iframe').forEach(function (frame) {{
                  if (frame.contentWindow) frame.contentWindow.postMessage(message, '*');
                }});
              }} catch (error) {{}}
            }}
            function updateUrl(values) {{
              try {{
                const url = new URL(window.parent.location.href);
                Object.keys(values).forEach(function(key) {{ url.searchParams.set(key, String(values[key])); }});
                window.parent.history.replaceState(null, '', url.toString());
              }} catch (error) {{}}
            }}
            function updateInterval(sendMessage) {{
              const value = Math.max(0, Math.min(totalIntervals, Number(interval.value) || 0));
              intervalValue.textContent = value + '/' + totalIntervals;
              updateUrl({{flare_interval:value}});
              if (sendMessage !== false) post({{type:'flare-set-cumulative-interval', interval:value}});
            }}
            function updateDose(sendMessage, commit) {{
              const pair = constrainPair(doseMin, doseMax);
              const minimum = doseOptions[pair[0]], maximum = doseOptions[pair[1]];
              setTrack(document.getElementById('flare-dose-track'), pair[0], pair[1], doseOptions.length - 1);
              doseValue.textContent = formatValue(minimum) + ' – ' + formatValue(maximum);
              updateUrl({{flare_dose_min:minimum, flare_dose_max:maximum}});
              if (sendMessage !== false) post({{type:'flare-set-dose-range', minimum:minimum, maximum:maximum, commit:Boolean(commit)}});
            }}
            function updateRadius(sendMessage, commit) {{
              const pair = constrainPair(radiusMin, radiusMax);
              const minimum = radiusOptions[pair[0]], maximum = radiusOptions[pair[1]];
              setTrack(document.getElementById('flare-radius-track'), pair[0], pair[1], radiusOptions.length - 1);
              radiusValue.textContent = formatValue(minimum) + ' – ' + formatValue(maximum);
              updateUrl({{flare_radius_min:minimum, flare_radius_max:maximum}});
              if (maximum <= loadedRadius * 1.000001) {{
                radiusStatus.textContent = '';
                if (sendMessage !== false) {{
                  post({{type:'flare-set-radius-range', minimum:minimum, maximum:maximum, fitView:false, commit:Boolean(commit)}});
                }}
              }} else {{
                radiusStatus.textContent = 'Release to load expanded extent';
              }}
            }}
            function commitRadiusExpansion(fitView) {{
              clearTimeout(radiusTimer);
              const pair = constrainPair(radiusMin, radiusMax);
              const minimum = radiusOptions[pair[0]], maximum = radiusOptions[pair[1]];
              if (maximum <= loadedRadius * 1.000001) {{
                radiusExpansionRequestId = null;
                if (radiusExpansionTimeout) clearTimeout(radiusExpansionTimeout);
                updateRadius(true, true);
                if (fitView === true) post({{type:'flare-reset-view', maximum:maximum}});
                return;
              }}
              const requestId = Date.now().toString(36) + '-' + Math.random().toString(36).slice(2);
              radiusExpansionRequestId = requestId;
              radiusStatus.textContent = 'Loading expanded extent…';
              updateUrl({{flare_radius_min:minimum, flare_radius_max:maximum}});
              const request = {{
                type:'flare-radius-expansion-request',
                requestId:requestId,
                minimum:minimum,
                maximum:maximum,
                fitView:fitView === true
              }};
              // Send a few identical requests because the zero-height bridge iframe
              // may still be completing its first render.  The bridge de-duplicates
              // requestId values before returning a component value to Streamlit.
              [0, 140, 420].forEach(function(delay) {{
                window.setTimeout(function() {{
                  if (radiusExpansionRequestId === requestId) post(request);
                }}, delay);
              }});
              if (radiusExpansionTimeout) clearTimeout(radiusExpansionTimeout);
              radiusExpansionTimeout = window.setTimeout(function() {{
                if (radiusExpansionRequestId === requestId) {{
                  radiusExpansionRequestId = null;
                  radiusStatus.textContent = 'Could not start expansion; release the slider again';
                }}
              }}, 1800);
            }}

            interval.addEventListener('input', function() {{
              updateInterval(false);
              clearTimeout(intervalTimer);
              intervalTimer = setTimeout(function() {{updateInterval(true);}}, 60);
            }});
            interval.addEventListener('change', function() {{
              clearTimeout(intervalTimer);
              updateInterval(true);
            }});
            doseMin.addEventListener('input', function() {{ clearTimeout(doseTimer); doseTimer = setTimeout(function() {{updateDose(true, false);}}, 90); }});
            doseMax.addEventListener('input', function() {{ clearTimeout(doseTimer); doseTimer = setTimeout(function() {{updateDose(true, false);}}, 90); }});
            doseMin.addEventListener('change', function() {{ clearTimeout(doseTimer); updateDose(true, true); }});
            doseMax.addEventListener('change', function() {{ clearTimeout(doseTimer); updateDose(true, true); }});
            radiusMin.addEventListener('input', function() {{ clearTimeout(radiusTimer); radiusTimer = setTimeout(function() {{updateRadius(true, false);}}, 90); }});
            radiusMax.addEventListener('input', function() {{ clearTimeout(radiusTimer); radiusTimer = setTimeout(function() {{updateRadius(true, false);}}, 90); }});
            radiusMin.addEventListener('change', commitRadiusExpansion);
            radiusMax.addEventListener('change', commitRadiusExpansion);
            window.addEventListener('message', function(event) {{
              if (!event || !event.data) return;
              if (event.data.type === 'flare-reset-view-request') {{
                commitRadiusExpansion(true);
                return;
              }}
              if (event.data.type !== 'flare-radius-expansion-accepted') return;
              if (event.data.requestId !== radiusExpansionRequestId) return;
              if (radiusExpansionTimeout) clearTimeout(radiusExpansionTimeout);
              radiusStatus.textContent = 'Recalculating expanded extent…';
            }});

            doseMin.value = String(nearestIndex(doseOptions, {float(minimum_dose):.12g}));
            doseMax.value = String(nearestIndex(doseOptions, {float(maximum_dose):.12g}));
            radiusMin.value = String(nearestIndex(radiusOptions, {float(minimum_radius):.12g}));
            radiusMax.value = String(nearestIndex(radiusOptions, {float(radius):.12g}));
            doseMin.disabled = doseDisabled; doseMax.disabled = doseDisabled;
            intervalValue.textContent = interval.value + '/' + totalIntervals;
            updateDose(false, false); updateRadius(false, false);
            window.setTimeout(function() {{ post({{type:'flare-request-map-state'}}); }}, 500);
          }})();
        </script>
        """,
        height=142,
    )

map_state = st_folium(
    m,
    use_container_width=False,
    width=620,
    height=620,
    # Only map clicks are returned to Python. Pan and zoom remain entirely
    # inside Leaflet, so repeated zoom refinements do not rerun Streamlit.
    returned_objects=["last_clicked"],
    key=f"flare_population_map_{st.session_state.get('map_revision', 0)}",
)

# Keep ordinary map interaction in pan mode.  A click is consumed only after the
# user explicitly arms location selection in the sidebar.  Coordinates are staged
# in non-widget keys and applied at the beginning of the next Streamlit run.
last_clicked = map_state.get("last_clicked") if map_state else None
if last_clicked and st.session_state.get("location_pick_armed", False):
    new_lat = float(last_clicked["lat"])
    new_lon = float(last_clicked["lng"])
    click_signature = f"{new_lat:.8f},{new_lon:.8f}"
    if click_signature != st.session_state.get("last_consumed_map_click"):
        try:
            # Persist before rerunning.  A browser refresh therefore starts from
            # this accepted click rather than from the fallback location.
            save_site_location(new_lat, new_lon, source="map_selection")
            st.session_state.pop("site_location_save_error", None)
        except Exception as exc:
            st.session_state.site_location_save_error = str(exc)
            st.session_state.location_pick_armed = False
            st.rerun()

        st.session_state.last_consumed_map_click = click_signature
        st.session_state.pending_site_lat = new_lat
        st.session_state.pending_site_lon = new_lon
        st.session_state.location_pick_armed = False
        st.rerun()

if case is not None:
    legend_data_json = json.dumps(report_payload["legend"], ensure_ascii=False).replace("</", "<\\/")
    analysis_rows_by_interval = report_payload["summary_by_interval"]
    analysis_rows_json = json.dumps(analysis_rows_by_interval, ensure_ascii=False).replace("</", "<\\/")
    workbook_json = json.dumps(str(workbook_display), ensure_ascii=False).replace("</", "<\\/")
    legend_column, analysis_column = st.columns([1.05, 1.95], gap="medium")
    with legend_column:
        st.iframe(
            f"""
            <div id="flare-legend-panel" style="border:1px solid #777;border-radius:7px;
                 background:white;padding:10px 12px;font:13px/1.25 Arial,sans-serif;color:#222;
                 box-sizing:border-box;overflow-wrap:anywhere;">
              <div id="flare-legend-title" style="font-weight:700;font-size:15px;margin-bottom:7px;"></div>
              <div id="flare-legend-items"></div>
              <div id="flare-legend-note" style="margin-top:7px;color:#444;"></div>
            </div>
            <script>
              (function () {{
                let currentLegend = {legend_data_json};
                const title = document.getElementById('flare-legend-title');
                const items = document.getElementById('flare-legend-items');
                const note = document.getElementById('flare-legend-note');
                function render(legend) {{
                  if (!legend) return;
                  currentLegend = legend;
                  title.textContent = String(legend.title || 'Legend');
                  items.innerHTML = '';
                  (legend.items || []).forEach(function(item) {{
                    const row = document.createElement('div');
                    row.style.cssText = 'display:flex;align-items:center;gap:7px;margin:4px 0;';
                    const swatch = document.createElement('span');
                    swatch.style.cssText = 'width:22px;height:14px;border:1px solid #666;display:inline-block;flex:0 0 auto;background:' + item.color + ';';
                    const label = document.createElement('span');
                    label.textContent = String(item.label);
                    row.appendChild(swatch); row.appendChild(label); items.appendChild(row);
                  }});
                  note.textContent = String(legend.note || '');
                }}
                window.addEventListener('message', function(event) {{
                  if (event && event.data && event.data.type === 'flare-map-state-updated' && event.data.legend) {{
                    render(event.data.legend);
                  }}
                }});
                render(currentLegend);
              }})();
            </script>
            """,
            # height="content" lets st.iframe measure the panel and size the
            # frame to it. This replaces a hardcoded pixel height that clipped
            # long values and the legend note on narrow windows.
            height="content",
        )
    with analysis_column:
        st.iframe(
            f"""
            <div id="flare-analysis-panel" style="border:1px solid #bbb;border-radius:7px;
                 background:white;padding:10px 12px;font:13px/1.35 Arial,sans-serif;color:#222;
                 box-sizing:border-box;overflow-wrap:anywhere;">
              <div style="font-weight:700;font-size:15px;margin-bottom:8px;">Analysis summary</div>
              <div id="flare-analysis-grid" style="display:grid;
                   grid-template-columns:repeat(auto-fit,minmax(232px,1fr));
                   column-gap:18px;row-gap:6px;"></div>
              <div style="margin-top:10px;padding-top:8px;border-top:1px solid #ccc;">
                <b>Source workbook</b><br><span id="flare-source-workbook"></span>
              </div>
            </div>
            <script>
              (function () {{
                const rowsByInterval = {analysis_rows_json};
                const workbook = {workbook_json};
                const grid = document.getElementById('flare-analysis-grid');
                document.getElementById('flare-source-workbook').textContent = workbook;
                let state = {{interval:{int(step)}, elapsed:{float(current_elapsed_hr):.12g}, minimumDose:{float(minimum_dose):.12g},
                  maximumDose:{float(maximum_dose):.12g}, minimumRadius:{float(minimum_radius):.12g},
                  maximumRadius:{float(radius):.12g}, bearing:{float(result.bearing_deg):.12g},
                  population:{float(scenario_population_above_threshold):.12g}}};

                function rowsForState() {{
                  const bounded = Math.max(0, Math.min(rowsByInterval.length - 1, Math.round(Number(state.interval) || 0)));
                  return (rowsByInterval[bounded] || []).map(function(row) {{
                    const next = {{label:String(row.label), value:String(row.value)}};
                    if (next.label === 'Selected pathway') next.value = Number(state.bearing || 0).toFixed(1) + '°';
                    else if (next.label === 'Current elapsed time') next.value = Number(state.elapsed || 0).toPrecision(3) + ' hr';
                    else if (next.label === 'Cumulative interval') next.value = bounded + '/{INTERVAL_COUNT}';
                    else if (next.label === 'Population above threshold' && state.population !== null && state.population !== undefined) next.value = Math.round(Number(state.population) || 0).toLocaleString();
                    else if (next.label === 'Map maximum' && {str(radiological_layer == 'Airborne dose').lower()}) next.value = Number(state.maximumDose).toPrecision(3) + ' rem display maximum';
                    else if (next.label === 'Dose threshold') next.value = Number(state.minimumDose).toPrecision(3) + ' rem';
                    else if (next.label === 'Analysis radius range') next.value = Number(state.minimumRadius).toFixed(3) + '-' + Number(state.maximumRadius).toFixed(3) + ' miles';
                    return next;
                  }});
                }}
                function render() {{
                  grid.innerHTML = '';
                  rowsForState().forEach(function(row) {{
                    const item = document.createElement('div');
                    item.style.display = 'grid';
                    item.style.gridTemplateColumns = 'minmax(125px, 1fr) minmax(70px, auto)';
                    item.style.columnGap = '8px';
                    const label = document.createElement('b'); label.textContent = row.label;
                    const value = document.createElement('span'); value.textContent = row.value; value.style.textAlign = 'right';
                    item.appendChild(label); item.appendChild(value); grid.appendChild(item);
                  }});
                }}
                window.addEventListener('message', function(event) {{
                  if (event && event.data && event.data.type === 'flare-map-state-updated') {{
                    state = Object.assign(state, {{
                      interval:event.data.interval, elapsed:event.data.elapsed,
                      minimumDose:event.data.minimumDose, maximumDose:event.data.maximumDose,
                      minimumRadius:event.data.minimumRadius, maximumRadius:event.data.maximumRadius,
                      bearing:event.data.bearing, population:event.data.population
                    }});
                    render();
                  }}
                }});
                render();
              }})();
            </script>
            """,
            # height="content" lets st.iframe measure the panel and size the
            # frame to it. This replaces a hardcoded pixel height that clipped
            # long values and the legend note on narrow windows.
            height="content",
        )

    st.iframe(
        """
        <div style="display:flex;justify-content:center;margin-top:24px;">
          <button id="flare-export-report" type="button"
            style="border:1px solid #777;border-radius:7px;padding:0.55rem 1rem;cursor:pointer;
                   background:white;color:#222;font:600 14px system-ui,sans-serif;">
            Download report-quality PDF
          </button>
        </div>
        <div id="flare-export-status" style="text-align:center;margin-top:4px;
             color:#555;font:12px system-ui,sans-serif;min-height:16px;"></div>
        <script>
          const button = document.getElementById('flare-export-report');
          const status = document.getElementById('flare-export-status');
          button.addEventListener('click', function () {
            button.disabled = true;
            status.textContent = 'Generating centered map report…';
            let delivered = false;
            try {
              const frames = window.parent.document.querySelectorAll('iframe');
              frames.forEach(function (frame) {
                if (frame.contentWindow) {
                  frame.contentWindow.postMessage({type: 'flare-export-report-pdf'}, '*');
                  delivered = true;
                }
              });
            } catch (error) {
              console.error(error);
            }
            if (!delivered) {
              status.textContent = 'Could not contact the map component.';
            }
            window.setTimeout(function () {
              button.disabled = false;
              status.textContent = '';
            }, 5000);
          });
        </script>
        """,
        height=78,
    )
