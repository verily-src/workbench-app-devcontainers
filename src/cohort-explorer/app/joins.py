"""No-code join support across Aurora tables (BENCH-10344 phase 2 draft).

Scope for this draft: the core join path (config model, validation,
N-step SQLAlchemy-free SQL builder, collision-safe column naming, row-growth
preview). UI enforces a 3-table cap per the epic's decision; this module
itself does not, so saved/activated joins can hold more steps later.

Not implemented here (left for follow-up, see epic J16-J25):
saved join configs, NULL-key reporting, non-public schema listing beyond
passing a schema name through, views-on-views hardening.
"""
import hashlib
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

MAX_JOIN_TABLES = 3  # UI cap (BENCH-10344 decided answer to Q2)
ROWID_COLUMN = "_rowid"  # synthetic per-row identity, see build_select
IDENTIFIER_MAX_BYTES = 63  # Postgres identifier limit (J26)
PREVIEW_STATEMENT_TIMEOUT_MS = 10_000  # basic guard, see J28

JOIN_SQL = {"inner": "INNER JOIN", "left": "LEFT JOIN", "full": "FULL OUTER JOIN"}

# Same type-family grouping as the epic's Q7 answer: integer family can mix
# (smallint/integer/bigint), but text never auto-casts to a numeric family.
TYPE_FAMILIES = {
    "smallint": "integer", "integer": "integer", "bigint": "integer",
    "real": "float", "double precision": "float", "numeric": "float",
    "text": "text", "character varying": "text", "character": "text",
    "boolean": "boolean",
    "date": "date", "timestamp without time zone": "date", "timestamp with time zone": "date",
}


class JoinError(ValueError):
    """Raised for any invalid join definition; message is shown to the user as-is."""


@dataclass
class JoinStep:
    table: str
    schema: str = "public"
    join_to: str | None = None   # table name of a step already added (None only for the base step)
    left_key: str | None = None  # key column on the `join_to` side
    right_key: str | None = None  # key column on this step's table
    join_type: str = "inner"     # inner | left | full


def _quote_ident(name: str) -> str:
    if '"' in name or "\x00" in name:
        raise JoinError(f"Invalid identifier: {name!r}")
    return f'"{name}"'


def _validate_steps(steps: list[JoinStep]) -> dict[str, str]:
    """Structural validation + alias assignment. Does not hit the DB."""
    if not steps:
        raise JoinError("A join needs at least one table")
    if len(steps) > MAX_JOIN_TABLES:
        raise JoinError(f"At most {MAX_JOIN_TABLES} tables are supported")
    if steps[0].join_to is not None:
        raise JoinError("The first table is the base table and must not set join_to")

    aliases: dict[str, str] = {}
    seen_tables: set[tuple[str, str]] = set()
    for i, s in enumerate(steps):
        table_key = (s.schema, s.table)
        if table_key in seen_tables:
            raise JoinError(f"Table {s.schema}.{s.table} is used more than once (self-joins are not supported)")
        seen_tables.add(table_key)
        aliases[s.table] = f"t{i}"

        if i == 0:
            continue
        if not s.join_to or not s.left_key or not s.right_key:
            raise JoinError(f"Step {i + 1} ({s.table}) is missing join_to/left_key/right_key")
        if s.join_to not in aliases:
            raise JoinError(f"Step {i + 1} joins to '{s.join_to}', which hasn't been added yet")
        if s.join_type not in JOIN_SQL:
            raise JoinError(f"Unknown join type: {s.join_type}")
    return aliases


def build_join_select(steps: list[JoinStep]) -> str:
    """Build the raw FROM-clause SQL (with quoted identifiers) for N steps."""
    aliases = _validate_steps(steps)
    base = steps[0]
    from_sql = f"{_quote_ident(base.schema)}.{_quote_ident(base.table)} AS {aliases[base.table]}"
    for s in steps[1:]:
        this_alias = aliases[s.table]
        to_alias = aliases[s.join_to]
        from_sql += (
            f"\n{JOIN_SQL[s.join_type]} {_quote_ident(s.schema)}.{_quote_ident(s.table)} AS {this_alias} "
            f"ON {to_alias}.{_quote_ident(s.left_key)} = {this_alias}.{_quote_ident(s.right_key)}"
        )
    return from_sql


def _type_family(pg_type: str) -> str:
    return TYPE_FAMILIES.get(pg_type, "text")


def _column_type(cur, schema_name: str, table: str, column: str) -> str | None:
    cur.execute(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s AND column_name = %s",
        (schema_name, table, column),
    )
    row = cur.fetchone()
    return row[0] if row else None


def validate_join(resource_id: str, steps: list[JoinStep]) -> None:
    """Raises JoinError with a user-facing message on any structural or
    key-type problem (J06). Does not auto-cast (epic Q7)."""
    _validate_steps(steps)
    from schema import _connect_aurora

    with _connect_aurora(resource_id) as conn:
        with conn.cursor() as cur:
            by_table = {s.table: s for s in steps}
            for s in steps[1:]:
                parent = by_table[s.join_to]
                left_type = _column_type(cur, parent.schema, parent.table, s.left_key)
                right_type = _column_type(cur, s.schema, s.table, s.right_key)
                if left_type is None:
                    raise JoinError(f"Column {parent.table}.{s.left_key} not found")
                if right_type is None:
                    raise JoinError(f"Column {s.table}.{s.right_key} not found")
                if _type_family(left_type) != _type_family(right_type):
                    raise JoinError(
                        f"Join key type mismatch: {parent.table}.{s.left_key} ({left_type}) "
                        f"vs {s.table}.{s.right_key} ({right_type}). No auto-cast — "
                        f"pick keys of the same type family."
                    )


def row_growth_preview(resource_id: str, steps: list[JoinStep]) -> list[dict]:
    """Row count after each join step, cumulative (J10/J14). Each step gets
    its own statement timeout so one slow join doesn't block the others (J28,
    basic version — reports 'too large to count' rather than hanging)."""
    _validate_steps(steps)
    from schema import _connect_aurora

    results = []
    cumulative: list[JoinStep] = []
    with _connect_aurora(resource_id) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            for s in steps:
                cumulative.append(s)
                from_sql = build_join_select(cumulative)
                try:
                    cur.execute(f"SET statement_timeout = {PREVIEW_STATEMENT_TIMEOUT_MS}")
                    cur.execute(f"SELECT COUNT(*) FROM {from_sql}")
                    count = cur.fetchone()[0]
                    results.append({"table": s.table, "row_count": count, "timed_out": False})
                except Exception as e:
                    logger.warning("Row growth preview timed out/failed at %s: %s", s.table, e)
                    results.append({"table": s.table, "row_count": None, "timed_out": True})
    return results


def _safe_output_name(name: str, used: set[str]) -> str:
    """Shorten deterministically to fit Postgres's 63-byte identifier limit,
    with a short hash suffix so collisions from truncation are still unique (J26)."""
    fits = len(name.encode("utf-8")) <= IDENTIFIER_MAX_BYTES
    if fits and name not in used:
        used.add(name)
        return name
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    truncated = name.encode("utf-8")[: IDENTIFIER_MAX_BYTES - len(digest) - 1].decode("utf-8", "ignore")
    candidate = f"{truncated}_{digest}"
    n = 1
    while candidate in used:
        n += 1
        candidate = f"{truncated}_{digest}{n}"
    used.add(candidate)
    return candidate


def build_select(resource_id: str, steps: list[JoinStep]) -> tuple[str, list[dict]]:
    """Build the full SELECT (with collision-safe, length-safe column aliases)
    for a join. Returns (select_sql, output_columns) where output_columns is
    [{"output", "source_table", "source_column", "pg_type"}, ...] in table
    order. select_sql's first column is always the synthetic ROWID_COLUMN,
    which is deliberately omitted from output_columns (see set_active_join_mapping
    in dynamic_model.py for how it's consumed)."""
    aliases = _validate_steps(steps)
    from schema import _connect_aurora

    per_table_columns: dict[str, list[tuple[str, str]]] = {}
    with _connect_aurora(resource_id) as conn:
        with conn.cursor() as cur:
            for s in steps:
                cur.execute(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
                    (s.schema, s.table),
                )
                cols = cur.fetchall()
                if not cols:
                    raise JoinError(f"Table {s.schema}.{s.table} has no columns (does it exist?)")
                per_table_columns[s.table] = cols

    name_counts: dict[str, int] = {}
    for s in steps:
        for col_name, _ in per_table_columns[s.table]:
            name_counts[col_name] = name_counts.get(col_name, 0) + 1

    used: set[str] = {ROWID_COLUMN}  # reserve the synthetic row-id name in case a real column collides with it
    output_columns: list[dict] = []
    # A 1:N join has no natural column that's unique per output row (not even
    # the "count distinct by" entity column — that repeats once per fanned-out
    # row by design). Without a real per-row identity, SQLAlchemy's identity
    # map silently collapses rows that share a mapped "primary key", dropping
    # data. ROW_NUMBER() gives every output row a distinct id regardless of
    # join shape; it is mapped as the ORM primary key but never shown to the
    # user as a schema column.
    select_parts: list[str] = [f'ROW_NUMBER() OVER () AS {_quote_ident(ROWID_COLUMN)}']
    for s in steps:
        alias = aliases[s.table]
        for col_name, pg_type in per_table_columns[s.table]:
            collides = name_counts[col_name] > 1
            base_name = f"{s.table}_{col_name}" if collides else col_name
            output_name = _safe_output_name(base_name, used)
            output_columns.append({
                "output": output_name,
                "source_table": s.table,
                "source_column": col_name,
                "pg_type": pg_type,
            })
            select_parts.append(f"{alias}.{_quote_ident(col_name)} AS {_quote_ident(output_name)}")

    from_sql = build_join_select(steps)
    select_sql = f"SELECT {', '.join(select_parts)}\nFROM {from_sql}"
    return select_sql, output_columns
