import json
from datetime import date

import pandas as pd
import pytest

from snodas_tools import cli
from snodas_tools.config import ConfigError, parse_config
from snodas_tools.peaks import annual_peaks, basin_peaks, save_peaks


def _season(start: str, end: str, peak_day: str, peak: float, melt_days: int = 60) -> pd.Series:
    """Rises linearly from 0 at `start` to `peak` on `peak_day`, then melts to 0 over `melt_days`."""
    days = pd.date_range(start, end)
    up, top = pd.Timestamp(start), pd.Timestamp(peak_day)
    values = [
        peak * (d - up).days / max((top - up).days, 1)
        if d <= top
        else max(0.0, peak * (1 - (d - top).days / melt_days))
        for d in days
    ]
    return pd.Series(values, index=[d.date() for d in days])


def test_basin_peaks_final_years():
    series = pd.concat(
        [
            _season("2023-10-01", "2024-09-30", "2024-04-05", 1000.0),
            _season("2024-10-01", "2025-09-30", "2025-03-20", 600.0),
        ]
    )
    rows = basin_peaks({"sum": series, "avg": series / 100}, last_day=date(2025, 9, 30))
    assert [r["water_year"] for r in rows] == [2024, 2025]
    first = rows[0]
    assert first["peak_date"] == date(2024, 4, 5)
    assert first["peak_sum"] == 1000.0 and first["peak_avg"] == 10.0
    # 1% of 1000 is 10; the melt (1000 -> 0 over 60 days) first drops below that on day 60
    assert first["melt_out_date"] == date(2024, 6, 4)
    assert first["days"] == 366 and first["status"] == "final"


def test_melt_out_percent():
    series = _season("2023-10-01", "2024-09-30", "2024-04-05", 1000.0)
    rows = basin_peaks({"sum": series}, date(2024, 9, 30), melt_out_percent=50)
    assert rows[0]["melt_out_date"] == date(2024, 5, 6)  # first day below 500


def test_status():
    # the latest season stays open, even after an early storm melted out
    series = _season("2025-10-01", "2026-01-10", "2025-11-10", 300.0, melt_days=20)
    (row,) = basin_peaks({"sum": series}, last_day=date(2026, 1, 10))
    assert row["melt_out_date"] == date(2025, 11, 30) and row["status"] == "in progress"
    # data that starts on the peak day: the real peak may be earlier
    late_start = _season("2024-10-01", "2025-09-30", "2025-04-01", 900.0).loc[date(2025, 4, 1) :]
    assert basin_peaks({"sum": late_start}, date(2025, 9, 30))[0]["status"] == "incomplete"
    # data that stops mid-melt in an earlier year
    stops = _season("2023-10-01", "2024-05-01", "2024-04-05", 900.0)
    later = _season("2024-10-01", "2025-01-01", "2024-12-15", 100.0)
    rows = basin_peaks({"sum": pd.concat([stops, later])}, date(2025, 1, 1))
    assert rows[0]["melt_out_date"] is None and rows[0]["status"] == "incomplete"


def test_no_snow_year():
    series = pd.Series(0.0, index=[d.date() for d in pd.date_range("2023-10-01", "2024-09-30")])
    (row,) = basin_peaks({"sum": series}, date(2024, 9, 30))
    assert row["peak_date"] is None and row["peak_sum"] == 0.0 and row["status"] == "final"


def test_annual_peaks_columns_and_units():
    index = pd.Index(pd.date_range("2023-10-01", "2024-09-30").date, name="date")
    total = pd.DataFrame(
        {
            "a": _season("2023-10-01", "2024-09-30", "2024-04-05", 1000.0).to_numpy(),
            "b": _season("2023-10-01", "2024-09-30", "2024-03-01", 50.0).to_numpy(),
        },
        index=index,
    )
    df = annual_peaks({"sum": total, "avg": total / 100}, {"sum": "acre-ft", "avg": "in"})
    assert list(df.index) == [("a", 2024), ("b", 2024)]
    assert list(df.columns[:3]) == ["peak_date", "peak_avg_in", "peak_sum_acre_ft"]
    assert df.loc[("b", 2024), "peak_date"] == date(2024, 3, 1)
    with pytest.raises(ValueError, match="between 0 and 100"):
        annual_peaks({"sum": total}, {}, melt_out_percent=0)


@pytest.fixture
def output_dir(tmp_path):
    series = pd.concat(
        [
            _season("2023-10-01", "2024-09-30", "2024-04-05", 1000.0),
            _season("2024-10-01", "2025-02-01", "2025-01-20", 400.0),
        ]
    )
    pd.DataFrame({"date": series.index, "upper": series.to_numpy()}).to_csv(tmp_path / "swe_sum.csv", index=False)
    pd.DataFrame({"date": series.index, "upper": series.to_numpy() / 100}).to_csv(tmp_path / "swe_avg.csv", index=False)
    (tmp_path / "units.json").write_text(json.dumps({"swe_sum": "m^3", "swe_avg": "mm"}))
    return tmp_path


def test_save_peaks(output_dir):
    pytest.importorskip("xlsxwriter")
    _, written = save_peaks(output_dir, "swe", ("csv", "xlsx"))
    assert [p.name for p in written] == ["swe_peaks.csv", "swe_peaks.xlsx"]
    saved = pd.read_csv(output_dir / "swe_peaks.csv")
    assert list(saved.columns[:4]) == ["basin", "water_year", "peak_date", "peak_avg_mm"]
    assert list(saved["status"]) == ["final", "in progress"]
    with pytest.raises(FileNotFoundError, match="Run `snodas stats` for depth"):
        save_peaks(output_dir, "depth")


def test_cli_peaks(output_dir, capsys):
    assert cli.main(["peaks", "-o", str(output_dir), "--melt-out", "5"]) == 0
    out = capsys.readouterr().out
    assert "2024-04-05" in out and "in progress" in out and "swe_peaks.csv" in out
    assert cli.main(["peaks", "-o", str(output_dir), "--basin", "nope"]) == 1
    assert "No basin 'nope'" in capsys.readouterr().err
    assert cli.main(["peaks", "-o", str(output_dir), "--product", "temp"]) == 1


def test_peaks_config():
    cfg = parse_config({"peaks": {"products": ["swe", "depth"], "melt_out_percent": 5}})
    assert [p.key for p in cfg.peak_products] == ["swe", "depth"] and cfg.melt_out_percent == 5
    assert parse_config({"peaks": {"products": []}}).peak_products == []
    assert [p.key for p in parse_config({}).peak_products] == ["swe"]
    with pytest.raises(ConfigError, match="not in \\[stats\\] products"):
        parse_config({"stats": {"products": ["depth"]}, "peaks": {"products": ["swe"]}})
    with pytest.raises(ConfigError, match="temperature"):
        parse_config({"peaks": {"products": ["temp"]}})
    with pytest.raises(ConfigError, match="between 0 and 100"):
        parse_config({"peaks": {"melt_out_percent": 100}})


def test_run_writes_peaks(tmp_path, square_basin):
    """`snodas run` rebuilds the peaks table after saving statistics (days already converted: no network)."""
    from datetime import timedelta

    from conftest import make_grid

    from snodas_tools.convert import save_raster
    from snodas_tools.filenames import day_dir
    from snodas_tools.pipeline import run

    days = [date(2025, 3, 30) + timedelta(days=i) for i in range(5)]
    for day, value in zip(days, [0.2, 0.4, 0.5, 0.3, 0.1], strict=True):
        folder = day_dir(tmp_path / "data", day)
        folder.mkdir(parents=True)
        save_raster(make_grid(value), folder / f"us_ssmv11034tS__T0001TTNATS{day:%Y%m%d}05HP001.nc", "netcdf")
    cfg = parse_config(
        {
            "data": {"directory": "data"},
            "convert": {"products": ["swe"]},
            "stats": {"output_directory": "out"},
            "basin": [{"name": "a", "shapes": [str(square_basin)]}],
        },
        base=tmp_path,
    )
    summary = run(cfg, days, progress=False)
    assert tmp_path / "out" / "swe_peaks.csv" in summary.tables
    peaks = pd.read_csv(tmp_path / "out" / "swe_peaks.csv")
    assert peaks.loc[0, "peak_date"] == "2025-04-01" and peaks.loc[0, "status"] == "in progress"


def test_short_years_are_skipped():
    sliver = pd.Series([0.0], index=[date(2003, 9, 30)])  # WY2003 in the real tables: one day
    full = _season("2003-10-01", "2004-09-30", "2004-04-05", 1000.0)
    latest = _season("2004-10-01", "2004-10-05", "2004-10-03", 5.0)  # short, but the season in progress
    rows = basin_peaks({"sum": pd.concat([sliver, full, latest])}, last_day=date(2004, 10, 5))
    assert [r["water_year"] for r in rows] == [2004, 2005]
    assert rows[-1]["status"] == "in progress"
