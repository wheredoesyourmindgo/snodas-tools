"""
Saving basin statistics as tables.

Each product and statistic gets its own table, updated in place each run:

- `<product>_<stat>.csv`: one row per date, one column per basin
- `<product>_<stat>_elevation.csv`: one row per (date, basin), one column per elevation band

A `units.json` file next to the tables records each table's units. CSV is always written (it is the store that
later runs read back); Parquet and Excel copies are optional.
"""

from collections import defaultdict
import json
import logging
from pathlib import Path
import re

import pandas as pd

from .stats import BasinStats

log = logging.getLogger(__name__)

EXPORT_FORMATS = ("csv", "parquet", "xlsx")


def _band_lower_edge(label) -> float:
    """Lower edge of a band label such as '5000-6000' or '-500-0' (below sea level)."""
    match = re.match(r"^(-?[\d.]+)-", str(label))
    return float(match.group(1)) if match else float("inf")


def _read(path: Path, index: list[str]) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, parse_dates=["date"])
    df["date"] = df["date"].dt.date
    return df.set_index(index)


def _write(df: pd.DataFrame, csv_path: Path, formats: tuple[str, ...]) -> list[Path]:
    """Write a table as CSV (always) plus any other requested formats. Returns the files written."""
    written = []
    tmp = csv_path.with_name(csv_path.name + ".part")
    df.to_csv(tmp)
    tmp.replace(csv_path)
    written.append(csv_path)
    flat = df.reset_index()
    flat["date"] = pd.to_datetime(flat["date"])
    if "parquet" in formats:
        path = csv_path.with_suffix(".parquet")
        flat.to_parquet(path, index=False)
        written.append(path)
    if "xlsx" in formats:
        path = csv_path.with_suffix(".xlsx")
        flat.to_excel(path, index=False, engine="xlsxwriter")
        written.append(path)
    return written


def save(
    results: list[BasinStats],
    output_dir: Path,
    units: dict[str, dict[str, str]],
    formats: tuple[str, ...] = ("csv",),
) -> list[Path]:
    """
    Merge new results into the tables in `output_dir`. New values replace existing ones for the same date and basin.

    `units` maps product -> statistic -> units label, and is recorded in `units.json`.
    Returns the files written.
    """
    unknown = set(formats) - set(EXPORT_FORMATS)
    if unknown:
        raise ValueError(f"Unknown export format(s): {', '.join(sorted(unknown))}. Choose from {', '.join(EXPORT_FORMATS)}")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    totals: dict[str, list[dict]] = defaultdict(list)
    bands: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        for stat, value in r.values.items():
            totals[f"{r.product}_{stat}"].append({"date": r.day, "basin": r.basin, "value": value})
        for stat, by_band in (r.bands or {}).items():
            bands[f"{r.product}_{stat}_elevation"].append({"date": r.day, "basin": r.basin, **by_band})

    written: list[Path] = []
    for table, rows in totals.items():
        new = pd.DataFrame(rows).pivot_table(index="date", columns="basin", values="value", aggfunc="last")
        new.columns.name = None
        path = output_dir / f"{table}.csv"
        merged = new.combine_first(_read(path, ["date"])).sort_index()
        written += _write(merged, path, formats)

    for table, rows in bands.items():
        new = pd.DataFrame(rows).set_index(["date", "basin"])
        new = new[~new.index.duplicated(keep="last")]
        path = output_dir / f"{table}.csv"
        merged = new.combine_first(_read(path, ["date", "basin"])).sort_index()
        # keep band columns in elevation order
        merged = merged[sorted(merged.columns, key=_band_lower_edge)]
        written += _write(merged, path, formats)

    units_path = output_dir / "units.json"
    existing = json.loads(units_path.read_text()) if units_path.exists() else {}
    for product, stats in units.items():
        for stat, label in stats.items():
            existing[f"{product}_{stat}"] = label
            if any(t == f"{product}_{stat}_elevation" for t in bands):
                existing[f"{product}_{stat}_elevation"] = label
    units_path.write_text(json.dumps(dict(sorted(existing.items())), indent=2) + "\n")
    written.append(units_path)
    return written


def load(output_dir: Path, product: str, stat: str = "sum", elevation: bool = False) -> pd.DataFrame:
    """Read a saved table back (dates as the index)."""
    suffix = "_elevation" if elevation else ""
    path = Path(output_dir) / f"{product}_{stat}{suffix}.csv"
    if not path.exists():
        raise FileNotFoundError(f"No table at {path}")
    return _read(path, ["date", "basin"] if elevation else ["date"])
