"""
Resolving the set of dates a command should work on.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from dateutil.parser import parse as parse_datetime

# First day NSIDC has SNODAS data for.
MASKED_START = date(2003, 9, 30)
UNMASKED_START = date(2009, 12, 9)


def today(timezone: str = "UTC") -> date:
    """Today's date in the given IANA timezone (e.g. 'America/Denver')."""
    return datetime.now(tz=ZoneInfo(timezone)).date()


def parse_date(value: str | date) -> date:
    """Parse a date such as '2024-03-31' or '3/31/2024'."""
    if isinstance(value, date):
        return value
    try:
        return parse_datetime(value).date()
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"Not a valid date: '{value}'") from exc


def resolve_dates(
    day: str | date | None = None,
    start: str | date | None = None,
    end: str | date | None = None,
    recent: int | None = None,
    timezone: str = "UTC",
) -> list[date]:
    """
    Turn one of the supported date selections into a list of dates (oldest first):

    - a single `day`
    - a `start` date, with an optional `end` date (default: today)
    - `recent` N days, ending today

    "Today" is evaluated in `timezone`.
    """
    if end is not None and start is None:
        raise ValueError("--end needs --start.")
    chosen = sum(x is not None for x in (day, start, recent))
    if chosen == 0:
        raise ValueError("Choose dates with a DATE argument, --start/--end, or --recent N.")
    if chosen > 1:
        raise ValueError("Use only one of: a DATE argument, --start/--end, or --recent N.")

    now = today(timezone)
    if recent is not None:
        if recent < 1:
            raise ValueError("--recent must be at least 1.")
        first, last = now - timedelta(days=recent - 1), now
    elif day is not None:
        first = last = parse_date(day)
    else:
        first = parse_date(start)
        last = parse_date(end) if end is not None else now

    if first > last:
        raise ValueError(f"Start date {first} is after end date {last}.")
    if last > now:
        raise ValueError(f"{last} is in the future.")
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]
