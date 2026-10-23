"""
Downloading a digital elevation model (DEM) for a basin from the USGS 3D Elevation Program (3DEP).

The 3DEP image service is free and needs no API key. It covers the US, which includes everything SNODAS covers.
The DEM is used for elevation-band statistics.
"""

import logging
import math
from pathlib import Path
import tempfile

import numpy as np
import requests
import rioxarray  # noqa: F401  (registers the .rio accessor)
from rioxarray.merge import merge_arrays
from tenacity import retry, stop_after_attempt, wait_exponential

from .geometry import WGS84, buffer, load_shapes

log = logging.getLogger(__name__)

EXPORT_URL = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage"
MAX_TILE_PX = 2000


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=2, max=20), reraise=True)
def _fetch_tile(bbox: tuple[float, float, float, float], width: int, height: int, target: Path) -> None:
    params = {
        "bbox": ",".join(f"{v:.8f}" for v in bbox),
        "bboxSR": 4326,
        "imageSR": 4326,
        "size": f"{width},{height}",
        "format": "tiff",
        "pixelType": "F32",
        "noData": -9999,
        "noDataInterpretation": "esriNoDataMatchAny",
        "interpolation": "RSP_BilinearInterpolation",
        "f": "image",
    }
    response = requests.get(EXPORT_URL, params=params, timeout=180)
    response.raise_for_status()
    if not response.headers.get("Content-Type", "").startswith("image"):
        raise RuntimeError(f"3DEP returned an error instead of an image: {response.text[:300]}")
    target.write_bytes(response.content)


def download_dem(
    shapes: list[str | Path],
    output: str | Path,
    resolution_arcsec: float = 3.0,
    margin_m: float = 2000.0,
) -> Path:
    """
    Download a DEM (elevations in meters, WGS84) covering the given shapes, plus a margin, and save it as GeoTIFF.

    `resolution_arcsec` of 3 (about 90 m) is plenty for SNODAS' 30 arc-second (about 1 km) cells.
    """
    output = Path(output)
    area = buffer(load_shapes(shapes), margin_m)
    west, south, east, north = area.total_bounds
    res = resolution_arcsec / 3600
    width = math.ceil((east - west) / res)
    height = math.ceil((north - south) / res)
    cols = math.ceil(width / MAX_TILE_PX)
    rows = math.ceil(height / MAX_TILE_PX)
    log.info("Downloading %dx%d DEM in %d tile(s)", width, height, cols * rows)

    with tempfile.TemporaryDirectory() as tmp:
        tiles = []
        for r in range(rows):
            for c in range(cols):
                tw = min(MAX_TILE_PX, width - c * MAX_TILE_PX)
                th = min(MAX_TILE_PX, height - r * MAX_TILE_PX)
                x0 = west + c * MAX_TILE_PX * res
                y1 = north - r * MAX_TILE_PX * res
                bbox = (x0, y1 - th * res, x0 + tw * res, y1)
                path = Path(tmp) / f"tile_{r}_{c}.tif"
                _fetch_tile(bbox, tw, th, path)
                with rioxarray.open_rasterio(path, masked=True) as src:
                    tile = src.squeeze("band", drop=True).load()
                if tile.rio.crs is None:
                    tile = tile.rio.write_crs(WGS84)
                tile.encoding = {}  # drop the file's on-disk nodata encoding; NaN marks missing cells from here on
                tiles.append(tile.rio.write_nodata(np.nan, encoded=False))
        # nodata=NaN so any gap between tiles is marked missing rather than filled with 0 (a real elevation)
        dem = tiles[0] if len(tiles) == 1 else merge_arrays(tiles, nodata=np.nan)
        dem.attrs.update({"units": "m", "source": "USGS 3DEP"})
        output.parent.mkdir(parents=True, exist_ok=True)
        dem.rio.to_raster(output, driver="GTiff", compress="DEFLATE", dtype="float32")
    return output
