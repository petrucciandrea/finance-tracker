"""
Calendar period boundaries, shared by budgets and the planning engine.

This started as a private helper in `routers/budgets.py`. It moved here
when the planning engine needed the same month, because "which month is
this date in" has to have exactly one answer across the app: phase D
stamps a savings allocation with a period start and later asks how much of
that period's quota is already spoken for. Two definitions of a month that
disagree by a day would make that lookup silently miss.
"""

import calendar
from datetime import date as date_


def period_bounds(period: str, on_date: date_) -> tuple[date_, date_]:
    """Returns (start, end) inclusive dates for the month/year containing on_date."""
    if period == "monthly":
        start = on_date.replace(day=1)
        last_day = calendar.monthrange(on_date.year, on_date.month)[1]
        end = on_date.replace(day=last_day)
    else:  # yearly
        start = on_date.replace(month=1, day=1)
        end = on_date.replace(month=12, day=31)
    return start, end


def month_start(on_date: date_) -> date_:
    """First day of the month containing on_date — the canonical period key."""
    return on_date.replace(day=1)


def add_months(on_date: date_, months: int) -> date_:
    """
    Shift a date by whole months, clamping the day to the target month's
    length so e.g. 31 January minus one month is 31 December, not a crash.
    Used only on month starts here, but the clamp keeps it safe elsewhere.
    """
    total = on_date.year * 12 + (on_date.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    day = min(on_date.day, calendar.monthrange(year, month)[1])
    return date_(year, month, day)


def months_between(start: date_, end: date_) -> int:
    """Whole months from start to end, both taken at month granularity."""
    return (end.year - start.year) * 12 + (end.month - start.month)
