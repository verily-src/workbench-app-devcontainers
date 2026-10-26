import internal_data
import db as workbench
import postgres_sources


def __getattr__(name):
    return getattr(workbench, name)


def get_engine_for_resource(resource_id):
    if resource_id.startswith("postgres:"):
        return postgres_sources.engine(resource_id)
    return workbench.get_engine_for_resource(resource_id)


def list_aurora_resources(wait=False):
    existing = workbench.list_aurora_resources(wait=True) if wait else workbench.list_aurora_resources()
    return existing + postgres_sources.resources()


def list_aurora_tables(resource_id):
    if not resource_id.startswith("postgres:"):
        return [t for t in workbench.list_aurora_tables(resource_id)
                if not internal_data.is_internal(t.get("schema"), t.get("table") or t["name"])]
    import queries
    return queries.list_tables(get_engine_for_resource(resource_id))


def fetch_aurora_table(resource_id, table, cap):
    if not resource_id.startswith("postgres:"):
        return workbench.fetch_aurora_table(resource_id, table, cap)
    import queries
    return queries.fetch_table(get_engine_for_resource(resource_id), table, cap)


list_aurora_tables.invalidate = workbench.list_aurora_tables.invalidate
fetch_aurora_table.invalidate = workbench.fetch_aurora_table.invalidate
