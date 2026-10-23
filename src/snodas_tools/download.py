"""
Downloading SNODAS archives from NSIDC (https://noaadata.apps.nsidc.org/NOAA/G02158/).

Each day is a .tar of gzipped files. They are downloaded, unpacked and gunzipped into the day's folder
(see `filenames.day_dir`), leaving `.dat` (data) and `.txt` (metadata) files.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
import gzip
import logging
from pathlib import Path
import shutil
import tarfile

import requests
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential
from tqdm import tqdm

from .dates import MASKED_START, UNMASKED_START
from .filenames import day_dir

log = logging.getLogger(__name__)

BASE_URL = "https://noaadata.apps.nsidc.org/NOAA/G02158"


@dataclass(frozen=True)
class DownloadResult:
    """Outcome of downloading one day."""

    day: date
    status: str  # "downloaded", "exists", "missing" (not published by NSIDC), or "error"
    detail: str = ""


def build_url(day: date, masked: bool = True) -> str:
    """URL of the SNODAS archive for a day."""
    if masked:
        if day < MASKED_START:
            raise ValueError(f"Masked SNODAS data starts {MASKED_START}; {day} is too early.")
        name = f"SNODAS_{day:%Y%m%d}.tar"
        folder = "masked"
    else:
        if day < UNMASKED_START:
            raise ValueError(f"Unmasked SNODAS data starts {UNMASKED_START}; {day} is too early.")
        name = f"SNODAS_unmasked_{day:%Y%m%d}.tar"
        folder = "unmasked"
    return f"{BASE_URL}/{folder}/{day:%Y}/{day:%m_%b}/{name}"


def _is_retryable(exc: BaseException) -> bool:
    """Retry network problems and server errors, but not 404s (the day doesn't exist)."""
    if isinstance(exc, requests.HTTPError):
        return exc.response is not None and exc.response.status_code >= 500
    return isinstance(exc, requests.RequestException)


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=20),
    retry=retry_if_exception(_is_retryable),
    reraise=True,
)
def _fetch(url: str, target: Path, timeout: int) -> None:
    """Stream a URL to a file, writing to a temporary name first so partial downloads are never left behind."""
    partial = target.with_name(target.name + ".part")
    with requests.get(url, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        with open(partial, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
    partial.replace(target)


def _unpack(archive: Path) -> None:
    """Extract a SNODAS .tar into its folder, gunzip its members, and remove the archives."""
    folder = archive.parent
    with tarfile.open(archive) as tar:
        tar.extractall(path=folder, filter="data")
    archive.unlink()
    for gz_path in folder.glob("*.gz"):
        with gzip.open(gz_path, "rb") as src, open(gz_path.with_suffix(""), "wb") as dst:
            shutil.copyfileobj(src, dst)
        gz_path.unlink()


def download_day(
    day: date,
    data_dir: Path,
    masked: bool = True,
    overwrite: bool = False,
    timeout: int = 120,
) -> DownloadResult:
    """
    Download and unpack one day of SNODAS data into `data_dir`.

    Days that already have `.dat` files are skipped unless `overwrite` is set.
    """
    folder = day_dir(data_dir, day, masked)
    if not overwrite and folder.exists() and any(folder.glob("*.dat")):
        return DownloadResult(day, "exists")

    url = build_url(day, masked)
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / url.rsplit("/", 1)[-1]
    try:
        _fetch(url, archive, timeout)
        _unpack(archive)
    except requests.HTTPError as exc:
        _remove_if_empty(folder)
        if exc.response is not None and exc.response.status_code == 404:
            return DownloadResult(day, "missing", url)
        return DownloadResult(day, "error", f"{url}: {exc}")
    except (requests.RequestException, tarfile.TarError, OSError) as exc:
        _remove_if_empty(folder)
        return DownloadResult(day, "error", f"{url}: {exc}")
    return DownloadResult(day, "downloaded")


def _remove_if_empty(folder: Path) -> None:
    """Remove a day folder (and its empty parents) if nothing was saved in it."""
    for path in (folder, folder.parent):
        try:
            path.rmdir()
        except OSError:
            break


def download(
    days: list[date],
    data_dir: Path,
    masked: bool = True,
    overwrite: bool = False,
    workers: int = 4,
    progress: bool = True,
) -> list[DownloadResult]:
    """
    Download several days in parallel. Returns one result per day, sorted by date.

    NSIDC is a free public service, so keep `workers` modest.
    """
    results: list[DownloadResult] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(download_day, d, Path(data_dir), masked, overwrite) for d in days]
        for future in tqdm(as_completed(futures), total=len(futures), desc="Downloading", unit="day", disable=None if progress else True):
            result = future.result()
            if result.status == "missing":
                log.warning("%s: not available from NSIDC (%s)", result.day, result.detail)
            elif result.status == "error":
                log.error("%s: download failed: %s", result.day, result.detail)
            results.append(result)
    return sorted(results, key=lambda r: r.day)
