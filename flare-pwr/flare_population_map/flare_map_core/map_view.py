"""Folium map rendering kept separate from the calculation."""
from __future__ import annotations

import base64
import gzip
import json
import math

import folium
import pandas as pd
import numpy as np
from branca.element import Element, MacroElement, Template
from folium.plugins import HeatMap
from folium.utilities import image_to_url

from .core import local_xy_miles, plume_polygon
from .deposition import synthetic_deposition_field
from .dispersion import half_width_m, sigma_y_m


# Low-to-high dose colors. The numerical limits are generated from each case.
_DOSE_COLORS = ["#ffffb2", "#fed976", "#feb24c", "#fd8d3c", "#f03b20", "#bd0026"]
_DEPOSITION_COLORS = ["#313695", "#4575b4", "#74add1", "#abd9e9", "#ffffbf", "#fdae61", "#f46d43", "#a50026"]

# Pre-render raster overlays at a resolution substantially above the numerical
# consequence grid. Leaflet still uses one georeferenced image, but zooming now
# exposes a much denser, smoothly interpolated raster instead of the native cells.
_MAX_OVERLAY_PIXELS = 960


def _encode_field_stack(fields: tuple[np.ndarray, ...]) -> dict:
    """Compactly encode full native consequence grids for browser-side rendering.

    Every native grid cell is retained. Positive values are logarithmically mapped
    to 16-bit integers before frame-to-frame XOR and gzip compression. The mapping
    has substantially finer precision than the six displayed color bands while
    avoiding any spatial downsampling. Browser rendering still uses the existing
    ``_MAX_OVERLAY_PIXELS`` bilinear overlay resolution.
    """
    if not fields:
        return {"rows": 0, "cols": 0, "count": 0, "maxima": [], "floors": [], "encoding": "", "data": ""}
    first = np.asarray(fields[0], dtype=float)
    if first.ndim != 2:
        raise ValueError("Consequence fields must be two-dimensional")
    rows, cols = first.shape
    quantized_fields = []
    maxima = []
    floors = []
    for field in fields:
        values = np.asarray(field, dtype=float)
        if values.shape != (rows, cols):
            raise ValueError("All consequence fields must use the same grid")
        values = np.where(np.isfinite(values) & (values > 0.0), values, 0.0)
        maximum = float(np.max(values, initial=0.0))
        maxima.append(maximum)
        quantized = np.zeros((rows, cols), dtype="<u2")
        if maximum > 0.0:
            floor = max(maximum * 1.0e-12, 1.0e-30)
            positive = values > 0.0
            scaled = (
                np.log(np.maximum(values[positive], floor)) - math.log(floor)
            ) / max(math.log(maximum) - math.log(floor), 1.0e-30)
            quantized[positive] = (
                1 + np.rint(np.clip(scaled, 0.0, 1.0) * 65534.0)
            ).astype("<u2")
        else:
            floor = 0.0
        floors.append(floor)
        quantized_fields.append(quantized)

    stacked = np.ascontiguousarray(np.stack(quantized_fields, axis=0), dtype="<u2")
    encoded = stacked.copy()
    if len(quantized_fields) > 1:
        encoded[1:] = np.bitwise_xor(stacked[1:], stacked[:-1])
    compressed = gzip.compress(encoded.tobytes(), compresslevel=6, mtime=0)
    return {
        "rows": rows,
        "cols": cols,
        "count": len(quantized_fields),
        "maxima": maxima,
        "floors": floors,
        "encoding": "gzip-u16-log-xor",
        "data": base64.b64encode(compressed).decode("ascii"),
    }


def _radius_bounds(site_lat: float, site_lon: float, radius_miles: float) -> list[list[float]]:
    """Return bounds that tightly contain the selected analysis-radius circle."""
    earth_radius_miles = 3958.7613
    lat_delta = math.degrees(radius_miles / earth_radius_miles)
    cos_lat = max(abs(math.cos(math.radians(site_lat))), 1.0e-6)
    lon_delta = math.degrees(radius_miles / (earth_radius_miles * cos_lat))
    return [
        [site_lat - lat_delta, site_lon - lon_delta],
        [site_lat + lat_delta, site_lon + lon_delta],
    ]


def _offset_latlon(site_lat: float, site_lon: float, north_miles: float, east_miles: float) -> tuple[float, float]:
    lat = site_lat + math.degrees(north_miles / 3958.7613)
    lon = site_lon + math.degrees(east_miles / (3958.7613 * math.cos(math.radians(site_lat))))
    return lat, lon


def dose_plume_polygon(
    site_lat: float,
    site_lon: float,
    bearing_deg: float,
    radius_miles: float,
    dispersion_inputs,
    edge_fraction: float = 0.01,
    points: int = 50,
) -> list[tuple[float, float]]:
    """Return a Gaussian plume footprint at the selected relative-dose edge."""
    x_m = np.linspace(10.0, radius_miles * 1609.344, points)
    widths_m = half_width_m(x_m, dispersion_inputs, edge_fraction)
    return _polygon_from_widths(site_lat, site_lon, bearing_deg, x_m, widths_m)


def _polygon_from_widths(
    site_lat: float,
    site_lon: float,
    bearing_deg: float,
    x_m: np.ndarray,
    widths_m: np.ndarray,
) -> list[tuple[float, float]]:
    br = math.radians(bearing_deg)
    left, right = [], []
    for x, width in zip(x_m, widths_m):
        down_mi, cross_mi = x / 1609.344, width / 1609.344
        north = down_mi * math.cos(br) - cross_mi * math.sin(br)
        east = down_mi * math.sin(br) + cross_mi * math.cos(br)
        left.append(_offset_latlon(site_lat, site_lon, north, east))
        north = down_mi * math.cos(br) + cross_mi * math.sin(br)
        east = down_mi * math.sin(br) - cross_mi * math.cos(br)
        right.append(_offset_latlon(site_lat, site_lon, north, east))
    return [(site_lat, site_lon), *left, *reversed(right), (site_lat, site_lon)]


def _dose_scale(max_dose_rem: float, minimum_dose_rem: float, bands: int = 6) -> np.ndarray:
    """Return logarithmically spaced contour limits from display threshold to case maximum."""
    if not np.isfinite(max_dose_rem) or max_dose_rem <= 0.0:
        raise ValueError("Maximum dose must be positive")
    minimum = max(float(minimum_dose_rem), 1.0e-12)
    if minimum >= max_dose_rem:
        minimum = max_dose_rem * 0.1
    return np.geomspace(minimum, max_dose_rem, bands + 1)


def _dose_contour_polygon(
    site_lat: float,
    site_lon: float,
    bearing_deg: float,
    radius_miles: float,
    dispersion_inputs,
    dose_curve,
    threshold_rem: float,
    max_dose_rem: float,
    edge_fraction: float = 0.01,
    points: int = 120,
) -> list[tuple[float, float]]:
    """Build an absolute-dose contour polygon from centerline and lateral dose."""
    max_distance_m = radius_miles * 1609.344
    x_m = np.linspace(10.0, max_distance_m, points)
    centerline = np.minimum(dose_curve.dose_at(x_m), max_dose_rem)
    valid = centerline >= threshold_rem
    if not np.any(valid):
        return []
    # Keep the contiguous near-source portion; normal FLARE curves decline with distance.
    last = int(np.flatnonzero(valid)[-1])
    x_m = x_m[: last + 1]
    centerline = centerline[: last + 1]
    valid = centerline >= threshold_rem
    x_m = x_m[valid]
    centerline = centerline[valid]
    if len(x_m) < 2:
        return []
    sigma = sigma_y_m(x_m, dispersion_inputs)
    absolute_widths_m = sigma * np.sqrt(
        2.0 * np.log(np.maximum(centerline / threshold_rem, 1.0))
    )
    # The selected relative centerline-dose edge is the outer physical envelope.
    # Absolute-dose contours cannot extend beyond that envelope.
    edge_widths_m = sigma * math.sqrt(2.0 * math.log(1.0 / edge_fraction))
    widths_m = np.minimum(absolute_widths_m, edge_widths_m)
    return _polygon_from_widths(site_lat, site_lon, bearing_deg, x_m, widths_m)


def _format_dose(value: float) -> str:
    if value >= 10:
        return f"{value:,.1f}"
    if value >= 1:
        return f"{value:.2f}"
    if value >= 0.01:
        return f"{value:.3f}"
    return f"{value:.2e}"


def _add_dose_legend(m: folium.Map, limits: np.ndarray, title: str) -> None:
    rows = []
    for idx, color in enumerate(_DOSE_COLORS):
        low, high = limits[idx], limits[idx + 1]
        rows.append(
            f'<div style="display:flex;align-items:center;gap:7px;margin:3px 0;">'
            f'<span style="width:18px;height:12px;background:{color};border:1px solid #666;display:inline-block;"></span>'
            f'<span>{_format_dose(low)}–{_format_dose(high)} rem</span></div>'
        )
    html = f"""
    <div style="position:fixed; top:90px; right:12px; z-index:9999;
                background:rgba(255,255,255,0.94); border:1px solid #777;
                border-radius:6px; padding:9px 11px; font-size:12px;
                line-height:1.2; box-shadow:0 1px 4px rgba(0,0,0,.25);">
      <div style="font-weight:700;margin-bottom:5px;">{title}</div>
      {''.join(reversed(rows))}
      <div style="margin-top:5px;color:#444;">Scale maximum: {_format_dose(limits[-1])} rem</div>
    </div>
    """
    m.get_root().html.add_child(Element(html))



def _hex_rgba(value: str, alpha: int = 190) -> tuple[int, int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4)) + (alpha,)


def _deposition_overlay(
    m: folium.Map,
    site_lat: float,
    site_lon: float,
    bearing_deg: float,
    radius_miles: float,
    dispersion_inputs,
    release_intervals,
    group_name: str,
) -> None:
    """Add a colored gridded relative-deposition field and side legend."""
    size = min(_MAX_OVERLAY_PIXELS, 900)
    radius_m = radius_miles * 1609.344
    east = np.linspace(-radius_m, radius_m, size)
    north = np.linspace(radius_m, -radius_m, size)
    east_grid, north_grid = np.meshgrid(east, north)
    field = synthetic_deposition_field(
        east_grid, north_grid, bearing_deg, tuple(release_intervals), dispersion_inputs
    )
    radial = np.hypot(east_grid, north_grid)
    field = np.where(radial <= radius_m, field, 0.0)
    # Log-like bands emphasize the broad low-level footprint while preserving hot spots.
    limits = np.array([0.005, 0.01, 0.025, 0.05, 0.10, 0.25, 0.50, 0.75, 1.01])
    rgba = np.zeros((size, size, 4), dtype=np.uint8)
    for idx, color in enumerate(_DEPOSITION_COLORS):
        mask = (field >= limits[idx]) & (field < limits[idx + 1])
        rgba[mask] = _hex_rgba(color, 238 if idx < 5 else 250)
    overlay = folium.raster_layers.ImageOverlay(
        image=rgba,
        bounds=_radius_bounds(site_lat, site_lon, radius_miles),
        opacity=0.98,
        pane="flareConsequencePane",
        interactive=False,
        cross_origin=False,
        zindex=5,
        name=f"Synthetic deposition — {group_name}",
        show=True,
    )
    overlay.add_to(m)
    _add_zoom_refresh(m, [overlay])
    rows = []
    for idx, color in enumerate(_DEPOSITION_COLORS):
        low = limits[idx] * 100.0
        high = min(limits[idx + 1], 1.0) * 100.0
        rows.append(
            f'<div style="display:flex;align-items:center;gap:7px;margin:3px 0;">'
            f'<span style="width:18px;height:12px;background:{color};border:1px solid #666;display:inline-block;"></span>'
            f'<span>{low:g}–{high:g}%</span></div>'
        )
    html = f"""
    <div style="position:fixed; top:90px; right:12px; z-index:9999;
                background:rgba(255,255,255,0.94); border:1px solid #777;
                border-radius:6px; padding:9px 11px; font-size:12px;
                line-height:1.2; box-shadow:0 1px 4px rgba(0,0,0,.25);">
      <div style="font-weight:700;margin-bottom:2px;">Synthetic deposition</div>
      <div style="margin-bottom:5px;color:#444;max-width:180px;">{group_name}</div>
      {''.join(reversed(rows))}
      <div style="margin-top:5px;color:#444;max-width:180px;">Relative to this case/group maximum</div>
    </div>
    """
    m.get_root().html.add_child(Element(html))


def _add_flare_layer_panes(m: folium.Map) -> None:
    """Create stable Leaflet panes so consequence rasters stay above population heatmaps."""
    map_name = m.get_name()
    script = f"""
    {{% macro script(this, kwargs) %}}
    (function() {{
      var map = {map_name};
      if (!map.getPane('flarePopulationPane')) {{
        map.createPane('flarePopulationPane');
        map.getPane('flarePopulationPane').style.zIndex = 410;
        map.getPane('flarePopulationPane').style.pointerEvents = 'none';
      }}
      if (!map.getPane('flareConsequencePane')) {{
        map.createPane('flareConsequencePane');
        map.getPane('flareConsequencePane').style.zIndex = 460;
        map.getPane('flareConsequencePane').style.pointerEvents = 'none';
      }}
    }})();
    {{% endmacro %}}
    """
    macro = MacroElement()
    macro._template = Template(script)
    macro.add_to(m)


def _add_zoom_refresh(m: folium.Map, overlays: list) -> None:
    """Force Leaflet raster overlays to redraw after zooming."""
    if not overlays:
        return
    map_name = m.get_name()
    overlay_names = ",".join(overlay.get_name() for overlay in overlays)
    script = f"""
    {{% macro script(this, kwargs) %}}
    (function() {{
      var map = {map_name};
      var overlays = [{overlay_names}];
      map.on('zoomend', function() {{
        overlays.forEach(function(layer) {{
          if (!map.hasLayer(layer)) return;
          map.removeLayer(layer);
          layer.addTo(map);
          if (layer.bringToFront) layer.bringToFront();
        }});
      }});
    }})();
    {{% endmacro %}}
    """
    macro = MacroElement()
    macro._template = Template(script)
    macro.add_to(m)



def _upsample_field_bilinear(field: np.ndarray, maximum_pixels: int = _MAX_OVERLAY_PIXELS) -> np.ndarray:
    """Bilinearly upsample a regular 2-D field for smoother map raster rendering."""
    values = np.asarray(field, dtype=float)
    if values.ndim != 2 or min(values.shape) < 2:
        return values
    rows, cols = values.shape
    scale = min(maximum_pixels / max(rows, cols), 3.0)
    if scale <= 1.05:
        return values
    target_rows = max(rows, int(round(rows * scale)))
    target_cols = max(cols, int(round(cols * scale)))

    old_x = np.arange(cols, dtype=float)
    new_x = np.linspace(0.0, cols - 1.0, target_cols)
    horizontal = np.empty((rows, target_cols), dtype=float)
    for row in range(rows):
        horizontal[row] = np.interp(new_x, old_x, values[row])

    old_y = np.arange(rows, dtype=float)
    new_y = np.linspace(0.0, rows - 1.0, target_rows)
    result = np.empty((target_rows, target_cols), dtype=float)
    for col in range(target_cols):
        result[:, col] = np.interp(new_y, old_y, horizontal[:, col])
    return result

def _consequence_rgba(
    field: np.ndarray,
    units: str,
    minimum_value: float,
    scale_maximum: float,
) -> tuple[np.ndarray, list[str], list[str], str]:
    """Convert one precomputed frame to RGBA using the selected display range."""
    values = _upsample_field_bilinear(field)
    rgba = np.zeros((*values.shape, 4), dtype=np.uint8)
    if units == "rem":
        if scale_maximum <= 0.0:
            return rgba, _DOSE_COLORS, [], "Scale maximum: 0 rem"
        limits = _dose_scale(scale_maximum, minimum_value, len(_DOSE_COLORS))
        colors = _DOSE_COLORS
        labels = []
        for i, color in enumerate(colors):
            upper_test = values <= limits[i + 1] if i == len(colors) - 1 else values < limits[i + 1]
            mask = (values >= limits[i]) & upper_test
            rgba[mask] = _hex_rgba(color, 242)
            labels.append(f"{_format_dose(limits[i])}–{_format_dose(limits[i + 1])} rem")
        scale_note = f"Selected dose range: {_format_dose(minimum_value)}–{_format_dose(scale_maximum)} rem"
    else:
        limits = np.array([0.005, 0.01, 0.025, 0.05, 0.10, 0.25, 0.50, 0.75, 1.01])
        colors = _DEPOSITION_COLORS
        labels = []
        for i, color in enumerate(colors):
            mask = (values >= limits[i]) & (values < limits[i + 1])
            rgba[mask] = _hex_rgba(color, 238 if i < 5 else 250)
            labels.append(f"{limits[i] * 100:g}–{min(limits[i + 1], 1) * 100:g}%")
        scale_note = "Fixed to final LPZ maximum for this scenario/group"
    return rgba, colors, labels, scale_note


def consequence_legend_data(
    title: str,
    units: str,
    minimum_value: float,
    scale_maximum: float,
) -> dict:
    """Return structured legend content for screen and report exports."""
    if units == "rem":
        limits = _dose_scale(scale_maximum, minimum_value, len(_DOSE_COLORS))
        colors = _DOSE_COLORS
        labels = [
            f"{_format_dose(limits[i])}–{_format_dose(limits[i + 1])} rem"
            for i in range(len(colors))
        ]
        scale_note = f"Selected dose range: {_format_dose(minimum_value)}–{_format_dose(scale_maximum)} rem"
    else:
        limits = np.array([0.005, 0.01, 0.025, 0.05, 0.10, 0.25, 0.50, 0.75, 1.01])
        colors = _DEPOSITION_COLORS
        labels = [
            f"{limits[i] * 100:g}–{min(limits[i + 1], 1) * 100:g}%"
            for i in range(len(colors))
        ]
        scale_note = "Fixed to final LPZ maximum for this scenario/group"
    return {
        "title": str(title),
        "items": [
            {"color": color, "label": label}
            for color, label in reversed(list(zip(colors, labels)))
        ],
        "note": scale_note,
    }


def consequence_legend_html(
    title: str,
    units: str,
    minimum_value: float,
    scale_maximum: float,
) -> str:
    """Return a standalone consequence legend for placement beside the map."""
    data = consequence_legend_data(title, units, minimum_value, scale_maximum)
    rows = ''.join(
        f'<div class="flare-legend-row"><span class="flare-legend-swatch" style="background:{item["color"]};"></span>'
        f'<span>{item["label"]}</span></div>'
        for item in data["items"]
    )
    return (
        '<div class="flare-external-legend">'
        f'<div class="flare-legend-title">{data["title"]}</div>'
        f'{rows}'
        f'<div class="flare-legend-note">{data["note"]}</div>'
        '</div>'
    )


def _add_consequence_legend(
    m: folium.Map,
    title: str,
    colors: list[str],
    labels: list[str],
    scale_note: str,
    visible: bool = True,
) -> None:
    rows = []
    for color, label in zip(colors, labels):
        rows.append(
            f'<div style="display:flex;align-items:center;gap:7px;margin:3px 0;">'
            f'<span style="width:18px;height:12px;background:{color};border:1px solid #666;display:inline-block;"></span>'
            f'<span>{label}</span></div>'
        )
    if not visible:
        m.get_root().html.add_child(Element(
            '<div id="flare-time-control-container" style="display:none;"></div>'
        ))
        return
    html = f"""
    <div id="flare-consequence-legend" style="position:fixed; top:90px; right:12px; z-index:9999;
                background:rgba(255,255,255,0.94); border:1px solid #777;
                border-radius:6px; padding:9px 11px; font-size:12px;
                line-height:1.2; box-shadow:0 1px 4px rgba(0,0,0,.25);">
      <div style="font-weight:700;margin-bottom:5px;max-width:190px;">{title}</div>
      {''.join(reversed(rows))}
      <div style="margin-top:5px;color:#444;max-width:190px;">{scale_note}</div>
      <div id="flare-time-control-container" style="margin-top:9px;padding-top:8px;border-top:1px solid #bbb;"></div>
    </div>
    """
    m.get_root().html.add_child(Element(html))


def _add_time_evolving_overlays(
    m: folium.Map,
    site_lat: float,
    site_lon: float,
    radius_miles: float,
    fields: tuple[np.ndarray, ...],
    title: str,
    units: str,
    minimum_value: float,
    scale_maximum: float,
    elapsed_hours: tuple[float, ...],
    initial_step: int = 0,
    display_step: int | None = None,
    total_steps: int | None = None,
    embedded_legend: bool = True,
    minimum_radius_miles: float = 0.0,
    population_fields: tuple[np.ndarray, ...] = (),
    cells: pd.DataFrame | None = None,
    bearing_deg: float = 0.0,
    outer_circle=None,
    inner_circle=None,
    pathway_line=None,
    population_heat_layer=None,
    pathway_inputs: dict | None = None,
) -> None:
    """Add one persistent overlay and browser-local interval/dose/radius controls.

    The initial image retains the existing 960-pixel rendering path. Native model
    grids are gzip-compressed and embedded for lazy browser-side recoloring, so
    later control changes regenerate only the mounted plume image at the same
    960-pixel output resolution without rebuilding the Folium map.
    """
    if not fields:
        return
    initial_step = int(np.clip(initial_step, 0, len(fields) - 1))
    rows, cols = np.asarray(fields[0]).shape
    east = np.linspace(-radius_miles, radius_miles, cols)
    north = np.linspace(radius_miles, -radius_miles, rows)
    east_grid, north_grid = np.meshgrid(east, north)
    radial_grid = np.hypot(east_grid, north_grid)
    initial_mask = radial_grid >= max(float(minimum_radius_miles), 0.0)
    pre_rendered_urls: list[str] = []
    colors: list[str] = []
    labels: list[str] = []
    scale_note = ""
    for field in fields:
        display_field = np.where(initial_mask, np.asarray(field, dtype=float), 0.0)
        rgba, colors, labels, scale_note = _consequence_rgba(
            display_field, units, minimum_value, scale_maximum
        )
        pre_rendered_urls.append(image_to_url(rgba, origin="upper"))
    overlay = folium.raster_layers.ImageOverlay(
        image=pre_rendered_urls[initial_step],
        bounds=_radius_bounds(site_lat, site_lon, radius_miles),
        opacity=0.98,
        pane="flareConsequencePane",
        interactive=False,
        cross_origin=False,
        zindex=6,
        name=title,
        show=True,
        control=False,
    )
    overlay.add_to(m)

    _add_consequence_legend(m, title, colors, labels, scale_note, visible=embedded_legend)
    map_name = m.get_name()
    overlay_name = overlay.get_name()
    hours = ",".join(f"{value:.8g}" for value in elapsed_hours)
    pre_rendered_urls_json = json.dumps(pre_rendered_urls, separators=(",", ":"))
    field_stack = _encode_field_stack(fields)
    field_stack_json = json.dumps(field_stack, separators=(",", ":"))
    population_stack = population_fields or (fields if units == "rem" else ())
    population_uses_display_stack = (
        len(population_stack) == len(fields)
        and all(population_field is display_field for population_field, display_field in zip(population_stack, fields))
    )
    population_stack_json = (
        "fieldStack"
        if population_uses_display_stack
        else json.dumps(_encode_field_stack(tuple(population_stack)), separators=(",", ":"))
    )
    dose_colors_json = json.dumps(_DOSE_COLORS, separators=(",", ":"))
    deposition_colors_json = json.dumps(_DEPOSITION_COLORS, separators=(",", ":"))

    cell_rows = []
    if cells is not None and not cells.empty:
        lat = cells["latitude"].to_numpy(float)
        lon = cells["longitude"].to_numpy(float)
        pop = cells["population"].to_numpy(float)
        east_miles, north_miles = local_xy_miles(lat, lon, site_lat, site_lon)
        for la, lo, population, east, north in zip(lat, lon, pop, east_miles, north_miles):
            if population > 0.0:
                cell_rows.append([
                    round(float(la), 7), round(float(lo), 7), float(population),
                    round(float(east), 6), round(float(north), 6),
                ])
    cells_json = json.dumps(cell_rows, separators=(",", ":"), allow_nan=False)
    bounds = _radius_bounds(site_lat, site_lon, radius_miles)
    south, west = bounds[0]
    north, east = bounds[1]
    hover_enabled = units == "rem"
    outer_name = outer_circle.get_name() if outer_circle is not None else "null"
    inner_name = inner_circle.get_name() if inner_circle is not None else "null"
    pathway_name = pathway_line.get_name() if pathway_line is not None else "null"
    heat_name = population_heat_layer.get_name() if population_heat_layer is not None else "null"
    pathway_inputs_json = json.dumps(pathway_inputs or {}, separators=(",", ":"), allow_nan=False)

    slider_script = f"""
    {{% macro script(this, kwargs) %}}
    (function() {{
      var map = {map_name};
      var overlay = {overlay_name};
      var elapsed = [{hours}];
      var preRenderedUrls = {pre_rendered_urls_json};
      var current = {initial_step};
      var loadedRadiusMiles = {float(radius_miles):.12g};
      var baseMinimumRadiusMiles = {float(minimum_radius_miles):.12g};
      var baseMaximumRadiusMiles = {float(radius_miles):.12g};
      var baseMinimumDose = {float(minimum_value):.12g};
      var baseMaximumDose = {float(scale_maximum):.12g};
      var minimumRadiusMiles = baseMinimumRadiusMiles;
      var maximumRadiusMiles = baseMaximumRadiusMiles;
      var minimumDose = baseMinimumDose;
      var maximumDose = baseMaximumDose;
      var baseBearingDeg = {float(bearing_deg):.12g};
      var bearingDeg = {float(bearing_deg):.12g};
      var pathwayInputs = {pathway_inputs_json};
      var units = {json.dumps(str(units))};
      var title = {json.dumps(str(title))};
      var fieldStack = {field_stack_json};
      var populationStack = {population_stack_json};
      var cells = {cells_json};
      var doseColors = {dose_colors_json};
      var depositionColors = {deposition_colors_json};
      var decodedFields = [];
      var decodedPopulationFields = populationStack === fieldStack ? decodedFields : [];
      var renderedUrls = {{}};
      var renderRevision = 0;
      var stateRevision = 0;
      var hoverEnabled = {str(hover_enabled).lower()};
      var hoverReadout = null;
      var outerCircle = {outer_name};
      var innerCircle = {inner_name};
      var pathwayLine = {pathway_name};
      var populationHeatLayer = {heat_name};
      var box = document.getElementById('flare-time-control-container');
      var displayedTotal = {total_steps if total_steps is not None else len(fields)-1};
      var site = L.latLng({float(site_lat):.12g}, {float(site_lon):.12g});
      if (box) {{
        L.DomEvent.disableClickPropagation(box);
        L.DomEvent.disableScrollPropagation(box);
      }}

      async function inflateFieldStack(stack) {{
        if (!stack || !stack.data) return null;
        if (stack._quantized) return stack._quantized;
        if (stack._quantizedPromise) return stack._quantizedPromise;
        stack._quantizedPromise = (async function() {{
          if (typeof DecompressionStream === 'undefined') {{
            throw new Error('This browser does not support gzip decompression required for interactive plume controls.');
          }}
          var binary = atob(stack.data);
          var bytes = new Uint8Array(binary.length);
          for (var i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
          var decompressedStream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
          var buffer = await new Response(decompressedStream).arrayBuffer();
          var values = new Uint16Array(buffer);
          if (String(stack.encoding || '').endsWith('-xor')) {{
            var frameSize = Number(stack.rows) * Number(stack.cols);
            for (var frame = 1; frame < Number(stack.count || 0); frame += 1) {{
              var currentOffset = frame * frameSize;
              var previousOffset = currentOffset - frameSize;
              for (var valueIndex = 0; valueIndex < frameSize; valueIndex += 1) {{
                values[currentOffset + valueIndex] ^= values[previousOffset + valueIndex];
              }}
            }}
          }}
          stack._quantized = values;
          return values;
        }})();
        return stack._quantizedPromise;
      }}

      async function decodeStack(stack, index, cache) {{
        if (cache[index]) return cache[index];
        if (!stack || !stack.data || index < 0 || index >= Number(stack.count || 0)) return null;
        var packed = await inflateFieldStack(stack);
        if (!packed) return null;
        var frameSize = Number(stack.rows) * Number(stack.cols);
        var start = index * frameSize;
        var quantized = packed.subarray(start, start + frameSize);
        var decoded = new Float32Array(frameSize);
        var maximum = Number((stack.maxima || [])[index] || 0);
        var floor = Number((stack.floors || [])[index] || 0);
        if (maximum > 0 && floor > 0) {{
          var logFloor = Math.log(floor);
          var logSpan = Math.log(maximum) - logFloor;
          for (var j = 0; j < quantized.length; j += 1) {{
            decoded[j] = quantized[j] === 0
              ? 0
              : Math.exp(logFloor + ((quantized[j] - 1) / 65534.0) * logSpan);
          }}
        }}
        cache[index] = decoded;
        return decoded;
      }}

      function sampleGrid(values, rows, cols, row, col) {{
        if (!values || rows < 2 || cols < 2) return 0;
        row = Math.max(0, Math.min(rows - 1, row));
        col = Math.max(0, Math.min(cols - 1, col));
        var r0 = Math.floor(row), c0 = Math.floor(col);
        var r1 = Math.min(rows - 1, r0 + 1), c1 = Math.min(cols - 1, c0 + 1);
        var fr = row - r0, fc = col - c0;
        var top = values[r0 * cols + c0] * (1 - fc) + values[r0 * cols + c1] * fc;
        var bottom = values[r1 * cols + c0] * (1 - fc) + values[r1 * cols + c1] * fc;
        return top * (1 - fr) + bottom * fr;
      }}

      function doseLimits(minimum, maximum) {{
        var limits = [];
        minimum = Math.max(Number(minimum) || 0.01, 1e-12);
        maximum = Math.max(Number(maximum) || minimum, minimum * 1.000001);
        var logMin = Math.log(minimum), logMax = Math.log(maximum);
        for (var i = 0; i <= doseColors.length; i += 1) {{
          limits.push(Math.exp(logMin + (logMax - logMin) * i / doseColors.length));
        }}
        return limits;
      }}

      function pathwayCurveDose(distanceM) {{
        var distances = pathwayInputs.distance_m || [];
        var doses = pathwayInputs.dose_rem || [];
        if (distances.length < 2 || doses.length !== distances.length) return 0;
        var x = Math.max(Number(distanceM) || 0, 1);
        var logX = Math.log(x);
        var lower = 0, upper = distances.length - 1;
        while (upper - lower > 1) {{
          var middle = Math.floor((lower + upper) / 2);
          if (x < Number(distances[middle])) upper = middle;
          else lower = middle;
        }}
        var segment = x <= Number(distances[0]) ? 0
          : (x >= Number(distances[distances.length - 1]) ? distances.length - 2 : lower);
        var x0 = Math.max(Number(distances[segment]), 1e-30);
        var x1 = Math.max(Number(distances[segment + 1]), x0 * 1.0000001);
        var y0 = Math.max(Number(doses[segment]), 1e-30);
        var y1 = Math.max(Number(doses[segment + 1]), 1e-30);
        var fraction = (logX - Math.log(x0)) / (Math.log(x1) - Math.log(x0));
        return Math.exp(Math.log(y0) + fraction * (Math.log(y1) - Math.log(y0)));
      }}

      function pathwayMeanderMultiplier() {{
        var wind = Math.max(Number(pathwayInputs.wind_speed_m_s) || 1, 0.1);
        var duration = Math.max(Number(pathwayInputs.release_duration_hr) || 0, 0);
        var weakWind = Math.max(0, 1 - wind);
        var durationFactor = Math.min(1, Math.log1p(duration) / Math.log(25));
        return Math.min(2.5, 1 + 1.5 * weakWind * durationFactor);
      }}

      function optimizeBearing() {{
        var objective = String(pathwayInputs.objective || 'custom');
        if (objective === 'custom' || !cells.length) return false;
        var coefficients = {{A:[0.22,0.0001],B:[0.16,0.0001],C:[0.11,0.0001],D:[0.08,0.0001],E:[0.06,0.0001],F:[0.04,0.0001]}};
        var stability = String(pathwayInputs.stability_class || 'F').toUpperCase();
        var coefficient = coefficients[stability] || coefficients.F;
        var meander = pathwayMeanderMultiplier();
        var step = Math.max(0.1, Number(pathwayInputs.bearing_step_deg) || 1);
        var bestBearing = bearingDeg;
        var bestPrimary = -Infinity;
        var bestSecondary = -Infinity;
        for (var candidate = 0; candidate < 360 - 1e-9; candidate += step) {{
          var angle = candidate * Math.PI / 180;
          var sine = Math.sin(angle), cosine = Math.cos(angle);
          var populationScore = 0, populationDoseScore = 0;
          for (var cellIndex = 0; cellIndex < cells.length; cellIndex += 1) {{
            var cell = cells[cellIndex];
            var eastMiles = Number(cell[3]), northMiles = Number(cell[4]);
            var radial = Math.hypot(eastMiles, northMiles);
            if (radial < minimumRadiusMiles || radial > maximumRadiusMiles) continue;
            var downwindMiles = eastMiles * sine + northMiles * cosine;
            if (downwindMiles <= 0) continue;
            var crosswindMiles = eastMiles * cosine - northMiles * sine;
            var downwindM = Math.max(downwindMiles * 1609.344, 1);
            var sigma = coefficient[0] * downwindM / Math.sqrt(1 + coefficient[1] * downwindM) * meander;
            var lateral = Math.exp(-0.5 * Math.pow(crosswindMiles * 1609.344 / Math.max(sigma, 1e-9), 2));
            var dose = pathwayCurveDose(downwindM) * lateral;
            if (dose < minimumDose) continue;
            var population = Number(cell[2]) || 0;
            populationScore += population;
            populationDoseScore += population * dose;
          }}
          var primary = objective === 'population' ? populationScore : populationDoseScore;
          var secondary = objective === 'population' ? populationDoseScore : populationScore;
          if (primary > bestPrimary || (primary === bestPrimary && secondary > bestSecondary)) {{
            bestPrimary = primary;
            bestSecondary = secondary;
            bestBearing = candidate;
          }}
        }}
        var difference = Math.abs(((bestBearing - bearingDeg + 540) % 360) - 180);
        bearingDeg = ((bestBearing % 360) + 360) % 360;
        return difference > 1e-9;
      }}

      function hexRgba(hex, alpha) {{
        var value = hex.replace('#', '');
        return [parseInt(value.slice(0,2),16), parseInt(value.slice(2,4),16), parseInt(value.slice(4,6),16), alpha];
      }}

      function colorForValue(value, limits) {{
        if (!isFinite(value)) return [0,0,0,0];
        if (units === 'rem') {{
          if (value < limits[0] || value > limits[limits.length - 1]) return [0,0,0,0];
          var band = doseColors.length - 1;
          for (var i = 0; i < doseColors.length - 1; i += 1) {{
            if (value < limits[i + 1]) {{ band = i; break; }}
          }}
          return hexRgba(doseColors[band], 242);
        }}
        var depositionLimits = [0.005,0.01,0.025,0.05,0.10,0.25,0.50,0.75,1.01];
        for (var j = 0; j < depositionColors.length; j += 1) {{
          if (value >= depositionLimits[j] && value < depositionLimits[j + 1]) {{
            return hexRgba(depositionColors[j], j < 5 ? 238 : 250);
          }}
        }}
        return [0,0,0,0];
      }}

      function approximatelyEqual(a, b) {{
        return Math.abs(Number(a) - Number(b)) <= 1e-10 * Math.max(1, Math.abs(Number(a)), Math.abs(Number(b)));
      }}

      function usesPreRenderedState() {{
        return approximatelyEqual(minimumDose, baseMinimumDose)
          && approximatelyEqual(maximumDose, baseMaximumDose)
          && approximatelyEqual(minimumRadiusMiles, baseMinimumRadiusMiles)
          && approximatelyEqual(maximumRadiusMiles, baseMaximumRadiusMiles)
          && approximatelyEqual(bearingDeg, baseBearingDeg);
      }}

      async function renderFrame(index) {{
        if (!overlay || !overlay.setUrl) return;
        if (usesPreRenderedState() && preRenderedUrls[index]) {{
          overlay.setUrl(preRenderedUrls[index]);
          return;
        }}
        var key = index + '|' + [minimumDose, maximumDose, minimumRadiusMiles, maximumRadiusMiles, bearingDeg].join('|');
        if (renderedUrls[key]) {{ overlay.setUrl(renderedUrls[key]); return; }}
        var revision = ++renderRevision;
        var values = await decodeStack(fieldStack, index, decodedFields);
        if (!values) return;
        if (revision !== renderRevision || index !== current) return;
        var rows = Number(fieldStack.rows), cols = Number(fieldStack.cols);
        var scale = Math.min({_MAX_OVERLAY_PIXELS} / Math.max(rows, cols), 3.0);
        var outputRows = Math.max(rows, Math.round(rows * scale));
        var outputCols = Math.max(cols, Math.round(cols * scale));
        var canvas = document.createElement('canvas');
        canvas.width = outputCols;
        canvas.height = outputRows;
        var ctx = canvas.getContext('2d');
        var image = ctx.createImageData(outputCols, outputRows);
        var limits = doseLimits(minimumDose, maximumDose);
        var bearingDelta = (bearingDeg - baseBearingDeg) * Math.PI / 180;
        var deltaCosine = Math.cos(bearingDelta), deltaSine = Math.sin(bearingDelta);
        var offset = 0;
        for (var r = 0; r < outputRows; r += 1) {{
          var northMiles = loadedRadiusMiles - 2 * loadedRadiusMiles * r / Math.max(outputRows - 1, 1);
          for (var c = 0; c < outputCols; c += 1) {{
            var eastMiles = -loadedRadiusMiles + 2 * loadedRadiusMiles * c / Math.max(outputCols - 1, 1);
            var radial = Math.hypot(eastMiles, northMiles);
            var rgba = [0,0,0,0];
            if (radial >= minimumRadiusMiles && radial <= maximumRadiusMiles) {{
              var sourceEast = eastMiles * deltaCosine - northMiles * deltaSine;
              var sourceNorth = eastMiles * deltaSine + northMiles * deltaCosine;
              var sourceRow = (loadedRadiusMiles - sourceNorth) / (2 * loadedRadiusMiles) * (rows - 1);
              var sourceCol = (sourceEast + loadedRadiusMiles) / (2 * loadedRadiusMiles) * (cols - 1);
              rgba = colorForValue(sampleGrid(values, rows, cols, sourceRow, sourceCol), limits);
            }}
            image.data[offset++] = rgba[0];
            image.data[offset++] = rgba[1];
            image.data[offset++] = rgba[2];
            image.data[offset++] = rgba[3];
          }}
        }}
        ctx.putImageData(image, 0, 0);
        var dataUrl = canvas.toDataURL('image/png');
        if (revision !== renderRevision || index !== current) return;
        renderedUrls[key] = dataUrl;
        overlay.setUrl(dataUrl);
      }}

      function formatDose(value) {{
        if (value >= 1000) return value.toLocaleString(undefined, {{maximumFractionDigits:0}});
        if (value >= 10) return value.toFixed(1);
        if (value >= 1) return value.toFixed(2);
        if (value >= 0.01) return value.toFixed(3);
        return value.toExponential(2);
      }}

      function currentLegend() {{
        if (units !== 'rem') return null;
        var limits = doseLimits(minimumDose, maximumDose);
        return {{
          title: title,
          items: doseColors.map(function(color, index) {{
            return {{color:color, label:formatDose(limits[index]) + '–' + formatDose(limits[index+1]) + ' rem'}};
          }}).reverse(),
          note:'Selected dose range: ' + formatDose(minimumDose) + '–' + formatDose(maximumDose) + ' rem'
        }};
      }}

      async function populationTotal() {{
        if (!populationStack || !populationStack.data || !Number(populationStack.count || 0) || !cells.length) return null;
        var values = await decodeStack(populationStack, current, decodedPopulationFields);
        if (!values) return null;
        var rows = Number(populationStack.rows), cols = Number(populationStack.cols);
        var bearingDelta = (bearingDeg - baseBearingDeg) * Math.PI / 180;
        var deltaCosine = Math.cos(bearingDelta), deltaSine = Math.sin(bearingDelta);
        var total = 0;
        for (var i = 0; i < cells.length; i += 1) {{
          var cell = cells[i];
          var eastMiles = Number(cell[3]), northMiles = Number(cell[4]);
          var radial = Math.hypot(eastMiles, northMiles);
          if (radial < minimumRadiusMiles || radial > maximumRadiusMiles) continue;
          var sourceEast = eastMiles * deltaCosine - northMiles * deltaSine;
          var sourceNorth = eastMiles * deltaSine + northMiles * deltaCosine;
          var row = (loadedRadiusMiles - sourceNorth) / (2 * loadedRadiusMiles) * (rows - 1);
          var col = (sourceEast + loadedRadiusMiles) / (2 * loadedRadiusMiles) * (cols - 1);
          if (row < 0 || row > rows - 1 || col < 0 || col > cols - 1) continue;
          if (sampleGrid(values, rows, cols, row, col) >= minimumDose) total += Number(cell[2]) || 0;
        }}
        return total;
      }}

      function destinationPoint(distanceMiles) {{
        var earthRadiusMiles = 3958.7613;
        var angularDistance = distanceMiles / earthRadiusMiles;
        var bearing = bearingDeg * Math.PI / 180.0;
        var lat1 = site.lat * Math.PI / 180.0;
        var lon1 = site.lng * Math.PI / 180.0;
        var lat2 = Math.asin(Math.sin(lat1)*Math.cos(angularDistance) + Math.cos(lat1)*Math.sin(angularDistance)*Math.cos(bearing));
        var lon2 = lon1 + Math.atan2(Math.sin(bearing)*Math.sin(angularDistance)*Math.cos(lat1), Math.cos(angularDistance)-Math.sin(lat1)*Math.sin(lat2));
        return L.latLng(lat2 * 180 / Math.PI, lon2 * 180 / Math.PI);
      }}

      function updateGeometry(fitView) {{
        if (outerCircle && outerCircle.setRadius) outerCircle.setRadius(maximumRadiusMiles * 1609.344);
        if (innerCircle && innerCircle.setRadius) {{
          innerCircle.setRadius(minimumRadiusMiles * 1609.344);
          innerCircle.setStyle({{opacity: minimumRadiusMiles > 0 ? 1 : 0}});
        }}
        if (pathwayLine && pathwayLine.setLatLngs) {{
          pathwayLine.setLatLngs([destinationPoint(minimumRadiusMiles), destinationPoint(maximumRadiusMiles)]);
        }}
        if (populationHeatLayer && populationHeatLayer.setLatLngs) {{
          var visible = [];
          for (var i = 0; i < cells.length; i += 1) {{
            var radial = Math.hypot(Number(cells[i][3]), Number(cells[i][4]));
            if (radial >= minimumRadiusMiles && radial <= maximumRadiusMiles) visible.push([cells[i][0], cells[i][1], cells[i][2]]);
          }}
          populationHeatLayer.setLatLngs(visible);
        }}
        if (fitView && maximumRadiusMiles > 0) {{
          var angular = maximumRadiusMiles / 3958.7613;
          var latDelta = angular * 180 / Math.PI;
          var lonDelta = latDelta / Math.max(Math.abs(Math.cos(site.lat * Math.PI / 180)), 1e-6);
          map.fitBounds([[site.lat-latDelta, site.lng-lonDelta],[site.lat+latDelta,site.lng+lonDelta]], {{padding:[12,12], animate:false}});
        }}
      }}

      function updateIntervalReadout() {{
        if (box) box.innerHTML = '<div style="font-weight:700;margin-bottom:4px;">Cumulative interval: ' + current + '/' + displayedTotal + '</div>' +
          '<div style="margin-top:3px;color:#444;">Elapsed time: ' + Number(elapsed[current] || 0).toFixed(2) + ' hr</div>';
      }}

      async function broadcastState(revision) {{
        var population = await populationTotal();
        if (revision !== undefined && revision !== stateRevision) return;
        var message = {{
          type:'flare-map-state-updated', interval:current, elapsed:Number(elapsed[current] || 0),
          minimumDose:minimumDose, maximumDose:maximumDose,
          minimumRadius:minimumRadiusMiles, maximumRadius:maximumRadiusMiles,
          bearing:bearingDeg, population:population, legend:currentLegend()
        }};
        window.flareCurrentInterval = current;
        window.flareCurrentDoseRange = units === 'rem' ? {{minimum:minimumDose, maximum:maximumDose}} : null;
        window.flareCurrentRadiusRange = {{minimum:minimumRadiusMiles, maximum:maximumRadiusMiles}};
        window.flareCurrentBearing = bearingDeg;
        window.flareCurrentPopulation = message.population;
        window.flareCurrentLegend = message.legend;
        try {{ window.parent.postMessage(message, '*'); }} catch (error) {{}}
        try {{
          window.parent.document.querySelectorAll('iframe').forEach(function(frame) {{
            if (frame.contentWindow && frame.contentWindow !== window) frame.contentWindow.postMessage(message, '*');
          }});
        }} catch (error) {{}}
      }}

      async function setFrame(index) {{
        var revision = ++stateRevision;
        var next = Math.max(0, Math.min(Number(fieldStack.count || 1) - 1, Math.round(Number(index) || 0)));
        if (next !== current) {{
          current = next;
          await renderFrame(current);
          if (revision !== stateRevision) return;
          if (overlay && overlay.bringToFront) overlay.bringToFront();
          hideHoverReadout();
        }}
        updateIntervalReadout();
        await broadcastState(revision);
      }}

      async function setDoseRange(minimum, maximum, commit) {{
        if (units !== 'rem') return;
        var nextMinimum = Math.max(Number(minimum) || 0.01, 1e-12);
        var nextMaximum = Math.max(Number(maximum) || nextMinimum, nextMinimum);
        var valuesChanged = Math.abs(nextMinimum - minimumDose) > 1e-12 || Math.abs(nextMaximum - maximumDose) > 1e-12;
        if (!valuesChanged && !commit) return;
        minimumDose = nextMinimum;
        maximumDose = nextMaximum;
        var bearingChanged = Boolean(commit) && optimizeBearing();
        if (!valuesChanged && !bearingChanged) return;
        var revision = ++stateRevision;
        renderedUrls = {{}};
        await renderFrame(current);
        if (revision !== stateRevision) return;
        if (bearingChanged) updateGeometry(false);
        hideHoverReadout();
        await broadcastState(revision);
      }}

      async function setRadiusRange(minimum, maximum, fitView, commit) {{
        var nextMinimum = Math.max(0, Number(minimum) || 0);
        var nextMaximum = Math.max(nextMinimum, Math.min(Number(maximum) || loadedRadiusMiles, loadedRadiusMiles));
        var valuesChanged = Math.abs(nextMinimum - minimumRadiusMiles) > 1e-12 || Math.abs(nextMaximum - maximumRadiusMiles) > 1e-12;
        if (!valuesChanged && !commit) return;
        minimumRadiusMiles = nextMinimum;
        maximumRadiusMiles = nextMaximum;
        var bearingChanged = Boolean(commit) && optimizeBearing();
        if (!valuesChanged && !bearingChanged) return;
        var revision = ++stateRevision;
        renderedUrls = {{}};
        await renderFrame(current);
        if (revision !== stateRevision) return;
        updateGeometry(Boolean(fitView));
        hideHoverReadout();
        await broadcastState(revision);
      }}

      function interpolatedDose(lat, lon) {{
        var values = decodedFields[current];
        if (!values) return 0;
        var eastMiles = (lon - site.lng) * 69.172 * Math.cos(site.lat * Math.PI / 180);
        var northMiles = (lat - site.lat) * 69.0;
        var radial = Math.hypot(eastMiles, northMiles);
        if (radial < minimumRadiusMiles || radial > maximumRadiusMiles) return 0;
        var bearingDelta = (bearingDeg - baseBearingDeg) * Math.PI / 180;
        var sourceEast = eastMiles * Math.cos(bearingDelta) - northMiles * Math.sin(bearingDelta);
        var sourceNorth = eastMiles * Math.sin(bearingDelta) + northMiles * Math.cos(bearingDelta);
        var row = (loadedRadiusMiles - sourceNorth) / (2 * loadedRadiusMiles) * (fieldStack.rows - 1);
        var col = (sourceEast + loadedRadiusMiles) / (2 * loadedRadiusMiles) * (fieldStack.cols - 1);
        return sampleGrid(values, fieldStack.rows, fieldStack.cols, row, col);
      }}

      function hideHoverReadout() {{ if (hoverReadout) hoverReadout.style.display = 'none'; }}
      if (hoverEnabled) {{
        var container = map.getContainer();
        hoverReadout = document.createElement('div');
        hoverReadout.className = 'flare-dose-hover';
        hoverReadout.style.cssText = 'display:none;position:absolute;z-index:10000;pointer-events:none;background:rgba(255,255,255,.96);border:1px solid #555;border-radius:4px;padding:4px 7px;font:700 12px/1.25 Arial,sans-serif;white-space:nowrap;box-shadow:0 1px 4px rgba(0,0,0,.28);transform:translate(12px,-28px);';
        container.appendChild(hoverReadout);
        container.addEventListener('mousemove', function(event) {{
          var target = event.target;
          if (target && target.closest && target.closest('.leaflet-control')) {{ hideHoverReadout(); return; }}
          var point = map.mouseEventToContainerPoint(event);
          var latlng = map.containerPointToLatLng(point);
          var dose = interpolatedDose(latlng.lat, latlng.lng);
          if (!isFinite(dose) || dose < minimumDose) {{ hideHoverReadout(); return; }}
          hoverReadout.textContent = 'Estimated dose: ' + formatDose(dose) + ' rem';
          hoverReadout.style.left = point.x + 'px'; hoverReadout.style.top = point.y + 'px'; hoverReadout.style.display = 'block';
        }}, true);
        container.addEventListener('mouseleave', hideHoverReadout);
        map.on('dragstart zoomstart', hideHoverReadout);
      }}

      function refreshView() {{
        // Preserve the user's current center and zoom. invalidateSize/setView
        // lets Leaflet update geometry without removing the active tile layer.
        var center = map.getCenter();
        var zoom = map.getZoom();
        try {{ map.stop(); }} catch (error) {{}}
        try {{ map.invalidateSize({{animate:false, pan:false}}); }} catch (error) {{}}
        requestAnimationFrame(function() {{
          requestAnimationFrame(function() {{
            try {{ map.setView(center, zoom, {{animate:false, reset:true}}); }} catch (error) {{}}
            try {{
              map.eachLayer(function(layer) {{
                // TileLayer.redraw() first removes all tiles; on a slow or failed
                // request that leaves the gray map seen by the user. _update()
                // fills only missing tiles and leaves currently displayed tiles intact.
                if (typeof L !== 'undefined' && L.GridLayer && layer instanceof L.GridLayer) {{
                  if (typeof layer._update === 'function') layer._update();
                }} else if (layer && layer !== overlay && typeof layer.redraw === 'function') {{
                  layer.redraw();
                }}
              }});
            }} catch (error) {{}}
            try {{ if (overlay && typeof overlay._reset === 'function') overlay._reset(); }} catch (error) {{}}
            try {{ if (overlay && overlay.bringToFront) overlay.bringToFront(); }} catch (error) {{}}
            hideHoverReadout();
          }});
        }});
      }}

      window.flareSetCumulativeInterval = setFrame;
      window.flareSetDoseRange = setDoseRange;
      window.flareSetRadiusRange = setRadiusRange;
      window.flareRefreshView = refreshView;
      function runAsync(task) {{
        Promise.resolve(task).catch(function(error) {{
          console.error('FLARE interactive plume update failed', error);
        }});
      }}
      window.addEventListener('message', function(event) {{
        if (!event || !event.data) return;
        if (event.data.type === 'flare-set-cumulative-interval') runAsync(setFrame(event.data.interval));
        else if (event.data.type === 'flare-set-dose-range') runAsync(setDoseRange(event.data.minimum, event.data.maximum, event.data.commit));
        else if (event.data.type === 'flare-set-radius-range') runAsync(setRadiusRange(event.data.minimum, event.data.maximum, event.data.fitView, event.data.commit));
        else if (event.data.type === 'flare-refresh-view') refreshView();
        else if (event.data.type === 'flare-request-map-state') {{
          var revision = ++stateRevision;
          runAsync(broadcastState(revision));
        }}
      }});
      updateIntervalReadout();
      updateGeometry(false);
      map.whenReady(function() {{
      }});
      window.setTimeout(function() {{
        var revision = ++stateRevision;
        runAsync(broadcastState(revision));
      }}, 300);
    }})();
    {{% endmacro %}}
    """
    slider = MacroElement()
    slider._template = Template(slider_script)
    slider.add_to(m)


class _FitCircularViewport(MacroElement):
    """Fit a geographic radius to a circular Leaflet viewport using fractional zoom."""

    def __init__(self, site_lat: float, site_lon: float, radius_miles: float, margin_fraction: float = 0.03):
        super().__init__()
        self._name = "FitCircularViewport"
        self.site_lat = float(site_lat)
        self.site_lon = float(site_lon)
        self.radius_miles = float(radius_miles)
        self.margin_fraction = float(margin_fraction)
        self._template = Template(r"""
{% macro script(this, kwargs) %}
(function () {
    const map = {{ this._parent.get_name() }};
    const site = L.latLng({{ this.site_lat }}, {{ this.site_lon }});
    const earthRadiusMiles = 3958.7613;
    const angularDistance = {{ this.radius_miles }} / earthRadiusMiles;
    const lat1 = site.lat * Math.PI / 180.0;
    const lon1 = site.lng * Math.PI / 180.0;
    const lat2 = Math.asin(
        Math.sin(lat1) * Math.cos(angularDistance) +
        Math.cos(lat1) * Math.sin(angularDistance)
    );
    const lon2 = lon1 + Math.atan2(
        Math.sin(angularDistance) * Math.cos(lat1),
        Math.cos(angularDistance) - Math.sin(lat1) * Math.sin(lat2)
    );
    const northPoint = L.latLng(lat2 * 180.0 / Math.PI, lon2 * 180.0 / Math.PI);

    function fitRadius() {
        map.stop();
        map.invalidateSize({pan: false, animate: false});

        const size = map.getSize();
        const targetRadiusPx = 0.5 * Math.min(size.x, size.y) * (1.0 - {{ this.margin_fraction }});
        const referenceZoom = 0;
        const sitePx = map.project(site, referenceZoom);
        const northPx = map.project(northPoint, referenceZoom);
        const referenceRadiusPx = sitePx.distanceTo(northPx);
        if (!Number.isFinite(referenceRadiusPx) || referenceRadiusPx <= 0 || targetRadiusPx <= 0) {
            return;
        }

        const desiredZoom = referenceZoom + Math.log2(targetRadiusPx / referenceRadiusPx);
        let settled = false;
        const finish = function () {
            if (settled) return;
            settled = true;
            map.off('zoomend', finish);
            map.invalidateSize({pan: false, animate: false});
            map.setView(site, map.getZoom(), {animate: false, reset: true});
        };

        map.once('zoomend', finish);
        map.setView(site, desiredZoom, {animate: false, reset: true});
        // If the desired zoom equals the current zoom, Leaflet emits no zoomend.
        window.setTimeout(finish, 80);
    }

    map.whenReady(function () {
        requestAnimationFrame(function () {
            requestAnimationFrame(function () {
                map.invalidateSize({pan: false, animate: false});
                fitRadius();
            });
        });
    });
})();
{% endmacro %}
""")


class _ReportPdfExporter(MacroElement):
    """Generate a deterministic layered map/legend/data PDF inside the Leaflet iframe."""

    def __init__(self, site_lat: float, site_lon: float, radius_miles: float, payload: dict):
        super().__init__()
        self._name = "ReportPdfExporter"
        self.site_lat = float(site_lat)
        self.site_lon = float(site_lon)
        self.radius_miles = float(radius_miles)
        self.payload_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
        self._template = Template(r"""
{% macro script(this, kwargs) %}
(function () {
    const map = {{ this._parent.get_name() }};
    const payload = JSON.parse({{ this.payload_json|tojson }});
    const site = L.latLng({{ this.site_lat }}, {{ this.site_lon }});
    const loadedRadiusMiles = {{ this.radius_miles }};
    const viewportFactor = 1.05;
    function activeRadiusRange() {
        const current = window.flareCurrentRadiusRange || {};
        const minimum = Math.max(0, Number(current.minimum ?? payload.minimum_analysis_radius_miles ?? 0));
        const maximum = Math.max(minimum, Math.min(Number(current.maximum ?? loadedRadiusMiles), loadedRadiusMiles));
        return {minimum: minimum, maximum: maximum};
    }

    function loadScript(src) {
        return new Promise(function (resolve, reject) {
            const existing = Array.from(document.scripts).find(function (script) { return script.src === src; });
            if (existing) {
                if (existing.dataset.loaded === 'true') resolve();
                else existing.addEventListener('load', resolve, {once: true});
                return;
            }
            const script = document.createElement('script');
            script.src = src;
            script.crossOrigin = 'anonymous';
            script.onload = function () { script.dataset.loaded = 'true'; resolve(); };
            script.onerror = reject;
            document.head.appendChild(script);
        });
    }

    function nextPaint(delayMs) {
        return new Promise(function (resolve) {
            window.setTimeout(function () {
                requestAnimationFrame(function () { requestAnimationFrame(resolve); });
            }, delayMs || 0);
        });
    }

    function destinationPoint(origin, bearingDeg, distanceMiles) {
        const earthRadiusMiles = 3958.7613;
        const angularDistance = distanceMiles / earthRadiusMiles;
        const bearing = bearingDeg * Math.PI / 180.0;
        const lat1 = origin.lat * Math.PI / 180.0;
        const lon1 = origin.lng * Math.PI / 180.0;
        const lat2 = Math.asin(
            Math.sin(lat1) * Math.cos(angularDistance) +
            Math.cos(lat1) * Math.sin(angularDistance) * Math.cos(bearing)
        );
        const lon2 = lon1 + Math.atan2(
            Math.sin(bearing) * Math.sin(angularDistance) * Math.cos(lat1),
            Math.cos(angularDistance) - Math.sin(lat1) * Math.sin(lat2)
        );
        return L.latLng(lat2 * 180.0 / Math.PI, lon2 * 180.0 / Math.PI);
    }

    async function fitExportGeometry() {
        map.stop();
        map.invalidateSize({pan: false, animate: false});
        await nextPaint(40);

        const size = map.getSize();
        const openingRadiusPx = 0.5 * Math.min(size.x, size.y) - 3;
        const targetAnalysisRadiusPx = openingRadiusPx / viewportFactor;
        const radiusRange = activeRadiusRange();
        const northPoint = destinationPoint(site, 0, radiusRange.maximum);
        const siteAtZero = map.project(site, 0);
        const northAtZero = map.project(northPoint, 0);
        const referenceRadiusPx = siteAtZero.distanceTo(northAtZero);
        if (!Number.isFinite(referenceRadiusPx) || referenceRadiusPx <= 0) {
            throw new Error('Could not determine export map scale.');
        }
        const desiredZoom = Math.log2(targetAnalysisRadiusPx / referenceRadiusPx);
        map.setView(site, desiredZoom, {animate: false, reset: true});
        await nextPaint(100);
        map.invalidateSize({pan: false, animate: false});
        await nextPaint(50);
        map.setView(site, desiredZoom, {animate: false, reset: true});
        await nextPaint(100);

        for (let attempt = 0; attempt < 5; attempt += 1) {
            const currentSize = map.getSize();
            const desiredCenter = L.point(currentSize.x / 2, currentSize.y / 2);
            const actualSite = map.latLngToContainerPoint(site);
            const error = actualSite.subtract(desiredCenter);
            if (Math.abs(error.x) <= 0.25 && Math.abs(error.y) <= 0.25) break;
            map.panBy(error, {animate: false});
            await nextPaint(50);
        }
    }

    function waitForTiles(timeoutMs) {
        return new Promise(function (resolve) {
            let finished = false;
            const finish = function () {
                if (finished) return;
                finished = true;
                resolve();
            };
            let pending = 0;
            map.eachLayer(function (layer) {
                if (layer instanceof L.TileLayer && layer._loading) {
                    pending += 1;
                    layer.once('load', function () {
                        pending -= 1;
                        if (pending <= 0) finish();
                    });
                }
            });
            if (pending === 0) window.setTimeout(finish, 250);
            window.setTimeout(finish, timeoutMs);
        });
    }

    function rememberDisplay(element, hidden) {
        if (!element) return null;
        const state = {element: element, display: element.style.display};
        if (hidden) element.style.display = 'none';
        return state;
    }

    function restoreDisplays(states) {
        states.filter(Boolean).forEach(function (state) {
            state.element.style.display = state.display;
        });
    }

    function visibleConsequenceImages(mapRect) {
        const pane = map.getPane('flareConsequencePane');
        if (!pane) return [];
        return Array.from(pane.querySelectorAll('img')).filter(function (img) {
            const style = window.getComputedStyle(img);
            const rect = img.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' &&
                Number(style.opacity || 1) > 0 && rect.width > 0 && rect.height > 0;
        }).map(function (img) {
            const rect = img.getBoundingClientRect();
            return {
                image: img,
                x: rect.left - mapRect.left,
                y: rect.top - mapRect.top,
                width: rect.width,
                height: rect.height,
                opacity: Number(window.getComputedStyle(img).opacity || 1)
            };
        });
    }

    async function captureNativeMapRectangle(scale) {
        const source = map.getContainer();
        const mapRect = source.getBoundingClientRect();
        const cssSize = Math.max(1, Math.round(Math.min(mapRect.width, mapRect.height)));
        const consequenceImages = visibleConsequenceImages(mapRect);

        // Capture only the native rectangular map layer (basemap plus the optional
        // population-density canvas). Technical layers are reconstructed on the
        // same fixed canvas from the common export geometry.
        const hidden = [];
        hidden.push(rememberDisplay(map.getPane('flareConsequencePane'), true));
        hidden.push(rememberDisplay(map.getPane('overlayPane'), true));
        hidden.push(rememberDisplay(map.getPane('markerPane'), true));
        hidden.push(rememberDisplay(map.getPane('shadowPane'), true));
        hidden.push(rememberDisplay(map.getPane('tooltipPane'), true));
        hidden.push(rememberDisplay(source.querySelector('.leaflet-control-container'), true));
        hidden.push(rememberDisplay(source.querySelector('.flare-dose-hover'), true));
        await nextPaint(50);

        let baseCanvas;
        try {
            baseCanvas = await window.html2canvas(source, {
                backgroundColor: '#ffffff',
                scale: scale,
                useCORS: true,
                allowTaint: false,
                logging: false,
                imageTimeout: 12000,
                width: cssSize,
                height: cssSize,
                windowWidth: cssSize,
                windowHeight: cssSize,
                scrollX: -window.scrollX,
                scrollY: -window.scrollY
            });
        } finally {
            restoreDisplays(hidden);
        }
        return {baseCanvas: baseCanvas, consequenceImages: consequenceImages, cssSize: cssSize};
    }

    function drawSiteMarker(ctx, centerX, centerY, scale) {
        const r = 10 * scale;
        ctx.save();
        ctx.fillStyle = '#e43d30';
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 2 * scale;
        ctx.beginPath();
        ctx.arc(centerX, centerY, r, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = '#ffffff';
        ctx.font = 'bold ' + (11 * scale) + 'px Arial, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText('i', centerX, centerY + 0.5 * scale);
        ctx.restore();
    }

    function buildFlattenedMap(capture, scale) {
        const width = capture.baseCanvas.width;
        const height = capture.baseCanvas.height;
        const output = document.createElement('canvas');
        output.width = width;
        output.height = height;
        const ctx = output.getContext('2d');
        const centerX = width / 2;
        const centerY = height / 2;
        const openingRadius = Math.min(width, height) / 2 - 3 * scale;
        const analysisRadius = openingRadius / viewportFactor;
        const radiusRange = activeRadiusRange();
        const innerAnalysisRadius = radiusRange.maximum > 0
            ? analysisRadius * Math.min(radiusRange.minimum / radiusRange.maximum, 1)
            : 0;
        const bearingDeg = Number(
            window.flareCurrentBearing !== undefined
                ? window.flareCurrentBearing
                : (payload.selected_bearing_deg || 0)
        );
        const bearing = bearingDeg * Math.PI / 180.0;

        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, width, height);
        ctx.save();
        ctx.beginPath();
        ctx.arc(centerX, centerY, openingRadius, 0, Math.PI * 2);
        ctx.clip();

        // Layer 1: native rectangular map raster.
        ctx.drawImage(capture.baseCanvas, 0, 0, width, height);

        // Layer 2: plume/deposition raster(s), copied from their final rendered
        // rectangles and placed on this canvas using the same pixel dimensions.
        capture.consequenceImages.forEach(function (item) {
            ctx.save();
            ctx.globalAlpha = Math.max(0, Math.min(1, item.opacity));
            ctx.drawImage(
                item.image,
                item.x * scale,
                item.y * scale,
                item.width * scale,
                item.height * scale
            );
            ctx.restore();
        });

        // Layer 3: analysis circle and selected-pathway line, both generated from
        // the exact shared pixel center and user-selected radius.
        ctx.strokeStyle = '#4a4a4a';
        ctx.lineWidth = 3 * scale;
        ctx.setLineDash([]);
        ctx.beginPath();
        ctx.arc(centerX, centerY, analysisRadius, 0, Math.PI * 2);
        ctx.stroke();
        if (innerAnalysisRadius > 0) {
            ctx.lineWidth = 2 * scale;
            ctx.setLineDash([6 * scale, 5 * scale]);
            ctx.beginPath();
            ctx.arc(centerX, centerY, innerAnalysisRadius, 0, Math.PI * 2);
            ctx.stroke();
            ctx.setLineDash([]);
        }

        const startX = centerX + innerAnalysisRadius * Math.sin(bearing);
        const startY = centerY - innerAnalysisRadius * Math.cos(bearing);
        const endX = centerX + analysisRadius * Math.sin(bearing);
        const endY = centerY - analysisRadius * Math.cos(bearing);
        ctx.strokeStyle = '#9f3518';
        ctx.lineWidth = 2.3 * scale;
        ctx.setLineDash([9 * scale, 7 * scale]);
        ctx.beginPath();
        ctx.moveTo(startX, startY);
        ctx.lineTo(endX, endY);
        ctx.stroke();
        ctx.setLineDash([]);
        drawSiteMarker(ctx, centerX, centerY, scale);
        ctx.restore();

        // Layer 4: white mask outside the 105%-radius viewport, followed by a
        // crisp border. Applying it last guarantees that no layer leaks outside.
        ctx.save();
        ctx.beginPath();
        ctx.rect(0, 0, width, height);
        ctx.arc(centerX, centerY, openingRadius, 0, Math.PI * 2, true);
        ctx.fillStyle = '#ffffff';
        ctx.fill('evenodd');
        ctx.restore();
        ctx.beginPath();
        ctx.arc(centerX, centerY, openingRadius, 0, Math.PI * 2);
        ctx.lineWidth = 1.5 * scale;
        ctx.strokeStyle = '#666666';
        ctx.stroke();
        return output;
    }

    function drawWrapped(doc, text, x, y, width, options) {
        const lines = doc.splitTextToSize(String(text), width);
        doc.text(lines, x, y, options || {});
        return y + lines.length * 10;
    }

    async function exportPdf() {
        try {
            await Promise.all([
                loadScript('https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js'),
                loadScript('https://cdn.jsdelivr.net/npm/jspdf@2.5.2/dist/jspdf.umd.min.js')
            ]);
            await fitExportGeometry();
            await waitForTiles(2500);
            await nextPaint(100);

            const renderScale = 3;
            const capture = await captureNativeMapRectangle(renderScale);
            const mapCanvas = buildFlattenedMap(capture, renderScale);

            const jsPDF = window.jspdf.jsPDF;
            const doc = new jsPDF({orientation: 'portrait', unit: 'pt', format: 'letter', compress: true});
            const pageWidth = doc.internal.pageSize.getWidth();
            const pageHeight = doc.internal.pageSize.getHeight();
            const margin = 30;
            const mapSize = 466;
            const mapX = (pageWidth - mapSize) / 2;
            const mapY = 24;
            doc.addImage(mapCanvas.toDataURL('image/png'), 'PNG', mapX, mapY, mapSize, mapSize, undefined, 'FAST');

            const lowerY = mapY + mapSize + 16;
            const gutter = 18;
            const leftWidth = 190;
            const rightX = margin + leftWidth + gutter;
            const rightWidth = pageWidth - margin - rightX;

            doc.setTextColor(25, 25, 25);
            doc.setFont('helvetica', 'bold');
            doc.setFontSize(11);
            const activeLegend = window.flareCurrentLegend || payload.legend || {};
            // Wrap the legend title inside the left column. Titles such as
            // "Cumulative synthetic deposition - Halogens (I, Br)" are wider
            // than leftWidth, and an unwrapped doc.text() call runs straight
            // across the gutter and prints over the "Analysis summary" heading.
            const legendTitleLines = doc.splitTextToSize(
                String(activeLegend.title || 'Legend'), leftWidth);
            doc.text(legendTitleLines, margin, lowerY);
            // Push the swatches down by any extra title lines so they do not
            // collide with the wrapped heading.
            let ly = lowerY + 15 + Math.max(0, legendTitleLines.length - 1) * 12;
            doc.setFont('helvetica', 'normal');
            doc.setFontSize(8.2);
            (activeLegend.items || []).forEach(function (item) {
                doc.setFillColor(item.color);
                doc.setDrawColor(80, 80, 80);
                doc.rect(margin, ly - 7, 12, 8, 'FD');
                doc.setTextColor(25, 25, 25);
                doc.text(String(item.label), margin + 18, ly);
                ly += 12;
            });
            doc.setFontSize(7.2);
            doc.setTextColor(75, 75, 75);
            drawWrapped(doc, activeLegend.note || '', margin, ly + 2, leftWidth);

            doc.setTextColor(25, 25, 25);
            doc.setFont('helvetica', 'bold');
            doc.setFontSize(11);
            doc.text('Analysis summary', rightX, lowerY);
            let ry = lowerY + 15;
            doc.setFontSize(7.8);
            // Keep a fixed, visible gap between the longest label and the value column.
            // The previous 112-point offset allowed "Population above threshold" to
            // touch its value in the rendered PDF.
            const summaryValueOffset = 138;
            const summaryValueX = rightX + summaryValueOffset;
            const summaryValueWidth = Math.max(90, rightWidth - summaryValueOffset);
            const activeInterval = Math.max(0, Math.round(Number(window.flareCurrentInterval || 0)));
            const radiusRange = activeRadiusRange();
            const doseRange = window.flareCurrentDoseRange || {};
            const activePopulation = window.flareCurrentPopulation;
            const activeBearing = Number(
                window.flareCurrentBearing !== undefined
                    ? window.flareCurrentBearing
                    : (payload.selected_bearing_deg || 0)
            );
            const baseSummary = (payload.summary_by_interval && payload.summary_by_interval[activeInterval])
                ? payload.summary_by_interval[activeInterval]
                : (payload.summary || []);
            const activeSummary = baseSummary.map(function(row) {
                const next = {label:String(row.label), value:String(row.value)};
                if (next.label === 'Selected pathway')
                    next.value = activeBearing.toFixed(1) + '°';
                else if (next.label === 'Population above threshold' && activePopulation !== null && activePopulation !== undefined)
                    next.value = Math.round(Number(activePopulation) || 0).toLocaleString();
                else if (next.label === 'Map maximum' && doseRange.maximum !== undefined)
                    next.value = Number(doseRange.maximum).toPrecision(3) + ' rem display maximum';
                else if (next.label === 'Dose threshold' && doseRange.minimum !== undefined)
                    next.value = Number(doseRange.minimum).toPrecision(3) + ' rem';
                else if (next.label === 'Analysis radius range')
                    next.value = radiusRange.minimum.toFixed(3) + '-' + radiusRange.maximum.toFixed(3) + ' miles';
                return next;
            });
            activeSummary.forEach(function (row) {
                doc.setFont('helvetica', 'bold');
                doc.text(String(row.label), rightX, ry);
                doc.setFont('helvetica', 'normal');
                const valueLines = doc.splitTextToSize(
                    String(row.value),
                    summaryValueWidth
                );
                doc.text(valueLines, summaryValueX, ry);
                ry += Math.max(11, valueLines.length * 9);
            });
            if (payload.source_workbook) {
                ry += 2;
                doc.setFont('helvetica', 'bold');
                doc.text('Source workbook', rightX, ry);
                doc.setFont('helvetica', 'normal');
                doc.text(doc.splitTextToSize(String(payload.source_workbook), rightWidth), rightX, ry + 10);
            }

            doc.setFontSize(6.8);
            doc.setTextColor(100, 100, 100);
            doc.text('Centered layered map composite; viewport radius = 105% of analysis radius', pageWidth / 2, pageHeight - 23, {align: 'center'});
            doc.text('Generated by FLARE Population Map', pageWidth / 2, pageHeight - 14, {align: 'center'});
            doc.save(payload.filename || 'FLARE_dose_map.pdf');
        } catch (error) {
            console.error('FLARE report export failed', error);
            window.alert('Could not generate the report PDF. Verify that map tiles are fully loaded and internet access permits the PDF export libraries.');
        }
    }

    window.addEventListener('message', function (event) {
        if (event && event.data && event.data.type === 'flare-export-report-pdf') {
            exportPdf();
        }
    });
})();
{% endmacro %}
""")

def make_map(
    site_lat: float,
    site_lon: float,
    cells: pd.DataFrame,
    bearing_deg: float,
    radius_miles: float,
    minimum_radius_miles: float = 0.0,
    half_angle_deg: float | None = None,
    dispersion_inputs=None,
    dose_curve=None,
    plume_edge_fraction: float = 0.01,
    minimum_dose_rem: float = 0.01,
    show_population: bool = True,
    show_plume: bool = True,
    show_radius: bool = True,
    radiological_layer: str = "Airborne dose",
    deposition_intervals=(),
    deposition_group_name: str = "Total depositing inventory",
    consequence_field=None,
    consequence_fields: tuple[np.ndarray, ...] = (),
    population_consequence_fields: tuple[np.ndarray, ...] = (),
    consequence_title: str = "",
    consequence_units: str = "rem",
    consequence_scale_maximum: float | None = None,
    consequence_elapsed_hours: tuple[float, ...] = (),
    consequence_initial_step: int = 0,
    consequence_display_step: int | None = None,
    consequence_total_steps: int | None = None,
    embedded_legend: bool = True,
    view_bounds: list[list[float]] | None = None,
    fit_view_to_radius: bool = False,
    report_export_payload: dict | None = None,
    pathway_control_payload: dict | None = None,
) -> folium.Map:
    """Create a map centered and scaled to the selected analysis radius."""
    m = folium.Map(
        location=[site_lat, site_lon],
        control_scale=True,
        tiles=None,
        zoom_control=True,
        scroll_wheel_zoom=False,
        zoom_snap=0.05,
        zoom_delta=0.25,
    )
    m.get_root().header.add_child(Element(
        "<style>.leaflet-image-layer{image-rendering:auto!important;}</style>"
    ))
    folium.TileLayer(
        tiles="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        attr="&copy; OpenStreetMap contributors",
        name="OpenStreetMap",
        overlay=False,
        control=False,
        cross_origin=True,
    ).add_to(m)

    _add_flare_layer_panes(m)

    folium.Marker(
        [site_lat, site_lon],
        tooltip="Release location",
        icon=folium.Icon(color="red"),
    ).add_to(m)

    outer_circle = None
    inner_circle = None
    if show_radius:
        outer_circle = folium.Circle(
            [site_lat, site_lon],
            radius=radius_miles * 1609.344,
            fill=False,
            weight=3,
            color="#555555",
            tooltip=f"{radius_miles:g}-mile outer analysis radius",
            name="Outer analysis radius",
        )
        outer_circle.add_to(m)
        inner_circle = folium.Circle(
            [site_lat, site_lon],
            radius=max(minimum_radius_miles, 0.0) * 1609.344,
            fill=False,
            weight=2,
            color="#777777",
            opacity=1.0 if minimum_radius_miles > 0.0 else 0.0,
            dash_array="6,5",
            tooltip=f"{minimum_radius_miles:g}-mile inner analysis radius",
            name="Inner analysis radius",
        )
        inner_circle.add_to(m)

    population_heat_layer = None
    if show_population and not cells.empty:
        lat = cells["latitude"].to_numpy(float)
        lon = cells["longitude"].to_numpy(float)
        east_miles, north_miles = local_xy_miles(lat, lon, site_lat, site_lon)
        radial_distance = np.hypot(east_miles, north_miles)
        population_mask = (radial_distance >= minimum_radius_miles) & (radial_distance <= radius_miles)
        visible_cells = cells.loc[population_mask]
        heat = [
            [float(r.latitude), float(r.longitude), float(r.population)]
            for r in visible_cells.itertuples()
            if r.population > 0
        ]
        if heat:
            population_heat_layer = HeatMap(
                heat, radius=14, blur=18, min_opacity=0.25,
                name="Population density", show=True, pane="flarePopulationPane",
            )
            population_heat_layer.add_to(m)

    pathway_line = None
    if show_plume:
        pathway_line = folium.PolyLine(
            locations=[
                _offset_latlon(
                    site_lat, site_lon,
                    minimum_radius_miles * math.cos(math.radians(bearing_deg)),
                    minimum_radius_miles * math.sin(math.radians(bearing_deg)),
                ),
                _offset_latlon(
                    site_lat, site_lon,
                    radius_miles * math.cos(math.radians(bearing_deg)),
                    radius_miles * math.sin(math.radians(bearing_deg)),
                ),
            ],
            color="#8b2500",
            weight=3,
            opacity=0.9,
            dash_array="8,6",
            interactive=False,
            name="Predominant pathway",
        )
        pathway_line.add_to(m)

    if show_plume:
        if consequence_fields:
            fixed_maximum = consequence_scale_maximum
            if fixed_maximum is None:
                fixed_maximum = float(np.max(consequence_fields[-1], initial=0.0))
            _add_time_evolving_overlays(
                m, site_lat, site_lon, radius_miles, consequence_fields,
                consequence_title or radiological_layer, consequence_units, minimum_dose_rem,
                fixed_maximum, consequence_elapsed_hours, consequence_initial_step,
                consequence_display_step, consequence_total_steps, embedded_legend,
                minimum_radius_miles=minimum_radius_miles,
                population_fields=population_consequence_fields,
                cells=cells,
                bearing_deg=bearing_deg,
                outer_circle=outer_circle,
                inner_circle=inner_circle,
                pathway_line=pathway_line,
                population_heat_layer=population_heat_layer,
                pathway_inputs=pathway_control_payload,
            )
            plume_name = consequence_title or radiological_layer
        elif consequence_field is not None:
            fixed_maximum = consequence_scale_maximum
            if fixed_maximum is None:
                fixed_maximum = float(np.max(consequence_field, initial=0.0))
            rgba, colors, labels, note = _consequence_rgba(
                consequence_field, consequence_units, minimum_dose_rem, fixed_maximum
            )
            overlay = folium.raster_layers.ImageOverlay(
                image=rgba, bounds=_radius_bounds(site_lat, site_lon, radius_miles),
                opacity=0.98, pane="flareConsequencePane", interactive=False, cross_origin=False, zindex=6,
                name=consequence_title or radiological_layer, show=True,
            )
            overlay.add_to(m)
            _add_zoom_refresh(m, [overlay])
            _add_consequence_legend(
                m, consequence_title or radiological_layer, colors, labels, note,
                visible=embedded_legend,
            )
            plume_name = consequence_title or radiological_layer
        elif radiological_layer == "Ground deposition" and dispersion_inputs is not None and deposition_intervals:
            _deposition_overlay(
                m, site_lat, site_lon, bearing_deg, radius_miles, dispersion_inputs,
                deposition_intervals, deposition_group_name,
            )
            plume_name = f"Synthetic deposition; predominant pathway {bearing_deg:.0f}°"
        elif dispersion_inputs is not None and dose_curve is not None:
            positive = np.asarray(dose_curve.centerline_dose_rem, dtype=float)
            positive = positive[np.isfinite(positive) & (positive > 0.0)]
            max_dose_rem = float(np.max(positive))
            limits = _dose_scale(max_dose_rem, minimum_dose_rem, len(_DOSE_COLORS))
            # Draw outer low-dose contours first; inner high-dose contours overlay them.
            for idx, threshold in enumerate(limits[:-1]):
                polygon = _dose_contour_polygon(
                    site_lat, site_lon, bearing_deg, radius_miles,
                    dispersion_inputs, dose_curve, float(threshold), max_dose_rem,
                    edge_fraction=plume_edge_fraction,
                )
                if polygon:
                    folium.Polygon(
                        locations=polygon,
                        color=_DOSE_COLORS[idx],
                        weight=1.5 if idx < len(_DOSE_COLORS) - 1 else 2.5,
                        opacity=0.95,
                        fill=True,
                        fill_color=_DOSE_COLORS[idx],
                        fill_opacity=0.68,
                        tooltip=(
                            f"Dose band {_format_dose(limits[idx])}–"
                            f"{_format_dose(limits[idx + 1])} rem"
                        ),
                        name=f"Dose ≥ {_format_dose(threshold)} rem",
                        show=True,
                    ).add_to(m)
            _add_dose_legend(m, limits, f"{dose_curve.label} dose")
            plume_name = f"Dose-scaled Gaussian plume; centerline {bearing_deg:.0f}°"
        elif dispersion_inputs is not None:
            polygon = dose_plume_polygon(
                site_lat, site_lon, bearing_deg, radius_miles,
                dispersion_inputs, plume_edge_fraction,
            )
            plume_name = f"Gaussian plume ({plume_edge_fraction:.0%} centerline-dose edge)"
            folium.Polygon(
                locations=polygon, color="#d95f02", weight=4, opacity=0.95,
                fill=True, fill_color="#ff8c00", fill_opacity=0.40,
                tooltip=f"{plume_name}; centerline {bearing_deg:.0f}°",
                name=plume_name, show=True,
            ).add_to(m)
        else:
            polygon = plume_polygon(site_lat, site_lon, bearing_deg, radius_miles, half_angle_deg or 10.0)
            plume_name = "Geometric plume"
            folium.Polygon(
                locations=polygon, color="#d95f02", weight=4, opacity=0.95,
                fill=True, fill_color="#ff8c00", fill_opacity=0.40,
                tooltip=f"{plume_name}; centerline {bearing_deg:.0f}°",
                name=plume_name, show=True,
            ).add_to(m)


    if fit_view_to_radius:
        _FitCircularViewport(site_lat, site_lon, radius_miles, margin_fraction=0.03).add_to(m)
    else:
        m.fit_bounds(
            view_bounds if view_bounds is not None else _radius_bounds(site_lat, site_lon, radius_miles),
            padding=(0, 0) if view_bounds is not None else (12, 12),
        )
    folium.LayerControl().add_to(m)
    if report_export_payload:
        _ReportPdfExporter(site_lat, site_lon, radius_miles, report_export_payload).add_to(m)

    return m
