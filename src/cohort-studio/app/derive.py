"""Derived (computed) columns.

Structured operations only — no free-text expression evaluation (even
df.eval has escape surface). Three ops cover the common cases:
- bin:     cut a numeric column into labelled ranges
- formula: arithmetic between a column and another column or a constant
- map:     remap categorical values (grouping / relabelling)

Each produces a new column added to the dataset's in-memory frame, which
is then re-profiled so filters and charts pick it up.
"""

import re

import numpy as np
import pandas as pd

import datasets

NAME_RE = re.compile(r"^[A-Za-z0-9 _.\-]{1,60}$")
OPERATORS = {"+": np.add, "-": np.subtract, "*": np.multiply, "/": np.divide}


def _valid_name(name: str) -> str:
    name = (name or "").strip()
    if not NAME_RE.match(name):
        raise ValueError(
            "Column name must be 1–60 chars: letters, digits, space, _.-")
    return name


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        raise ValueError(f"Unknown column: {col}")
    return pd.to_numeric(df[col], errors="coerce")


def _bin(df: pd.DataFrame, spec: dict) -> pd.Series:
    col = spec.get("column")
    breaks = spec.get("breaks") or []
    if len(breaks) < 2:
        raise ValueError("Binning needs at least two break points.")
    breaks = [float(b) for b in breaks]
    if breaks != sorted(breaks):
        raise ValueError("Break points must be ascending.")
    labels = spec.get("labels")
    if labels and len(labels) != len(breaks) - 1:
        raise ValueError(
            f"Expected {len(breaks) - 1} labels for {len(breaks)} breaks.")
    cut = pd.cut(_num(df, col), bins=breaks, labels=labels or None,
                 include_lowest=True)
    return cut.astype(str).where(cut.notna(), None)


def _formula(df: pd.DataFrame, spec: dict) -> pd.Series:
    op = spec.get("operator")
    if op not in OPERATORS:
        raise ValueError(f"Operator must be one of {list(OPERATORS)}")
    left = _num(df, spec.get("left"))
    right_raw = spec.get("right")
    try:
        right = float(right_raw)           # constant operand
    except (TypeError, ValueError):
        right = _num(df, right_raw)         # another column
    with np.errstate(divide="ignore", invalid="ignore"):
        out = OPERATORS[op](left, right)
    return pd.Series(out, index=df.index).replace([np.inf, -np.inf], np.nan)


def _map(df: pd.DataFrame, spec: dict) -> pd.Series:
    col = spec.get("column")
    if col not in df.columns:
        raise ValueError(f"Unknown column: {col}")
    mapping = spec.get("mapping") or {}
    if not mapping:
        raise ValueError("Provide at least one value mapping.")
    default = spec.get("default")
    src = df[col].astype(str)
    mapped = src.map({str(k): v for k, v in mapping.items()})
    # Unmapped values keep the original (or a default if given).
    fill = default if default not in (None, "") else None
    return mapped.where(mapped.notna(), fill if fill is not None else src)


_OPS = {"bin": _bin, "formula": _formula, "map": _map}


def derive(dataset_id: str, spec: dict) -> dict:
    name = _valid_name(spec.get("name", ""))
    op = spec.get("op")
    if op not in _OPS:
        raise ValueError(f"Unknown op: {op}")
    df = datasets.get(dataset_id)["df"]
    series = _OPS[op](df, spec)
    return datasets.set_column(dataset_id, name, series)
