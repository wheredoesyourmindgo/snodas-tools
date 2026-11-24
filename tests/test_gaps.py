import importlib
from datetime import date, timedelta

import pytest
import requests

from snodas_tools import cli, gaps
from snodas_tools.download import DownloadResult
from snodas_tools.filenames import day_dir

RAW = "us_ssmv11034tS__T0001TTNATS{:%Y%m%d}05HP001.dat"
# the package also exports a download() function, so import the module explicitly
dl = importlib.import_module("snodas_tools.download")

CONVERTED = "us_ssmv11034tS__T0001TTNATS{:%Y%m%d}05HP001_basin.nc"


def _put(data_dir, day, template):
    folder = day_dir(data_dir, day)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / template.format(day)).write_bytes(b"")


class _Response:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


class _Session:
    def __init__(self, pages):
        self.pages, self.urls = pages, []

    def get(self, url, timeout):
        self.urls.append(url)
        page = self.pages.get(url)
        if isinstance(page, Exception):
            raise page
        return _Response(404) if page is None else _Response(200, page)


def test_published_days_reads_the_listing():
    url = "https://noaadata.apps.nsidc.org/NOAA/G02158/masked/2004/02_Feb/"
    listing = '<a href="SNODAS_20040224.tar">SNODAS_20040224.tar</a> <a href="SNODAS_20040226.tar">x</a>'
    session = _Session({url: listing})
    assert gaps.published_days(2004, 2, session=session) == {date(2004, 2, 24), date(2004, 2, 26)}
    assert session.urls == [url]
    assert gaps.published_days(2099, 1, session=session) == set()  # 404: nothing published that month
    failing = _Session({url: requests.ConnectionError("down")})
    assert gaps.published_days(2004, 2, session=failing) is None


def test_local_status_and_first_day(tmp_path):
    assert gaps.first_local_day(tmp_path) is None
    _put(tmp_path, date(2025, 1, 2), RAW)
    _put(tmp_path, date(2025, 1, 3), RAW)
    _put(tmp_path, date(2025, 1, 3), CONVERTED)
    day_dir(tmp_path, date(2025, 1, 4)).mkdir(parents=True)  # an empty folder counts as missing
    assert gaps.local_status(tmp_path, date(2025, 1, 2)) == "raw"
    assert gaps.local_status(tmp_path, date(2025, 1, 3)) == "converted"
    assert gaps.local_status(tmp_path, date(2025, 1, 4)) == "missing"
    assert gaps.local_status(tmp_path, date(2025, 1, 5)) == "missing"
    assert gaps.first_local_day(tmp_path) == date(2025, 1, 2)


def test_find_gaps_sorts_days(tmp_path, monkeypatch):
    days = [date(2025, 1, 30) + timedelta(days=i) for i in range(6)]  # Jan 30 - Feb 4
    _put(tmp_path, days[0], CONVERTED)
    _put(tmp_path, days[1], RAW)
    published = {(2025, 1): set(), (2025, 2): {date(2025, 2, 1), date(2025, 2, 3)}}
    asked = []

    def fake_published(year, month, masked=True, session=None):
        asked.append((year, month))
        return published[(year, month)]

    monkeypatch.setattr(gaps, "published_days", fake_published)
    report = gaps.find_gaps(tmp_path, days)
    assert report.converted == [date(2025, 1, 30)]
    assert report.not_converted == [date(2025, 1, 31)]
    assert report.not_downloaded == [date(2025, 2, 1), date(2025, 2, 3)]
    assert report.not_published == [date(2025, 2, 2), date(2025, 2, 4)]
    assert asked == [(2025, 2)]  # January has no missing days, so its listing isn't requested

    monkeypatch.setattr(gaps, "published_days", lambda *a, **k: None)
    assert len(gaps.find_gaps(tmp_path, days).unchecked) == 4
    offline = gaps.find_gaps(tmp_path, days, check_nsidc=False)
    assert offline.unchecked == days[2:] and not offline.not_published


def test_ranges_and_report():
    days = [date(2025, 1, 1), date(2025, 1, 3), date(2025, 1, 4), date(2025, 1, 5)]
    assert gaps.date_ranges(days) == [(date(2025, 1, 1), date(2025, 1, 1)), (date(2025, 1, 3), date(2025, 1, 5))]
    assert gaps.format_ranges(days) == "2025-01-01, 2025-01-03 to 2025-01-05 (3 days)"
    assert gaps.format_ranges(days, limit=1) == "2025-01-01, ... and 1 more range (--all lists them)"
    report = gaps.GapReport(days=days, converted=days[:1], not_published=[date(2004, 2, 25)])
    text = gaps.format_report(report)
    assert "1 not published by NSIDC: 2004-02-25" in text and "nothing to fetch or convert" in text


def test_cli_gaps(tmp_path, monkeypatch, capsys):
    assert cli.main(["gaps", "-d", str(tmp_path), "--offline"]) == 1
    assert "No data in" in capsys.readouterr().err

    _put(tmp_path, date(2025, 3, 1), CONVERTED)
    assert cli.main(["gaps", "-d", str(tmp_path), "--offline", "--start", "2025-03-01", "--end", "2025-03-04"]) == 0
    out = capsys.readouterr().out
    assert "2025-03-01 to 2025-03-04: 4 days" in out
    assert "3 missing here; NSIDC not checked: 2025-03-02 to 2025-03-04 (3 days)" in out

    # with no dates: from the first local day through today
    assert cli.main(["gaps", "-d", str(tmp_path), "--offline"]) == 0
    assert f"2025-03-01 to {date.today()}" in capsys.readouterr().out

    assert cli.main(["gaps", "-d", str(tmp_path), "--offline", "--download", "--recent", "2"]) == 1
    assert "drop --offline" in capsys.readouterr().err


def test_cli_gaps_download(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gaps, "published_days", lambda year, month, **k: {date(2025, 3, 2), date(2025, 3, 3)})
    fetched = []

    def fake_download(days, data_dir, masked, workers, progress):
        fetched.extend(days)
        return [DownloadResult(d, "downloaded") for d in days]

    monkeypatch.setattr(dl, "download", fake_download)
    args = ["-q", "gaps", "-d", str(tmp_path), "--start", "2025-03-01", "--end", "2025-03-03", "--download"]
    assert cli.main(args) == 0
    assert fetched == [date(2025, 3, 2), date(2025, 3, 3)]
    out = capsys.readouterr().out
    assert "1 not published by NSIDC: 2025-03-01" in out
    assert "Downloaded 2 day(s)" in out and "snodas convert --start 2025-03-02 --end 2025-03-03" in out


@pytest.mark.parametrize("masked, start", [(True, "2003-09-30"), (False, "2009-12-09")])
def test_cli_gaps_starts_at_the_first_snodas_day(tmp_path, capsys, masked, start):
    args = ["gaps", "-d", str(tmp_path), "--offline", "--start", "2003-01-01", "--end", "2010-01-01"]
    assert cli.main(args + ([] if masked else ["--unmasked"])) == 0
    assert capsys.readouterr().out.startswith(f"{start} to 2010-01-01")
