import numpy as np
import pytest
import rioxarray  # noqa: F401
from shapely.geometry import box

from snodas_tools.convert import RESOLUTION
from snodas_tools.geometry import area_m2, buffer, load_shapes
from snodas_tools.products import get_product
from snodas_tools.stats import M3_PER_ACRE_FT, M_PER_IN, Basin, ElevationBands, Units, basin_stats

from conftest import DAY, make_grid, write_shape


def test_equal_area_matches_a_known_area(tmp_path):
    # a 1 x 1 degree box at 40N is about 9,500 km^2 (111.2 km tall x 85.4 km wide)
    path = write_shape(tmp_path / "deg.geojson", box(-106, 39.5, -105, 40.5))
    km2 = area_m2(load_shapes(path)) / 1e6
    assert km2 == pytest.approx(111.19 * 85.18, rel=0.005)


def test_buffer_grows_shape(square_basin):
    shapes = load_shapes(square_basin)
    assert area_m2(buffer(shapes, 1000)) > area_m2(shapes)


def test_volume_and_average(grid, square_basin):
    basin = Basin("b", [square_basin])
    stats = basin_stats(grid, basin, get_product("swe"), DAY, Units("imperial"))
    expected_af = 0.5 * area_m2(load_shapes(square_basin)) / M3_PER_ACRE_FT
    assert stats.values["avg"] == pytest.approx(0.5 / M_PER_IN, abs=0.01)
    assert stats.values["sum"] == pytest.approx(expected_af, rel=1e-4)

    metric = basin_stats(grid, basin, get_product("swe"), DAY, Units("metric"))
    assert metric.values["avg"] == pytest.approx(500, abs=0.01)
    assert metric.values["sum"] == pytest.approx(expected_af * M3_PER_ACRE_FT, rel=1e-4)


def test_missing_cells_are_interpolated(grid, square_basin):
    holey = grid.copy()
    holey.values[50:55, 50:55] = np.nan  # a "lake" inside the basin
    basin = Basin("b", [square_basin], interpolate=True)
    stats = basin_stats(holey, basin, get_product("swe"), DAY, Units())
    assert stats.values["avg"] == pytest.approx(0.5 / M_PER_IN, abs=0.01)


def test_temperature_units(square_basin):
    temp = make_grid(273.15, name="temp")
    basin = Basin("b", [square_basin])
    product = get_product("temp")
    assert basin_stats(temp, basin, product, DAY, Units(temperature="C")).values == {"avg": 0.0}
    assert basin_stats(temp, basin, product, DAY, Units(temperature="F")).values == {"avg": 32.0}
    assert basin_stats(temp, basin, product, DAY, Units(temperature="K")).values == {"avg": 273.15}


def test_elevation_bands_add_up_to_the_total(tmp_path, grid, square_basin):
    # DEM: west half at 1000 m, east half at 2000 m
    dem = make_grid(1000.0, size=240, west=-106.0 - 60 * RESOLUTION, north=40.0 + 60 * RESOLUTION, name="dem")
    dem.values[:, 120:] = 2000.0
    dem_path = tmp_path / "dem.tif"
    dem.rio.to_raster(dem_path)

    basin = Basin("b", [square_basin], elevation_bands=ElevationBands(dem=dem_path, step=500, units="m"))
    stats = basin_stats(grid, basin, get_product("swe"), DAY, Units())
    sums = stats.bands["sum"]
    assert set(sums) == {"1000-1500", "1500-2000"}
    assert sums["1000-1500"] == pytest.approx(sums["1500-2000"], rel=0.05)  # half the basin each
    assert sum(sums.values()) == pytest.approx(stats.values["sum"], rel=1e-3)
    # each band's average is the plain SWE, since SWE is uniform
    assert all(v == pytest.approx(0.5 / M_PER_IN, abs=0.01) for v in stats.bands["avg"].values() if v)


def test_units_validation():
    with pytest.raises(ValueError):
        Units("furlongs")
    with pytest.raises(ValueError):
        Units(temperature="R")
