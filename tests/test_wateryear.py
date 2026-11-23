import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from snodas_tools import cli, wateryear


def _seasons(first_wy=2020, last_day="2026-03-15", scale=None):
    """A daily series that rises from 0 on Oct 1 to a peak on Apr 1 and melts out by Jul 1, scaled per water year."""
    days = pd.date_range(f"{first_wy - 1}-10-01", last_day)
    values = []
    for d in days:
        wy = wateryear.water_year(d.date())
        t = wateryear.water_year_slot(d.date())
        peak = (scale or {}).get(wy, 100.0 * (wy - first_wy + 1))
        values.append(peak * min(t / 183, max(0.0, (274 - t) / 91)))
    return pd.Series(values, index=days)


def test_water_year_and_slots():
    assert wateryear.water_year(date(2025, 10, 1)) == 2026
    assert wateryear.water_year(date(2026, 9, 30)) == 2026
    assert wateryear.water_year_slot(date(2025, 10, 1)) == 0
    assert wateryear.water_year_slot(date(2026, 9, 30)) == 365
    # the same calendar date lines up in leap and non-leap years
    assert wateryear.water_year_slot(date(2023, 3, 1)) == wateryear.water_year_slot(date(2024, 3, 1))
    assert wateryear.slot_date(wateryear.water_year_slot(date(2024, 2, 29)), 2024) == date(2024, 2, 29)
    assert wateryear.slot_date(0, 2026) == date(2025, 10, 1)


def test_by_water_year_fills_feb29_in_non_leap_years():
    series = pd.Series(
        [1.0, 3.0, 5.0], index=pd.to_datetime(["2023-02-28", "2023-03-01", "2024-02-29"])
    )  # WY2023 (no Feb 29) and WY2024
    table = wateryear.by_water_year(series)
    feb29 = wateryear.water_year_slot(date(2024, 2, 29))
    assert list(table.columns) == [2023, 2024]
    assert len(table) == wateryear.DAYS
    assert table.loc[feb29, 2023] == 2.0
    assert table.loc[feb29, 2024] == 5.0


def test_envelope_and_monthly_means():
    table = wateryear.by_water_year(_seasons(first_wy=2020, last_day="2023-09-30"))
    env = wateryear.envelope(table, exclude=[2023])
    apr1 = wateryear.water_year_slot(date(2023, 4, 1))
    assert env.loc[apr1, "min"] == pytest.approx(100.0, rel=0.01)
    assert env.loc[apr1, "max"] == pytest.approx(300.0, rel=0.01)
    assert env.loc[apr1, "years"] == 3
    monthly = wateryear.monthly_means(table)
    assert list(monthly.index) == wateryear.MONTHS
    assert monthly.loc["Aug"].eq(0).all()
    assert monthly.loc["Apr", 2023] > monthly.loc["Apr", 2020]


def test_summarize():
    table = wateryear.by_water_year(_seasons(first_wy=2020, last_day="2026-03-15", scale={2026: 900.0}))
    line = wateryear.summarize(table, 2026)
    assert line.startswith("WY2026 on 2026-03-15:")
    assert "of median" in line and "1st highest of 7 years" in line
    # a finished year ends at zero like every other year: no rank, but its peak
    line = wateryear.summarize(table, 2021)
    assert "highest" not in line and "peak 200 on 2021-04-01" in line


def test_render_views_plain():
    table = wateryear.by_water_year(_seasons())
    text = wateryear.render_water_years(table, [2026, 2022], width=60, height=8, units="acre-ft", color=False)
    assert "● WY2026" in text and "◆ WY2022" in text and "range (5 other years, WY2020-WY2025)" in text
    assert "Oct" in text and "units: acre-ft" in text
    assert text.splitlines()[-2].startswith("WY2026 on 2026-03-15")

    text = wateryear.render_heatmap(table, width=60, color=False)
    assert "WY2020 │" in text and "WY2026 │" in text and "@" in text

    text = wateryear.render_months(table, [2026], width=80, color=False)
    lines = text.splitlines()
    assert lines[0].startswith("Oct │") and any(line.startswith("Apr │") for line in lines)
    assert "median" in text and "● WY2026" in text


def test_check_years():
    table = wateryear.by_water_year(_seasons())
    assert wateryear.default_years(table) == [2026]
    with pytest.raises(ValueError, match="No data for water year"):
        wateryear.check_years(table, [1999])
    with pytest.raises(ValueError, match="at most"):
        wateryear.check_years(table, [2020, 2021, 2022, 2023, 2024])


@pytest.fixture
def table_file(tmp_path):
    path = tmp_path / "swe_sum.csv"
    series = _seasons()
    pd.DataFrame({"date": series.index.date, "upper": np.round(series.to_numpy(), 2)}).to_csv(path, index=False)
    (tmp_path / "units.json").write_text(json.dumps({"swe_sum": "acre-ft"}))
    return path


@pytest.mark.parametrize("view", ["water-years", "heatmap", "months"])
def test_cli_chart_views(table_file, view, capsys):
    assert cli.main(["chart", str(table_file), "--view", view, "--width", "70", "--no-color"]) == 0
    out = capsys.readouterr().out
    assert "swe_sum: upper" in out and "WY2026" in out


@pytest.mark.parametrize("view", ["series", "water-years", "heatmap", "months"])
def test_cli_chart_png(table_file, tmp_path, view):
    pytest.importorskip("matplotlib")
    png = tmp_path / f"{view}.png"
    assert cli.main(["chart", str(table_file), "--view", view, "--png", str(png)]) == 0
    assert png.stat().st_size > 1000


def test_cli_chart_year_errors(table_file, capsys):
    assert cli.main(["chart", str(table_file), "--view", "water-years", "--years", "1999"]) == 1
    assert "No data for water year" in capsys.readouterr().err
    assert cli.main(["chart", str(table_file), "--view", "heatmap", "--years", "2026"]) == 1
    assert "--years is for" in capsys.readouterr().err
