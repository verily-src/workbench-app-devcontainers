import logging

from sqlalchemy import Boolean, Column, Date, Float, Integer, Text
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)

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


def set_active_mapping(mappings: list[dict], table_name: str = "data"):
    global _active_mapping, _active_model, _active_table_name
    _active_mapping = mappings
    _active_table_name = table_name

    DynamicBase.metadata.clear()

    global _pk_name
    user_columns = {m["column"] for m in mappings}
    _pk_name = "_rowid" if "id" in user_columns else "id"

    attrs: dict = {
        "__tablename__": table_name,
        _pk_name: Column(Integer, primary_key=True),
    }
    for m in mappings:
        sa_type = SA_TYPE_MAP.get(m["type"], Text)
        attrs[m["column"]] = Column(sa_type)

    _active_model = type("DynamicRow", (DynamicBase,), attrs)
    logger.info("Dynamic model created: table=%s, %d columns", table_name, len(mappings))


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
