"""
Annual peaks: for each basin and water year (Oct 1 - Sep 30), the day snowpack peaked, how much there was, and when it
melted out. Built from the daily `<product>_avg` / `<product>_sum` tables that `snodas stats` writes, and saved as
`<product>_peaks.csv` (plus Parquet / Excel copies if requested) next to them.

Columns:

- `basin`, `water_year`
- `peak_date` and the peak values, e.g. `peak_avg_in` and `peak_sum_acre_ft` (units are part of the column names)
- `melt_out_date`: the first day after the peak with less than `melt_out_percent` (default 1%) of the peak left
- `first_date`, `last_date`, `days`: the data the row is based on
- `status`: `final`; `in progress` (the latest water year, until it ends on Sep 30: a later storm can still beat the
  peak so far); or `incomplete` (the data starts on the peak day, so the real peak may be earlier, or it stops before
  the snow melted out)

Water years with fewer than 30 days of data, other than the latest, are left out.
"""

import json
import logging
import re
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from . import store
from .wateryear import MIN_DAYS, water_year

log = logging.getLogger(__name__)

DEFAULT_MELT_OUT_PERCENT = 1.0


def _unit_suffix(label: str) -> str:
    """'acre-ft' -> 'acre_ft', 'm^3' -> 'm3'."""
    return re.sub(r"[^0-9A-Za-z]+", "_", label.replace("^", "")).strip("_")


def _water_year_start(wy: int) -> date:
    return date(wy - 1, 10, 1)


def basin_peaks(
    stats: dict[str, pd.Series], last_day: date, melt_out_percent: float = DEFAULT_MELT_OUT_PERCENT
) -> list[dict]:
    """
    Peaks for one basin. `stats` maps statistic name ('sum', 'avg') to a daily series; the peak day is found from the
    first one (volume, when available) and every statistic's value on that day is reported. `last_day` is the last
    day in the tables, used to tell a season that is still going from one whose data simply stops.
    """
    names = list(stats)
    frame = pd.DataFrame(stats).dropna(how="all")
    frame.index = [pd.Timestamp(d).date() for d in frame.index]
    if frame.empty:
        return []
    key = frame[names[0]]
    rows = []
    latest = water_year(last_day)
    for wy, season in key.groupby([water_year(d) for d in key.index]):
        season = season.dropna().sort_index()
        if season.empty or (season.size < MIN_DAYS and wy != latest):
            continue  # a sliver of a year (e.g. WY2003, only Sep 30, 2003) has no meaningful peak
        peak_day, peak = season.idxmax(), float(season.max())
        row = {"water_year": int(wy), "peak_date": peak_day if peak > 0 else None}
        for name in names:
            row[f"peak_{name}"] = float(frame.loc[peak_day, name]) if peak > 0 else 0.0
        after = season.loc[peak_day:]
        melted = after[after < peak * melt_out_percent / 100] if peak > 0 else after.iloc[0:0]
        row["melt_out_date"] = melted.index[0] if not melted.empty else None
        first, last = season.index[0], season.index[-1]
        row.update({"first_date": first, "last_date": last, "days": int(season.size)})
        if peak > 0 and peak_day == first and first > _water_year_start(wy):
            row["status"] = "incomplete"  # the snowpack may have peaked before the data starts
        elif last >= date(wy, 9, 30):
            row["status"] = "final"
        elif last == last_day:
            # the latest season stays open until it ends: an early storm can melt out and be outdone later
            row["status"] = "in progress"
        elif row["melt_out_date"] is not None:
            row["status"] = "final"
        else:
            row["status"] = "incomplete"  # the data stops before the snow melted out
        rows.append(row)
    return rows


def annual_peaks(
    tables: dict[str, pd.DataFrame], units: dict[str, str], melt_out_percent: float = DEFAULT_MELT_OUT_PERCENT
) -> pd.DataFrame:
    """
    Peaks for every basin. `tables` maps statistic name ('sum' and/or 'avg') to a daily table (dates x basins, as
    saved by `snodas stats`); `units` maps statistic name to its units label.
    """
    if not 0 < melt_out_percent < 100:
        raise ValueError("The melt-out percentage must be between 0 and 100.")
    order = [s for s in ("sum", "avg") if s in tables]
    if not order:
        raise ValueError("No statistics tables to find peaks in.")
    basins = sorted(set().union(*(tables[s].columns for s in order)))
    last_day = max(pd.Timestamp(tables[s].index.max()).date() for s in order)
    rows = []
    for basin in basins:
        stats = {s: tables[s][basin] for s in order if basin in tables[s].columns}
        rows += [{"basin": basin, **row} for row in basin_peaks(stats, last_day, melt_out_percent)]
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    renames = {f"peak_{s}": f"peak_{s}_{_unit_suffix(units[s])}" for s in order if units.get(s)}
    columns = ["basin", "water_year", "peak_date", *[f"peak_{s}" for s in ("avg", "sum") if s in order]]
    columns += ["melt_out_date", "first_date", "last_date", "days", "status"]
    return df[columns].rename(columns=renames).set_index(["basin", "water_year"]).sort_index()


def save_peaks(
    output_dir: Path,
    product: str = "swe",
    formats: tuple[str, ...] = ("csv",),
    melt_out_percent: float = DEFAULT_MELT_OUT_PERCENT,
) -> tuple[pd.DataFrame, list[Path]]:
    """
    Compute peaks from the `<product>_sum` / `<product>_avg` tables in `output_dir` and save `<product>_peaks`.
    Returns the table and the files written.
    """
    output_dir = Path(output_dir)
    tables = {}
    for stat in ("sum", "avg"):
        try:
            tables[stat] = store.load(output_dir, product, stat)
        except FileNotFoundError:
            continue
    if not tables:
        raise FileNotFoundError(
            f"No {product}_sum.csv or {product}_avg.csv in {output_dir}. Run `snodas stats` for {product} first."
        )
    units_path = output_dir / "units.json"
    all_units = json.loads(units_path.read_text()) if units_path.exists() else {}
    units = {stat: all_units.get(f"{product}_{stat}", "") for stat in tables}
    df = annual_peaks(tables, units, melt_out_percent)
    if df.empty:
        return df, []
    return df, store.write_table(df, output_dir / f"{product}_peaks.csv", formats)


def format_peaks(df: pd.DataFrame) -> str:
    """The peaks table as aligned text."""
    if df.empty:
        return "(no peaks)"
    text = df.copy()
    for column in text.columns:
        if column.startswith("peak_") and column != "peak_date":
            text[column] = [
                f"{v:,.0f}" if abs(v) >= 100 else f"{v:.2f}" if np.isfinite(v) else "" for v in text[column]
            ]
    return text.drop(columns=["first_date", "last_date"]).fillna("").to_string()
