"""
Basin statistics for converted SNODAS grids.

For each basin and day this computes:

- `avg`: the basin's average value (e.g. average SWE in inches or mm; average snowpack temperature)
- `sum`: the basin's total water volume (acre-feet or cubic meters) for depth-type products
  (SWE, depth, melt, sublimation, precipitation). Volume = average depth over the basin's valid cells x basin area.

Optionally, the same statistics per elevation band, using a DEM you provide (see `snodas dem`).
"""

from dataclasses import dataclass, field
from datetime import date
import logging
from pathlib import Path

import numpy as np
import rioxarray  # noqa: F401  (registers the .rio accessor)
import xarray as xr
from rasterio.enums import Resampling
from scipy.spatial import QhullError

from .convert import ensure_spatial, open_raster
from .geometry import WGS84, area_m2, load_shapes_cached
from .products import Product

log = logging.getLogger(__name__)

M_PER_FT = 0.3048
M_PER_IN = 0.0254
M3_PER_ACRE_FT = 1233.48183754752


@dataclass
class ElevationBands:
    """Settings for splitting a basin into elevation bands."""

    dem: Path  # any raster GDAL can read, elevations in meters
    step: float = 500  # band height, in `units`
    units: str = "ft"  # "ft" or "m"; band edges and labels use these units
    min: float | None = None  # lowest band edge (default: rounded down from the basin's lowest point)
    max: float | None = None  # highest band edge (default: rounded up from the basin's highest point)
    dem_nodata: float | None = None  # override the DEM's nodata value


@dataclass
class Basin:
    """An area to compute statistics for."""

    name: str
    shapes: list[Path]
    source: str | None = None  # name of a clip region to read from (default: the full grid)
    interpolate: bool = True  # fill missing cells (e.g. lakes) inside the basin before computing statistics
    elevation_bands: ElevationBands | None = None
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Units:
    """Output units."""

    system: str = "imperial"  # "imperial": inches and acre-feet; "metric": millimeters and cubic meters
    temperature: str = "F"  # "K", "C" or "F"

    def __post_init__(self):
        if self.system not in ("imperial", "metric"):
            raise ValueError("units must be 'imperial' or 'metric'")
        if self.temperature not in ("K", "C", "F"):
            raise ValueError("temperature units must be 'K', 'C' or 'F'")

    def depth_label(self) -> str:
        return "in" if self.system == "imperial" else "mm"

    def volume_label(self) -> str:
        return "acre-ft" if self.system == "imperial" else "m^3"

    def depth(self, meters: float) -> float:
        return meters / M_PER_IN if self.system == "imperial" else meters * 1000

    def volume(self, cubic_meters: float) -> float:
        return cubic_meters / M3_PER_ACRE_FT if self.system == "imperial" else cubic_meters

    def temp(self, kelvin: float) -> float:
        if self.temperature == "C":
            return kelvin - 273.15
        if self.temperature == "F":
            return (kelvin - 273.15) * 9 / 5 + 32
        return kelvin

    def labels(self, product: Product) -> dict[str, str]:
        """Units of each statistic for a product."""
        if product.kind == "temperature":
            return {"avg": self.temperature}
        return {"avg": self.depth_label(), "sum": self.volume_label()}


def clip_to_basin(da: xr.DataArray, basin: Basin) -> xr.DataArray:
    """Clip a grid to a basin (cell centers inside the basin), interpolating missing cells if requested."""
    shapes = load_shapes_cached(basin.shapes)
    if basin.interpolate:
        # clip first so interpolation only works on the basin's neighborhood, then clip again after filling
        da = da.rio.clip(shapes.geometry, crs=WGS84, drop=True, all_touched=True)
        if int(da.notnull().sum()) >= 3 and bool(da.isnull().any()):
            try:
                da = da.rio.interpolate_na(method="linear")
            except QhullError:
                log.warning("Could not interpolate %s for basin '%s'", da.name, basin.name)
    return da.rio.clip(shapes.geometry, crs=WGS84, drop=True, all_touched=False)


_area_cache: dict[tuple[str, ...], float] = {}


def basin_area_m2(basin: Basin) -> float:
    """Basin area in square meters (cached)."""
    key = tuple(str(p) for p in basin.shapes)
    if key not in _area_cache:
        _area_cache[key] = area_m2(load_shapes_cached(basin.shapes))
    return _area_cache[key]


class _DemCache:
    """
    Reprojects each basin's DEM onto the SNODAS grid once (clipped to the basin) and reuses it for every date and
    product.
    """

    def __init__(self):
        self._cache: dict[tuple, xr.DataArray] = {}

    def get(self, basin: Basin, like: xr.DataArray) -> xr.DataArray:
        bands = basin.elevation_bands
        x, y = like.rio.x_dim, like.rio.y_dim
        key = (
            tuple(str(p) for p in basin.shapes),
            str(bands.dem),
            bands.units,
            bands.dem_nodata,
            like.shape,
            round(float(like[x][0]), 9),
            round(float(like[y][0]), 9),
        )
        if key not in self._cache:
            if not Path(bands.dem).exists():
                raise FileNotFoundError(f"DEM not found: {bands.dem} (create one with `snodas dem`)")
            with rioxarray.open_rasterio(bands.dem, masked=True) as src:
                dem = (src[0] if isinstance(src, list) else src).squeeze(drop=True).load()
            if bands.dem_nodata is not None:
                dem = dem.where(dem != bands.dem_nodata)
            # average the fine DEM cells that fall in each SNODAS cell
            dem = dem.rio.reproject_match(like, resampling=Resampling.average, nodata=np.nan)
            dem = dem.rename({dem.rio.x_dim: x, dem.rio.y_dim: y}) if dem.rio.x_dim != x else dem
            dem = dem.assign_coords({x: like[x], y: like[y]})
            dem = dem.rio.clip(load_shapes_cached(basin.shapes).geometry, crs=WGS84, drop=False, all_touched=False)
            if bands.units == "ft":
                dem = dem / M_PER_FT
            self._cache[key] = dem
        return self._cache[key]


_dem_cache = _DemCache()


def band_edges(dem: xr.DataArray, bands: ElevationBands) -> np.ndarray:
    """Elevation band edges covering the basin, every `step` units."""
    step = bands.step
    lo = bands.min if bands.min is not None else np.floor(float(dem.min()) / step) * step
    hi = bands.max if bands.max is not None else np.ceil(float(dem.max()) / step) * step
    if hi <= lo:
        hi = lo + step
    count = int(np.ceil((hi - lo) / step))
    return lo + np.arange(count + 1) * step


def band_label(lower: float, upper: float) -> str:
    return f"{lower:g}-{upper:g}"


@dataclass
class BasinStats:
    """Statistics for one basin, product and date."""

    basin: str
    product: str
    day: date
    values: dict[str, float]  # statistic -> value, e.g. {"avg": 12.3, "sum": 45678.9}
    bands: dict[str, dict[str, float]] | None = None  # statistic -> {band label -> value}


def basin_stats(raster: str | Path | xr.DataArray, basin: Basin, product: Product, day: date, units: Units) -> BasinStats:
    """Compute statistics for one basin from one converted SNODAS grid (values in the product's physical units)."""
    da = ensure_spatial(raster) if isinstance(raster, xr.DataArray) else open_raster(raster)
    clipped = clip_to_basin(da, basin)
    valid = clipped.notnull()
    count = int(valid.sum())

    def summarize(values: xr.DataArray) -> dict[str, float]:
        if product.kind == "temperature":
            mean = float(values.mean()) if bool(values.notnull().any()) else np.nan
            return {"avg": round(units.temp(mean), 2)}
        mean_m = float(values.mean()) if bool(values.notnull().any()) else np.nan
        # each band's share of the basin volume: its cells' total depth spread over all the basin's valid cells
        share = float(values.sum()) / count if count else np.nan
        return {
            "avg": round(units.depth(mean_m), 2),
            "sum": round(units.volume(share * basin_area_m2(basin)), 2),
        }

    result = BasinStats(basin.name, product.key, day, summarize(clipped))
    if count == 0:
        log.warning("%s %s: no valid cells in basin '%s'", day, product.key, basin.name)

    if basin.elevation_bands:
        dem = _dem_cache.get(basin, clipped)
        # edges come from the whole basin (not just today's valid cells) so the band columns are stable over time
        edges = band_edges(dem, basin.elevation_bands)
        per_stat: dict[str, dict[str, float]] = {}
        for i, (lower, upper) in enumerate(zip(edges[:-1], edges[1:], strict=True)):
            # bands include their upper edge; the lowest band also includes its lower edge
            above = dem >= lower if i == 0 else dem > lower
            in_band = above & (dem <= upper) & valid
            stats = summarize(clipped.where(in_band))
            if product.kind != "temperature" and not bool(in_band.any()):
                stats = {k: 0.0 for k in stats}
            for stat, value in stats.items():
                per_stat.setdefault(stat, {})[band_label(lower, upper)] = value
        result.bands = per_stat
    return result
