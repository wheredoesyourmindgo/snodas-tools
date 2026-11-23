"""
Water-year views of a statistics table: each year laid over the others on an October-to-September axis, a year-by-day
heatmap, and monthly box plots. Each can be drawn in the terminal or (with the `plot` extra) with matplotlib.

A water year runs from October 1 to September 30 and is named for the year it ends in: WY2026 starts on 2025-10-01.
Days are placed on a 366-day axis so a calendar date lines up across years (Feb 29 has its own slot; in other years it
is the average of Feb 28 and Mar 1, so the median there doesn't come from leap years alone).
"""

import calendar
from datetime import date, timedelta
from itertools import pairwise

import numpy as np
import pandas as pd

from .preview import _ASCII_RAMP, _ansi, _color_mode, _rgb, pyplot

DAYS = 366
_REF_START = date(1999, 10, 1)  # WY2000, a water year with a Feb 29
_MONTH_NUMBERS = (10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9)
MONTHS = [calendar.month_abbr[m] for m in _MONTH_NUMBERS]
# first slot of each month, plus the end of the axis
_MONTH_EDGES = [(date(1999 if m >= 10 else 2000, m, 1) - _REF_START).days for m in _MONTH_NUMBERS] + [DAYS]
_FEB29 = (date(2000, 2, 29) - _REF_START).days

# highlighted years, in drawing priority: (symbol, color)
_HIGHLIGHT = [("●", (230, 85, 13)), ("◆", (49, 130, 189)), ("▲", (49, 163, 84)), ("■", (117, 107, 177))]
MAX_HIGHLIGHT = len(_HIGHLIGHT)
_GRAY = (140, 140, 140)
_RESET = "\x1b[0m"


def water_year(day: date) -> int:
    """The water year a date falls in (WY2026 is 2025-10-01 through 2026-09-30)."""
    return day.year + 1 if day.month >= 10 else day.year


def water_year_slot(day: date) -> int:
    """A date's position (0-365) on the October-to-September axis; the same calendar date gets the same slot each year."""
    return (date(1999 if day.month >= 10 else 2000, day.month, day.day) - _REF_START).days


def slot_date(slot: int, wy: int) -> date:
    """The real date of a slot in a given water year (Feb 29 in a non-leap year gives Mar 1)."""
    ref = _REF_START + timedelta(days=slot)
    year = wy - 1 if ref.month >= 10 else wy
    if ref.month == 2 and ref.day == 29 and not calendar.isleap(year):
        return date(year, 3, 1)
    return date(year, ref.month, ref.day)


def by_water_year(series: pd.Series) -> pd.DataFrame:
    """Reshape a daily series into a table with one row per slot (0-365) and one column per water year."""
    series = series.dropna()
    table = pd.DataFrame(index=pd.RangeIndex(DAYS))
    if series.empty:
        return table
    days = [pd.Timestamp(d).date() for d in series.index]
    long = pd.DataFrame(
        {
            "wy": [water_year(d) for d in days],
            "slot": [water_year_slot(d) for d in days],
            "value": series.to_numpy(dtype=float),
        }
    )
    table = long.pivot_table(index="slot", columns="wy", values="value", aggfunc="last").reindex(range(DAYS))
    table.columns.name = None
    for wy in table.columns:
        if not calendar.isleap(wy):
            table.loc[_FEB29, wy] = table.loc[[_FEB29 - 1, _FEB29 + 1], wy].mean(skipna=False)
    return table


def envelope(table: pd.DataFrame, exclude=()) -> pd.DataFrame:
    """Per-slot min, median and max across water years (leaving out `exclude`), and how many years had data."""
    others = table.drop(columns=[y for y in exclude if y in table.columns])
    return pd.DataFrame(
        {
            "min": others.min(axis=1),
            "median": others.median(axis=1),
            "max": others.max(axis=1),
            "years": others.notna().sum(axis=1),
        }
    )


def monthly_means(table: pd.DataFrame) -> pd.DataFrame:
    """Each water year's average for each month (rows Oct-Sep, columns water years). Partial months use the days present."""
    rows = [table.iloc[a:b].mean(axis=0) for a, b in pairwise(_MONTH_EDGES)]
    return pd.DataFrame(rows, index=MONTHS)


def default_years(table: pd.DataFrame) -> list[int]:
    """The latest water year with data."""
    return [int(table.columns.max())] if len(table.columns) else []


def check_years(table: pd.DataFrame, years: list[int]) -> None:
    """Raise a ValueError unless `years` is a short list of water years present in the table."""
    if len(years) > MAX_HIGHLIGHT:
        raise ValueError(f"Highlight at most {MAX_HIGHLIGHT} water years at a time.")
    missing = [y for y in years if y not in table.columns]
    if missing:
        have = f"WY{min(table.columns)}-WY{max(table.columns)}" if len(table.columns) else "none"
        raise ValueError(f"No data for water year(s) {', '.join(map(str, missing))} (have {have}).")


def _fmt(value: float) -> str:
    return f"{value:,.0f}" if abs(value) >= 100 else f"{value:.3g}"


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def summarize(table: pd.DataFrame, year: int, exclude=()) -> str:
    """
    One line on a water year: its latest value compared with the other years on the same day, and its peak so far.
    """
    column = table[year].dropna()
    if column.empty:
        return f"WY{year}: no data"
    slot, value = int(column.index[-1]), float(column.iloc[-1])
    others = table.drop(columns=[y for y in {year, *exclude} if y in table.columns]).loc[slot].dropna()
    parts = [f"WY{year} on {slot_date(slot, year):%Y-%m-%d}: {_fmt(value)}"]
    if others.empty:
        parts.append("no other years to compare with")
    else:
        median = float(others.median())
        if median > 0:
            parts.append(f"{value / median:.0%} of median ({_fmt(median)})")
        if (others != value).any():  # a rank means nothing when every year is the same (e.g. no snow)
            parts.append(f"{_ordinal(1 + int((others > value).sum()))} highest of {len(others) + 1} years")
    peak_slot = int(column.idxmax())
    if column.max() > 0 and peak_slot != slot:
        parts.append(f"peak {_fmt(float(column.max()))} on {slot_date(peak_slot, year):%Y-%m-%d}")
    return ", ".join(parts)


def _squeeze(values: np.ndarray, width: int) -> np.ndarray:
    """Average a 366-slot array into `width` columns (ignoring NaN)."""
    edges = np.linspace(0, len(values), width + 1).astype(int)
    out = np.full(width, np.nan)
    for j in range(width):
        block = values[edges[j] : max(edges[j + 1], edges[j] + 1)]
        if np.isfinite(block).any():
            out[j] = np.nanmean(block)
    return out


def _month_axis(width: int) -> str:
    """Month labels positioned under a `width`-column Oct-Sep axis."""
    chars = [" "] * width
    short = width < 48
    for month, start in zip(MONTHS, _MONTH_EDGES, strict=False):
        col = round(start * width / DAYS)
        label = month[0] if short else month
        if col + len(label) <= width and all(c == " " for c in chars[max(0, col - 1) : col + len(label)]):
            chars[col : col + len(label)] = label
    return "".join(chars)


def _paint(char: str, rgb, mode: str) -> str:
    return char if mode == "none" or char == " " else _ansi(rgb, mode, False) + char + _RESET


def _y_labels(rows: list[str], hi: float, lo: float) -> list[str]:
    label_w = max(len(_fmt(hi)), len(_fmt(lo)))
    out = []
    for i, line in enumerate(rows):
        label = _fmt(hi) if i == 0 else (_fmt(lo) if i == len(rows) - 1 else "")
        out.append(f"{label:>{label_w}} │{line}")
    return out


def _range_note(table: pd.DataFrame, years) -> str:
    others = [y for y in table.columns if y not in years]
    if not others:
        return "no other years"
    span = f"WY{min(others)}" if len(others) == 1 else f"WY{min(others)}-WY{max(others)}"
    return f"{len(others)} other year{'s' if len(others) > 1 else ''}, {span}"


def render_water_years(
    table: pd.DataFrame,
    years: list[int],
    width: int = 72,
    height: int = 12,
    title: str = "",
    units: str = "",
    color: bool | None = None,
) -> str:
    """Draw the highlighted water years over the median and range of the other years."""
    if table.dropna(how="all", axis=1).empty:
        return "(no data to chart)"
    mode = _color_mode(color)
    width = max(12, min(width, DAYS))
    height = max(3, height)
    env = envelope(table, exclude=years)
    lows, mids, highs = (_squeeze(env[c].to_numpy(dtype=float), width) for c in ("min", "median", "max"))
    lines = {y: _squeeze(table[y].to_numpy(dtype=float), width) for y in years}

    plotted = np.concatenate([lows, highs, *lines.values()])
    lo, hi = min(0.0, float(np.nanmin(plotted))), float(np.nanmax(plotted))
    span = (hi - lo) or 1.0

    def row(v):
        return int(round((v - lo) / span * (height - 1)))  # noqa: RUF046 - numpy 1.x round() returns a float

    grid = [[" "] * width for _ in range(height)]  # grid[0] is the bottom row
    for j in range(width):
        if np.isfinite(lows[j]) and np.isfinite(highs[j]):
            for r in range(row(lows[j]), row(highs[j]) + 1):
                grid[r][j] = _paint("░", _GRAY, mode)
        if np.isfinite(mids[j]):
            grid[row(mids[j])][j] = _paint("─", _GRAY, mode)
    for i in reversed(range(len(years))):  # the first year is drawn last, on top
        symbol, rgb = _HIGHLIGHT[i]
        for j, v in enumerate(lines[years[i]]):
            if np.isfinite(v):
                grid[row(v)][j] = _paint(symbol, rgb, mode)

    rows = ["".join(r) for r in reversed(grid)]
    out = [title] if title else []
    out += _y_labels(rows, hi, lo)
    pad = " " * max(len(_fmt(hi)), len(_fmt(lo)))
    out.append(f"{pad} └{'─' * width}")
    out.append(f"{pad}  {_month_axis(width)}")
    keys = [_paint(_HIGHLIGHT[i][0], _HIGHLIGHT[i][1], mode) + f" WY{y}" for i, y in enumerate(years)]
    keys += [_paint("─", _GRAY, mode) + " median", _paint("░", _GRAY, mode) + f" range ({_range_note(table, years)})"]
    out.append(f"{pad}  " + "  ".join(keys))
    if units:
        out.append(f"{pad}  units: {units}")
    out += [summarize(table, y, exclude=years) for y in years]
    return "\n".join(out)


def render_heatmap(
    table: pd.DataFrame, width: int = 72, title: str = "", units: str = "", color: bool | None = None
) -> str:
    """Draw one row per water year, colored by value across the October-to-September axis."""
    table = table.dropna(how="all", axis=1)
    if table.empty:
        return "(no data to chart)"
    mode = _color_mode(color)
    width = max(12, min(width, DAYS))
    rows = {wy: _squeeze(table[wy].to_numpy(dtype=float), width) for wy in table.columns}
    values = np.concatenate(list(rows.values()))
    lo, hi = min(0.0, float(np.nanmin(values))), float(np.nanmax(values))
    span = (hi - lo) or 1.0
    out = [title] if title else []
    for wy, row in rows.items():
        cells = []
        for v in row:
            if not np.isfinite(v):
                cells.append(" ")
            elif mode == "none":  # skip the ramp's blank, which here means no data
                ramp = _ASCII_RAMP[1:]
                cells.append(ramp[min(int((v - lo) / span * len(ramp)), len(ramp) - 1)])
            else:
                cells.append(_ansi(_rgb((v - lo) / span), mode, True) + " " + _RESET)
        out.append(f"WY{wy} │{''.join(cells)}")
    out.append(f"{'':6} └{'─' * width}")
    out.append(f"{'':6}  {_month_axis(width)}")
    if mode == "none":
        legend = f"low '{_ASCII_RAMP[1]}' {_fmt(lo)} ... high '{_ASCII_RAMP[-1]}' {_fmt(hi)}"
    else:
        legend = (
            f"{_fmt(lo)} " + "".join(_ansi(_rgb(i / 19), mode, True) + " " for i in range(20)) + f"{_RESET} {_fmt(hi)}"
        )
    out.append(f"{'':6}  {legend} {units}".rstrip())
    return "\n".join(out)


def render_months(
    table: pd.DataFrame,
    years: list[int],
    width: int = 72,
    title: str = "",
    units: str = "",
    color: bool | None = None,
) -> str:
    """
    Draw a box plot per month of the other years' monthly averages (whiskers min-max, box the middle half, ┃ the
    median), with the highlighted years marked.
    """
    mode = _color_mode(color)
    monthly = monthly_means(table)
    others = monthly.drop(columns=[y for y in years if y in monthly.columns])
    if monthly.dropna(how="all").empty:
        return "(no data to chart)"
    width = max(20, width - 20)  # room for the month name and the median label
    values = monthly.to_numpy(dtype=float)
    lo, hi = min(0.0, float(np.nanmin(values))), float(np.nanmax(values))
    span = (hi - lo) or 1.0

    def col(v):
        return int(round((v - lo) / span * (width - 1)))  # noqa: RUF046 - numpy 1.x round() returns a float

    out = [title] if title else []
    for month in MONTHS:
        if monthly.loc[month].isna().all():
            continue
        chars = [" "] * width
        dist = others.loc[month].dropna()
        label = ""
        if not dist.empty:
            q0, q1, q2, q3, q4 = np.percentile(dist.to_numpy(dtype=float), [0, 25, 50, 75, 100])
            for c in range(col(q0), col(q4) + 1):
                chars[c] = _paint("─", _GRAY, mode)
            for c in range(col(q1), col(q3) + 1):
                chars[c] = _paint("▒", _GRAY, mode)
            chars[col(q0)], chars[col(q4)] = _paint("├", _GRAY, mode), _paint("┤", _GRAY, mode)
            chars[col(q2)] = _paint("┃", _GRAY, mode)
            label = f"median {_fmt(q2)}"
        for i in reversed(range(len(years))):
            v = monthly.loc[month].get(years[i], np.nan)
            if np.isfinite(v):
                chars[col(v)] = _paint(_HIGHLIGHT[i][0], _HIGHLIGHT[i][1], mode)
        out.append(f"{month} │{''.join(chars)}│ {label}".rstrip())
    out.append(f"    {_fmt(lo)}{' ' * max(1, width + 2 - len(_fmt(lo)) - len(_fmt(hi)))}{_fmt(hi)}")
    keys = [_paint(_HIGHLIGHT[i][0], _HIGHLIGHT[i][1], mode) + f" WY{y}" for i, y in enumerate(years)]
    keys.append(f"boxes: monthly averages, {_range_note(table, years)}")
    out.append("    " + "  ".join(keys))
    if units:
        out.append(f"    units: {units}")
    return "\n".join(out)


def _month_ticks(ax) -> None:
    ax.set_xticks(_MONTH_EDGES[:-1])
    ax.set_xticklabels(MONTHS)
    ax.set_xlim(0, DAYS - 1)


def _hex(rgb) -> str:
    r, g, b = rgb
    return f"#{r:02x}{g:02x}{b:02x}"


def plot(
    table: pd.DataFrame,
    view: str,
    years: list[int],
    title: str = "",
    units: str = "",
    png=None,
    show: bool = False,
) -> None:
    """Draw a water-year view ('water-years', 'heatmap' or 'months') with matplotlib; save to `png` and/or show it."""
    plt = pyplot(show)
    from matplotlib.ticker import FuncFormatter  # pylint: disable=import-outside-toplevel

    ticks = FuncFormatter(lambda v, _pos: _fmt(v))  # 1,200,000 rather than 1.2 with a "1e6" offset
    fig, ax = plt.subplots(figsize=(10, 5.5 if view != "heatmap" else max(3, 0.3 * len(table.columns) + 1.5)))
    if view != "heatmap":
        ax.yaxis.set_major_formatter(ticks)
    label = f"{title} ({units})" if units else title
    if view == "water-years":
        env = envelope(table, exclude=years)
        x = np.arange(DAYS)
        ax.fill_between(x, env["min"], env["max"], color="0.85", label=f"range ({_range_note(table, years)})")
        for wy in table.columns:
            if wy not in years:
                ax.plot(x, table[wy], color="0.65", linewidth=0.6)
        ax.plot(x, env["median"], color="0.3", linestyle="--", linewidth=1.2, label="median")
        for i, wy in enumerate(years):  # the first year on top
            ax.plot(x, table[wy], color=_hex(_HIGHLIGHT[i][1]), linewidth=2.2, label=f"WY{wy}", zorder=10 - i)
        _month_ticks(ax)
        ax.set_ylabel(label)
        ax.set_ylim(bottom=min(0, ax.get_ylim()[0]))
        ax.legend(loc="upper left", frameon=False)
        ax.grid(axis="y", alpha=0.3)
    elif view == "heatmap":
        table = table.dropna(how="all", axis=1)
        image = ax.imshow(table.T.to_numpy(dtype=float), aspect="auto", cmap="viridis", interpolation="nearest")
        ax.set_yticks(range(len(table.columns)))
        ax.set_yticklabels([f"WY{wy}" for wy in table.columns])
        _month_ticks(ax)
        ax.set_xlim(-0.5, DAYS - 0.5)
        fig.colorbar(image, ax=ax, label=label, format=ticks)
    elif view == "months":
        monthly = monthly_means(table)
        others = monthly.drop(columns=[y for y in years if y in monthly.columns])
        data = [others.loc[m].dropna().to_numpy(dtype=float) for m in MONTHS]
        ax.boxplot(data, whis=(0, 100), medianprops={"color": "0.2"})
        ax.set_xticks(range(1, 13))
        ax.set_xticklabels(MONTHS)
        for i, wy in enumerate(years):
            ax.plot(
                range(1, 13),
                monthly[wy],
                marker="o",
                linestyle="none",
                color=_hex(_HIGHLIGHT[i][1]),
                label=f"WY{wy}",
            )
        ax.set_ylabel(label)
        ax.legend(loc="upper left", frameon=False, title=f"boxes: {_range_note(table, years)}")
        ax.grid(axis="y", alpha=0.3)
    else:
        raise ValueError(f"Unknown view '{view}'")
    ax.set_title(title)
    fig.tight_layout()
    if png:
        fig.savefig(png, dpi=150)
    if show:
        plt.show()
    plt.close(fig)
