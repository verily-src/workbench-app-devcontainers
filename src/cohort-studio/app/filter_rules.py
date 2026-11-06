"""Shared filter rules for every query engine.

Engines (pandas, live PostgreSQL, DuckDB on disk, DuckDB aggregates) only
understand absolute filters. This module turns the richer UI forms into them:

* ``{"kind": "date", "start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}`` — either
  bound may be missing; ``end`` is inclusive (the whole day).
* ``{"kind": "date", "last": N, "unit": "day|week|month|year"}`` — relative
  to today; resolved to a ``start`` here so all engines agree.
"""
from __future__ import annotations

from datetime import date, timedelta

UNITS = ("day", "week", "month", "year")
MAX_LAST = 10_000


def _parse(value, what: str) -> date | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError(f"Date filter {what} must be a YYYY-MM-DD string.")
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise ValueError(f"Date filter {what} {value!r} is not a valid date.") from exc


def _months_back(today: date, months: int) -> date:
    year, month = divmod(today.year * 12 + today.month - 1 - months, 12)
    month += 1
    day = min(today.day, [31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28,
                          31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


def relative_start(last: int, unit: str, today: date | None = None) -> date:
    today = today or date.today()
    if unit not in UNITS:
        raise ValueError(f"Date filter unit must be one of {', '.join(UNITS)}.")
    if not isinstance(last, int) or isinstance(last, bool) or not 0 < last <= MAX_LAST:
        raise ValueError(f"Date filter 'last' must be a whole number from 1 to {MAX_LAST:,}.")
    if unit == "day":
        return today - timedelta(days=last)
    if unit == "week":
        return today - timedelta(weeks=last)
    return _months_back(today, last * (12 if unit == "year" else 1))


def date_bounds(item: dict, today: date | None = None) -> tuple[date | None, date | None]:
    """(start inclusive, end exclusive) for a date filter; either may be None."""
    if item.get("last") is not None:
        return relative_start(item["last"], item.get("unit") or "day", today), None
    start, end = _parse(item.get("start"), "start"), _parse(item.get("end"), "end")
    if start and end and end < start:
        raise ValueError("Date filter end is before its start.")
    return start, (end + timedelta(days=1)) if end else None


def is_active(item: dict) -> bool:
    kind = item.get("kind")
    if kind == "categorical":
        return bool(item.get("values"))
    if kind == "range":
        return item.get("min") is not None and item.get("max") is not None
    if kind == "date":
        return any(item.get(k) not in (None, "") for k in ("start", "end", "last"))
    return False
