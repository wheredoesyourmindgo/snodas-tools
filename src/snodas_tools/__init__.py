"""
snodas-tools: download, convert, and summarize NOAA SNODAS snow data for any basin in the contiguous US.

Typical Python use:

    from snodas_tools import Basin, Units, basin_stats, download, convert, resolve_dates, get_product

    days = resolve_dates(start="2024-04-01", end="2024-04-07")
    download(days, "snodas_data")
    convert(days, "snodas_data", products=[get_product("swe")])
"""

__version__ = "0.1.4"

from .convert import ClipRegion, convert, open_raster
from .dates import resolve_dates
from .download import download
from .products import PRODUCTS, get_product
from .stats import Basin, ElevationBands, Units, basin_stats

__all__ = [
    "Basin",
    "ClipRegion",
    "ElevationBands",
    "PRODUCTS",
    "Units",
    "__version__",
    "basin_stats",
    "convert",
    "download",
    "get_product",
    "open_raster",
    "resolve_dates",
]
