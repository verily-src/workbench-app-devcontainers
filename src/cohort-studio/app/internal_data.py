INTERNAL_TABLES = {"_agent_turn", "_lineage_event", "_lineage_edge", "_studio_views", "_studio_materialized_sources"}


def is_internal(schema: str | None, table: str = "") -> bool:
    return (str(schema or "").casefold().startswith("_studio_")
            or table.casefold().startswith("_studio_mv_")
            or table.casefold() in INTERNAL_TABLES)


def require_public_source(schema: str | None, table: str):
    pieces = table.replace('"', '').split('.')
    if is_internal(schema, pieces[-1]) or (len(pieces) > 1 and is_internal(pieces[-2], pieces[-1])):
        raise ValueError("Internal application data is not available as a datasource.")
