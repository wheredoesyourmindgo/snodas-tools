from datetime import date
import gzip
import importlib
import io
import tarfile

import pytest
import requests

from snodas_tools.filenames import day_dir

# the package also exports a download() function, so import the module explicitly
dl = importlib.import_module("snodas_tools.download")


def test_build_url():
    assert dl.build_url(date(2024, 3, 9)) == "https://noaadata.apps.nsidc.org/NOAA/G02158/masked/2024/03_Mar/SNODAS_20240309.tar"
    assert dl.build_url(date(2024, 3, 9), masked=False).endswith("/unmasked/2024/03_Mar/SNODAS_unmasked_20240309.tar")
    with pytest.raises(ValueError):
        dl.build_url(date(2003, 9, 29))
    with pytest.raises(ValueError):
        dl.build_url(date(2009, 1, 1), masked=False)


def _fake_tar(target):
    """Write a SNODAS-like .tar containing gzipped .dat and .txt members."""
    with tarfile.open(target, "w") as tar:
        for name, payload in [
            ("us_ssmv11034tS__T0001TTNATS2025040105HP001.dat.gz", b"\x00\x01" * 8),
            ("us_ssmv11034tS__T0001TTNATS2025040105HP001.txt.gz", b"metadata"),
        ]:
            data = gzip.compress(payload)
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def test_download_day_unpacks(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "_fetch", lambda url, target, timeout: _fake_tar(target))
    result = dl.download_day(date(2025, 4, 1), tmp_path)
    assert result.status == "downloaded"
    folder = day_dir(tmp_path, date(2025, 4, 1))
    names = sorted(p.name for p in folder.iterdir())
    assert names == ["us_ssmv11034tS__T0001TTNATS2025040105HP001.dat", "us_ssmv11034tS__T0001TTNATS2025040105HP001.txt"]
    assert (folder / names[0]).read_bytes() == b"\x00\x01" * 8

    # already present -> skipped
    assert dl.download_day(date(2025, 4, 1), tmp_path).status == "exists"


def _http_error(status):
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(response=response)


def test_missing_day_is_reported_and_cleaned_up(tmp_path, monkeypatch):
    def fail(url, target, timeout):
        raise _http_error(404)

    monkeypatch.setattr(dl, "_fetch", fail)
    result = dl.download_day(date(2025, 4, 1), tmp_path)
    assert result.status == "missing"
    assert not day_dir(tmp_path, date(2025, 4, 1)).exists()


def test_server_error_is_an_error(tmp_path, monkeypatch):
    def fail(url, target, timeout):
        raise _http_error(503)

    monkeypatch.setattr(dl, "_fetch", fail)
    assert dl.download_day(date(2025, 4, 1), tmp_path).status == "error"


def test_retry_policy():
    assert dl._is_retryable(_http_error(503))
    assert not dl._is_retryable(_http_error(404))
    assert dl._is_retryable(requests.ConnectionError())
