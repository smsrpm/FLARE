"""Create a small synthetic database around Lynchburg for immediate testing.

This is deliberately synthetic and must not be used for actual population results.
"""
from pathlib import Path
import numpy as np
import pandas as pd

from flare_map_core.database import replace_cells

rng = np.random.default_rng(20260724)
site_lat, site_lon = 37.4138, -79.1422
clusters = [
    (37.4138, -79.1422, 60000, 220),
    (37.4450, -79.2050, 15000, 90),
    (37.3550, -79.0900, 8000, 60),
]
rows = []
cell_id = 1
for lat0, lon0, total, n in clusters:
    pops = rng.multinomial(total, np.ones(n)/n)
    for p in pops:
        rows.append((cell_id, lat0+rng.normal(0, .025), lon0+rng.normal(0, .032), int(p)))
        cell_id += 1
cells = pd.DataFrame(rows, columns=["cell_id", "latitude", "longitude", "population"])
out = Path(__file__).resolve().parents[1] / "data" / "demo_population.sqlite"
replace_cells(out, cells, {"source": "synthetic demonstration data", "warning": "not Census data"})
print(out)
