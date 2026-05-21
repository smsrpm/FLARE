# flare_model_editor.py
# FLARE Model Editor with Validator and subfolder input-file discovery
#
# Supports FLARE input files stored in subfolders below the FLARE root.
# Root-level *_in.xlsx files are intentionally ignored to match the current
# FLARE project organization.

import streamlit as st
from openpyxl import load_workbook
from pathlib import Path
import shutil
import re

st.set_page_config(layout="wide", page_title="FLARE Model Editor")

WORK_DIR = Path(__file__).parent

# ── Input discovery helpers ──────────────────────────────────────────────────

_EXCLUDE_DIR_PREFIXES = (
    "sim_",
    "risk_",
    "ua_",
    ".sim_all_",
)
_EXCLUDE_DIR_NAMES = {
    "__pycache__",
    "runtime",
    "Runtime",
    "icons",
    "Icons",
    "manuals",
    "Manuals",
    "install",
    ".git",
    ".streamlit",
}


def _is_generated_or_support_path(path: Path) -> bool:
    """Return True if path is inside a generated/support folder to exclude."""
    try:
        rel_parts = path.relative_to(WORK_DIR).parts
    except Exception:
        rel_parts = path.parts

    for part in rel_parts[:-1]:
        if part in _EXCLUDE_DIR_NAMES:
            return True
        if any(part.startswith(prefix) for prefix in _EXCLUDE_DIR_PREFIXES):
            return True
    return False


def find_case_files():
    """
    Find FLARE input files in subfolders below WORK_DIR.

    Root-level *_in.xlsx files are intentionally ignored.  Generated folders
    such as sim_*, risk_*, ua_*, and .sim_all_* are also ignored.
    """
    found = []
    for p in WORK_DIR.rglob("*_in.xlsx"):
        if p.parent == WORK_DIR:
            continue
        if p.name.startswith(".~") or p.stem.startswith("ua_"):
            continue
        if _is_generated_or_support_path(p):
            continue
        found.append(p)

    # Deduplicate and sort by case name, then folder.
    found = sorted(set(found), key=lambda x: (x.stem.lower(), str(x.parent).lower()))
    return found


def case_label(path: Path) -> str:
    case_name = path.stem.replace("_in", "")
    rel_dir = path.parent.relative_to(WORK_DIR)
    return f"{case_name}  —  {rel_dir}"


# ── Styling ──────────────────────────────────────────────────────────────────
st.markdown("""
<style>
section[data-testid="stSidebar"] { background: #1a1f2e !important; }
section[data-testid="stSidebar"] button {
    background-color: #2a3145 !important;
    color: #e6edf3 !important;
    border: 1px solid #3b435c !important;
    border-radius: 8px !important;
}
section[data-testid="stSidebar"] button:hover {
    background-color: #343c55 !important;
    box-shadow: 0 0 6px rgba(100,150,255,0.6);
}
section[data-testid="stSidebar"] * { color: #e6edf3 !important; }
/* Exclude selectbox internals from the wildcard so Streamlit renders its own default colors */
section[data-testid="stSidebar"] [data-baseweb="select"] *,
section[data-testid="stSidebar"] [data-baseweb="select"] input {
    color: unset !important;
}

/* Force dark text inside selectbox controls */
section[data-testid="stSidebar"] [data-baseweb="select"] span,
section[data-testid="stSidebar"] [data-baseweb="select"] div,
section[data-testid="stSidebar"] [data-baseweb="select"] input,
section[data-testid="stSidebar"] [data-baseweb="select"] * {
    color: #111111 !important;
    -webkit-text-fill-color: #111111 !important;
}

/* Selected value background */
section[data-testid="stSidebar"] [data-baseweb="select"] > div {
    background: #ffffff !important;
}

/* Dropdown menu items */
div[role="listbox"] *,
ul[role="listbox"] * {
    color: #111111 !important;
    -webkit-text-fill-color: #111111 !important;
}
/* Caption code blocks: transparent bg so path doesn't appear as a dark block */
section[data-testid="stSidebar"] code {
    background: transparent !important;
}
</style>
""", unsafe_allow_html=True)


# ── Helpers ──────────────────────────────────────────────────────────────────

def load_rows(path):
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = [(i, row[0]) for i, row in enumerate(ws.iter_rows(max_col=1, values_only=True), 1)]
    wb.close()
    return rows


def build_sections(rows):
    sections, current = [], None
    banner_lines = []
    prev_blank, in_banner = True, True

    for i, (r, text) in enumerate(rows):
        raw = "" if text is None else str(text)
        stripped = raw.strip()

        if stripped == "":
            prev_blank = True
            continue

        # lookahead
        next_nonblank, intervening_hash = None, False
        for j in range(i + 1, len(rows)):
            nxt = rows[j][1]
            if nxt is None:
                continue
            nxt = str(nxt).strip()
            if not nxt:
                continue
            if nxt.startswith("#"):
                intervening_hash = True
                break
            next_nonblank = nxt
            break

        if in_banner:
            if stripped.startswith("#"):
                if next_nonblank and "=" in next_nonblank and not intervening_hash:
                    in_banner = False
                else:
                    banner_lines.append(stripped[1:].strip())
                    prev_blank = False
                    continue
            else:
                in_banner = False

        if stripped.startswith("#") and prev_blank:
            current = {"name": stripped[1:].strip(), "vars": []}
            sections.append(current)
            prev_blank = False
            continue

        if "=" in stripped:
            if current is None:
                current = {"name": "Unlabeled (Top Block)", "vars": []}
                sections.append(current)

            key, val = [x.strip() for x in stripped.split("=", 1)]
            try:
                val = float(val)
            except Exception:
                pass

            current["vars"].append({"row": r, "key": key, "value": val})

        prev_blank = False

    return "\n".join(banner_lines), sections


def validate(rows):
    issues, prev_blank, in_banner = [], True, True
    for r, text in rows:
        raw = "" if text is None else str(text)
        stripped = raw.strip()

        if stripped == "":
            prev_blank = True
            continue

        if in_banner:
            if stripped.startswith("#"):
                prev_blank = False
                continue
            else:
                in_banner = False

        if stripped.startswith("#") and not prev_blank:
            issues.append(f"Line {r}: '#' not preceded by blank line")

        prev_blank = False
    return issues


def apply_updates(path, updates, banner_text):
    wb = load_workbook(path)
    ws = wb.active

    row_idx = 1
    for line in banner_text.split("\n"):
        ws.cell(row=row_idx, column=1).value = "#   " + line
        row_idx += 1

    for row, key, new_val in updates:
        cell = ws.cell(row=row, column=1)
        if isinstance(cell.value, str) and "=" in cell.value:
            cell.value = re.sub(
                r"(\b" + re.escape(key) + r"\s*=\s*)(.*)",
                r"\1" + str(new_val),
                cell.value,
            )

    out = path.with_name(path.stem + "_edited.xlsx")
    wb.save(out)
    wb.close()
    return out


# ── FLARE Home button ────────────────────────────────────────────────────────
st.sidebar.markdown("""
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
if st.sidebar.button("\U0001f525  FLARE Home", key="home_btn", width="stretch"):
    st.session_state.page = "home"
    st.query_params.clear()
    st.rerun()
st.sidebar.divider()

# ── UI Modes ─────────────────────────────────────────────────────────────────
mode = st.sidebar.radio("Mode", ["Model Editor", "Validator", "New Model"])

case_files = find_case_files()

if not case_files:
    st.error(
        "No *_in.xlsx files found in FLARE subfolders.\n\n"
        "Input files are now expected in subfolders below the FLARE root. "
        "Root-level input files and generated folders such as sim_*, risk_*, "
        "ua_*, and .sim_all_* are ignored."
    )
    st.stop()

label_to_path = {case_label(p): p for p in case_files}
selected_label = st.sidebar.selectbox("Select Case", list(label_to_path.keys()))
file_path = label_to_path[selected_label]
rows = load_rows(file_path)

st.sidebar.markdown("---")
st.sidebar.caption(f"Selected file:\n`{file_path.relative_to(WORK_DIR)}`")

with open(file_path, "rb") as _fh:
    st.sidebar.download_button(
        label="⬇ Download Model",
        data=_fh,
        file_name=file_path.name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

# ── NEW MODEL MODE ───────────────────────────────────────────────────────────
if mode == "New Model":
    st.title("Create New Model from Template")
    st.markdown(f"Template: `{file_path.relative_to(WORK_DIR)}`")

    new_name = st.text_input("Enter new model name (without _in.xlsx)")
    same_folder = st.checkbox("Create in same folder as template", value=True)
    if same_folder:
        target_dir = file_path.parent
    else:
        target_dir_label = st.selectbox(
            "Target folder",
            sorted({str(p.parent.relative_to(WORK_DIR)) for p in case_files}),
        )
        target_dir = WORK_DIR / target_dir_label

    if st.button("Create Model"):
        if not new_name:
            st.error("Please provide a name.")
        else:
            safe_name = new_name.strip()
            if safe_name.endswith("_in.xlsx"):
                new_file = target_dir / safe_name
            elif safe_name.endswith(".xlsx"):
                new_file = target_dir / safe_name
            else:
                new_file = target_dir / f"{safe_name}_in.xlsx"

            if new_file.exists():
                st.error(f"File already exists: `{new_file.relative_to(WORK_DIR)}`")
            else:
                shutil.copy(file_path, new_file)
                st.success(f"Created: `{new_file.relative_to(WORK_DIR)}`")

# ── VALIDATOR MODE ───────────────────────────────────────────────────────────
elif mode == "Validator":
    st.title("FLARE Input Validator")
    st.subheader(file_path.stem.replace("_in", ""))
    st.caption(str(file_path.relative_to(WORK_DIR)))

    issues = validate(rows)

    if not issues:
        st.success("File complies with formatting rules.")
    else:
        st.error(f"{len(issues)} issue(s) found")
        for issue in issues:
            st.write(issue)

# ── EDITOR MODE ──────────────────────────────────────────────────────────────
else:
    st.title("FLARE Input Model Editor")
    case_name = file_path.stem.replace("_in", "")
    st.subheader(case_name)
    st.caption(str(file_path.relative_to(WORK_DIR)))

    banner_text, sections = build_sections(rows)

    if "section" not in st.session_state:
        st.session_state.section = "Banner"

    st.sidebar.markdown("---")
    st.sidebar.header("Model Sections")

    if st.sidebar.button("Banner Header", use_container_width=True):
        st.session_state.section = "Banner"

    for sec in sections:
        if st.sidebar.button(sec["name"], use_container_width=True):
            st.session_state.section = sec["name"]

    updates = []

    if st.session_state.section == "Banner":
        st.header("Banner Header")
        banner_text = st.text_area("Edit Header", value=banner_text, height=200)
    else:
        section = next((s for s in sections if s["name"] == st.session_state.section), None)
        if section is None:
            st.session_state.section = "Banner"
            st.rerun()

        st.header(section["name"])

        for var in section["vars"]:
            col1, col2 = st.columns([2, 2])
            with col1:
                st.text(var["key"])
            with col2:
                new_val = st.text_input(
                    var["key"],
                    value=str(var["value"]),
                    key=f"{file_path}_{section['name']}_{var['key']}",
                )
            updates.append((var["row"], var["key"], new_val))

    if st.button("Save Updated Excel"):
        out = apply_updates(file_path, updates, banner_text)
        st.success(f"Saved to `{out.relative_to(WORK_DIR)}`")

st.sidebar.markdown("---")
st.sidebar.caption(f"Working Dir:\n`{WORK_DIR}`")
