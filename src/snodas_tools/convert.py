"""
Converting raw SNODAS `.dat` grids into georeferenced NetCDF or GeoTIFF files, and optionally saving clipped
subsets for regions of interest.

SNODAS grids are flat binary files of big-endian 16-bit integers on a 30 arc-second (1/120 degree) WGS84 grid.
See https://nsidc.org/data/user-resources/help-center/how-do-i-convert-snodas-binary-files-geotiff-or-netcdf
"""

from dataclasses import dataclass, field
from datetime import date
import gc
import logging
from pathlib import Path
from typing import Literal

import numpy as np
import rioxarray  # noqa: F401  (registers the .rio accessor)
import xarray as xr
from rasterio.enums import Resampling
from scipy.spatial import QhullError
from tqdm import tqdm

from .filenames import date_from_path, find_files, parse_snodas_filename
from .geometry import WGS84, buffer, load_shapes_cached
from .products import Product

log = logging.getLogger(__name__)

Format = Literal["netcdf", "geotiff"]
EXTENSIONS: dict[str, str] = {"netcdf": ".nc", "geotiff": ".tif"}

RESOLUTION = 1 / 120  # degrees (30 arc-seconds)
NODATA = -9999
GRID_CHANGE = date(2013, 10, 1)  # NSIDC shifted the grid slightly on this date

# (rows, columns)
MASKED_SHAPE = (3351, 6935)
UNMASKED_SHAPE = (4096, 8192)


def grid_bounds(day: date, masked: bool) -> tuple[float, float, float, float]:
    """Outer edges (west, south, east, north) of the SNODAS grid, in degrees."""
    if masked:
        if day < GRID_CHANGE:
            return (-124.73375, 24.949583333333333, -66.942083333333333, 52.874583333333333)
        return (-124.733333333333333, 24.95, -66.941666666666667, 52.875)
    if day < GRID_CHANGE:
        return (-130.517083333333333, 24.099583333333333, -62.250416666666667, 58.232916666666667)
    return (-130.516666666666667, 24.1, -62.25, 58.233333333333333)


@dataclass
class ClipRegion:
    """
    A region to save a clipped copy of each converted grid for.

    The output file is named `<snodas name>_<name>.nc` (or `.tif`) next to the full grid.
    """

    name: str
    shapes: list[Path]
    buffer_m: float = 0.0  # grow the region by this many meters before clipping
    interpolate: bool = False  # fill missing cells (e.g. lakes) by linear interpolation
    upscale: int = 1  # resample to N times finer resolution (bilinear)
    format: Format | None = None  # defaults to the conversion format
    extra: dict = field(default_factory=dict)


# SNODAS metadata units -> how many of the product's units (m, K) one metadata unit is
METADATA_UNITS = {"meters": 1.0, "kelvins": 1.0, "kilograms per square meter": 0.001}  # 1 kg/m^2 of water = 1 mm


def read_scale(dat_path: Path, product: Product | None) -> float:
    """
    The divisor that turns a .dat file's raw integers into the product's units, read from the .txt metadata file
    SNODAS ships next to it (e.g. "Data units: Kelvins / 10.000000"). NOAA has changed these over time (snowpack
    temperature went from kelvins to tenths of a kelvin), so they're read per file rather than assumed. Falls back to
    the product's documented scale if there's no metadata file.
    """
    default = product.scale if product else 1.0
    txt = dat_path.with_suffix(".txt")
    if not txt.exists():
        log.warning("%s: no metadata file, assuming a scale of 1/%g", dat_path.name, default)
        return default
    fields = {}
    for line in txt.read_text(errors="replace").splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip().lower()] = value.strip()
    if float(fields.get("data slope", 1)) != 1 or float(fields.get("data intercept", 0)) != 0:
        raise ValueError(f"{txt.name}: unsupported data slope/intercept {fields.get('data slope')}/{fields.get('data intercept')}")
    unit, _, divisor = fields.get("data units", "").partition("/")
    unit = unit.strip().lower()
    if unit not in METADATA_UNITS:
        raise ValueError(f"{txt.name}: unrecognized data units '{fields.get('data units')}'")
    return float(divisor or 1) / METADATA_UNITS[unit]


def read_dat(path: Path, masked: bool) -> np.ndarray:
    """Read a raw SNODAS .dat grid as int16."""
    rows, cols = MASKED_SHAPE if masked else UNMASKED_SHAPE
    data = np.fromfile(path, dtype=">i2")
    if data.size != rows * cols:
        raise ValueError(
            f"{path.name} has {data.size} values but a {'masked' if masked else 'unmasked'} grid has {rows * cols}. "
            "Is the masked/unmasked setting right?"
        )
    return data.reshape(rows, cols).astype(np.int16)


def to_dataarray(
    raw: np.ndarray, day: date, masked: bool, product: Product | None, name: str, scale: float | None = None
) -> xr.DataArray:
    """
    Wrap a raw SNODAS grid as a georeferenced DataArray in the product's physical units (NaN where there's no data).
    `scale` is the divisor for the raw values (see `read_scale`); it defaults to the product's documented scale.
    """
    west, south, east, north = grid_bounds(day, masked)
    rows, cols = raw.shape
    # coordinates are pixel centers
    lon = west + (np.arange(cols) + 0.5) * RESOLUTION
    lat = north - (np.arange(rows) + 0.5) * RESOLUTION
    if scale is None:
        scale = product.scale if product else 1.0
    values = np.where(raw == NODATA, np.nan, raw.astype(np.float32) / np.float32(scale))
    da = xr.DataArray(
        values.astype(np.float32),
        coords={"lat": lat, "lon": lon},
        dims=("lat", "lon"),
        name=name,
        attrs={
            "long_name": product.label if product else "SNODAS data",
            "units": product.units if product else "unknown",
        },
    )
    da["lat"].attrs = {"standard_name": "latitude", "units": "degrees_north"}
    da["lon"].attrs = {"standard_name": "longitude", "units": "degrees_east"}
    da = da.rio.set_spatial_dims(x_dim="lon", y_dim="lat").rio.write_crs(WGS84)
    da.rio.write_nodata(np.nan, encoded=False, inplace=True)
    # pack back to int16 on disk: readers that follow CF conventions get physical units automatically
    da.encoding.update({"dtype": "int16", "scale_factor": 1 / scale, "_FillValue": NODATA, "zlib": True, "complevel": 4})
    return da


def ensure_spatial(da: xr.DataArray) -> xr.DataArray:
    """
    Make sure rioxarray knows a grid's spatial dimensions and CRS. Copies of a DataArray forget which dimensions are
    spatial when they're named lat/lon, so this is applied to every grid passed in.
    """
    if "lon" in da.dims and "lat" in da.dims:
        da = da.rio.set_spatial_dims(x_dim="lon", y_dim="lat")
    if da.rio.crs is None:
        da = da.rio.write_crs(WGS84)
    if da.rio.nodata is None and da.rio.encoded_nodata is None and np.issubdtype(da.dtype, np.floating):
        # missing cells are NaN; rioxarray needs to be told so for clipping and interpolation
        da = da.rio.write_nodata(np.nan, encoded=False)
    return da


def open_raster(path: str | Path) -> xr.DataArray:
    """
    Open a NetCDF or GeoTIFF written by snodas-tools as a DataArray in physical units, NaN for missing data.
    """
    path = Path(path)
    if path.suffix == ".nc":
        with xr.open_dataset(path, decode_coords="all") as ds:
            names = [v for v in ds.data_vars if ds[v].ndim == 2]
            if not names:
                raise ValueError(f"No 2D data variable found in {path}")
            da = ds[names[0]].load()
    else:
        # close the file explicitly; leaving it to garbage collection prints errors at interpreter shutdown
        with rioxarray.open_rasterio(path, masked=True) as src:
            da = (src[0] if isinstance(src, list) else src).squeeze("band", drop=True).load()
    return ensure_spatial(da)


def save_raster(da: xr.DataArray, path: Path, fmt: Format) -> None:
    """Write a DataArray as NetCDF or a compressed GeoTIFF."""
    tmp = path.with_name(path.name + ".part")
    if fmt == "netcdf":
        out = da.copy()
        # the fill value is set through encoding (packed int16), not as an attribute
        out.attrs.pop("_FillValue", None)
        out.to_dataset(promote_attrs=False).to_netcdf(tmp, format="NETCDF4")
    else:
        # GeoTIFFs are written as float32 in physical units; drop the NetCDF int16 packing settings
        out = da.copy()
        out.encoding = {}
        out.rio.write_nodata(np.nan, encoded=False, inplace=True)
        out.rio.to_raster(tmp, driver="GTiff", compress="DEFLATE", dtype="float32")
    tmp.replace(path)


def clip_dataarray(da: xr.DataArray, region: ClipRegion) -> xr.DataArray:
    """Clip a grid to a region, applying its buffer, interpolation and upscaling options."""
    shapes = buffer(load_shapes_cached(region.shapes), region.buffer_m)
    da = ensure_spatial(da)
    clipped = da.rio.clip(shapes.geometry, crs=WGS84, drop=True, all_touched=True)
    if region.interpolate:
        try:
            clipped = clipped.rio.interpolate_na(method="linear")
        except QhullError:
            log.warning("Could not interpolate %s for region '%s' (too few valid cells)", da.name, region.name)
    if region.upscale > 1:
        clipped = clipped.rio.reproject(
            clipped.rio.crs,
            shape=(clipped.rio.height * region.upscale, clipped.rio.width * region.upscale),
            resampling=Resampling.bilinear,
            nodata=np.nan,
        )
    clipped.encoding = dict(da.encoding)
    return clipped


def output_path(dat_path: Path, fmt: Format, region: str | None = None) -> Path:
    """Where the converted (or clipped) version of a .dat file goes."""
    stem = parse_snodas_filename(dat_path).stem
    suffix = f"_{region}" if region else ""
    return dat_path.with_name(f"{stem}{suffix}{EXTENSIONS[fmt]}")


def convert_file(
    dat_path: Path,
    masked: bool = True,
    fmt: Format = "netcdf",
    regions: list[ClipRegion] | None = None,
    keep_full_extent: bool = True,
    overwrite: bool = False,
) -> list[Path]:
    """
    Convert one `.dat` file, and save a clipped copy for each region. Returns the paths written (or already present).
    """
    regions = regions or []
    info = parse_snodas_filename(dat_path)
    product = info.product
    name = product.key if product else "data"

    full_path = output_path(dat_path, fmt)
    region_paths = {r.name: output_path(dat_path, r.format or fmt, r.name) for r in regions}
    wanted = list(region_paths.values()) + ([full_path] if keep_full_extent or not regions else [])
    if not overwrite and all(p.exists() for p in wanted):
        return wanted

    raw = read_dat(dat_path, masked)
    da = to_dataarray(raw, date_from_path(dat_path), masked, product, name, read_scale(dat_path, product))
    da.attrs.update({"snodas_file": info.stem, "date": info.date.isoformat(), "time_utc": f"{info.timestamp_utc:%H:%M}"})

    if keep_full_extent or not regions:
        if overwrite or not full_path.exists():
            save_raster(da, full_path, fmt)
    for region in regions:
        path = region_paths[region.name]
        if overwrite or not path.exists():
            save_raster(clip_dataarray(da, region), path, region.format or fmt)
    # Free the grids now. Each holds ~100 MB in a few objects, and Python's automatic collection (which counts objects,
    # not bytes) rarely runs in time, so a long run would otherwise grow by ~100 MB per file until it ran out of memory.
    del raw, da
    gc.collect()
    return wanted


def convert(
    days: list[date],
    data_dir: Path,
    masked: bool = True,
    products: list[Product] | None = None,
    fmt: Format = "netcdf",
    regions: list[ClipRegion] | None = None,
    keep_raw: bool = True,
    keep_full_extent: bool = True,
    overwrite: bool = False,
    progress: bool = True,
) -> list[Path]:
    """
    Convert the downloaded `.dat` files for the given days. Returns the paths of all converted files.

    - `products`: only convert these products (default: every product in the download).
    - `regions`: also save clipped copies for these regions.
    - `keep_raw`: keep the original `.dat`/`.txt` files after converting.
    - `keep_full_extent`: keep the full continental grid (only meaningful when regions are given).
    """
    wanted_codes = {(p.code, p.vertical_code) for p in products} if products else None
    dat_paths = []
    for path in find_files(Path(data_dir), days, masked, "*.dat"):
        try:
            info = parse_snodas_filename(path)
        except ValueError:
            continue
        if wanted_codes is not None:
            product = info.product
            if product is None or (product.code, product.vertical_code) not in wanted_codes:
                continue
        dat_paths.append(path)

    written: list[Path] = []
    for path in tqdm(dat_paths, desc="Converting", unit="file", disable=None if progress else True):
        written.extend(convert_file(path, masked, fmt, regions, keep_full_extent, overwrite))

    if not keep_raw:
        for path in find_files(Path(data_dir), days, masked, "*.dat") + find_files(Path(data_dir), days, masked, "*.txt"):
            path.unlink(missing_ok=True)
    return written
