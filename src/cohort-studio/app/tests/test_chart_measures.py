"""Chart measures and series give the same numbers on every engine:
pandas, in-memory DuckDB, DuckDB on disk and live PostgreSQL."""
import math
import uuid

import duckdb
import pandas as pd
import pytest
from sqlalchemy import text

import agg_duck
import chart_measures
import datasets
import disk_data

RID = "omopdb"


def _frame() -> pd.DataFrame:
    rows = []
    for i in range(15):
        for j in range(20 + i):
            n = len(rows)
            rows.append({"dx": f"d{i:02d}", "grp": f"g{n % 8}", "patient": f"p{n % 37}",
                         "lab": None if n % 11 == 0 else round(4 + (n * 7919 % 97) / 10, 1),
                         "age": 20 + n % 60})
    return pd.DataFrame(rows)


FILTERS = [{"column": "age", "kind": "range", "min": 25, "max": 70}]
CHARTS = [
    {"kind": "bar", "x": "dx", "measure": {"agg": agg, "column": "lab"}} for agg in
    ("sum", "mean", "median", "min", "max")] + [
    {"kind": "bar", "x": "dx", "measure": {"agg": "count_distinct", "column": "patient"}},
    {"kind": "bar", "x": "dx", "series": "grp"},
    {"kind": "bar", "x": "dx", "series": "grp", "measure": {"agg": "mean", "column": "lab"}},
    {"kind": "bar", "x": "grp", "series": "dx", "measure": {"agg": "median", "column": "lab"}},
]


def _close(a, b):
    if isinstance(a, dict):
        assert a.keys() == b.keys()
        for key in a:
            _close(a[key], b[key])
    elif isinstance(a, list):
        assert len(a) == len(b)
        for x, y in zip(a, b):
            _close(x, y)
    elif isinstance(a, float) or isinstance(b, float):
        assert a is not None and b is not None and math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9), (a, b)
    else:
        assert a == b


@pytest.fixture(scope="module")
def expected():
    df = _frame()
    filt = datasets.apply_filters(df, FILTERS)
    return [chart_measures.frame_bar(df, filt, c) for c in CHARTS]


def test_pandas_shapes_and_values(expected):
    df = _frame()
    filt = datasets.apply_filters(df, FILTERS)
    mean = expected[1]
    assert [d["category"] for d in mean["data"]][-1] == "Other"
    assert len(mean["data"]) == 13 and "all" not in mean["data"][0]
    top = filt[filt.dx == "d14"]
    assert math.isclose(mean["data"][0]["value"], top.lab.mean())   # count order: d14 first
    other = filt[~filt.dx.isin([f"d{i:02d}" for i in range(3, 15)])]
    assert math.isclose(mean["data"][-1]["value"], other.lab.mean())   # over folded rows
    split = expected[6]
    assert split["series"] == [f"g{i}" for i in range(6)] + ["Other"]
    first = split["data"][0]
    assert first["category"] == "d14"
    assert first["values"][0] == int(((filt.dx == "d14") & (filt.grp == "g0")).sum())
    assert sum(first["values"]) == int((filt.dx == "d14").sum())


def test_in_memory_duckdb_matches_pandas(expected):
    out = agg_duck.query(_frame(), FILTERS, CHARTS, 0, 5)
    _close(out["charts"], expected)


def test_disk_duckdb_matches_pandas(tmp_path, expected):
    path = str(tmp_path / "m.duckdb")
    con = duckdb.connect(path)
    frame = _frame()
    con.register("frame", frame)
    con.execute("CREATE TABLE data AS SELECT * FROM frame")
    con.close()
    source = {"path": path, "table": "data", "columns": list(frame.columns), "scan_bytes": 1}
    out = disk_data.query(source, FILTERS, CHARTS, 0, 5)
    _close(out["charts"], expected)


@pytest.fixture
def labs(client, engine):
    table = f"labs_{uuid.uuid4().hex[:8]}"
    frame = _frame()
    with engine.begin() as conn:
        conn.execute(text(f'CREATE TABLE public."{table}" (dx text, grp text, patient text, '
                          'lab double precision, age integer)'))
        conn.execute(text(f'INSERT INTO public."{table}" VALUES (:dx, :grp, :patient, :lab, :age)'),
                     [{**r, "lab": None if pd.isna(r["lab"]) else r["lab"]} for r in frame.to_dict("records")])
    yield table
    with engine.begin() as conn:
        conn.execute(text(f'DROP TABLE IF EXISTS public."{table}"'))


def test_live_postgres_matches_pandas_through_the_api(client, labs, expected):
    opened = client.post("/api/datasets/open", json={"source_ref": {
        "kind": "aurora", "resource_id": RID, "table": labs}})
    assert opened.status_code == 200, opened.text
    dataset_id = opened.json()["dataset_id"]
    response = client.post(f"/api/datasets/{dataset_id}/query",
                           json={"filters": FILTERS, "charts": CHARTS})
    assert response.status_code == 200, response.text
    _close(response.json()["charts"], expected)
    # Plain counts keep the all-vs-selected overlay.
    plain = client.post(f"/api/datasets/{dataset_id}/query", json={
        "filters": FILTERS, "charts": [{"kind": "bar", "x": "dx", "measure": {"agg": "count"}}]})
    assert set(plain.json()["charts"][0]["data"][0]) == {"category", "all", "selected"}


def test_bad_measures_are_rejected(client):
    df = _frame()
    dataset_id = datasets.open_dataset(df, "labs.csv")["dataset_id"]
    url = f"/api/datasets/{dataset_id}/query"
    cases = [
        ({"kind": "bar", "x": "dx", "measure": {"agg": "mode", "column": "lab"}}, 422, "agg"),
        ({"kind": "bar", "x": "dx", "measure": {"agg": "mean"}}, 422, "Choose a field"),
        ({"kind": "histogram", "x": "lab", "series": "grp"}, 422, "apply to bar"),
        ({"kind": "bar", "x": "dx", "series": "dx"}, 422, "other than the chart field"),
        ({"kind": "bar", "x": "dx", "measure": {"agg": "sum", "column": "nope"}}, 400, "Unknown chart field"),
        ({"kind": "bar", "x": "dx", "series": "nope"}, 400, "Unknown chart field"),
    ]
    for chart, status, message in cases:
        response = client.post(url, json={"charts": [chart]})
        assert response.status_code == status, (chart, response.text)
        assert message in response.text


def test_a_real_other_value_keeps_its_own_group():
    frame = pd.DataFrame({"x": ["a"] * 18, "s": ["Other"] * 10 + list("abcdefgh")})
    chart = {"kind": "bar", "x": "x", "series": "s"}
    pandas_out = chart_measures.frame_bar(frame, frame, chart)
    duck_out = agg_duck.query(frame, [], [chart], 0, 5)["charts"][0]
    for out in (pandas_out, duck_out):
        assert out["series"] == ["Other", "a", "b", "c", "d", "e", "Other values"]
        assert out["other_series"] == "Other values"
        assert out["data"][0]["values"] == [10, 1, 1, 1, 1, 1, 3]
