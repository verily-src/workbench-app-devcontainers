"""Chart measures and series give the same numbers on every engine:
pandas, in-memory DuckDB, DuckDB on disk and live PostgreSQL."""
import math
import uuid

import duckdb
import numpy as np
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
                         "lab": None if n % 11 == 0 else 40.0 if n % 50 == 7 else round(4 + (n * 7919 % 97) / 10, 1),
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
    {"kind": "box", "x": "lab", "y": "dx"},
    {"kind": "box", "x": "lab"},
    {"kind": "box", "x": "age", "y": "grp"},
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
    return [datasets.chart_aggregate(df, filt, c) for c in CHARTS]


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


def test_box_plot_quartiles_and_whiskers(expected):
    df = _frame()
    filt = datasets.apply_filters(df, FILTERS)
    single = next(e for e in expected if e["kind"] == "box" and not e["y"])
    assert len(single["data"]) == 1 and single["data"][0]["category"] is None
    values = filt.lab.dropna().to_numpy()
    q1, med, q3 = np.quantile(values, [0.25, 0.5, 0.75])
    box = single["data"][0]
    assert math.isclose(box["q1"], q1) and math.isclose(box["median"], med) and math.isclose(box["q3"], q3)
    fence = q3 + 1.5 * (q3 - q1)
    assert box["max"] == 40.0 and box["high"] == values[values <= fence].max() < 40
    assert box["outliers"] == int((values > fence).sum() + (values < q1 - 1.5 * (q3 - q1)).sum()) > 0
    assert box["n"] == len(values)
    grouped = next(e for e in expected if e["kind"] == "box" and e["y"] == "dx")
    assert [d["category"] for d in grouped["data"]][-1] == "Other"
    assert grouped["other_category"] == "Other" and len(grouped["data"]) == 13


def test_reference_lines_and_axis_format_are_validated(client):
    import main
    dataset_id = datasets.open_dataset(_frame(), "labs.csv")["dataset_id"]
    url = f"/api/datasets/{dataset_id}/query"
    good = {"kind": "histogram", "x": "lab", "references": [
        {"axis": "x", "value": 6.5, "label": "HbA1c 6.5"}, {"value": 2, "to": 4, "param": "low"}],
        "y_axis": {"format": {"decimals": 1, "unit": "%", "percent": False}}}
    assert client.post(url, json={"charts": [good]}).status_code == 200
    for chart, message in (
        ({**good, "references": [{"label": "no value"}]}, "needs a value"),
        ({**good, "references": [{"value": 1, "param": "bad name"}]}, "pattern"),
        ({**good, "references": [{"value": 1}] * 6}, "at most 5"),
        ({**good, "y_axis": {"format": {"decimals": 9}}}, "less than or equal"),
        ({**good, "y_axis": {"format": {"unit": "x" * 17}}}, "at most 16"),
    ):
        response = client.post(url, json={"charts": [chart]})
        assert response.status_code == 422, (chart, response.text)
        assert message in response.text, response.text
    source = {"kind": "aurora", "resource_id": RID, "table": "labs"}
    view = {"source": source, "charts": [good], "parameters": [{"name": "low", "kind": "number", "value": 3}]}
    main.ViewDataset.model_validate(view)
    with pytest.raises(ValueError, match="not a number parameter"):
        main.ViewDataset.model_validate({**view, "parameters": []})
