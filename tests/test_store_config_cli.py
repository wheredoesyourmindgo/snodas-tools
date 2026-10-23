from datetime import date
import json
from pathlib import Path

import numpy as np
import pytest

from snodas_tools import cli, store
from snodas_tools.config import ConfigError, load_config, parse_config
from snodas_tools.convert import save_raster
from snodas_tools.preview import render_chart, render_terminal
from snodas_tools.stats import BasinStats

from conftest import make_grid

EXAMPLE_CONFIG = Path(__file__).parents[1] / "examples" / "config.example.toml"


def _stats(day, basin, value, bands=None):
    return BasinStats(basin, "swe", day, {"avg": value / 100, "sum": value}, bands)


def test_store_merges_and_new_values_win(tmp_path):
    units = {"swe": {"avg": "in", "sum": "acre-ft"}}
    store.save([_stats(date(2025, 1, 1), "a", 10), _stats(date(2025, 1, 2), "a", 20)], tmp_path, units)
    store.save([_stats(date(2025, 1, 2), "a", 25), _stats(date(2025, 1, 2), "b", 5)], tmp_path, units)
    df = store.load(tmp_path, "swe", "sum")
    assert df.loc[date(2025, 1, 1), "a"] == 10
    assert df.loc[date(2025, 1, 2), "a"] == 25  # replaced
    assert df.loc[date(2025, 1, 2), "b"] == 5
    assert np.isnan(df.loc[date(2025, 1, 1), "b"])
    assert json.loads((tmp_path / "units.json").read_text())["swe_sum"] == "acre-ft"


def test_store_elevation_tables(tmp_path):
    bands = {"sum": {"1000-2000": 1.0, "-500-0": 2.0}, "avg": {"1000-2000": 3.0, "-500-0": 4.0}}
    written = store.save([_stats(date(2025, 1, 1), "a", 3, bands)], tmp_path, {"swe": {"avg": "in", "sum": "acre-ft"}}, ("csv", "parquet"))
    assert (tmp_path / "swe_sum_elevation.parquet") in written
    df = store.load(tmp_path, "swe", "sum", elevation=True)
    assert list(df.columns) == ["-500-0", "1000-2000"]


def test_store_rejects_unknown_format(tmp_path):
    with pytest.raises(ValueError):
        store.save([], tmp_path, {}, ("csv", "docx"))


def test_example_config_parses():
    cfg = load_config(EXAMPLE_CONFIG)
    assert cfg.basins[0].name == "colorado_headwaters"
    assert cfg.basins[0].shapes[0].is_absolute()
    assert cfg.basins[0].elevation_bands.step == 1000
    assert cfg.clips[0].buffer_m == 2000
    assert [p.key for p in cfg.products] == ["swe", "depth", "melt", "temp"]


@pytest.mark.parametrize(
    "raw, message",
    [
        ({"stats": {"unitz": "metric"}}, "Unknown setting"),
        ({"convert": {"keep_full_extent": False}}, "needs at least one"),
        ({"basin": [{"shapes": ["x.geojson"]}]}, "'name' is required"),
        ({"basin": [{"name": "a", "shapes": ["x.geojson"], "source": "nope"}]}, "not a \\[\\[convert.clip\\]\\] name"),
        ({"convert": {"products": ["swe", "snowballs"]}}, "Unknown SNODAS product"),
        ({"stats": {"units": "furlongs"}}, "imperial"),
    ],
)
def test_config_errors(raw, message):
    with pytest.raises(ConfigError, match=message):
        parse_config(raw)


def test_zip_paths_are_resolved_before_the_bang(tmp_path):
    cfg = parse_config({"basin": [{"name": "a", "shapes": ["shapes.zip!inner/a.shp"]}]}, base=tmp_path)
    assert str(cfg.basins[0].shapes[0]) == f"{tmp_path}/shapes.zip!inner/a.shp"


def test_render_terminal_plain():
    da = make_grid()
    da.values[:60] = 1.0
    text = render_terminal(da, width=20, color=False)
    lines = text.splitlines()
    assert lines[0].startswith("Snow water equivalent")
    assert "@" in text and "m" in lines[-1]


def test_render_chart():
    import pandas as pd

    series = pd.Series([1, 5, 3, 8], index=pd.date_range("2025-01-01", periods=4))
    text = render_chart(series, width=40, height=4, title="t", units="acre-ft")
    assert "t" in text.splitlines()[0]
    assert "2025-01-01" in text and "2025-01-04" in text and "units: acre-ft" in text


def test_cli_info_and_products(tmp_path, capsys):
    da = make_grid()
    path = tmp_path / "grid.nc"
    save_raster(da, path, "netcdf")
    assert cli.main(["info", str(path)]) == 0
    out = capsys.readouterr().out
    assert "Snow water equivalent" in out and "0.5" in out
    assert cli.main(["products"]) == 0
    assert "swe" in capsys.readouterr().out


def test_cli_reports_errors(capsys):
    assert cli.main(["stats", "2025-01-01"]) == 1
    assert "No basins" in capsys.readouterr().err


def test_parallel_statistics_match_serial(tmp_path, square_basin):
    """Workers only compute; results are sorted before saving, so tables don't depend on finishing order."""
    from datetime import timedelta

    from snodas_tools.filenames import day_dir
    from snodas_tools.pipeline import compute_stats
    from snodas_tools.products import get_product
    from snodas_tools.stats import Basin, Units

    days = [date(2025, 4, 1) + timedelta(days=i) for i in range(4)]
    for i, day in enumerate(days):
        folder = day_dir(tmp_path / "data", day)
        folder.mkdir(parents=True)
        save_raster(make_grid(0.1 * (i + 1)), folder / f"us_ssmv11034tS__T0001TTNATS{day:%Y%m%d}05HP001.nc", "netcdf")
    basins = [Basin("a", [square_basin]), Basin("b", [square_basin], interpolate=False)]
    args = (days, tmp_path / "data", basins, [get_product("swe")], Units())
    serial = compute_stats(*args, progress=False, workers=1)
    parallel = compute_stats(*args, progress=False, workers=3)
    assert [(r.day, r.basin, r.values) for r in serial] == [(r.day, r.basin, r.values) for r in parallel]
    units = {"swe": {"avg": "in", "sum": "acre-ft"}}
    store.save(serial, tmp_path / "s", units)
    store.save(parallel, tmp_path / "p", units)
    assert (tmp_path / "s" / "swe_sum.csv").read_text() == (tmp_path / "p" / "swe_sum.csv").read_text()
