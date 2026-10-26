import uuid

import pytest
from sqlalchemy import text

import live_query
import materialized_sources


def _recipe(left, right):
    return {
        "kind": "join",
        "base": {"kind": "aurora", "resource_id": "omopdb",
                 "schema": "public", "table": left},
        "steps": [{
            "source": {"kind": "aurora", "resource_id": "omopdb",
                       "schema": "public", "table": right},
            "how": "inner", "conditions": [{"left": "person_id",
                                               "op": "=", "right": "person_id"}],
            "alias": "samples",
        }],
    }


def test_materialize_refresh_open_and_drop_full_source(engine, monkeypatch):
    suffix = uuid.uuid4().hex[:10]
    people = f"materialized_people_{suffix}"
    samples = f"materialized_samples_{suffix}"
    with engine.begin() as conn:
        conn.execute(text(
            f'CREATE TABLE public."{people}" '
            "(person_id integer PRIMARY KEY, person_label text)"))
        conn.execute(text(
            f'CREATE TABLE public."{samples}" '
            "(person_id integer, sample_label text)"))
        conn.execute(text(
            f'INSERT INTO public."{people}" VALUES '
            "(1, 'one'), (2, 'two'), (3, 'three')"))
        conn.execute(text(
            f'INSERT INTO public."{samples}" VALUES '
            "(1, 'O''Reilly'), (2, 'second'), (3, 'third')"))
    live_source = {
        "resource_id": "omopdb",
        "sql": (f'SELECT p.person_id, p.person_label, '
                's.sample_label AS "samples → sample_label" '
                f'FROM public."{people}" p JOIN public."{samples}" s '
                "ON p.person_id = s.person_id "
                "WHERE p.person_id > :minimum AND s.sample_label <> :excluded "
                "ORDER BY p.person_id"),
        "params": {"minimum": 0, "excluded": "not 'present'"},
        "columns": {"person_id": "person_id", "person_label": "person_label",
                    "samples → sample_label": "samples → sample_label"},
    }
    recipe = _recipe(people, samples)
    monkeypatch.setattr(live_query.db, "get_engine_for_resource",
                        lambda _resource_id: engine)
    metadata = None
    try:
        with engine.begin() as conn:
            metadata = materialized_sources.create(
                conn, "omopdb", live_source, recipe)
        assert metadata["rows"] == 3
        assert metadata["created_at"] == metadata["refreshed_at"]
        assert list(metadata["columns"].values()) == ["_c0", "_c1", "_c2"]
        ref = metadata["source_ref"]
        assert ref["kind"] == "materialized"
        assert set(ref) == {"kind", "resource_id", "materialized_id"}
        with engine.begin() as conn:
            with pytest.raises(ValueError, match="not found"):
                materialized_sources.resolve(conn, "another-resource",
                                             ref["materialized_id"])

        with engine.begin() as conn:
            resolved = materialized_sources.resolve(
                conn, ref["resource_id"], ref["materialized_id"])
        frame = live_query.fetch_frame(resolved["live_source"], max_rows=10)
        assert sorted(frame.to_dict(orient="records"), key=lambda row: row["person_id"]) == [
            {"person_id": 1, "person_label": "one",
             "samples → sample_label": "O'Reilly"},
            {"person_id": 2, "person_label": "two",
             "samples → sample_label": "second"},
            {"person_id": 3, "person_label": "three",
             "samples → sample_label": "third"},
        ]

        with engine.begin() as conn:
            conn.execute(text(f'INSERT INTO public."{people}" VALUES (4, \'four\')'))
            conn.execute(text(f'INSERT INTO public."{samples}" VALUES (4, \'fourth\')'))
        with engine.begin() as conn:
            metadata = materialized_sources.refresh(
                conn, ref["resource_id"], ref["materialized_id"])
        assert metadata["rows"] == 4
        with engine.begin() as conn:
            resolved = materialized_sources.resolve(
                conn, ref["resource_id"], ref["materialized_id"])
        refreshed = live_query.fetch_frame(resolved["live_source"], max_rows=10)
        assert sorted(refreshed["person_id"].tolist()) == [1, 2, 3, 4]

        with engine.begin() as conn:
            materialized_sources.drop(conn, ref["resource_id"], ref["materialized_id"])
        with engine.connect() as conn:
            assert conn.execute(text("SELECT to_regclass(:name)"), {
                "name": f'public."{metadata["physical_name"]}"',
            }).scalar_one() is None
    finally:
        if metadata is not None:
            ref = metadata["source_ref"]
            with engine.begin() as conn:
                materialized_sources.drop(
                    conn, ref["resource_id"], ref["materialized_id"])
        with engine.begin() as conn:
            conn.execute(text(f'DROP TABLE IF EXISTS public."{people}"'))
            conn.execute(text(f'DROP TABLE IF EXISTS public."{samples}"'))


@pytest.mark.parametrize("ref", [
    None,
    {"resource_id": "omopdb", "materialized_id": "../public.person"},
    {"resource_id": "", "materialized_id": "a" * 32},
])
def test_materialized_source_refs_need_server_generated_ids(ref):
    with pytest.raises(ValueError):
        materialized_sources._identifier(
            ref.get("resource_id") if isinstance(ref, dict) else None,
            ref.get("materialized_id") if isinstance(ref, dict) else None)


def test_materialization_rejects_view_and_custom_type_inputs(engine):
    suffix = uuid.uuid4().hex[:8]
    table = f"materialized_guard_{suffix}"
    other = f"materialized_guard_other_{suffix}"
    view = f"materialized_guard_view_{suffix}"
    enum = f"materialized_guard_state_{suffix}"
    typed = f"materialized_guard_typed_{suffix}"
    with engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE TABLE public."{table}" (person_id integer)')
        conn.exec_driver_sql(f'CREATE TABLE public."{other}" (person_id integer)')
        conn.exec_driver_sql(
            f'CREATE VIEW public."{view}" AS SELECT person_id FROM public."{table}"')
        conn.exec_driver_sql(
            f'CREATE TYPE public."{enum}" AS ENUM (\'one\', \'two\')')
        conn.exec_driver_sql(
            f'CREATE TABLE public."{typed}" (person_id integer, state public."{enum}")')
    try:
        source = {
            "resource_id": "omopdb",
            "sql": (f'SELECT a.person_id FROM public."{view}" a '
                    f'JOIN public."{other}" b USING (person_id)'),
            "columns": {"person_id": "person_id"},
        }
        recipe = _recipe(view, other)
        with engine.begin() as conn:
            with pytest.raises(ValueError, match="must be a table"):
                materialized_sources.create(conn, "omopdb", source, recipe)

        with engine.begin() as conn:
            conn.exec_driver_sql(
                f'ALTER TABLE public."{other}" ENABLE ROW LEVEL SECURITY')
        source["sql"] = (f'SELECT a.person_id FROM public."{table}" a '
                         f'JOIN public."{other}" b USING (person_id)')
        recipe = _recipe(table, other)
        with engine.begin() as conn:
            with pytest.raises(ValueError, match="row-level security"):
                materialized_sources.create(conn, "omopdb", source, recipe)

        source["sql"] = (f'SELECT a.person_id, a.state FROM public."{typed}" a '
                         f'JOIN public."{table}" b USING (person_id)')
        recipe = _recipe(typed, table)
        with engine.begin() as conn:
            with pytest.raises(ValueError, match="unsupported column type"):
                materialized_sources.create(conn, "omopdb", source, recipe)
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql(f'DROP VIEW IF EXISTS public."{view}"')
            conn.exec_driver_sql(f'DROP TABLE IF EXISTS public."{typed}"')
            conn.exec_driver_sql(f'DROP TYPE IF EXISTS public."{enum}"')
            conn.exec_driver_sql(f'DROP TABLE IF EXISTS public."{other}"')
            conn.exec_driver_sql(f'DROP TABLE IF EXISTS public."{table}"')


def test_materialized_view_and_registry_roll_back_together(engine):
    suffix = uuid.uuid4().hex[:8]
    left = f"materialized_rollback_left_{suffix}"
    right = f"materialized_rollback_right_{suffix}"
    with engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE TABLE public."{left}" (person_id integer)')
        conn.exec_driver_sql(f'CREATE TABLE public."{right}" (person_id integer)')
        conn.exec_driver_sql(f'INSERT INTO public."{left}" VALUES (1)')
        conn.exec_driver_sql(f'INSERT INTO public."{right}" VALUES (1)')
    recipe = _recipe(left, right)
    source = {"resource_id": "omopdb",
              "sql": (f'SELECT l.person_id FROM public."{left}" l '
                      f'JOIN public."{right}" r USING (person_id)'),
              "params": {}, "columns": {"person_id": "person_id"}}
    created = {}
    try:
        with pytest.raises(RuntimeError, match="rollback the save"):
            with engine.begin() as conn:
                created.update(materialized_sources.create(
                    conn, "omopdb", source, recipe))
                raise RuntimeError("rollback the save")
        materialized_id = created["materialized_id"]
        with engine.begin() as conn:
            physical = conn.execute(text("SELECT pg_catalog.to_regclass(:name)"), {
                "name": f'public."{created["physical_name"]}"'}).scalar_one()
            registry_exists = conn.execute(text(
                "SELECT pg_catalog.to_regclass(:name) IS NOT NULL"), {
                    "name": f"public.{materialized_sources.REGISTRY_TABLE}"}).scalar_one()
            count = 0
            if registry_exists:
                count = conn.execute(text(
                    f"SELECT count(*) FROM public.{materialized_sources._q(materialized_sources.REGISTRY_TABLE)} "
                    "WHERE materialized_id = :id"), {"id": materialized_id}).scalar_one()
        assert physical is None
        assert count == 0
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql(f'DROP TABLE IF EXISTS public."{left}"')
            conn.exec_driver_sql(f'DROP TABLE IF EXISTS public."{right}"')
