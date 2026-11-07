"""One text form for category values in every engine.

PostgreSQL ``CAST(col AS text)`` (in a UTC session) is the reference. Profiles,
bar/heatmap categories and categorical filters use this form, so a value shown
by one engine matches the same rows in every other engine:

* booleans: ``true`` / ``false``
* floats: integral values without ``.0`` (``1``, not ``1.0``); others as the
  shortest round-trip text (``2.5``, ``1e+20``)
* timestamps: ``YYYY-MM-DD HH:MM:SS[.ffffff]`` with trailing zeros trimmed;
  time-zone aware values in UTC with ``+00``
* dates: ``YYYY-MM-DD``; everything else: ``str(value)``
"""
from __future__ import annotations

import datetime as _dt
import math
from decimal import Decimal

import numpy as np
import pandas as pd

# Integral floats at or above this are written in exponent form (DuckDB and Python).
_INTEGRAL_LIMIT = 1e15


def _float_text(value) -> str:
    number = float(value)
    if not math.isfinite(number):
        return str(number)
    scientific = np.format_float_scientific(value, unique=True, trim="-", exp_digits=2)
    exponent = int(scientific.split("e")[1])
    limit = 6 if isinstance(value, np.float32) else 15
    if number and (exponent >= limit or exponent < -4):
        return scientific
    return np.format_float_positional(value, unique=True, trim="-")


def _clock(value: _dt.datetime) -> str:
    text = value.strftime("%Y-%m-%d %H:%M:%S")
    ns = value.microsecond * 1000 + getattr(value, "nanosecond", 0)
    if ns:
        text += f".{ns:09d}".rstrip("0")
    return text


def _datetime_text(value: _dt.datetime) -> str:
    if value.tzinfo is not None and value.utcoffset() is not None:
        return _clock(value.astimezone(_dt.timezone.utc).replace(tzinfo=None)) + "+00"
    return _clock(value)


def value_text(value) -> str | None:
    """The category text of one value, or None for a missing value."""
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (bool, np.bool_)):
        return "True" if value else "False"
    if isinstance(value, (float, np.floating)):
        return None if math.isnan(value) else _float_text(value)
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, _dt.datetime):
        return _datetime_text(value)
    if isinstance(value, _dt.date):
        return value.isoformat()
    if isinstance(value, np.datetime64):
        return None if np.isnat(value) else _datetime_text(pd.Timestamp(value))
    if isinstance(value, Decimal):
        return None if value.is_nan() else str(value)
    return str(value)


def _datetime_series(series: pd.Series) -> pd.Series:
    if isinstance(series.dtype, pd.ArrowDtype):
        series = pd.to_datetime(series.astype(object), utc=bool(series.dtype.pyarrow_dtype.tz))
    if getattr(series.dt, "tz", None) is not None:
        series, suffix = series.dt.tz_convert("UTC").dt.tz_localize(None), "+00"
    else:
        suffix = ""
    base = series.dt.strftime("%Y-%m-%d %H:%M:%S")
    nanos = series.dt.microsecond * 1000 + series.dt.nanosecond
    fraction = nanos.map(lambda ns: f".{int(ns):09d}".rstrip("0") if pd.notna(ns) and ns else "")
    out = (base + fraction + suffix).astype(object)
    return out.where(series.notna(), None)


def frame_text(series: pd.Series) -> pd.Series:
    """Category text for a pandas column (object dtype; missing values are None)."""
    dtype = series.dtype
    if isinstance(dtype, pd.CategoricalDtype):
        series, dtype = series.astype(object), np.dtype(object)
    if pd.api.types.is_bool_dtype(dtype):
        out = series.map({True: "True", False: "False"}).astype(object)
        return out.where(series.notna(), None)
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return _datetime_series(series)
    numpy_dtype = getattr(dtype, "numpy_dtype", dtype)
    if isinstance(dtype, pd.ArrowDtype):
        numpy_dtype = dtype.pyarrow_dtype.to_pandas_dtype()
    if numpy_dtype == np.dtype("float32"):
        return series.map(lambda value: _float_text(np.float32(value)) if pd.notna(value) else None).astype(object)
    if pd.api.types.is_float_dtype(dtype) or pd.api.types.is_integer_dtype(dtype) or dtype == object:
        return series.map(value_text, na_action="ignore").astype(object).where(series.notna(), None)
    return series.astype(str).astype(object).where(series.notna(), None)


def duck_text(expr: str, duck_type: str | None) -> str:
    """DuckDB SQL for the category text of ``expr`` (session TimeZone must be UTC)."""
    kind = (duck_type or "").upper()
    if kind in ("DOUBLE", "FLOAT", "REAL", "FLOAT4", "FLOAT8"):
        return f"CAST({expr} AS VARCHAR)"
    if kind == "TIMESTAMP_NS":
        return f"CAST({expr} AS VARCHAR)"
    if kind.startswith("TIMESTAMP_") or kind == "DATETIME":
        return f"CAST(CAST({expr} AS TIMESTAMP) AS VARCHAR)"
    return f"CAST({expr} AS VARCHAR)"


def normalize_label(value, storage_type):
    """Render a returned float category using its storage precision."""
    kind = str(storage_type).upper()
    if kind in ("16", "BOOLEAN", "BOOL") and str(value).lower() in ("true", "false"):
        return str(value).capitalize()
    if kind not in ("700", "701", "FLOAT", "REAL", "FLOAT4", "FLOAT8", "DOUBLE"):
        return value
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return value
    if math.isnan(parsed):
        return "NaN"
    return _float_text(np.float32(parsed) if kind in ("700", "FLOAT", "REAL", "FLOAT4") else parsed)


def normalize_chart(chart, storage_types):
    """Normalize category labels after SQL grouping, leaving folded labels intact."""
    kind = chart.get("kind")
    x_type = storage_types.get(chart.get("y") if kind == "box" else chart.get("x"))
    y_type = storage_types.get(chart.get("y"))
    series_type = storage_types.get(chart.get("series_column"))
    if kind in ("bar", "box"):
        for row in chart.get("data", []):
            if row.get("category") != chart.get("other_category"):
                row["category"] = normalize_label(row.get("category"), x_type)
        if "series" in chart:
            chart["series"] = [normalize_label(label, series_type) if label != chart.get("other_series") else label
                               for label in chart["series"]]
    elif kind == "heatmap":
        for row in chart.get("data", []):
            row[0], row[1] = normalize_label(row[0], x_type), normalize_label(row[1], y_type)
    return chart


def value_kind(dtype_or_type) -> str | None:
    """'bool' or 'float' for columns whose filter values have a legacy text form."""
    if isinstance(dtype_or_type, str):
        kind = dtype_or_type.upper()
        if kind in ("BOOLEAN", "BOOL"):
            return "bool"
        if kind in ("DOUBLE", "FLOAT", "REAL", "FLOAT4", "FLOAT8"):
            return "float"
        return None
    if pd.api.types.is_bool_dtype(dtype_or_type):
        return "bool"
    if pd.api.types.is_float_dtype(dtype_or_type):
        return "float"
    return None


def series_value_kind(series: pd.Series) -> str | None:
    kind = value_kind(series.dtype)
    if kind is None and series.dtype == object:
        sample = series.dropna().head(50)
        if len(sample) and all(isinstance(v, (bool, np.bool_)) for v in sample):
            return "bool"
    return kind


def filter_values(values, kind: str | None) -> list[str]:
    """Canonical categorical filter values; older forms ("True", "1.0") still match."""
    out = []
    for value in values:
        text = str(value)
        if kind == "bool" and text.strip().lower() in ("true", "false"):
            text = text.strip().capitalize()
        elif kind == "float":
            try:
                number = float(text)
            except ValueError:
                pass
            else:
                if math.isfinite(number):
                    text = _float_text(number)
        out.append(text)
    return out


# ---- numeric range filters ---------------------------------------------------

def check_range_dtype(name: str, series: pd.Series) -> None:
    dtype = series.dtype
    if (pd.api.types.is_bool_dtype(dtype) or pd.api.types.is_datetime64_any_dtype(dtype)
            or pd.api.types.is_timedelta64_dtype(dtype) or series_value_kind(series) == "bool"):
        raise ValueError(f"Range filters require a numeric column: {name}")


_NON_NUMERIC_DUCK = ("BOOLEAN", "BOOL", "DATE", "TIME", "TIMESTAMP", "DATETIME", "INTERVAL")


def check_range_duck(name: str, duck_type: str | None) -> None:
    kind = (duck_type or "").upper()
    if kind.startswith(_NON_NUMERIC_DUCK):
        raise ValueError(f"Range filters require a numeric column: {name}")


