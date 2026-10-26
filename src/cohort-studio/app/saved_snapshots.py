from __future__ import annotations

import copy
import json
from datetime import datetime

from sql_utils import statement as text

import materialized_sources
from source_models import source_dict

RECIPE_STATUS = "Only same-resource PostgreSQL joins are snapshotted."
UNSUPPORTED_JOIN_STATUS = "This join cannot be compiled as a full-source PostgreSQL snapshot."


def _walk_refs(value):
    if isinstance(value, dict):
        if value.get("kind") == "materialized":
            resource_id = value.get("resource_id")
            materialized_id = value.get("materialized_id")
            if isinstance(resource_id, str) and isinstance(materialized_id, str):
                yield resource_id, materialized_id
        for child in value.values():
            yield from _walk_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_refs(child)


def _state_refs(state: dict, resource_id: str | None = None) -> set[str]:
    refs = set()
    for rid, materialized_id in _walk_refs(state):
        if resource_id is None or rid == resource_id:
            refs.add(materialized_id)
    return refs


def _root_snapshot_refs(state: dict, resource_id: str) -> set[str]:
    refs = set()
    for dataset in state.get("datasets", []):
        source = dataset.get("source", {})
        if (source.get("kind") == "materialized"
                and source.get("resource_id") == resource_id
                and isinstance(source.get("materialized_id"), str)):
            refs.add(source["materialized_id"])
    return refs


def _leaf_sources(source: dict):
    kind = source.get("kind")
    if kind == "join":
        yield from _leaf_sources(source.get("base") or {})
        for step in source.get("steps", []):
            yield from _leaf_sources(step.get("source") or {})
    elif kind == "derived":
        yield from _leaf_sources(source.get("base") or {})
    else:
        yield source


def is_same_aurora_join(source: dict, resource_id: str) -> bool:
    if not isinstance(source, dict):
        return False
    has_join = False

    def visit(node: dict) -> bool:
        nonlocal has_join
        kind = node.get("kind")
        if kind == "join":
            has_join = True
            return (visit(node.get("base") or {})
                    and all(visit(step.get("source") or {})
                            for step in node.get("steps", [])))
        if kind == "derived":
            return visit(node.get("base") or {})
        return (kind in {"aurora", "postgres", "sql", "materialized", "omop_cohort"}
                and node.get("resource_id") == resource_id)

    valid = visit(source)
    return valid and has_join


def has_join_source(state: dict, resource_id: str) -> bool:
    return any(is_same_aurora_join(dataset.get("source", {}), resource_id)
               for dataset in state.get("datasets", []))


def has_materialized_source(state: dict, resource_id: str) -> bool:
    return bool(_root_snapshot_refs(state, resource_id))


def _resource_lock(conn, resource_id: str) -> None:
    conn.exec_driver_sql("SET LOCAL lock_timeout = 3000")
    conn.exec_driver_sql("SET LOCAL statement_timeout = 300000")
    conn.execute(text(
        "SELECT pg_catalog.pg_advisory_xact_lock "
        "(pg_catalog.hashtextextended(:lock_key, 0))"),
        {"lock_key": f"cohort-studio-saved-snapshots:{resource_id}"})


def _public_path(conn) -> None:
    conn.exec_driver_sql("SET LOCAL search_path = public, pg_catalog")


def _get_state(conn, table, name: str, for_update: bool = False) -> dict | None:
    query = table.select().with_only_columns(table.c.state).where(table.c.name == name)
    if for_update:
        query = query.with_for_update()
    value = conn.execute(query).scalar_one_or_none()
    return json.loads(value) if value is not None else None


def _put_state(conn, views_module, resource_id: str, name: str, state: dict) -> None:
    table = views_module.view_table
    conn.execute(views_module.delete(table).where(table.c.name == name))
    conn.execute(views_module.insert(table).values(
        name=name, created_by=views_module._actor(), state=json.dumps(state)))


def _write_state(conn, views_module, resource_id: str, name: str,
                 state: dict, old_state: dict | None) -> set[str]:
    old_refs = _state_refs(old_state or {}, resource_id)
    _put_state(conn, views_module, resource_id, name, state)
    return old_refs


def _saved_refs(conn, views_module, resource_id: str) -> set[str]:
    _public_path(conn)
    rows = conn.execute(views_module.select(views_module.view_table.c.state)).scalars()
    refs = set()
    for raw in rows:
        refs.update(_state_refs(json.loads(raw), resource_id))
    return refs


def _open_refs(resource_id: str) -> set[str]:
    import datasets
    with datasets._lock:
        return set().union(*(
            _state_refs(dataset.get("source_ref") or {}, resource_id)
            for dataset in datasets._store.values()))


def _dependency_order(conn, resource_id: str, ids: set[str]) -> list[str]:
    dependencies = {}
    for materialized_id in ids:
        row = conn.execute(text(
            "SELECT recipe::text FROM public._studio_materialized_sources "
            "WHERE resource_id = :resource_id AND materialized_id = :id"),
            {"resource_id": resource_id, "id": materialized_id}).scalar_one_or_none()
        dependencies[materialized_id] = (
            _state_refs(json.loads(row), resource_id) & ids if row else set())
    depended_on = set().union(*dependencies.values()) if ids else set()
    ordered = []
    visiting = set()
    visited = set()

    def visit(materialized_id: str) -> None:
        if materialized_id in visited:
            return
        if materialized_id in visiting:
            raise ValueError("Materialized source dependency cycle was found.")
        visiting.add(materialized_id)
        for dependency in sorted(dependencies.get(materialized_id, set())):
            visit(dependency)
        visiting.remove(materialized_id)
        visited.add(materialized_id)
        ordered.append(materialized_id)

    for materialized_id in sorted(ids - depended_on):
        visit(materialized_id)
    if visited != ids:
        raise ValueError("Materialized source dependency cycle was found.")
    return ordered


def _cleanup_unshared_locked(conn, views_module, resource_id: str,
                             candidates: set[str]) -> None:
    saved = _saved_refs(conn, views_module, resource_id)
    opened = _open_refs(resource_id)
    registry_exists = conn.exec_driver_sql(
            "SELECT pg_catalog.to_regclass('public._studio_materialized_sources') "
            "IS NOT NULL").scalar_one()
    if not registry_exists:
        return
    _public_path(conn)
    all_ids = set(conn.execute(text(
        "SELECT materialized_id FROM public._studio_materialized_sources "
        "WHERE resource_id = :resource_id"),
        {"resource_id": resource_id}).scalars())
    retained = saved | opened
    queue = list(retained)
    dependency_rows = {}
    while queue:
        materialized_id = queue.pop()
        if materialized_id in dependency_rows:
            continue
        row = conn.execute(text(
            "SELECT recipe::text FROM public._studio_materialized_sources "
            "WHERE resource_id = :resource_id AND materialized_id = :id"),
            {"resource_id": resource_id, "id": materialized_id}).scalar_one_or_none()
        if row is None:
            dependency_rows[materialized_id] = set()
            continue
        dependencies = _state_refs(json.loads(row), resource_id)
        dependency_rows[materialized_id] = dependencies
        queue.extend(dependencies - retained)
        retained.update(dependencies)
    remaining = (candidates | all_ids) - retained
    for materialized_id in reversed(_dependency_order(conn, resource_id, remaining)):
        materialized_sources.drop(conn, resource_id, materialized_id)


def _cleanup_unshared(conn, views_module, resource_id: str,
                      candidates: set[str]) -> None:
    with materialized_sources.operation_lock:
        _cleanup_unshared_locked(conn, views_module, resource_id, candidates)


def _snapshot_meta(metadata: dict) -> dict:
    return {"status": "materialized", "rows": metadata["rows"],
            "created_at": metadata["created_at"],
            "refreshed_at": metadata["refreshed_at"],
            "refresh_mode": "blocking"}


def portable_recipe_state(state: dict) -> dict:
    import views

    def expand(node: dict, visiting: set[tuple[str, str]]) -> dict:
        source = source_dict(node)
        kind = source["kind"]
        if kind == "materialized":
            key = (source["resource_id"], source["materialized_id"])
            if key in visiting:
                raise ValueError("Materialized source dependency cycle was found.")
            with views._engine(key[0]).begin() as conn:
                metadata = materialized_sources.resolve(conn, *key)
            recipe = expand(metadata["recipe"], visiting | {key})
            if source.get("settings"):
                recipe["settings"] = source["settings"]
            return source_dict(recipe)
        if kind == "join":
            source["base"] = expand(source["base"], visiting)
            for step in source["steps"]:
                step["source"] = expand(step["source"], visiting)
        elif kind == "derived":
            source["base"] = expand(source["base"], visiting)
        return source_dict(source)

    result = copy.deepcopy(state)
    for dataset in result.get("datasets", []):
        dataset["source"] = expand(dataset["source"], set())
    return mark_recipe_status(result)


def mark_recipe_status(state: dict) -> dict:
    result = copy.deepcopy(state)
    for dataset in result.get("datasets", []):
        source = dataset.get("source") or {}
        if source.get("kind") == "materialized":
            dataset["snapshot"] = {"status": "materialized_ref"}
        else:
            dataset["snapshot"] = {"status": "recipe", "reason": RECIPE_STATUS}
    return result


def _summary(state: dict, resource_id: str, name: str) -> dict:
    refs = _root_snapshot_refs(state, resource_id)
    dates = [dataset.get("snapshot", {}).get("refreshed_at")
             for dataset in state.get("datasets", [])
             if (dataset.get("source", {}).get("kind") == "materialized"
                 and dataset.get("source", {}).get("resource_id") == resource_id
                 and dataset.get("snapshot", {}).get("refreshed_at"))]
    oldest = None
    if dates:
        oldest = min(dates, key=lambda value: datetime.fromisoformat(value))
    return {"name": name, "materialized_sources": len(refs),
            "refreshed_at": oldest,
            "refresh_mode": "blocking" if refs else None}


def save(resource_id: str, name: str, state: dict, compile_source,
         progress=None) -> dict:
    import views

    views._validate(name)
    engine = views._engine(resource_id)
    if engine.dialect.name != "postgresql":
        raise ValueError("Saved snapshots require a PostgreSQL datasource.")
    prepared = copy.deepcopy(state)
    datasets = prepared.get("datasets", [])
    total = len(datasets)
    compiled_sources = {}
    for index, dataset in enumerate(datasets):
        source = source_dict(dataset.get("source") or {})
        dataset["source"] = source
        if (source.get("kind") != "materialized"
                and is_same_aurora_join(source, resource_id)):
            compiled_sources[index] = compile_source(resource_id, source)
    candidates: set[str] = set()
    with engine.begin() as conn:
        _resource_lock(conn, resource_id)
        _public_path(conn)
        old_state = _get_state(conn, views.view_table, name, for_update=True)
        candidates.update(_state_refs(old_state or {}, resource_id))
        for index, dataset in enumerate(datasets, start=1):
            source = dataset.get("source") or {}
            if source.get("kind") == "materialized":
                if source.get("resource_id") != resource_id:
                    dataset["snapshot"] = {"status": "recipe", "reason": RECIPE_STATUS}
                else:
                    resolved = materialized_sources.resolve(
                        conn, resource_id, source.get("materialized_id"))
                    metadata = resolved
                    source_ref = dict(metadata["source_ref"])
                    if source.get("settings"):
                        source_ref["settings"] = source["settings"]
                    dataset["source"] = source_ref
                    dataset["snapshot"] = _snapshot_meta(metadata)
                    candidates.add(source_ref["materialized_id"])
            elif is_same_aurora_join(source, resource_id):
                live_source = compiled_sources.get(index - 1)
                if not isinstance(live_source, dict):
                    dataset["snapshot"] = {"status": "recipe",
                                           "reason": UNSUPPORTED_JOIN_STATUS}
                    if progress is not None:
                        progress(index)
                    continue
                metadata = materialized_sources.create(
                    conn, resource_id, live_source, source)
                source_ref = dict(metadata["source_ref"])
                if source.get("settings"):
                    source_ref["settings"] = source["settings"]
                dataset["source"] = source_ref
                dataset["snapshot"] = _snapshot_meta(metadata)
                candidates.add(source_ref["materialized_id"])
            else:
                dataset["snapshot"] = {"status": "recipe", "reason": RECIPE_STATUS}
            if progress is not None:
                progress(index)
        _public_path(conn)
        _put_state(conn, views, resource_id, name, prepared)
        _cleanup_unshared(conn, views, resource_id, candidates)
    return _summary(prepared, resource_id, name)


def _load_for_update(conn, views_module, resource_id: str, name: str) -> dict:
    _public_path(conn)
    state = _get_state(conn, views_module.view_table, name, for_update=True)
    if state is None:
        raise ValueError(f"Saved view {name!r} was not found.")
    return state


def materialized_count(resource_id: str, name: str) -> int:
    import views

    engine = views._engine(resource_id)
    with engine.begin() as conn:
        _resource_lock(conn, resource_id)
        state = _load_for_update(conn, views, resource_id, name)
        return len(_root_snapshot_refs(state, resource_id))


def refresh(resource_id: str, name: str, progress=None) -> dict:
    import views

    engine = views._engine(resource_id)
    if engine.dialect.name != "postgresql":
        raise ValueError("Saved snapshots require a PostgreSQL datasource.")
    with engine.begin() as conn:
        _resource_lock(conn, resource_id)
        state = _load_for_update(conn, views, resource_id, name)
        datasets = state.get("datasets", [])
        root_ids = _root_snapshot_refs(state, resource_id)
        if not root_ids:
            raise ValueError("This saved view has no materialized snapshots to refresh.")
        target_ids = set(root_ids)
        queue = list(root_ids)
        while queue:
            materialized_id = queue.pop()
            row = conn.execute(text(
                "SELECT recipe::text FROM public._studio_materialized_sources "
                "WHERE resource_id = :resource_id AND materialized_id = :id"),
                {"resource_id": resource_id, "id": materialized_id}).scalar_one_or_none()
            if row is None:
                continue
            dependencies = _state_refs(json.loads(row), resource_id) - target_ids
            target_ids.update(dependencies)
            queue.extend(dependencies)
        metadata = {}
        for index, materialized_id in enumerate(
                _dependency_order(conn, resource_id, target_ids), start=1):
            metadata[materialized_id] = materialized_sources.refresh(
                conn, resource_id, materialized_id)
            if progress is not None:
                progress(index)
        for dataset in datasets:
            source = dataset.get("source") or {}
            materialized_id = source.get("materialized_id")
            if source.get("kind") == "materialized" and materialized_id in metadata:
                dataset["snapshot"] = _snapshot_meta(metadata[materialized_id])
        _public_path(conn)
        _put_state(conn, views, resource_id, name, state)
    return _summary(state, resource_id, name)


def replace_recipe(resource_id: str, name: str, state: dict) -> None:
    import views

    views._validate(name)
    engine = views._engine(resource_id)
    prepared = mark_recipe_status(state)
    with engine.begin() as conn:
        _resource_lock(conn, resource_id)
        _public_path(conn)
        old_state = _get_state(conn, views.view_table, name, for_update=True)
        old_refs = _state_refs(old_state or {}, resource_id)
        _put_state(conn, views, resource_id, name, prepared)
        _cleanup_unshared(conn, views, resource_id, old_refs)


def delete_saved_view(resource_id: str, name: str) -> None:
    import views

    engine = views._engine(resource_id)
    with engine.begin() as conn:
        _resource_lock(conn, resource_id)
        _public_path(conn)
        old_state = _get_state(conn, views.view_table, name, for_update=True)
        if old_state is None:
            _cleanup_unshared(conn, views, resource_id, set())
            return
        old_refs = _state_refs(old_state, resource_id)
        conn.execute(views.delete(views.view_table).where(
            views.view_table.c.name == name))
        _cleanup_unshared(conn, views, resource_id, old_refs)


def list_status(conn, resource_id: str, state: dict) -> dict:
    ids = _root_snapshot_refs(state, resource_id)
    if not ids:
        return {"materialized_sources": 0, "refreshed_at": None,
                "refresh_mode": None}
    if not conn.exec_driver_sql(
            "SELECT pg_catalog.to_regclass('public._studio_materialized_sources') "
            "IS NOT NULL").scalar_one():
        return {"materialized_sources": 0, "refreshed_at": None,
                "refresh_mode": None}
    params = {f"id_{i}": value for i, value in enumerate(sorted(ids))}
    placeholders = ", ".join(f":{key}" for key in params)
    rows = conn.execute(text(
        "SELECT materialized_id, refreshed_at FROM public._studio_materialized_sources "
        f"WHERE resource_id = :resource_id AND materialized_id IN ({placeholders})"),
        {"resource_id": resource_id, **params}).all()
    dates = [row[1] for row in rows]
    oldest = min(dates).isoformat() if dates else None
    return {"materialized_sources": len(rows), "refreshed_at": oldest,
            "refresh_mode": "blocking" if rows else None}
