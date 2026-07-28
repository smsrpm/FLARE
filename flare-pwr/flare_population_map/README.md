# FLARE Maximum-Population Plume Prototype

> This package is the Dose Map screen of the FLARE Plant Analyzer. Its Python
> dependencies are part of the merged `requirements.txt` at the FLARE root; it
> no longer keeps a separate requirements file.

This standalone prototype establishes three separable components:

1. **Population database** — a compact, boundary-free SQLite table of occupied grid cells.
2. **Maximum-population pathway search** — rotates the plume through 360 degrees and identifies either the greatest population-dose score or the greatest population inside the plume.
3. **Map interface** — Folium rendering with an optional Streamlit front end.

The calculation module has no Streamlit dependency and can later be imported by NOTBADTRAD.

## Immediate demonstration

The included demo database is synthetic and centered near Lynchburg, Virginia.

```bash
python tools/make_demo_database.py
pip install -r ../requirements.txt
streamlit run flare_map.py
```

## Build an official Census-derived database

The development utility combines two official 2020 Census products:

- P.L. 94-171 total population at block level (`P1_001N`)
- TIGER/Line tabulation-block attributes, including `GEOID20` and internal-point coordinates

Example for Virginia and North Carolina:

```bash
python tools/build_from_census.py --states 51 37 --output data/population_2020.sqlite --grid-km 1.0
```

For a national build, supply all state FIPS codes. State files are only an input convention used by Census; the final SQLite database contains no state partitions and queries cross borders automatically.

## Database schema

```sql
population_cells(
    cell_id INTEGER PRIMARY KEY,
    latitude REAL,
    longitude REAL,
    population INTEGER
)
```

Only occupied cells are retained. The current builder uses a nominal 1-km grid. Resolution can be changed at build time without changing the runtime API.

## Current plume model

The prototype uses a wedge defined by:

- site latitude and longitude;
- maximum radius;
- centerline bearing;
- plume half-angle.

The search rotates the wedge and sums population. Three provisional radial weights are supplied. Later, NOTBADTRAD dose-versus-distance values can replace these weights without changing the map/database architecture.

## Important limitations

- The demonstration database is synthetic.
- Census block population is represented by the block internal point before grid aggregation.
- The current longitude gridding is intentionally simple and should be reviewed before a production national build.
- The plume is a geometric screening depiction, not a meteorological dispersion calculation.

## Production national build

The production builder now reads `POP20`, `INTPTLAT20`, and `INTPTLON20`
directly from the updated 2020 TIGER/Line tabulation-block files. Polygon
geometry is not loaded. The build is resumable and all source areas accumulate
into one common national grid, so cells at state borders are merged rather than
partitioned.

```bash
python tools/build_national_census.py \
  --scope all \
  --grid-km 1.0 \
  --output data/population_2020_national.sqlite
```

Use `--scope core` for the 50 states, District of Columbia, and Puerto Rico;
`--scope all` additionally includes American Samoa, Guam, the Commonwealth of
the Northern Mariana Islands, and the U.S. Virgin Islands. Downloaded source
ZIPs are deleted after each area by default to limit temporary disk use. Pass
`--keep-zips` to retain them. Interrupted builds resume from `build_progress`.

## Fast national build pipeline

The national builder now avoids shapefile geometry completely. For each Census
TABBLOCK20 ZIP it extracts only the DBF member, streams `POP20`, `INTPTLAT20`,
and `INTPTLON20`, and aggregates occupied blocks before writing them to a
resumable DuckDB staging file. The final national merge is performed once and
exported to the SQLite file used by the Streamlit application.

```bash
pip install -r ../requirements.txt
python tools/build_national_census.py \
  --scope all \
  --grid-km 1.0 \
  --output data/population_2020_national.sqlite
```

Interrupted builds may be rerun with the same command. Completed Census source
areas are skipped. Use `--finalize-only` to recreate the SQLite runtime database
from an already-complete DuckDB staging database.

## Windows launcher

Double-click `Launch_FLARE_Population_Map.bat`. The launcher:

- locates Python 3.11 or newer;
- creates an isolated `.venv` environment in the project folder;
- installs or repairs the libraries in the FLARE root `requirements.txt`;
- validates required project files and Python syntax;
- verifies the SQLite population database schema and integrity;
- regenerates the synthetic demonstration database if it is missing or damaged;
- automatically selects the national Census database when present; and
- launches the Streamlit interface.

The national database is not rebuilt automatically during ordinary launch because
that is a separate, long-running development operation. If it is absent, the tool
opens with the clearly labeled synthetic demonstration database.

## On-demand national database builder

The builder is distributed with the application. Double-click:

```text
Build_National_Population_Database.bat
```

The builder creates or resumes:

```text
data\population_2020_national.sqlite
```

It verifies Python and required libraries, downloads the official 2020 Census
TIGER/Line tabulation-block files, reads only the DBF population and internal-point
attributes, aggregates them into a seamless nominal 1-km national grid, validates
the result, and writes the SQLite runtime database. Interrupted builds are
resumable.

The ordinary launcher also detects a missing national database and offers three
choices: build it, launch with the synthetic Lynchburg demonstration database, or
exit. Once the national database exists, the application selects it automatically.

## Circular analysis map

The Streamlit display uses a circular map viewport. Its perimeter corresponds to the user-selected analysis radius, which defaults to 10 miles. The map remains zoomable and pannable within the circular frame. A small upper-left extension of the viewport mask exposes Leaflet's native zoom buttons without moving them. Pan and zoom changes remain entirely browser-local and therefore do not rerun Streamlit. **Reset View** precisely recenters the release site in the circular opening and refits the current radius. The two-ended map-side radius slider uses 56 discrete snap points from 0 to 100 miles (for example 0.10, 0.15, 0.20; 1.0, 1.5, 2.0; 10, 15, 20). Changes within the loaded domain remain browser-local. Increasing the outer radius beyond the currently loaded extent sends one committed value through a small Streamlit component bridge, then performs one deliberate population/consequence recalculation.

## Enhanced dose-informed lateral-dispersion model

Upload a FLARE output workbook containing the `Input Echo` and `Dose` sheets.
The application reads the existing NOTBADTRAD inputs and outputs directly:

- `nbt_stability_class`
- `nbt_wind_speed_m_s`
- `nbt_release_height_m`
- release and dose-integration durations
- the NOTBADTRAD centerline TEDE-versus-distance table

The centerline dose is preserved. Lateral spreading uses a rural
Pasquill-Gifford/Turner horizontal correlation by stability class:

```text
sigma_y = a x / sqrt(1 + b x)
```

A bounded, duration-dependent low-wind meander multiplier is applied below
1 m/s. The two-dimensional dose is then:

```text
D(x,y) = D_centerline(x) exp[-y^2/(2 sigma_y^2)]
```

The plume is rotated through 360 degrees. The user can select either the bearing that maximizes the population-dose score or the bearing containing the greatest population inside the dose-defined plume footprint. The displayed footprint edge defaults to 1 percent of
the centerline dose and can be changed in the interface. The population count
uses a separately selected absolute dose threshold, defaulting to 0.01 rem.

This is a reduced-order screening model. It is intended to provide a traceable,
case-specific visualization without introducing an online meteorological or
dispersion-service dependency.

## Map layer controls

The Streamlit sidebar includes independent controls for:

- population density,
- plume footprint,
- analysis-radius boundary.

Turn off **Show population density** to inspect the plume by itself. The plume uses a bold orange outline, translucent orange fill, and dashed centerline so it remains distinguishable from the population heat map.

## Airborne dose and synthetic deposition layers

After a FLARE output workbook is loaded, the sidebar offers two radiological views:

- **Airborne dose** uses the NOTBADTRAD centerline dose-distance curve and the enhanced Gaussian lateral-dispersion correlation. All time-step legends use one fixed scale based on the final LPZ maximum for the selected scenario.
- **Ground deposition** creates a synthetic relative deposition field from the source-term groups and FLARE gap and early-in-vessel release intervals already present in the output workbook. The dominant release interval is fixed on the maximum-population pathway. Other release intervals receive deterministic, bounded offsets about that same pathway; they do not form a random walk.

The deposition selector supports total depositing inventory or an individual depositing release group. Noble gases are excluded from deposition. Every interval is normalized to the final LPZ maximum for the selected scenario and release group, so early frames remain below 100% and progression is directly visible. The values are intended as a reduced-order visualization, not a reconstruction of site-specific weather or measured contamination.

When a workbook is first loaded, the map opens on the off-site annulus: the inner radius is taken from `nbt_distance_eab_m`, the exclusion-area boundary, and the outer radius is the conventional 10-mile plume-exposure EPZ radius. There is no resident population inside the EAB, so the population and dose figures on this screen concern the region beyond it. The user may then override both radii with the two-ended slider above the map. If a workbook carries no readable EAB distance, no inner cut is applied.

Earlier versions used `nbt_distance_eab_m` as the *outer* radius, which zoomed the map to a few hundred metres and hid the surrounding population.

## Time-Evolving Consequence Footprint

The application now constructs 24 cumulative synthetic intervals between the
FLARE EAB and LPZ integration times. Step 0 is the EAB cumulative anchor and
step 24 is the LPZ cumulative anchor. Intermediate states interpolate the
centerline dose curves and accumulate each interval contribution on a
radial/azimuthal field.

Two meteorological scenarios are available:

- **Conservative maximum-population pathway** keeps every interval centerline on
  the bearing that maximizes the population-dose score. Wind speed and stability
  vary internally, changing transport and lateral spreading without redirecting
  the predominant pathway.
- **Better-estimate synthetic meteorology** uses a deterministic, bounded,
  mean-reverting directional sequence. The same workbook and site always
  reproduce the same sequence.

The filled map can display cumulative airborne TEDE or cumulative synthetic
relative deposition for a selected depositing release group. No additional
FLARE input or meteorological file is required. The cumulative-interval, dose-range,
and map/analysis-radius sliders are rendered in the persistent browser-side map
interface. Interval and dose changes update the existing Leaflet overlay without
rebuilding the basemap or rerunning Streamlit. The dose-range slider uses discrete
three-significant-digit snap points whose third significant digit is 0 or 5
(for example 1.00, 1.05, 1.10, 1.15, and 1.20 rem). Radius changes within the
loaded extent are also browser-local; only an expansion beyond that extent triggers
a single Python recalculation. The native consequence-grid dimensions and the
existing 960-pixel rendered overlay resolution are retained.

Use **Select new location on map** in the sidebar to arm a one-time site pick.
The map remains pannable; the next click updates the sidebar coordinates and
reruns the population-pathway and consequence calculations at that location.
Ordinary clicks are ignored when location selection is not armed.

The **Prepare updated FLARE output workbook** button creates a copy of the
uploaded output workbook containing:

- `Footprint Summary`
- `Footprint Intervals`
- `Footprint Spatial`

The spatial table records cumulative airborne TEDE and relative deposition at
48 radial bins and 72 azimuth bins for the EAB anchor and all 24 synthetic
intervals. The result is a synthetic consequence scenario, not a site-specific
meteorological reconstruction.

- Use **Select new location on map** in the sidebar, pan as needed, then click once to update the site coordinates and rerun the analysis.
### Map zoom behavior

Use the visible Leaflet **+ / −** buttons to zoom. Mouse-wheel zoom is disabled so scrolling over the map or its exposed zoom-control tab continues to scroll the Streamlit page instead of changing the map scale.

