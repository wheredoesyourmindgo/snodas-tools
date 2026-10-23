from datetime import date, timedelta
from pathlib import Path

import pytest

from snodas_tools.dates import resolve_dates, today
from snodas_tools.filenames import date_from_path, day_dir, parse_snodas_filename
from snodas_tools.products import PRODUCTS, get_product


def test_parse_raw_and_converted_names():
    raw = parse_snodas_filename("us_ssmv11034tS__T0001TTNATS2025040105HP001.dat")
    assert raw.product_code == 1034
    assert raw.product.key == "swe"
    assert raw.date == date(2025, 4, 1)
    assert raw.timestamp_utc.hour == 5
    assert raw.suffix == ".dat"

    clipped = parse_snodas_filename("us_ssmv11034tS__T0001TTNATS2025040105HP001_my_basin.nc")
    assert clipped.stem == raw.stem
    assert clipped.suffix == "_my_basin.nc"


def test_precipitation_products_are_told_apart():
    liquid = parse_snodas_filename("us_ssmv01025SlL00T0024TTNATS2025040105DP001.dat")
    solid = parse_snodas_filename("us_ssmv01025SlL01T0024TTNATS2025040105DP001.dat")
    assert liquid.product.key == "precip_liquid"
    assert solid.product.key == "precip_solid"


def test_other_products():
    assert parse_snodas_filename("us_ssmv11038wS__A0024TTNATS2025040105DP001.dat").product.key == "temp"
    assert parse_snodas_filename("us_ssmv11044bS__T0024TTNATS2025040105DP000.dat").product.key == "melt"
    assert parse_snodas_filename("us_ssmv11050lL00T0024TTNATS2025040105DP000.dat").product.key == "sublimation"
    assert parse_snodas_filename("us_ssmv11039lL00T0024TTNATS2025040105DP000.dat").product.key == "sublimation_blowing"


def test_bad_name():
    with pytest.raises(ValueError):
        parse_snodas_filename("readme.txt")


def test_unknown_product_key():
    with pytest.raises(ValueError, match="Valid products"):
        get_product("snowballs")
    assert set(PRODUCTS) >= {"swe", "depth", "melt", "temp"}


def test_day_dir_and_date_from_path(tmp_path):
    folder = day_dir(tmp_path, date(2024, 1, 5))
    assert folder == tmp_path / "2024" / "01" / "05" / "masked"
    assert day_dir(tmp_path, date(2024, 1, 5), masked=False).name == "unmasked"
    assert date_from_path(folder / "anything.nc") == date(2024, 1, 5)
    assert date_from_path(Path("us_ssmv11034tS__T0001TTNATS2025040105HP001.nc")) == date(2025, 4, 1)


def test_resolve_single_and_range():
    assert resolve_dates("2024-03-31") == [date(2024, 3, 31)]
    days = resolve_dates(start="2024-02-27", end="2024-03-01")
    assert days == [date(2024, 2, 27), date(2024, 2, 28), date(2024, 2, 29), date(2024, 3, 1)]


def test_resolve_recent():
    days = resolve_dates(recent=3, timezone="America/Denver")
    end = today("America/Denver")
    assert days == [end - timedelta(days=2), end - timedelta(days=1), end]


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({}, "Choose dates"),
        ({"day": "2024-01-01", "recent": 2}, "only one"),
        ({"end": "2024-01-01"}, "needs --start"),
        ({"start": "2024-02-01", "end": "2024-01-01"}, "after end"),
        ({"day": "2999-01-01"}, "future"),
        ({"day": "not a date"}, "Not a valid date"),
        ({"recent": 0}, "at least 1"),
    ],
)
def test_resolve_errors(kwargs, message):
    with pytest.raises(ValueError, match=message):
        resolve_dates(**kwargs)
