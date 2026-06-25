import csv
import io
import logging
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

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


def generate_label(column_name: str) -> str:
    name = column_name.replace("_", " ").replace(".", " ")
    return name.strip().title()


def _is_boolean(values: list[str]) -> bool:
    return all(v.lower() in BOOLEAN_VALUES for v in values)


def _is_integer(values: list[str]) -> bool:
    for v in values:
        try:
            float_val = float(v)
            if float_val != int(float_val):
                return False
        except ValueError:
            return False
    return True


def _is_float(values: list[str]) -> bool:
    for v in values:
        try:
            float(v)
        except ValueError:
            return False
    return True


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


def infer_from_csv(file_path: str, sample_size: int = 1000) -> list[ColumnMapping]:
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
                else:
                    unique_count = CATEGORICAL_THRESHOLD + 1

                col_filter = _infer_filter(col_type, unique_count)
                mappings.append(ColumnMapping(
                    column=col_name,
                    type=col_type,
                    filter=col_filter,
                    label=generate_label(col_name),
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
            )
            for row in reader
        ]


def save_mapping_csv(file_path: str, mappings: list[ColumnMapping]):
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["column", "type", "filter", "label"])
        writer.writeheader()
        for m in mappings:
            writer.writerow(asdict(m))


def mappings_to_dicts(mappings: list[ColumnMapping]) -> list[dict]:
    return [asdict(m) for m in mappings]
