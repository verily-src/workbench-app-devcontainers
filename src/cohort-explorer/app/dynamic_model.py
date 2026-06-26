import json
import logging
from pathlib import Path

from sqlalchemy import Boolean, Column, Date, Float, Integer, Text
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

_active_mapping: list[dict] | None = None
_active_model: type | None = None
_active_table_name: str | None = None


class DynamicBase(DeclarativeBase):
    pass


def set_active_mapping(mappings: list[dict], table_name: str = "data", needs_pk: bool = True):
    global _active_mapping, _active_model, _active_table_name, _pk_name
    _active_mapping = mappings
    _active_table_name = table_name

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
        sa_type = SA_TYPE_MAP.get(m["type"], Text)
        is_pk = not needs_pk and m["column"] == _pk_name
        attrs[m["column"]] = Column(sa_type, primary_key=is_pk)

    _active_model = type("DynamicRow", (DynamicBase,), attrs)
    logger.info("Dynamic model created: table=%s, %d columns", table_name, len(mappings))

    try:
        _SCHEMA_FILE.write_text(json.dumps({
            "mappings": mappings,
            "table_name": table_name,
            "needs_pk": needs_pk,
        }))
    except Exception as e:
        logger.warning("Failed to save schema to disk: %s", e)


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


def get_visible_columns() -> list[str]:
    if not _active_mapping:
        return []
    return [m["column"] for m in _active_mapping if m["filter"] != "none"]


def get_mapping_for_column(column: str) -> dict | None:
    if not _active_mapping:
        return None
    for m in _active_mapping:
        if m["column"] == column:
            return m
    return None


def load_schema_from_disk():
    if not _SCHEMA_FILE.exists():
        return
    try:
        data = json.loads(_SCHEMA_FILE.read_text())
        set_active_mapping(
            data["mappings"],
            table_name=data.get("table_name", "data"),
            needs_pk=data.get("needs_pk", True),
        )
        logger.info("Restored schema from disk: %d columns", len(data["mappings"]))
    except Exception as e:
        logger.warning("Failed to load schema from disk: %s", e)


def clear_schema():
    global _active_mapping, _active_model, _active_table_name
    _active_mapping = None
    _active_model = None
    _active_table_name = None
    DynamicBase.metadata.clear()
    _SCHEMA_FILE.unlink(missing_ok=True)
    logger.info("Schema cleared")
