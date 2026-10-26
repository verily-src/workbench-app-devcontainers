import uuid

import pytest
from sqlalchemy import event

import live_query


@pytest.fixture
def typed_source(engine, monkeypatch):
    name = f"live_numeric_{uuid.uuid4().hex[:10]}"
    with engine.begin() as conn:
        conn.exec_driver_sql(
            f'CREATE TABLE public."{name}" '
            '(integer_value bigint, measure double precision, exact_value numeric, text_value text)')
        conn.exec_driver_sql(f'''INSERT INTO public."{name}" VALUES
            (1, 1, 1, '1'), (2, 2, 2, '2'), (3, 3, 3, '3'),
            (4, 'NaN'::double precision, 'NaN'::numeric, 'NaN'),
            (5, 'Infinity'::double precision, 'Infinity'::numeric, 'Infinity'),
            (6, NULL, NULL, 'not numeric')''')
    monkeypatch.setattr(live_query.db, "get_engine_for_resource", lambda _rid: engine)
    source = {"resource_id": "numeric-test",
              "sql": f'SELECT integer_value, measure, exact_value, text_value FROM public."{name}"',
              "columns": {"integer_value": "integer_value", "measure": "measure", "exact_value": "exact_value",
                          "text_value": "text_value"}}
    yield source
    with engine.begin() as conn:
        conn.exec_driver_sql(f'DROP TABLE public."{name}"')


def test_native_types_and_text_fallback_keep_nonfinite_values_out_of_histograms(
        typed_source, engine):
    statements = []
    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)
    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = live_query.query(typed_source, [], [
            {"kind": "histogram", "x": "integer_value"},
            {"kind": "histogram", "x": "measure"},
            {"kind": "histogram", "x": "exact_value"},
            {"kind": "histogram", "x": "text_value"},
        ], 0, 10, refresh=True)
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert (result["total"], result["filtered"]) == (6, 6)
    assert [sum(b["all"] for b in chart["data"]) for chart in result["charts"]] == [6, 3, 3, 3]
    assert all(chart["data"] == [
        {**bucket, "selected": bucket["all"]} for bucket in chart["data"]
    ] for chart in result["charts"])
    histogram_sql = [s for s in statements if "FLOOR(" in s]
    assert len(histogram_sql) == 4
    assert all("WHERE (TRUE)" not in s for s in histogram_sql)
    integer_sql = [s for s in histogram_sql if 'live."integer_value"' in s]
    assert integer_sql and all("::text" not in s and " ~ " not in s for s in integer_sql)
    native_sql = [s for s in histogram_sql if 'live."measure"' in s]
    assert native_sql and all(" ~ " not in s for s in native_sql)
    assert any('TRIM((live."text_value")::text) ~' in s for s in histogram_sql)
    total_scans = [s for s in statements if s.startswith("SELECT COUNT(*) FROM (")
                   and " WHERE " not in s]
    assert len(total_scans) == 1


def test_numeric_range_profile_filter_and_frame_use_native_driver_types(typed_source):
    profiles = live_query.profile_columns(typed_source, [
        {"name": "measure", "filter_kind": "range"},
        {"name": "integer_value", "filter_kind": "range"},
        {"name": "text_value", "filter_kind": "range"},
    ])
    assert (profiles[0]["min"], profiles[0]["max"]) == (1, 3)
    assert (profiles[1]["min"], profiles[1]["max"]) == (1, 6)
    assert (profiles[2]["min"], profiles[2]["max"]) == (1, 3)
    filters = [{"column": "measure", "kind": "range", "min": 1, "max": 2}]
    result = live_query.query(typed_source, filters, [
        {"kind": "histogram", "x": "text_value"}], 0, 10, refresh=True)
    assert (result["total"], result["filtered"]) == (6, 2)
    assert sum(bucket["selected"] for bucket in result["charts"][0]["data"]) == 2
    frame = live_query.fetch_frame(typed_source, filters, max_rows=10)
    assert sorted(frame["measure"].tolist()) == [1.0, 2.0]



def test_primary_key_pages_keep_full_counts_and_use_index_order(engine, monkeypatch):
    name = f"live_paging_{uuid.uuid4().hex[:10]}"
    monkeypatch.setattr(live_query.db, "get_engine_for_resource", lambda _rid: engine)
    with engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE TABLE public."{name}" (id bigint PRIMARY KEY, label text)')
        conn.exec_driver_sql(f'INSERT INTO public."{name}" SELECT i, repeat(\'x\', 100) FROM generate_series(1, 12000) i')
        conn.exec_driver_sql(f'ANALYZE public."{name}"')
    source = {"resource_id": name, "sql": f'SELECT id AS key, label FROM public."{name}"',
              "columns": {"key": "key", "label": "label"}}
    statements = []
    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)
    event.listen(engine, "before_cursor_execute", capture)
    try:
        first = live_query.query(source, [], [], 0, 10, refresh=True)
        second = live_query.query(source, [], [], 1, 10, refresh=True)
        assert first["total"] == second["total"] == 12000
        assert [row[0] for row in first["rows"]["data"]] == list(range(1, 11))
        assert [row[0] for row in second["rows"]["data"]] == list(range(11, 21))
        pages = [s for s in statements if s.startswith('SELECT live.') and 'OFFSET' in s]
        assert len(pages) == 2 and all('to_jsonb' not in s for s in pages)
        with engine.begin() as conn:
            plan = conn.exec_driver_sql(f'EXPLAIN SELECT id AS key, label FROM public."{name}" ORDER BY id LIMIT 10').all()
            assert any('Index Scan' in row[0] for row in plan)
            assert live_query._primary_key_order(conn, {**source, "sql": f'SELECT label FROM public."{name}"'}) is None
            assert live_query._primary_key_order(conn, {**source, "sql": f'SELECT a.id AS key, a.label FROM public."{name}" a JOIN public."{name}" b ON a.id=b.id'}) is None
    finally:
        event.remove(engine, "before_cursor_execute", capture)
        with engine.begin() as conn:
            conn.exec_driver_sql(f'DROP TABLE public."{name}"')


def test_api_table_open_pages_by_primary_key(client, engine):
    import datasets
    name = f"live_open_{uuid.uuid4().hex[:10]}"
    identifier = None
    statements = []
    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)
    with engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE TABLE public."{name}" (id bigint PRIMARY KEY, label text)')
        conn.exec_driver_sql(f"INSERT INTO public.\"{name}\" SELECT i, 'row-' || i FROM generate_series(1, 1005) i")
    try:
        opened = client.post("/api/datasets/open", json={"source_ref": {
            "kind": "aurora", "resource_id": "omopdb", "schema": "public", "table": name}})
        assert opened.status_code == 200, opened.text
        identifier = opened.json()["dataset_id"]
        assert "SELECT *" in datasets.get(identifier)["live_source"]["sql"]
        event.listen(engine, "before_cursor_execute", capture)
        result = client.post(f"/api/datasets/{identifier}/query", json={"page": 1, "page_size": 5})
        assert result.status_code == 200, result.text
        assert result.json()["total"] == result.json()["filtered"] == 1005
        assert [row[0] for row in result.json()["rows"]["data"]] == [6, 7, 8, 9, 10]
        pages = [sql for sql in statements if sql.startswith("SELECT live.") and "OFFSET" in sql]
        assert pages and all('ORDER BY live."id"' in sql and 'to_jsonb' not in sql for sql in pages)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
        if identifier:
            datasets.close_dataset(identifier)
        with engine.begin() as conn:
            conn.exec_driver_sql(f'DROP TABLE public."{name}"')

