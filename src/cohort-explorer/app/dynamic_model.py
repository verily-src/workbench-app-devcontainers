import json
import logging
from pathlib import Path

from sqlalchemy import Boolean, Column, Date, Float, Integer, Text, column as sa_column, text
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)

_SCHEMA_FILE = Path(__file__).parent / "active_schema.json"

SA_TYPE_MAP = {
    "boolean": Boolean,
    "integer": Integer,
    "float": Float,
    "text": Text,
    "date": Date,
}

TEXT_STORAGE_TYPES = {"text", "character", "character varying"}

_active_mapping: list[dict] | None = None
_active_model: type | None = None
_active_table_name: str | None = None
_entity_column: str | None = None


class DynamicBase(DeclarativeBase):
    pass


def set_active_mapping(mappings: list[dict], table_name: str = "data", needs_pk: bool = True, entity_column: str | None = None):
    global _active_mapping, _active_model, _active_table_name, _pk_name, _entity_column
    _active_mapping = mappings
    _active_table_name = table_name
    _entity_column = entity_column

    DynamicBase.metadata.clear()

    user_columns = {m["column"] for m in mappings}

    if needs_pk:
        _pk_name = "_rowid" if "id" in user_columns else "id"
        attrs: dict = {
            "__tablename__": table_name,
            _pk_name: Column(Integer, primary_key=True),
        }
    else:
        _pk_name = "id" if "id" in user_columns else mappings[0]["column"]
        attrs = {
            "__tablename__": table_name,
        }

    for m in mappings:
        sa_type = (
            Text
            if m.get("storage_type") in TEXT_STORAGE_TYPES
            else SA_TYPE_MAP.get(m["type"], Text)
        )
        is_pk = not needs_pk and m["column"] == _pk_name
        attrs[m["column"]] = Column(sa_type, primary_key=is_pk)

    _active_model = type("DynamicRow", (DynamicBase,), attrs)
    logger.info("Dynamic model created: table=%s, %d columns", table_name, len(mappings))

    try:
        _SCHEMA_FILE.write_text(json.dumps({
            "mappings": mappings,
            "table_name": table_name,
            "needs_pk": needs_pk,
            "entity_column": entity_column,
        }))
    except Exception as e:
        logger.warning("Failed to save schema to disk: %s", e)


_JOIN_ROWID_COLUMN = "_rowid"  # must match joins.ROWID_COLUMN


def set_active_join_mapping(
    mappings: list[dict], select_sql: str, resource_id: str,
    table_name: str = "joined", entity_column: str | None = None,
):
    """Map the dynamic model to a joined Aurora SELECT instead of a single
    physical table (BENCH-10344 J09). The join is read-only: __table__ is a
    subquery over the join's SELECT, not a real table, so no writes/DDL are
    possible through it — queries flow through the same ORM path as a
    single-table Aurora source (_apply_filters, get_filters, get_counts all
    work unchanged against it, including the text-backed-numeric CAST path,
    since that keys off storage_type in the mapping, not the source table).

    select_sql's first column must be the synthetic row-id joins.py adds
    (ROW_NUMBER() OVER ()). A real join column can't serve as the ORM primary
    key: in a 1:N join no column — not even the "count distinct by" entity
    column — is guaranteed unique per output row, and SQLAlchemy's identity
    map silently drops rows that share a mapped "primary key"."""
    global _active_mapping, _active_model, _active_table_name, _pk_name, _entity_column
    _active_mapping = mappings
    _active_table_name = table_name
    _entity_column = entity_column

    DynamicBase.metadata.clear()

    def _sa_type(m: dict):
        return Text if m.get("storage_type") in TEXT_STORAGE_TYPES else SA_TYPE_MAP.get(m["type"], Text)

    sa_columns = [sa_column(_JOIN_ROWID_COLUMN, Integer)]
    sa_columns += [sa_column(m["column"], _sa_type(m)) for m in mappings]
    subq = text(select_sql).columns(*sa_columns).subquery(table_name)

    _pk_name = _JOIN_ROWID_COLUMN
    attrs = {
        "__table__": subq,
        "__mapper_args__": {"primary_key": [subq.c[_JOIN_ROWID_COLUMN]]},
    }
    _active_model = type("DynamicJoinRow", (DynamicBase,), attrs)
    logger.info("Dynamic join model created: %d columns", len(mappings))

    try:
        _SCHEMA_FILE.write_text(json.dumps({
            "mappings": mappings,
            "table_name": table_name,
            "needs_pk": False,
            "entity_column": entity_column,
            "join": {"select_sql": select_sql, "resource_id": resource_id},
        }))
    except Exception as e:
        logger.warning("Failed to save join schema to disk: %s", e)


def get_active_mapping() -> list[dict] | None:
    return _active_mapping


_pk_name: str = "id"


def get_active_model() -> type | None:
    return _active_model


def get_pk_name() -> str:
    return _pk_name


def get_categorical_filters() -> list[str]:
    if not _active_mapping:
        return []
    return [m["column"] for m in _active_mapping if m["filter"] == "categorical"]


def get_range_filters() -> list[str]:
    if not _active_mapping:
        return []
    return [m["column"] for m in _active_mapping if m["filter"] == "range"]


def get_all_columns() -> list[str]:
    if not _active_mapping:
        return []
    return [m["column"] for m in _active_mapping]


def get_mapping_for_column(column: str) -> dict | None:
    if not _active_mapping:
        return None
    for m in _active_mapping:
        if m["column"] == column:
            return m
    return None


def get_entity_column() -> str | None:
    return _entity_column


def load_schema_from_disk():
    if not _SCHEMA_FILE.exists():
        return
    try:
        data = json.loads(_SCHEMA_FILE.read_text())
        join = data.get("join")
        if join:
            set_active_join_mapping(
                data["mappings"], join["select_sql"], join["resource_id"],
                table_name=data.get("table_name", "joined"),
                entity_column=data.get("entity_column"),
            )
        else:
            set_active_mapping(
                data["mappings"],
                table_name=data.get("table_name", "data"),
                needs_pk=data.get("needs_pk", True),
                entity_column=data.get("entity_column"),
            )
        logger.info("Restored schema from disk: %d columns", len(data["mappings"]))
    except Exception as e:
        logger.warning("Failed to load schema from disk: %s", e)


def clear_schema():
    global _active_mapping, _active_model, _active_table_name, _entity_column
    _active_mapping = None
    _active_model = None
    _active_table_name = None
    _entity_column = None
    DynamicBase.metadata.clear()
    _SCHEMA_FILE.unlink(missing_ok=True)
    logger.info("Schema cleared")
