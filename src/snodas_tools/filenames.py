"""
Parsing of SNODAS file names and the on-disk folder layout used by snodas-tools.

Downloaded data is stored as `<data_dir>/YYYY/MM/DD/<masked|unmasked>/<snodas files>`.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
import re

from .products import Product, product_for_file

# e.g. us_ssmv11034tS__T0001TTNATS2024010105HP001.dat
SNODAS_FILENAME_RE = re.compile(
    r"(?P<region>[a-z]{2})_"  # region ('us' masked CONUS, 'zz' unmasked)
    r"(?P<model>[a-z]{3})"  # model ('ssm')
    r"(?P<type_code>[a-z]\d)"  # 'v0' driving data, 'v1' model output
    r"(?P<product_code>\d{4})"  # product code, e.g. 1034
    r"(?P<downscale>S?)"  # 'S' when downscaled to SNODAS resolution
    r"(?P<vertical_code>[a-zA-Z]{2,3}\d{2}|[a-zA-Z]{2}__)?"  # vertical integration, e.g. 'tS__', 'lL00'
    r"(?P<time_code>[TA])(?P<time_integration>\d{4})"  # e.g. 'T0024'
    r"(?P<operation>[a-zA-Z]{4})"  # always 'TTNA'
    r"TS(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})(?P<hour>\d{2})"  # time step
    r"(?P<interval>[HD])"  # 'H' hourly or 'D' daily
    r"(?P<offset>P\d{3})"  # offset, e.g. 'P001'
    r"(?P<suffix>.*)$"  # extension and any suffix added by snodas-tools (e.g. '_myclip.nc')
)


@dataclass(frozen=True)
class SnodasFile:
    """Metadata parsed from a SNODAS file name."""

    path: Path
    stem: str  # the SNODAS part of the name, without any extension or suffix
    product_code: int
    vertical_code: str | None
    timestamp_utc: datetime
    suffix: str

    @property
    def date(self) -> date:
        """The date the file represents."""
        return self.timestamp_utc.date()

    @property
    def product(self) -> Product | None:
        """The known product for this file, if any."""
        return product_for_file(self.product_code, self.vertical_code)


def parse_snodas_filename(path: str | Path) -> SnodasFile:
    """Parse a SNODAS file name (raw `.dat`/`.txt`, or a converted `.nc`/`.tif`, optionally with a clip suffix)."""
    path = Path(path)
    match = SNODAS_FILENAME_RE.match(path.name)
    if not match:
        raise ValueError(f"Not a SNODAS file name: {path.name}")
    m = match.groupdict()
    timestamp = datetime(int(m["year"]), int(m["month"]), int(m["day"])) + timedelta(hours=int(m["hour"]))
    stem = path.name[: len(path.name) - len(m["suffix"])]
    return SnodasFile(
        path=path,
        stem=stem,
        product_code=int(m["product_code"]),
        vertical_code=m["vertical_code"],
        timestamp_utc=timestamp,
        suffix=m["suffix"],
    )


def day_dir(data_dir: Path, day: date, masked: bool = True) -> Path:
    """Folder holding the files for one day."""
    return Path(data_dir) / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}" / ("masked" if masked else "unmasked")


def date_from_path(path: Path) -> date:
    """
    Find the date of a SNODAS file from its folder (YYYY/MM/DD) or, failing that, its file name.
    """
    parts = Path(path).parts
    for i in range(len(parts) - 2):
        year, month, day = parts[i : i + 3]
        if len(year) == 4 and year.isdigit() and len(month) == 2 and month.isdigit() and len(day) == 2 and day.isdigit():
            return date(int(year), int(month), int(day))
    return parse_snodas_filename(path).date


def find_files(data_dir: Path, days: list[date], masked: bool, pattern: str) -> list[Path]:
    """Find files matching a glob pattern in each day's folder."""
    found: list[Path] = []
    for day in days:
        folder = day_dir(data_dir, day, masked)
        if folder.exists():
            found.extend(sorted(folder.glob(pattern)))
    return found
