import csv
import io
import logging
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from joins import ROWID_COLUMN

logger = logging.getLogger(__name__)

BOOLEAN_VALUES = {"true", "false", "yes", "no", "0", "1", "t", "f", "y", "n"}
DATE_PATTERNS = [
    re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}"),
    re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$"),
]
SENTINEL_VALUES = {"", "n/a", "N/A", "NA", "na", "null", "NULL", "None", "none", "."}
CATEGORICAL_THRESHOLD = 50


@dataclass
class ColumnMapping:
    column: str
    type: str
    filter: str
    label: str
    storage_type: str | None = None


def generate_label(column_name: str) -> str:
    name = column_name.replace("_", " ").replace(".", " ")
    return name.strip().title()


def _is_boolean(values: list[str]) -> bool:
    return all(v.lower() in BOOLEAN_VALUES for v in values)


NUMERIC_THRESHOLD = 0.9


def _is_integer(values: list[str]) -> bool:
    if not values:
        return False
    hits = 0
    for v in values:
        try:
            float_val = float(v)
            if float_val != int(float_val):
                return False
            hits += 1
        except ValueError:
            pass
    return hits / len(values) >= NUMERIC_THRESHOLD


def _is_float(values: list[str]) -> bool:
    if not values:
        return False
    hits = 0
    for v in values:
        try:
            float(v)
            hits += 1
        except ValueError:
            pass
    return hits / len(values) >= NUMERIC_THRESHOLD


def _is_date(values: list[str]) -> bool:
    matches = sum(1 for v in values if any(p.match(v) for p in DATE_PATTERNS))
    return matches / len(values) > 0.8 if values else False


def _infer_type(values: list[str]) -> str:
    if not values:
        return "text"
    if _is_boolean(values):
        return "boolean"
    if _is_integer(values):
        return "integer"
    if _is_float(values):
        return "float"
    if _is_date(values):
        return "date"
    return "text"


def _infer_filter(col_type: str, unique_count: int) -> str:
    if col_type == "boolean":
        return "categorical"
    if col_type == "integer":
        return "categorical" if unique_count <= CATEGORICAL_THRESHOLD else "range"
    if col_type == "float":
        return "range"
    if col_type == "text":
        return "categorical" if unique_count <= CATEGORICAL_THRESHOLD else "none"
    return "none"


def infer_from_csv(file_path: str, sample_size: int = 5000) -> list[ColumnMapping]:
    path = Path(file_path)
    with open(path, newline="", encoding="utf-8") as f:
        sample = f.read(8192)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t")
        except csv.Error:
            dialect = None
    delimiter = dialect.delimiter if dialect else ("\t" if path.suffix.lower() != ".csv" else ",")

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        columns: dict[str, list[str]] = {col: [] for col in (reader.fieldnames or [])}
        unique_values: dict[str, set[str]] = {col: set() for col in columns}

        for i, row in enumerate(reader):
            if i >= sample_size:
                break
            for col in columns:
                raw = row.get(col, "").strip()
                if raw not in SENTINEL_VALUES:
                    columns[col].append(raw)
                    unique_values[col].add(raw)

    mappings = []
    for col in columns:
        col_type = _infer_type(columns[col])
        col_filter = _infer_filter(col_type, len(unique_values[col]))
        mappings.append(ColumnMapping(
            column=col,
            type=col_type,
            filter=col_filter,
            label=generate_label(col),
        ))

    logger.info("Inferred schema from %s: %d columns", file_path, len(mappings))
    return mappings


PG_TYPE_MAP = {
    "boolean": "boolean",
    "smallint": "integer",
    "integer": "integer",
    "bigint": "integer",
    "real": "float",
    "double precision": "float",
    "numeric": "float",
    "date": "date",
    "timestamp without time zone": "date",
    "timestamp with time zone": "date",
}

def _connect_aurora(resource_id: str):
    from db import resolve_connection_string, _conn_string_cache
    import psycopg

    conn_str = resolve_connection_string(resource_id)
    try:
        return psycopg.connect(conn_str)
    except psycopg.OperationalError:
        _conn_string_cache.pop(resource_id, None)
        conn_str = resolve_connection_string(resource_id)
        return psycopg.connect(conn_str)


def list_aurora_tables(resource_id: str) -> list[dict]:
    with _connect_aurora(resource_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name, table_type
                FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_type, table_name
            """)
            return [
                {"name": row[0], "type": "view" if row[1] == "VIEW" else "table"}
                for row in cur.fetchall()
            ]


def get_aurora_storage_types(resource_id: str, table: str) -> dict[str, str]:
    with _connect_aurora(resource_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
            """, (table,))
            return dict(cur.fetchall())


def list_aurora_columns(resource_id: str, table: str, schema: str = "public") -> list[dict]:
    """List a table's columns for the join-builder's key pickers (J07)."""
    with _connect_aurora(resource_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
            """, (schema, table))
            return [{"column": row[0], "type": row[1]} for row in cur.fetchall()]


def infer_from_join(resource_id: str, select_sql: str, output_columns: list[dict], sample_size: int = 2000) -> list[ColumnMapping]:
    """Infer a schema for a join's SELECT list in one bounded pass over all
    columns at once, instead of infer_from_aurora's per-column full-table
    scans (BENCH-10344 J27 — a joined/fanned-out result is expensive to
    rescan once per column). Trade-off: classification is based on a sample,
    like infer_from_csv, not an exact full-table count.

    Sets storage_type from the join's own information_schema lookup (same
    column that drives infer_from_aurora's text-vs-numeric reclassification),
    so the text-backed-numeric CAST path in main.py applies to joins too."""
    pg_type_by_output = {c["output"]: c["pg_type"] for c in output_columns}

    with _connect_aurora(resource_id) as conn:
        with conn.cursor() as cur:
            cur.execute(f"{select_sql}\nLIMIT %s", (sample_size,))
            colnames = [d.name for d in cur.description]
            rows = cur.fetchall()

    samples: dict[str, list[str]] = {name: [] for name in colnames}
    for row in rows:
        for name, val in zip(colnames, row):
            if val is not None and str(val).strip() not in SENTINEL_VALUES:
                samples[name].append(str(val))

    mappings = []
    for name in colnames:
        if name == ROWID_COLUMN:
            continue  # synthetic row id, added back by set_active_join_mapping
        pg_type = pg_type_by_output.get(name, "text")
        col_type = PG_TYPE_MAP.get(pg_type, "text")
        if col_type == "text" and samples[name]:
            if _is_integer(samples[name]):
                col_type = "integer"
            elif _is_float(samples[name]):
                col_type = "float"
        unique_count = len(set(samples[name])) if col_type == "text" else CATEGORICAL_THRESHOLD + 1
        col_filter = _infer_filter(col_type, unique_count)
        mappings.append(ColumnMapping(
            column=name,
            type=col_type,
            filter=col_filter,
            label=generate_label(name),
            storage_type=pg_type,
        ))

    logger.info("Inferred schema from join (%d tables worth of columns): %d columns", len({c["source_table"] for c in output_columns}), len(mappings))
    return mappings


def infer_from_aurora(resource_id: str, table: str) -> list[ColumnMapping]:
    with _connect_aurora(resource_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                ORDER BY ordinal_position
            """, (table,))
            columns = cur.fetchall()

            mappings = []
            for col_name, pg_type in columns:
                col_type = PG_TYPE_MAP.get(pg_type, "text")

                if col_type == "text":
                    cur.execute(
                        f'SELECT COUNT(DISTINCT "{col_name}") FROM "{table}"'
                    )
                    unique_count = cur.fetchone()[0]

                    cur.execute(f"""
                        SELECT COUNT(*) FROM "{table}"
                        WHERE "{col_name}" IS NOT NULL AND "{col_name}" != ''
                    """)
                    non_empty = cur.fetchone()[0]
                    if non_empty > 0:
                        cur.execute(f"""
                            SELECT COUNT(*) FROM "{table}"
                            WHERE "{col_name}" IS NOT NULL AND "{col_name}" != ''
                            AND NOT "{col_name}" ~ '^-?[0-9]*\\.?[0-9]+$'
                        """)
                        non_numeric = cur.fetchone()[0]
                        if non_numeric == 0:
                            cur.execute(f"""
                                SELECT COUNT(*) FROM "{table}"
                                WHERE "{col_name}" ~ '\\.'
                            """)
                            has_decimal = cur.fetchone()[0] > 0
                            col_type = "float" if has_decimal else "integer"
                else:
                    unique_count = CATEGORICAL_THRESHOLD + 1

                col_filter = _infer_filter(col_type, unique_count)
                mappings.append(ColumnMapping(
                    column=col_name,
                    type=col_type,
                    filter=col_filter,
                    label=generate_label(col_name),
                    storage_type=pg_type,
                ))

    logger.info("Inferred schema from Aurora %s.%s: %d columns", resource_id, table, len(mappings))
    return mappings


def load_mapping_csv(file_path: str) -> list[ColumnMapping]:
    with open(file_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [
            ColumnMapping(
                column=row["column"],
                type=row["type"],
                filter=row["filter"],
                label=row["label"],
                storage_type=row.get("storage_type") or None,
            )
            for row in reader
        ]


def save_mapping_csv(file_path: str, mappings: list[ColumnMapping]):
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["column", "type", "filter", "label", "storage_type"],
        )
        writer.writeheader()
        for m in mappings:
            writer.writerow(asdict(m))


def mappings_to_dicts(mappings: list[ColumnMapping]) -> list[dict]:
    return [asdict(m) for m in mappings]
