"""
Shared test fixtures: small synthetic grids and basins, so tests never touch the network.
"""

from datetime import date
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rioxarray  # noqa: F401
import xarray as xr
from shapely.geometry import box

from snodas_tools.convert import RESOLUTION

DAY = date(2025, 4, 1)
SWE_NAME = "us_ssmv11034tS__T0001TTNATS2025040105HP001"


def make_grid(value: float = 0.5, west: float = -106.0, north: float = 40.0, size: int = 120, name: str = "swe") -> xr.DataArray:
    """A size x size grid at SNODAS resolution, filled with `value` (physical units)."""
    lon = west + (np.arange(size) + 0.5) * RESOLUTION
    lat = north - (np.arange(size) + 0.5) * RESOLUTION
    da = xr.DataArray(np.full((size, size), value, dtype=np.float32), coords={"lat": lat, "lon": lon}, dims=("lat", "lon"), name=name)
    da.attrs.update({"units": "m", "long_name": "Snow water equivalent", "date": DAY.isoformat()})
    return da.rio.set_spatial_dims(x_dim="lon", y_dim="lat").rio.write_crs("EPSG:4326")


def write_shape(path: Path, geometry, crs: str = "EPSG:4326") -> Path:
    gpd.GeoDataFrame(geometry=[geometry], crs=crs).to_file(path, driver="GeoJSON")
    return path


@pytest.fixture
def grid() -> xr.DataArray:
    return make_grid()


@pytest.fixture
def square_basin(tmp_path) -> Path:
    """A basin covering the middle of the synthetic grid (cell edges line up with the grid)."""
    r = RESOLUTION
    return write_shape(tmp_path / "basin.geojson", box(-106.0 + 20 * r, 40.0 - 100 * r, -106.0 + 100 * r, 40.0 - 20 * r))
