import pandas as pd
import pytest
from sqlalchemy import text

import agg_duck
import datasets


@pytest.mark.parametrize("filter_spec", [
    {"kind": "categorical", "column": "flag", "values": ["True"]},
    {"kind": "categorical", "column": "amount", "values": ["1.0"]},
    {"kind": "range", "column": "text", "min": 5},
    {"kind": "date", "column": "when", "start": "2024-01-02", "end": "2024-01-02"},
])
def test_loaded_filters_match_duckdb(filter_spec):
    df = pd.DataFrame({
        "flag": [True, False, True, None],
        "amount": [1.0, 2.5, None, 1.0],
        "text": ["10", "bad", None, "5"],
        "when": pd.to_datetime(["2024-01-01T23:30:00-05:00", "2024-01-02T00:30:00Z", None, "2024-01-01T12:00:00Z"], utc=True),
        "pid": [1, 2, 1, 3],
    })
    expected = datasets.apply_filters(df, [filter_spec])
    result = agg_duck.query(df, [filter_spec], [], 0, 50, entity_column="pid")
    assert result["filtered"] == len(expected)
    assert result["entity"]["filtered"] == expected.pid.nunique()


def test_bar_categories_and_selection_match_across_engines():
    df = pd.DataFrame({"flag": [True, False, True, None], "pid": [1, 2, 3, 4]})
    filters = [{"kind": "categorical", "column": "flag", "values": ["True"]}]
    chart = {"kind": "bar", "x": "flag"}
    expected = datasets.chart_aggregate(df, datasets.apply_filters(df, filters), chart)
    result = agg_duck.query(df, filters, [chart], 0, 50, entity_column="pid")
    assert result["charts"][0] == expected


def test_api_query_matches_when_dataset_crosses_duckdb_threshold(client, monkeypatch):
    df = pd.DataFrame({"flag": [True, False, True] * 20000,
                       "pid": [1, 2, 3] * 20000})
    opened = datasets.open_dataset(df, "flags.csv")
    dataset_id = opened["dataset_id"]
    payload = {"filters": [{"kind": "categorical", "column": "flag", "values": ["True"]}],
               "charts": [{"kind": "bar", "x": "flag"}], "entity_column": "pid"}
    try:
        results = []
        for threshold in (100000, 1):
            monkeypatch.setattr(agg_duck, "DUCKDB_AGG_ROWS", threshold)
            response = client.post(f"/api/datasets/{dataset_id}/query", json=payload)
            assert response.status_code == 200, response.text
            results.append(response.json())
        for key in ("total", "filtered", "entity", "charts"):
            assert results[0][key] == results[1][key]
        assert results[0]["filtered"] == 40000
        assert results[0]["entity"]["filtered"] == 2
    finally:
        datasets.close_dataset(dataset_id)


def test_api_filter_and_chart_match_postgres(client, engine):
    df = pd.DataFrame({"flag": [True, False, True], "pid": [1, 2, 3]})
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE public.invariant_parity (flag boolean, pid integer)"))
        conn.execute(text("INSERT INTO public.invariant_parity VALUES (true, 1), (false, 2), (true, 3)"))
    loaded = datasets.open_dataset(df, "flags.csv")["dataset_id"]
    payload = {"filters": [{"kind": "categorical", "column": "flag", "values": ["True"]}],
               "charts": [{"kind": "bar", "x": "flag"}], "entity_column": "pid"}
    try:
        opened = client.post("/api/datasets/open", json={"source_ref": {
            "kind": "aurora", "resource_id": "omopdb", "table": "invariant_parity"}})
        assert opened.status_code == 200, opened.text
        live = opened.json()["dataset_id"]
        results = []
        for dataset_id in (loaded, live):
            response = client.post(f"/api/datasets/{dataset_id}/query", json=payload)
            assert response.status_code == 200, response.text
            results.append(response.json())
        for key in ("total", "filtered", "entity", "charts"):
            assert results[0][key] == results[1][key]
    finally:
        datasets.close_dataset(loaded)
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE public.invariant_parity"))


def test_postgres_float_category_text_matches_loaded(engine):
    import category_text
    values = [1e15, 1e20, 1e-8, 1e-5, 1.0, 1.2345678901234567]
    with engine.connect() as conn:
        actual = [conn.execute(text("SELECT CAST(CAST(:v AS double precision) AS text)"), {"v": value}).scalar_one() for value in values]
    assert [category_text.value_text(value) for value in values] == [category_text.normalize_label(value, 701) for value in actual]


def test_arrow_timestamp_filter():
    import category_text
    import pyarrow as pa
    series = pd.Series([pd.Timestamp("2024-01-02", tz="UTC"), None],
                       dtype=pd.ArrowDtype(pa.timestamp("us", tz="UTC")))
    df = pd.DataFrame({"when": series})
    assert len(datasets.apply_filters(df, [{"kind": "date", "column": "when", "start": "2024-01-02"}])) == 1
    assert datasets.profile_columns(df)
    assert category_text.frame_text(series).iloc[0] == "2024-01-02 00:00:00+00"


def test_nanosecond_timestamp_categories_remain_distinct():
    import category_text
    import duckdb
    values = pd.to_datetime(["2024-01-01 00:00:00.000000001", "2024-01-01 00:00:00.000000002"])
    frame = pd.DataFrame({"v": values})
    expected = list(category_text.frame_text(frame["v"]))
    assert expected == ["2024-01-01 00:00:00.000000001", "2024-01-01 00:00:00.000000002"]
    chart = {"kind": "bar", "x": "v"}
    assert {d["category"] for d in datasets.chart_aggregate(frame, frame, chart)["data"]} == set(expected)
    assert {d["category"] for d in agg_duck.query(frame, [], [chart], 0, 10)["charts"][0]["data"]} == set(expected)


def test_case_distinct_columns_remain_available_at_scale(client):
    frame = pd.DataFrame({"v": [1] * 50000, "V": [2] * 50000})
    assert not agg_duck.should_use(frame)
    opened = datasets.open_dataset(frame, "case.csv")
    try:
        response = client.post(f"/api/datasets/{opened['dataset_id']}/query", json={
            "filters": [{"kind": "range", "column": "V", "min": 2}], "charts": []})
        assert response.status_code == 200, response.text
        assert response.json()["filtered"] == 50000
    finally:
        datasets.close_dataset(opened["dataset_id"])


def test_internal_position_does_not_shadow_case_variant(client):
    frame = pd.DataFrame({"__POS__": list(range(50000, 0, -1)), "id": list(range(50000))})
    opened = datasets.open_dataset(frame, "position.csv")
    try:
        response = client.post(f"/api/datasets/{opened['dataset_id']}/query", json={
            "filters": [], "charts": [], "page": 1, "page_size": 10})
        assert response.status_code == 200, response.text
        rows = response.json()["rows"]
        assert [row[rows["columns"].index("id")] for row in rows["data"]] == list(range(10, 20))
    finally:
        datasets.close_dataset(opened["dataset_id"])


@pytest.mark.parametrize("value", ["inf", "-inf", "NaN"])
def test_postgres_special_float_category_remains_selectable(client, engine, value):
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE public.invariant_special (v double precision)"))
        conn.execute(text("INSERT INTO public.invariant_special VALUES ('Infinity'), ('-Infinity'), ('NaN'), (1)"))
    try:
        opened = client.post("/api/datasets/open", json={"source_ref": {
            "kind": "aurora", "resource_id": "omopdb", "table": "invariant_special"}})
        assert opened.status_code == 200, opened.text
        response = client.post(f"/api/datasets/{opened.json()['dataset_id']}/query", json={
            "filters": [{"kind": "categorical", "column": "v", "values": [value]}],
            "charts": [{"kind": "bar", "x": "v"}]})
        assert response.status_code == 200, response.text
        assert response.json()["filtered"] == 1
    finally:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE public.invariant_special"))


def test_postgres_float32_category_text_matches_loaded(engine):
    import category_text
    import numpy as np
    values = [np.float32(1.2345678), np.float32(1e-8), np.float32(1e8)]
    with engine.connect() as conn:
        actual = [conn.execute(text("SELECT CAST(CAST(:v AS real) AS text)"), {"v": float(value)}).scalar_one() for value in values]
    assert [category_text.value_text(value) for value in values] == [category_text.normalize_label(value, 700) for value in actual]


@pytest.mark.parametrize("column,value", [("d", "1000000000000000.0"), ("r", "100000000")])
def test_saved_float_category_filters_query_postgres(client, engine, column, value):
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE public.invariant_float (d double precision, r real)"))
        conn.execute(text("INSERT INTO public.invariant_float VALUES (1e15, 1e8), (2, 2)"))
    try:
        opened = client.post("/api/datasets/open", json={"source_ref": {
            "kind": "aurora", "resource_id": "omopdb", "table": "invariant_float"}})
        assert opened.status_code == 200, opened.text
        dataset_id = opened.json()["dataset_id"]
        response = client.post(f"/api/datasets/{dataset_id}/query", json={
            "filters": [{"kind": "categorical", "column": column, "values": [value]}],
            "charts": [{"kind": "bar", "x": column}]})
        assert response.status_code == 200, response.text
        assert response.json()["filtered"] == 1
        assert sum(row["selected"] for row in response.json()["charts"][0]["data"]) == 1
    finally:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE public.invariant_float"))


def test_float32_category_filter_matches_duckdb():
    import numpy as np
    df = pd.DataFrame({"v": np.array([1.2345678, 2.0], dtype="float32")})
    filters = [{"kind": "categorical", "column": "v", "values": ["1.2345678"]}]
    assert len(datasets.apply_filters(df, filters)) == 1
    assert agg_duck.query(df, filters, [], 0, 10)["filtered"] == 1


@pytest.mark.parametrize("dtype", ["float32", "Float32", "float32[pyarrow]"])
def test_float32_nullable_and_arrow_category_text(dtype):
    import category_text
    import numpy as np
    values = [np.float32(628040768), np.float32(-74015696)]
    series = pd.Series(values, dtype=dtype)
    assert list(category_text.frame_text(series)) == [category_text.value_text(v) for v in values]


@pytest.mark.parametrize("dtype", ["int64", "Int64", "int64[pyarrow]", "uint64"])
def test_integer_range_keeps_precision(dtype):
    threshold = 2**53 + 1
    df = pd.DataFrame({"v": pd.Series([threshold, threshold + 1], dtype=dtype)})
    filters = [{"kind": "range", "column": "v", "max": threshold}]
    assert list(datasets.apply_filters(df, filters)["v"]) == [threshold]
    assert agg_duck.query(df, filters, [], 0, 10)["filtered"] == 1


def test_integer_range_api_matches_postgres(client, engine, monkeypatch):
    threshold = 2**53 + 1
    frame = pd.DataFrame({"v": [threshold, threshold + 1]})
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE public.invariant_bigints (v bigint)"))
        conn.execute(text("INSERT INTO public.invariant_bigints VALUES (:a), (:b)"),
                     {"a": threshold, "b": threshold + 1})
    loaded = datasets.open_dataset(frame, "bigints.csv")["dataset_id"]
    try:
        opened = client.post("/api/datasets/open", json={"source_ref": {
            "kind": "aurora", "resource_id": "omopdb", "table": "invariant_bigints"}})
        assert opened.status_code == 200, opened.text
        live = opened.json()["dataset_id"]
        for dataset_id, cutoff in ((loaded, 100000), (loaded, 1), (live, 1)):
            monkeypatch.setattr(agg_duck, "DUCKDB_AGG_ROWS", cutoff)
            response = client.post(f"/api/datasets/{dataset_id}/query", json={
                "filters": [{"kind": "range", "column": "v", "max": threshold}], "charts": []})
            assert response.status_code == 200, response.text
            assert response.json()["filtered"] == 1
    finally:
        datasets.close_dataset(loaded)
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE public.invariant_bigints"))


def test_float32_distinct_chart_labels_across_api_engines(client, engine, monkeypatch):
    import numpy as np
    import category_text

    first = np.float32(628040768)
    second = np.nextafter(first, np.float32(float("inf")))
    values = [first, second, np.float32(-74015696)]
    assert len({category_text.value_text(v) for v in values}) == 3
    df = pd.DataFrame({"v": values, "pid": [1, 2, 3]})
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE public.invariant_float_labels (v real, pid integer)"))
        for pid, value in enumerate(values, 1):
            conn.execute(text("INSERT INTO public.invariant_float_labels VALUES (:v, :pid)"),
                         {"v": float(value), "pid": pid})
    loaded = datasets.open_dataset(df, "float-labels.csv")["dataset_id"]
    payload = {"filters": [], "charts": [{"kind": "bar", "x": "v"},
               {"kind": "bar", "x": "v", "measure": {"agg": "sum", "column": "pid"}},
               {"kind": "heatmap", "x": "v", "y": "pid"}]}
    try:
        opened = client.post("/api/datasets/open", json={"source_ref": {
            "kind": "aurora", "resource_id": "omopdb", "table": "invariant_float_labels"}})
        assert opened.status_code == 200, opened.text
        live = opened.json()["dataset_id"]
        results = []
        for dataset_id, threshold in ((loaded, 100000), (loaded, 1), (live, 1)):
            monkeypatch.setattr(agg_duck, "DUCKDB_AGG_ROWS", threshold)
            response = client.post(f"/api/datasets/{dataset_id}/query", json=payload)
            assert response.status_code == 200, response.text
            results.append(response.json()["charts"])
        for charts in results:
            labels = {row["category"] for row in charts[0]["data"]}
            assert labels == {category_text.value_text(v) for v in values}
            assert {row["category"] for row in charts[1]["data"]} == labels
            assert {row[0] for row in charts[2]["data"]} == labels
        for dataset_id, threshold in ((loaded, 100000), (loaded, 1), (live, 1)):
            monkeypatch.setattr(agg_duck, "DUCKDB_AGG_ROWS", threshold)
            for value in values:
                response = client.post(f"/api/datasets/{dataset_id}/query", json={
                    "filters": [{"kind": "categorical", "column": "v",
                                 "values": [category_text.value_text(value)]}],
                    "charts": [{"kind": "bar", "x": "v"}]})
                assert response.status_code == 200, response.text
                result = response.json()
                assert result["filtered"] == 1
                assert sum(row["selected"] for row in result["charts"][0]["data"]) == 1
    finally:
        datasets.close_dataset(loaded)
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE public.invariant_float_labels"))


@pytest.mark.parametrize("dtype,pg_type,duck_type", [("float32", "real", "FLOAT"), ("float64", "double precision", "DOUBLE")])
def test_float_label_parity_at_format_boundaries(engine, dtype, pg_type, duck_type):
    import category_text
    import duckdb
    import numpy as np
    values = np.array([0, -0.0, 0.00001, 0.0001, 1.2345678, 999999, 1e6, 12345678.9,
                       999999999999999, 1e15, 1.234567890123456e15, -1e8], dtype=dtype)
    rng = np.random.default_rng(42)
    values = np.concatenate([values, (rng.uniform(-10, 10, 100) * np.power(10.0, rng.integers(-12, 18, 100))).astype(dtype)])
    duck = duckdb.connect()
    expression = category_text.duck_text("v", duck_type)
    try:
        mismatches = []
        with engine.connect() as conn:
            for value in values:
                pg = conn.execute(text(f"SELECT CAST(CAST(:v AS {pg_type}) AS text)"), {"v": float(value)}).scalar_one()
                dk = duck.execute(f"SELECT {expression} FROM (SELECT ?::{duck_type} AS v)", [float(value)]).fetchone()[0]
                expected = category_text.value_text(value)
                actual = (category_text.normalize_label(pg, 700 if dtype == "float32" else 701),
                          category_text.normalize_label(dk, duck_type))
                if actual != (expected, expected):
                    mismatches.append((str(value), pg, dk, expected))
        assert not mismatches, mismatches[:10]
    finally:
        duck.close()
