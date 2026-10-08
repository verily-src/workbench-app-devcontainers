"""
Technical Profiler — schema stats, column profiling, pattern detection, validation.

No LLM — pure BigQuery queries.

Performance: phases 1 (nulls/distinct), 3 (string lengths), 4 (numeric stats +
medians) are combined into a single table scan. Top-value and pattern-sample
queries run in parallel afterward.
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from verily_profiler.discovery import get_table_api_metadata
from verily_profiler.models import BQColumnInfo, BQTableInfo, TechColumnProfile, TechTableProfile, ValidationResult

_NUMERIC_BQ_TYPES = {"INT64", "INTEGER", "FLOAT64", "FLOAT", "NUMERIC", "BIGNUMERIC"}
_STRING_BQ_TYPES = {"STRING", "BYTES"}

_PATTERNS = [
    ("UUID", re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)),
    ("EMAIL", re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)),
    ("URL", re.compile(r"^https?://", re.I)),
    ("IP_V4", re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")),
    ("DATE_ISO", re.compile(r"^\d{4}-\d{2}-\d{2}$")),
    ("DATETIME_ISO", re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")),
    ("PHONE_US", re.compile(r"^\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}$")),
]

_MAX_WORKERS = 16


def _detect_pattern(values: list[str]) -> Optional[str]:
    if not values:
        return None
    for name, regex in _PATTERNS:
        matches = sum(1 for v in values if regex.match(v))
        if matches >= len(values) * 0.8:
            return name
    return None


def _safe_col(name: str) -> str:
    return name.replace("`", "")


def profile_technical(
    table_info: BQTableInfo,
    billing_project: Optional[str] = None,
) -> TechTableProfile:
    """
    Profile a BQ table: NULL counts, distinct counts, top values,
    string/numeric stats, pattern detection, and structural validation.
    """
    from google.cloud import bigquery

    start = time.time()
    client = bigquery.Client(project=billing_project or table_info.project_id)
    fq_table = f"`{table_info.project_id}.{table_info.dataset_id}.{table_info.table_id}`"
    columns = table_info.columns

    resolved_size = table_info.size_bytes
    if resolved_size is None:
        _, api_bytes = get_table_api_metadata(
            table_info.project_id,
            table_info.dataset_id,
            table_info.table_id,
            billing_project=billing_project or table_info.project_id,
            log_failures=True,
        )
        if api_bytes is not None:
            resolved_size = api_bytes

    profile = TechTableProfile(
        table_name=table_info.fq_name,
        size_bytes=resolved_size,
    )

    string_col_indices = [
        i for i, col in enumerate(columns)
        if col.data_type.upper().split("<")[0].strip() in _STRING_BQ_TYPES
    ]
    numeric_col_indices = [
        i for i, col in enumerate(columns)
        if col.data_type.upper().split("<")[0].strip() in _NUMERIC_BQ_TYPES
    ]
    string_set = set(string_col_indices)
    numeric_set = set(numeric_col_indices)

    # ── Combined query: nulls, distinct, string lengths, numeric stats, medians ──

    parts = ["COUNT(*) AS total_rows"]

    for i, col in enumerate(columns):
        cn = _safe_col(col.column_name)
        parts.append(f"COUNTIF(`{cn}` IS NULL) AS n_{i}")
        parts.append(f"APPROX_COUNT_DISTINCT(`{cn}`) AS d_{i}")

    for j, i in enumerate(string_col_indices):
        cn = _safe_col(columns[i].column_name)
        parts.append(f"MIN(LENGTH(`{cn}`)) AS smin_{j}")
        parts.append(f"MAX(LENGTH(`{cn}`)) AS smax_{j}")
        parts.append(f"CAST(AVG(LENGTH(`{cn}`)) AS FLOAT64) AS savg_{j}")

    for j, i in enumerate(numeric_col_indices):
        cn = _safe_col(columns[i].column_name)
        parts.append(f"MIN(`{cn}`) AS nmin_{j}")
        parts.append(f"MAX(`{cn}`) AS nmax_{j}")
        parts.append(f"STDDEV(`{cn}`) AS nstd_{j}")
        parts.append(f"APPROX_QUANTILES(`{cn}`, 2)[OFFSET(1)] AS nmed_{j}")

    combined_sql = f"SELECT {', '.join(parts)} FROM {fq_table}"

    try:
        row = next(iter(client.query(combined_sql).result()))
        profile.row_count = row.total_rows or 0

        for i, col in enumerate(columns):
            nulls = getattr(row, f"n_{i}", 0) or 0
            distinct = getattr(row, f"d_{i}", 0) or 0
            pct = round(100.0 * nulls / profile.row_count, 1) if profile.row_count > 0 else 0.0

            cp = TechColumnProfile(
                column_name=col.column_name,
                data_type=col.data_type,
                nullable=col.is_nullable == "YES",
                null_count=nulls,
                null_percent=pct,
                distinct_count=distinct,
            )

            if i in string_set:
                j = string_col_indices.index(i)
                cp.min_length = getattr(row, f"smin_{j}", None)
                cp.max_length = getattr(row, f"smax_{j}", None)
                avg = getattr(row, f"savg_{j}", None)
                cp.avg_length = round(float(avg), 1) if avg is not None else None

            if i in numeric_set:
                j = numeric_col_indices.index(i)
                nmin = getattr(row, f"nmin_{j}", None)
                nmax = getattr(row, f"nmax_{j}", None)
                nstd = getattr(row, f"nstd_{j}", None)
                nmed = getattr(row, f"nmed_{j}", None)
                cp.min_value = float(nmin) if nmin is not None else None
                cp.max_value = float(nmax) if nmax is not None else None
                cp.stddev = round(float(nstd), 4) if nstd is not None else None
                cp.median = float(nmed) if nmed is not None else None

            profile.columns.append(cp)

    except Exception as e:
        print(f"Profiling query failed for {table_info.fq_name}: {e}")
        for col in columns:
            profile.columns.append(TechColumnProfile(
                column_name=col.column_name,
                data_type=col.data_type,
                nullable=col.is_nullable == "YES",
                anomalies=[f"profiling_failed: {e}"],
            ))
        profile.validation = ValidationResult(status="fail", anomalies=[f"Combined query failed: {e}"])
        return profile

    # ── Parallel: top values (low-cardinality) + pattern samples (string) ────

    coded_cols = [
        (i, columns[i]) for i in range(len(columns))
        if 1 < profile.columns[i].distinct_count <= 50
    ]
    high_card_strings = [
        (i, columns[i]) for i in string_col_indices
        if profile.columns[i].distinct_count > 50
    ]

    def _fetch_top_values(idx: int, col_info: BQColumnInfo) -> tuple[str, int, list[str], dict[str, int]]:
        cn = _safe_col(col_info.column_name)
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
            return "top", idx, values, counts
        except Exception:
            return "top", idx, [], {}

    def _fetch_pattern_samples(idx: int, col_info: BQColumnInfo) -> tuple[str, int, list[str], dict]:
        cn = _safe_col(col_info.column_name)
        q = f"""
        SELECT CAST(`{cn}` AS STRING) AS val
        FROM {fq_table}
        WHERE `{cn}` IS NOT NULL
        LIMIT 20
        """
        try:
            rows = list(client.query(q).result())
            return "pattern", idx, [r.val for r in rows if r.val], {}
        except Exception:
            return "pattern", idx, [], {}

    all_tasks = []
    for idx, col in coded_cols:
        all_tasks.append(("top", idx, col))
    for idx, col in high_card_strings:
        all_tasks.append(("pattern", idx, col))

    if all_tasks:
        with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(all_tasks))) as ex:
            futures = []
            for kind, idx, col in all_tasks:
                if kind == "top":
                    futures.append(ex.submit(_fetch_top_values, idx, col))
                else:
                    futures.append(ex.submit(_fetch_pattern_samples, idx, col))

            for f in as_completed(futures):
                kind, idx, vals, counts = f.result()
                cp = profile.columns[idx]
                if kind == "top":
                    cp.top_values = vals
                    cp.value_counts = counts
                elif kind == "pattern" and vals:
                    cp.detected_pattern = _detect_pattern(vals)

    # Pattern detection for low-cardinality strings (use existing top_values)
    for i in string_col_indices:
        cp = profile.columns[i]
        if cp.detected_pattern:
            continue
        samples = cp.top_values[:10] if cp.top_values else []
        if samples:
            cp.detected_pattern = _detect_pattern(samples)

    # ── Validation ───────────────────────────────────────────────────────────

    profile.validation = _validate(profile)

    elapsed = time.time() - start
    print(f"  Profiled {table_info.fq_name}: {profile.row_count:,} rows, "
          f"{len(columns)} cols — {elapsed:.1f}s")

    return profile


def _validate(profile: TechTableProfile) -> ValidationResult:
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
