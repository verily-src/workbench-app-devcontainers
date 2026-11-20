"""Small-cell masking in the All of Us style, so what the agent shows never names a handful of
people: a count from 1 to ``threshold - 1`` is reported as ``"<threshold"``, and a rate built on
such a count is reported as a bound. Standard library only.

It is on for every dataset, synthetic or not. ``KUMO_FORECAST_SMALL_CELL=0`` turns it off.
"""
from __future__ import annotations

import os


def threshold() -> int:
    try:
        return max(0, int(os.environ.get("KUMO_FORECAST_SMALL_CELL", "20")))
    except ValueError:
        return 20


def count(n: int, limit: int | None = None) -> int | str:
    """``n``, or ``"<limit"`` when 0 < n < limit."""
    limit = threshold() if limit is None else limit
    n = int(n)
    return f"<{limit}" if limit and 0 < n < limit else n


def count_of(events: int, total: int, limit: int | None = None) -> int | str:
    """``events``, a count that is part of ``total``, where ``total`` is shown beside it: ``"<limit"``
    when 0 < events < limit, ``">total - limit"`` when 0 < total - events < limit (the rest of the
    total would name them), else the count."""
    limit = threshold() if limit is None else limit
    events, total = int(events), int(total)
    if limit and 0 < events < limit:
        return f"<{limit}"
    if limit and 0 < total - events < limit:
        return f">{total - limit}"
    return events


def rate(events: int, total: int, limit: int | None = None) -> str:
    """events/total as a percentage, masked when either the events or the non-events are small."""
    limit = threshold() if limit is None else limit
    events, total = int(events), int(total)
    if total <= 0:
        return "n/a"
    if limit and total < 2 * limit:
        # a bound from a masked count says nothing in a group this small (a count under 20 of 20)
        return f"masked (group of fewer than {2 * limit})"
    if limit and (0 < events < limit):
        return f"<{100 * limit / total:.1f}%"
    if limit and (0 < total - events < limit):
        return f">{100 * (total - limit) / total:.1f}%"
    return f"{100 * events / total:.1f}%"


def _bound(value: int, limit: int) -> int:
    """The next multiple of ``limit`` above ``value``."""
    return (value // limit + 1) * limit


def rates(groups: list[tuple[int, int]], limit: int | None = None) -> list[str]:
    """``rate`` for each (events, total) group of a split of one population, where the groups' sizes
    and the exact overall count are shown too. One masked rate alone could be solved for from the
    overall count and the other groups' rates, so when exactly one is masked the group with the next
    smallest count of the same kind (events, non-events, or members) is reported as a bound as well,
    leaving two unknowns."""
    limit = threshold() if limit is None else limit
    out = [rate(e, t, limit) for e, t in groups]
    if not limit or len(groups) < 3:
        return out
    kinds = []
    for e, t in groups:
        if t <= 0:
            kinds.append(None)
        elif t < 2 * limit:
            kinds.append("size")
        elif 0 < e < limit:
            kinds.append("events")
        elif 0 < t - e < limit:
            kinds.append("non")
        else:
            kinds.append(None)
    masked = [i for i, k in enumerate(kinds) if k]
    if len(masked) != 1 or any(t <= 0 for _, t in groups):
        return out
    kind = kinds[masked[0]]
    size = {"size": lambda e, t: t, "events": lambda e, t: e, "non": lambda e, t: t - e}[kind]
    j = min((i for i in range(len(groups)) if i != masked[0]), key=lambda i: size(*groups[i]))
    e, t = groups[j]
    if kind == "size":
        out[j] = f"masked (group of fewer than {_bound(t, 2 * limit)})"
    elif kind == "events":
        out[j] = f"<{100 * _bound(e, limit) / t:.1f}%"
    else:
        out[j] = f">{100 * (t - _bound(t - e, limit)) / t:.1f}%"
    return out
