"""Shared filter rules for every query engine.

Engines (pandas, live PostgreSQL, DuckDB on disk, DuckDB aggregates) only
understand absolute filters. This module turns the richer UI forms into them:

* ``{"kind": "date", "start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}`` — either
  bound may be missing; ``end`` is inclusive (the whole day).
* ``{"kind": "date", "last": N, "unit": "day|week|month|year"}`` — relative
  to today; resolved to a ``start`` here so all engines agree.
"""
from __future__ import annotations

import math
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


def range_bounds(item: dict) -> tuple[int | float | None, int | float | None]:
    """(min, max) of a range filter, both inclusive; either may be None (one-sided)."""
    bounds = []
    for key in ("min", "max"):
        value = item.get(key)
        if value is None:
            bounds.append(None)
            continue
        if isinstance(value, bool):
            raise ValueError("Range filter values must be numbers.")
        try:
            number = value if isinstance(value, int) else float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Range filter values must be numbers.") from exc
        if isinstance(number, float) and not math.isfinite(number):
            raise ValueError("Range filter values must be finite.")
        bounds.append(number)
    low, high = bounds
    if low is not None and high is not None and low > high:
        raise ValueError(f"Range filter on {item.get('column')!r}: minimum is above maximum.")
    return low, high


def is_active(item: dict) -> bool:
    kind = item.get("kind")
    if kind == "categorical":
        return bool(item.get("values"))
    if kind == "range":
        return item.get("min") is not None or item.get("max") is not None
    if kind == "date":
        return any(item.get(k) not in (None, "") for k in ("start", "end", "last"))
    return False


# ---- AND/OR criteria groups -------------------------------------------------
#
# ``{"kind": "any", "groups": [[f, f], [f]]}`` keeps rows that match every
# filter of at least one group: (f AND f) OR (f). Other filters in the list are
# still ANDed with it. Groups hold ordinary filters only (no nesting).

MAX_GROUPS = 20


def leaves(filters: list[dict]) -> list[dict]:
    """Every ordinary filter, including those inside criteria groups."""
    out = []
    for item in filters or []:
        if item.get("kind") == "any":
            for group in item.get("groups") or []:
                out.extend(group)
        else:
            out.append(item)
    return out


def validate_groups(item: dict) -> list[list[dict]]:
    groups = item.get("groups")
    if not isinstance(groups, list) or not groups or len(groups) > MAX_GROUPS:
        raise ValueError(f"A criteria group filter needs 1–{MAX_GROUPS} groups.")
    for group in groups:
        if not isinstance(group, list) or any(f.get("kind") == "any" for f in group):
            raise ValueError("Criteria groups hold ordinary filters (no nested groups).")
    return groups


def combine(filters: list[dict], flat):
    """Combine ordinary filters with criteria groups for '?'-style SQL.

    ``flat(list_of_filters) -> (sql, params_list)`` is the engine's own AND builder."""
    plain = [f for f in filters or [] if f.get("kind") != "any"]
    sql, params = flat(plain)
    parts, params = [sql], list(params)
    for item in filters or []:
        if item.get("kind") != "any":
            continue
        ors = []
        for group in validate_groups(item):
            group_sql, group_params = flat(group)
            ors.append(f"({group_sql})")
            params.extend(group_params)
        parts.append("(" + " OR ".join(ors) + ")")
    return " AND ".join(parts), params


def combine_named(filters: list[dict], flat):
    """Like ``combine`` for ':name' parameters: ``flat(filters, prefix) -> (sql, dict)``.
    Each group gets its own parameter prefix so names never collide."""
    plain = [f for f in filters or [] if f.get("kind") != "any"]
    sql, params = flat(plain, "")
    parts, params = [sql], dict(params)
    for a, item in enumerate(f for f in filters or [] if f.get("kind") == "any"):
        ors = []
        for b, group in enumerate(validate_groups(item)):
            group_sql, group_params = flat(group, f"g{a}_{b}_")
            ors.append(f"({group_sql})")
            params.update(group_params)
        parts.append("(" + " OR ".join(ors) + ")")
    return " AND ".join(parts), params
