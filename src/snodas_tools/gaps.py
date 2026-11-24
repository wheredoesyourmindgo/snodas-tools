"""
Finding the days missing from the local data folder, and why: not downloaded yet, downloaded but not converted, or
never published by NSIDC (SNODAS has a few dozen missing days, mostly in its early years).

Whether NSIDC has a day is read from its monthly directory listings (one request per month with gaps), not by
requesting each archive.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import requests

from .convert import EXTENSIONS
from .download import BASE_URL
from .filenames import day_dir, parse_snodas_filename

log = logging.getLogger(__name__)

_ARCHIVE_RE = re.compile(r"SNODAS_(?:unmasked_)?(\d{8})\.tar")


@dataclass
class GapReport:
    """Each day of a range, sorted into what the local data folder has for it."""

    days: list[date]
    converted: list[date] = field(default_factory=list)
    not_converted: list[date] = field(default_factory=list)  # raw .dat files, but nothing converted
    not_downloaded: list[date] = field(default_factory=list)  # published by NSIDC, not here
    not_published: list[date] = field(default_factory=list)  # NSIDC doesn't have it
    unchecked: list[date] = field(default_factory=list)  # not here; NSIDC not asked (offline, or the request failed)


def local_status(data_dir: Path, day: date, masked: bool = True) -> str:
    """'converted', 'raw' (downloaded, not converted) or 'missing'."""
    folder = day_dir(data_dir, day, masked)
    if not folder.exists():
        return "missing"
    raw = False
    for path in folder.iterdir():
        try:
            info = parse_snodas_filename(path)
        except ValueError:
            continue
        if any(info.suffix.endswith(ext) for ext in EXTENSIONS.values()):
            return "converted"
        raw = raw or info.suffix == ".dat"
    return "raw" if raw else "missing"


def first_local_day(data_dir: Path, masked: bool = True) -> date | None:
    """The earliest day with a folder in the data directory."""
    kind = "masked" if masked else "unmasked"
    for folder in sorted(Path(data_dir).glob(f"[0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9]/{kind}")):
        year, month, day = folder.parts[-4:-1]
        try:
            return date(int(year), int(month), int(day))
        except ValueError:
            continue
    return None


def published_days(year: int, month: int, masked: bool = True, session=None, timeout: int = 60) -> set[date] | None:
    """
    The days NSIDC has archives for in a month, from its directory listing. A month that doesn't exist (404) has
    none; returns None if the listing couldn't be read.
    """
    first = date(year, month, 1)
    url = f"{BASE_URL}/{'masked' if masked else 'unmasked'}/{first:%Y}/{first:%m_%b}/"
    try:
        response = (session or requests).get(url, timeout=timeout)
        if response.status_code == 404:
            return set()
        response.raise_for_status()
    except requests.RequestException as exc:
        log.warning("Could not read %s: %s", url, exc)
        return None
    found = set()
    for stamp in _ARCHIVE_RE.findall(response.text):
        day = date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:]))
        if (day.year, day.month) == (year, month):
            found.add(day)
    return found


def find_gaps(data_dir: Path, days: list[date], masked: bool = True, check_nsidc: bool = True) -> GapReport:
    """Sort each day by what's on disk; for days that are missing, ask NSIDC whether they were ever published."""
    report = GapReport(days=list(days))
    missing = []
    for day in days:
        status = local_status(data_dir, day, masked)
        if status == "converted":
            report.converted.append(day)
        elif status == "raw":
            report.not_converted.append(day)
        else:
            missing.append(day)
    if not check_nsidc:
        report.unchecked = missing
        return report
    months = sorted({(d.year, d.month) for d in missing})
    with requests.Session() as session:
        listings = {m: published_days(*m, masked=masked, session=session) for m in months}
    for day in missing:
        published = listings[(day.year, day.month)]
        if published is None:
            report.unchecked.append(day)
        elif day in published:
            report.not_downloaded.append(day)
        else:
            report.not_published.append(day)
    return report


def date_ranges(days: list[date]) -> list[tuple[date, date]]:
    """Collapse sorted days into runs of consecutive days."""
    ranges: list[tuple[date, date]] = []
    for day in sorted(days):
        if ranges and day == ranges[-1][1] + timedelta(days=1):
            ranges[-1] = (ranges[-1][0], day)
        else:
            ranges.append((day, day))
    return ranges


def format_ranges(days: list[date], limit: int | None = 10) -> str:
    """'2024-01-03, 2024-02-10 to 2024-02-12 (3 days), ...', listing at most `limit` runs."""
    parts = [f"{a}" if a == b else f"{a} to {b} ({(b - a).days + 1} days)" for a, b in date_ranges(days)]
    if limit is not None and len(parts) > limit:
        hidden = len(parts) - limit
        parts = parts[:limit] + [f"... and {hidden} more range{'s' if hidden > 1 else ''} (--all lists them)"]
    return ", ".join(parts)


def format_report(report: GapReport, limit: int | None = 10) -> str:
    """A short summary of a GapReport."""
    if not report.days:
        return "No days to check."
    n = len(report.days)
    lines = [f"{report.days[0]} to {report.days[-1]}: {n} day{'s' if n != 1 else ''}"]
    groups = [
        (report.converted, "converted", False),
        (report.not_converted, "downloaded, not converted (run `snodas convert`)", True),
        (report.not_downloaded, "not downloaded (`snodas gaps --download` fetches them)", True),
        (report.not_published, "not published by NSIDC", True),
        (report.unchecked, "missing here; NSIDC not checked", True),
    ]
    if report.not_published and report.not_published[-1] >= date.today() - timedelta(days=3):
        groups[3] = (report.not_published, "not published by NSIDC (the latest days may still be on the way)", True)
    for days, label, listed in groups:
        if days:
            lines.append(f"  {len(days):>6} {label}" + (f": {format_ranges(days, limit)}" if listed else ""))
    if not (report.not_converted or report.not_downloaded or report.unchecked):
        lines.append("  nothing to fetch or convert")
    return "\n".join(lines)
