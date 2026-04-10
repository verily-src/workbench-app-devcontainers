"""
C2a Technical Profiler — schema stats, column profiling, pattern detection, validation.

No LLM — pure BigQuery queries.

Phases:
  1. Aggregate NULL/distinct counts (one scan)
  2. Top values for low-cardinality columns (parallel)
  3. String length stats
  4. Numeric stats (min/max/stddev + median)
  5. Pattern detection on string samples
  6. Structural validation
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from models import BQColumnInfo, BQTableInfo, TechColumnProfile, TechTableProfile, ValidationResult

_NUMERIC_BQ_TYPES = {"INT64", "INTEGER", "FLOAT64", "FLOAT", "NUMERIC", "BIGNUMERIC"}
_STRING_BQ_TYPES = {"STRING", "BYTES"}

# Patterns checked against sampled values
_PATTERNS = [
    ("UUID", re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)),
    ("EMAIL", re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)),
    ("URL", re.compile(r"^https?://", re.I)),
    ("IP_V4", re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")),
    ("DATE_ISO", re.compile(r"^\d{4}-\d{2}-\d{2}$")),
    ("DATETIME_ISO", re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")),
    ("PHONE_US", re.compile(r"^\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}$")),
]


def _detect_pattern(values: list[str]) -> Optional[str]:
    """Match sampled string values against known patterns. Returns pattern name or None."""
    if not values:
        return None
    for name, regex in _PATTERNS:
        matches = sum(1 for v in values if regex.match(v))
        if matches >= len(values) * 0.8:
            return name
    return None


def profile_table(
    table_info: BQTableInfo,
    billing_project_id: Optional[str] = None,
) -> TechTableProfile:
    """
    Profile a BQ table: NULL counts, distinct counts, top values,
    string/numeric stats, pattern detection, and structural validation.
    """
    from google.cloud import bigquery

    start = time.time()
    client = bigquery.Client(project=billing_project_id or table_info.project_id)
    fq_table = f"`{table_info.project_id}.{table_info.dataset_id}.{table_info.table_id}`"
    columns = table_info.columns

    profile = TechTableProfile(
        table_name=table_info.fq_name,
        size_bytes=table_info.size_bytes,
    )

    # ── Phase 1: NULL counts + distinct counts ──
    parts = ["COUNT(*) AS total_rows"]
    for i, col in enumerate(columns):
        cn = col.column_name.replace("`", "")
        parts.append(f"COUNTIF(`{cn}` IS NULL) AS n_{i}")
        parts.append(f"APPROX_COUNT_DISTINCT(`{cn}`) AS d_{i}")

    sql = f"SELECT {', '.join(parts)} FROM {fq_table}"

    try:
        row = next(iter(client.query(sql).result()))
        profile.row_count = row.total_rows or 0

        for i, col in enumerate(columns):
            nulls = getattr(row, f"n_{i}", 0) or 0
            distinct = getattr(row, f"d_{i}", 0) or 0
            pct = round(100.0 * nulls / profile.row_count, 1) if profile.row_count > 0 else 0.0
            profile.columns.append(TechColumnProfile(
                column_name=col.column_name,
                data_type=col.data_type,
                nullable=col.is_nullable == "YES",
                null_count=nulls,
                null_percent=pct,
                distinct_count=distinct,
            ))
    except Exception as e:
        print(f"Profiling query failed for {table_info.fq_name}: {e}")
        for col in columns:
            profile.columns.append(TechColumnProfile(
                column_name=col.column_name,
                data_type=col.data_type,
                nullable=col.is_nullable == "YES",
                anomalies=[f"profiling_failed: {e}"],
            ))
        profile.validation = ValidationResult(status="fail", anomalies=[f"Phase 1 failed: {e}"])
        return profile

    # ── Phase 2: Top values for low-cardinality columns (parallel) ──
    coded_cols = [
        (i, col) for i, col in enumerate(columns)
        if 1 < profile.columns[i].distinct_count <= 50
    ]

    def _fetch_top_values(idx: int, col_info: BQColumnInfo) -> tuple[int, list[str], dict[str, int]]:
        cn = col_info.column_name.replace("`", "")
        q = f"""
        SELECT CAST(`{cn}` AS STRING) AS val, COUNT(*) AS cnt
        FROM {fq_table}
        WHERE `{cn}` IS NOT NULL
        GROUP BY 1 ORDER BY cnt DESC LIMIT 25
        """
        try:
            rows = list(client.query(q).result())
            values = [r.val for r in rows if r.val]
            counts = {r.val: r.cnt for r in rows if r.val}
            return idx, values, counts
        except Exception:
            return idx, [], {}

    if coded_cols:
        with ThreadPoolExecutor(max_workers=min(8, len(coded_cols))) as ex:
            futures = {ex.submit(_fetch_top_values, idx, c): idx for idx, c in coded_cols}
            for f in as_completed(futures):
                idx, vals, val_counts = f.result()
                profile.columns[idx].top_values = vals
                profile.columns[idx].value_counts = val_counts

    # ── Phase 3: String length stats ──
    string_cols = [
        (i, col) for i, col in enumerate(columns)
        if col.data_type.upper().split("<")[0].strip() in _STRING_BQ_TYPES
    ]
    if string_cols:
        len_parts = []
        for j, (i, col) in enumerate(string_cols):
            cn = col.column_name.replace("`", "")
            len_parts.append(f"MIN(LENGTH(`{cn}`)) AS smin_{j}")
            len_parts.append(f"MAX(LENGTH(`{cn}`)) AS smax_{j}")
            len_parts.append(f"AVG(LENGTH(`{cn}`)) AS savg_{j}")

        len_sql = f"SELECT {', '.join(len_parts)} FROM {fq_table}"
        try:
            row = next(iter(client.query(len_sql).result()))
            for j, (i, _col) in enumerate(string_cols):
                cp = profile.columns[i]
                cp.min_length = getattr(row, f"smin_{j}", None)
                cp.max_length = getattr(row, f"smax_{j}", None)
                avg = getattr(row, f"savg_{j}", None)
                cp.avg_length = round(float(avg), 1) if avg is not None else None
        except Exception as e:
            print(f"  String length profiling failed: {e}")

    # ── Phase 4: Numeric stats ──
    numeric_cols = [
        (i, col) for i, col in enumerate(columns)
        if col.data_type.upper().split("<")[0].strip() in _NUMERIC_BQ_TYPES
    ]
    if numeric_cols:
        num_parts = []
        for j, (i, col) in enumerate(numeric_cols):
            cn = col.column_name.replace("`", "")
            num_parts.append(f"MIN(`{cn}`) AS nmin_{j}")
            num_parts.append(f"MAX(`{cn}`) AS nmax_{j}")
            num_parts.append(f"STDDEV(`{cn}`) AS nstd_{j}")

        num_sql = f"SELECT {', '.join(num_parts)} FROM {fq_table}"
        try:
            row = next(iter(client.query(num_sql).result()))
            for j, (i, _col) in enumerate(numeric_cols):
                cp = profile.columns[i]
                nmin = getattr(row, f"nmin_{j}", None)
                nmax = getattr(row, f"nmax_{j}", None)
                nstd = getattr(row, f"nstd_{j}", None)
                cp.min_value = float(nmin) if nmin is not None else None
                cp.max_value = float(nmax) if nmax is not None else None
                cp.stddev = round(float(nstd), 4) if nstd is not None else None
        except Exception as e:
            print(f"  Numeric stats profiling failed: {e}")

        def _fetch_median(idx: int, col_info: BQColumnInfo) -> tuple[int, Optional[float]]:
            cn = col_info.column_name.replace("`", "")
            q = f"""
            SELECT APPROX_QUANTILES(`{cn}`, 2)[OFFSET(1)] AS median_val
            FROM {fq_table}
            WHERE `{cn}` IS NOT NULL
            """
            try:
                row = next(iter(client.query(q).result()))
                return idx, float(row.median_val) if row.median_val is not None else None
            except Exception:
                return idx, None

        with ThreadPoolExecutor(max_workers=min(8, len(numeric_cols))) as ex:
            futures = {ex.submit(_fetch_median, i, c): i for i, c in numeric_cols}
            for f in as_completed(futures):
                idx, med = f.result()
                if med is not None:
                    profile.columns[idx].median = med

    # ── Phase 5: Pattern detection on string columns ──
    for i, col in string_cols:
        cp = profile.columns[i]
        samples = cp.top_values[:10] if cp.top_values else []
        if not samples and cp.distinct_count > 0:
            cn = col.column_name.replace("`", "")
            sample_q = f"""
            SELECT CAST(`{cn}` AS STRING) AS val
            FROM {fq_table}
            WHERE `{cn}` IS NOT NULL
            LIMIT 20
            """
            try:
                rows = list(client.query(sample_q).result())
                samples = [r.val for r in rows if r.val]
            except Exception:
                pass
        if samples:
            cp.detected_pattern = _detect_pattern(samples)

    # ── Phase 6: Structural validation ──
    profile.validation = _validate(profile)

    elapsed = time.time() - start
    n_coded = len(coded_cols)
    n_str = len(string_cols)
    n_num = len(numeric_cols)
    print(f"  Profiled {table_info.fq_name}: {profile.row_count:,} rows, "
          f"{len(columns)} cols, {n_coded} coded, {n_str} string, {n_num} numeric — {elapsed:.1f}s")

    return profile


def _validate(profile: TechTableProfile) -> ValidationResult:
    """Run structural validation checks on the technical profile."""
    anomalies: list[str] = []
    warnings: list[str] = []

    for cp in profile.columns:
        if cp.null_percent == 100.0:
            cp.anomalies.append("all_null")
            anomalies.append(f"{cp.column_name}: 100% NULL")
        elif cp.null_percent >= 95.0:
            cp.anomalies.append("near_all_null")
            warnings.append(f"{cp.column_name}: {cp.null_percent}% NULL")

        if cp.distinct_count == 1 and profile.row_count > 1:
            cp.anomalies.append("single_value")
            warnings.append(f"{cp.column_name}: single distinct value")

        if cp.distinct_count == profile.row_count and profile.row_count > 10:
            cp.anomalies.append("unique_key_candidate")

    status = "fail" if anomalies else "pass"
    return ValidationResult(status=status, anomalies=anomalies, warnings=warnings)
