"""
Using snodas-tools from Python: download a week of data, compute basin statistics, and plot them.

    pip install "snodas-tools[plot]"
    python examples/explore.py

Writes to ./snodas_data and ./snodas_output, and saves explore.png.
"""

from pathlib import Path

import matplotlib.pyplot as plt

from snodas_tools import Basin, Units, basin_stats, convert, download, get_product, open_raster, resolve_dates
from snodas_tools.pipeline import find_raster
from snodas_tools.preview import crop_to_shapes

HERE = Path(__file__).parent
DATA = Path("snodas_data")
basin = Basin("colorado_headwaters", [HERE / "basins" / "colorado_headwaters.geojson"])
swe = get_product("swe")

# 1. download and convert a week of SNODAS data (only SWE)
days = resolve_dates(start="2025-03-25", end="2025-04-01")
download(days, DATA)
convert(days, DATA, products=[swe])

# 2. basin statistics for each day
units = Units("imperial")
rows = []
for day in days:
    grid = find_raster(day, DATA, masked=True, product=swe, source=None)
    if grid is not None:
        stats = basin_stats(grid, basin, swe, day, units)
        rows.append((day, stats.values["sum"], stats.values["avg"]))
        print(f"{day}  {stats.values['sum']:>12,.0f} acre-ft  {stats.values['avg']:5.2f} in")

# 3. a map of the last day, clipped to the basin, next to the time series
grid = open_raster(find_raster(days[-1], DATA, True, swe, None))
clipped = crop_to_shapes(grid, basin.shapes)

fig, (left, right) = plt.subplots(1, 2, figsize=(13, 5))
clipped.plot(ax=left, cmap="viridis", robust=True, cbar_kwargs={"label": "SWE (m)"})
left.set_title(f"SWE {days[-1]}")
right.plot([r[0] for r in rows], [r[1] for r in rows], marker="o")
right.set_title("Basin SWE volume")
right.set_ylabel("acre-feet")
fig.autofmt_xdate()
fig.tight_layout()
fig.savefig("explore.png", dpi=120)
print("Saved explore.png")
