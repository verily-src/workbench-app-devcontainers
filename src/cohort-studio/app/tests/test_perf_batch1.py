import threading
import time
import uuid

import pandas as pd
import pytest
from sqlalchemy import event

import datasets
import db
import joins
import live_query


@pytest.fixture
def events_table(engine, monkeypatch):
    """1,000 rows with no primary key, a btree index on a low-cardinality
    integer column, and a jsonb column (orderable) plus a json one (not)."""
    name = f"perf_events_{uuid.uuid4().hex[:10]}"
    monkeypatch.setattr(live_query.db, "get_engine_for_resource", lambda _rid: engine)
    live_query._order_cache.clear()
    with engine.begin() as conn:
        conn.exec_driver_sql(
            f'CREATE TABLE public."{name}" (concept_id integer, quantity integer, '
            'label text, attrs json)')
        conn.exec_driver_sql(
            f"INSERT INTO public.\"{name}\" SELECT i %% 7, i %% 13, 'row-' || i, "
            f"json_build_object('i', i) FROM generate_series(1, 1000) i")
        conn.exec_driver_sql(f'CREATE INDEX ON public."{name}" (concept_id)')
        conn.exec_driver_sql(f'ANALYZE public."{name}"')
    source = {"resource_id": name, "sql": f'SELECT * FROM public."{name}"',
              "columns": {"concept_id": "concept_id", "quantity": "quantity",
                          "label": "label", "attrs": "attrs"}}
    yield name, source
    live_query._order_cache.clear()
    with engine.begin() as conn:
        conn.exec_driver_sql(f'DROP TABLE public."{name}"')


def _capture(engine):
    statements = []

    def hook(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)
    event.listen(engine, "before_cursor_execute", hook)
    return statements, lambda: event.remove(engine, "before_cursor_execute", hook)


def test_default_order_uses_native_tie_breakers_and_pages_without_gaps(engine, events_table):
    name, source = events_table
    with engine.begin() as conn:
        order = live_query._primary_key_order(conn, source)
    assert order == 'live."concept_id", live."quantity", live."label", (live."attrs")::text'
    assert "to_jsonb" not in order
    for sort in (None, {"column": "quantity", "direction": "desc"}):
        seen = []
        for page in range(10):
            rows = live_query.query(source, [], [], page, 100, refresh=True, sort=sort)["rows"]["data"]
            seen += [row[2] for row in rows]
        assert len(seen) == len(set(seen)) == 1000, sort


def test_default_order_is_memoized(engine, events_table):
    _name, source = events_table
    statements, stop = _capture(engine)
    try:
        for page in range(3):
            live_query.query(source, [], [], page, 10, refresh=True)
    finally:
        stop()
    catalog = [s for s in statements if "pg_catalog.pg_index" in s or "pg_catalog.pg_opclass" in s]
    assert len(catalog) == 3  # pk lookup + index candidates + tie-breaker types, once


def test_integer_filters_compare_natively_and_can_use_the_index(engine, events_table):
    name, source = events_table
    statements, stop = _capture(engine)
    try:
        result = live_query.query(source, [
            {"column": "concept_id", "kind": "categorical", "values": ["3", "5"]},
            {"column": "quantity", "kind": "range", "min": 2.5, "max": 7.9},
        ], [], 0, 5, refresh=True)
    finally:
        stop()
    expected = sum(1 for i in range(1, 1001) if i % 7 in (3, 5) and 3 <= i % 13 <= 7)
    assert result["filtered"] == expected
    counts = next(s for s in statements if s.startswith("SELECT COUNT(*), COUNT(*) FILTER"))
    assert '"concept_id" IN (' in counts and 'CAST("concept_id" AS text)' not in counts
    assert '"quantity" BETWEEN' in counts and "double precision" not in counts
    with engine.begin() as conn:
        conn.exec_driver_sql("SET LOCAL enable_seqscan = off")
        plan = "\n".join(row[0] for row in conn.exec_driver_sql(
            f'EXPLAIN SELECT * FROM public."{name}" WHERE concept_id IN (3, 5)').all())
    assert "Index Cond" in plan


def test_text_values_on_integer_column_fall_back_to_text_and_empty_range_is_false(events_table):
    _name, source = events_table
    where, params = live_query._where(
        [{"column": "concept_id", "kind": "categorical", "values": ["3", "n/a"]},
         {"column": "quantity", "kind": "range", "min": 2.2, "max": 2.8}],
        source["columns"], {"concept_id": 23, "quantity": 23})
    assert 'CAST("concept_id" AS text) IN' in where
    assert "FALSE" in where
    assert params == {"f0_0": "3", "f0_1": "n/a"}


def test_bar_chart_is_one_statement_with_same_counts(engine, events_table):
    _name, source = events_table
    statements, stop = _capture(engine)
    try:
        result = live_query.query(source, [
            {"column": "quantity", "kind": "range", "min": 0, "max": 5},
        ], [{"kind": "bar", "x": "concept_id"}, {"kind": "bar", "x": "label"}],
            0, 1, refresh=True)
    finally:
        stop()
    bars = [s for s in statements if "SUM(COUNT(*)) OVER ()" in s]
    assert len(bars) == 2
    assert not [s for s in statements if s.startswith("SELECT COUNT(*) FROM (") and "IS NOT NULL" in s]
    concept = result["charts"][0]["data"]
    assert {d["category"]: d["all"] for d in concept} == {
        str(k): sum(1 for i in range(1, 1001) if i % 7 == k) for k in range(7)}
    assert {d["category"]: d["selected"] for d in concept} == {
        str(k): sum(1 for i in range(1, 1001) if i % 7 == k and i % 13 <= 5) for k in range(7)}
    label = result["charts"][1]["data"]
    other = next(d for d in label if d["category"] == "Other")
    assert other["all"] == 1000 - live_query.BAR_TOP_N
    assert sum(d["selected"] for d in label) == sum(1 for i in range(1, 1001) if i % 13 <= 5)


def test_profiling_reads_every_range_column_in_one_statement(engine, events_table):
    _name, source = events_table
    statements, stop = _capture(engine)
    try:
        profiles = live_query.profile_columns(source, [
            {"name": "concept_id", "filter_kind": "range"},
            {"name": "quantity", "filter_kind": "range"},
            {"name": "label", "filter_kind": "categorical"},
        ])
    finally:
        stop()
    minmax = [s for s in statements if s.startswith("SELECT MIN(")]
    assert len(minmax) == 1
    assert (profiles[0]["min"], profiles[0]["max"]) == (0.0, 6.0)
    assert (profiles[1]["min"], profiles[1]["max"]) == (0.0, 12.0)
    assert len(profiles[2]["values"]) == live_query.CATEGORICAL_VALUES_LIMIT


def test_concurrent_first_queries_resolve_credentials_once(monkeypatch):
    calls = []

    class Done:
        stdout = "postgresql://u:p@h/db\n"

    def slow_run(args, **kwargs):
        calls.append(args)
        time.sleep(0.2)
        return Done()

    resource = f"res-{uuid.uuid4().hex[:6]}"
    monkeypatch.setattr(db.cloud_cli, "run", slow_run)
    db._conn_string_cache.pop(resource, None)
    results = []
    threads = [threading.Thread(target=lambda: results.append(db.resolve_connection_string(resource)))
               for _ in range(4)]
    db.warm_connection_string(resource)
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert results == ["postgresql://u:p@h/db"] * 4
    assert len(calls) == 1
    db._conn_string_cache.pop(resource, None)


def test_cross_source_join_reports_capped_in_memory_inputs():
    capped = datasets.open_dataset(pd.DataFrame({"person_id": [1, 2, 3], "x": [1, 2, 3]}),
                                   "bq / genotypes", capped=True)
    full = datasets.open_dataset(pd.DataFrame({"person_id": [1, 2], "y": [5, 6]}), "upload / samples")
    try:
        out = joins.run(capped["dataset_id"], [{
            "right_id": full["dataset_id"], "how": "inner", "alias": "s",
            "conditions": [{"left": "person_id", "op": "=", "right": "person_id"}],
            "columns": None}])
        assert out["stats"]["capped_inputs"] == ["bq / genotypes"]
        assert out["stats"].get("complete_source") in (False, None)
        assert any("may be incomplete" in note for note in out["stats"]["notes"])
    finally:
        datasets.close_dataset(capped["dataset_id"])
        datasets.close_dataset(full["dataset_id"])


@pytest.mark.parametrize("lo,hi,expected", [
    (1e20, 2e20, "FALSE"), (-2e20, -1e20, "FALSE"), (2.2, 2.8, "FALSE"),
    (-1e30, 1e30, "BETWEEN"), (1.5, 3.5, "BETWEEN"),
    (2 ** 63 - 1, 2 ** 63 - 1, "BETWEEN"), (-(2 ** 63), -(2 ** 63), "BETWEEN"),
])
def test_integer_range_intersects_the_bigint_domain(lo, hi, expected):
    where, params = live_query._where(
        [{"column": "q", "kind": "range", "min": lo, "max": hi}], {"q": "q"}, {"q": 20})
    assert expected in where
    if expected == "BETWEEN":
        assert live_query._INT64_MIN <= params["f0_lo"] <= params["f0_hi"] <= live_query._INT64_MAX


def test_profiling_json_scalar_column_as_categorical(engine, events_table):
    _name, source = events_table
    profiles = live_query.profile_columns(source, [{"name": "attrs", "filter_kind": "categorical"}])
    assert len(profiles[0]["values"]) == live_query.CATEGORICAL_VALUES_LIMIT


def test_paging_and_filter_changes_reuse_cached_aggregates(engine, events_table, monkeypatch):
    import query_cache
    monkeypatch.setenv("STUDIO_QUERY_CACHE_TTL", "30")
    query_cache.cache.clear()
    _name, source = events_table
    charts = [{"kind": "histogram", "x": "quantity"}, {"kind": "bar", "x": "concept_id"}]
    statements, stop = _capture(engine)
    try:
        first = live_query.query(source, [], charts, 0, 10)
        assert first["cache"]["hit"] is False
        statements.clear()

        page2 = live_query.query(source, [], charts, 1, 10)
        data_sql = [s for s in statements if s.startswith("SELECT") and "pg_catalog" not in s]
        assert len(data_sql) == 1 and "OFFSET" in data_sql[0]      # only the row page
        assert page2["cache"]["hit"] is False and page2["total"] == 1000
        assert page2["charts"] == first["charts"]
        statements.clear()

        filtered = live_query.query(source, [
            {"column": "concept_id", "kind": "categorical", "values": ["3"]}], charts, 0, 10)
        assert not [s for s in statements if s.startswith("SELECT MIN(")]   # bounds reused
        assert not [s for s in statements if "FLOOR(" in s and "FILTER" not in s and "WHERE (" not in s]
        histogram = filtered["charts"][0]["data"]
        assert sum(b["all"] for b in histogram) == 1000
        assert sum(b["selected"] for b in histogram) == filtered["filtered"]
        statements.clear()

        live_query.query(source, [], charts, 0, 10, refresh=True)
        assert [s for s in statements if s.startswith("SELECT MIN(")]       # refresh recomputes
        assert live_query.query(source, [], charts, 0, 10)["cache"]["hit"] is True
    finally:
        stop()
        query_cache.cache.clear()


def test_reported_freshness_includes_reused_histogram_base(engine, events_table, monkeypatch):
    import query_cache
    monkeypatch.setenv("STUDIO_QUERY_CACHE_TTL", "30")
    query_cache.cache.clear()
    _name, source = events_table
    charts = [{"kind": "histogram", "x": "quantity"}]
    try:
        first = live_query.query(source, [], charts, 0, 10)
        base_time = first["cache"]["as_of"]
        time.sleep(0.05)
        # A different filter builds a new summary but reuses the cached base.
        later = live_query.query(source, [
            {"column": "concept_id", "kind": "categorical", "values": ["1"]}], charts, 0, 10)
        assert later["cache"]["as_of"] <= base_time
        assert "_data_as_of" not in later
        again = live_query.query(source, [
            {"column": "concept_id", "kind": "categorical", "values": ["1"]}], charts, 0, 10)
        assert again["cache"]["hit"] is True and again["cache"]["as_of"] <= base_time
    finally:
        query_cache.cache.clear()
