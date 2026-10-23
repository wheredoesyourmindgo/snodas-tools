from datetime import date

import numpy as np
import pytest

from snodas_tools.convert import (
    MASKED_SHAPE,
    NODATA,
    RESOLUTION,
    UNMASKED_SHAPE,
    ClipRegion,
    convert_file,
    grid_bounds,
    open_raster,
    output_path,
    read_dat,
    save_raster,
    to_dataarray,
)
from snodas_tools.filenames import day_dir
from snodas_tools.products import get_product

from conftest import DAY, SWE_NAME


@pytest.mark.parametrize("masked, shape", [(True, MASKED_SHAPE), (False, UNMASKED_SHAPE)])
@pytest.mark.parametrize("day", [date(2010, 1, 1), date(2020, 1, 1)])
def test_grid_bounds_match_grid_size(masked, shape, day):
    west, south, east, north = grid_bounds(day, masked)
    rows, cols = shape
    assert (east - west) / RESOLUTION == pytest.approx(cols, abs=1e-6)
    assert (north - south) / RESOLUTION == pytest.approx(rows, abs=1e-6)


def test_to_dataarray_scales_masks_and_uses_cell_centers():
    raw = np.array([[1000, NODATA], [250, 0]], dtype=np.int16)
    da = to_dataarray(raw, date(2020, 1, 1), True, get_product("swe"), "swe")
    np.testing.assert_allclose(da.values, [[1.0, np.nan], [0.25, 0.0]])
    west, _, _, north = grid_bounds(date(2020, 1, 1), True)
    assert float(da.lon[0]) == pytest.approx(west + RESOLUTION / 2)
    assert float(da.lat[0]) == pytest.approx(north - RESOLUTION / 2)
    assert da.attrs["units"] == "m"
    assert str(da.rio.crs) == "EPSG:4326"


@pytest.mark.parametrize("fmt, suffix", [("netcdf", ".nc"), ("geotiff", ".tif")])
def test_round_trip(tmp_path, fmt, suffix):
    raw = (np.arange(12, dtype=np.int16).reshape(3, 4) * 100).astype(np.int16)
    raw[0, 0] = NODATA
    da = to_dataarray(raw, date(2020, 1, 1), True, get_product("swe"), "swe")
    path = tmp_path / f"grid{suffix}"
    save_raster(da, path, fmt)
    back = open_raster(path)
    np.testing.assert_allclose(back.values, da.values, atol=1e-6)
    np.testing.assert_allclose(back[back.rio.x_dim].values, da.lon.values)
    assert back.rio.crs is not None


def test_read_dat_checks_size(tmp_path):
    path = tmp_path / f"{SWE_NAME}.dat"
    np.zeros(10, dtype=">i2").tofile(path)
    with pytest.raises(ValueError, match="masked/unmasked"):
        read_dat(path, masked=True)


def test_convert_file_full_and_clipped(tmp_path, square_basin):
    folder = day_dir(tmp_path, DAY)
    folder.mkdir(parents=True)
    dat = folder / f"{SWE_NAME}.dat"
    rows, cols = MASKED_SHAPE
    raw = np.full((rows, cols), 500, dtype=">i2")  # 0.5 m everywhere
    raw.tofile(dat)

    region = ClipRegion("basin", [square_basin], buffer_m=1000)
    written = convert_file(dat, regions=[region], keep_full_extent=False)
    assert written == [output_path(dat, "netcdf", "basin")]
    assert not output_path(dat, "netcdf").exists()

    clipped = open_raster(written[0])
    assert 80 < clipped.rio.width < 120  # 80 cells of basin plus the buffer
    assert np.nanmean(clipped.values) == pytest.approx(0.5)

    # second call is a no-op because outputs exist
    mtime = written[0].stat().st_mtime_ns
    convert_file(dat, regions=[region], keep_full_extent=False)
    assert written[0].stat().st_mtime_ns == mtime
