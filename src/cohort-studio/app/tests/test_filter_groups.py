"""AND/OR criteria groups: {kind: "any", groups: [[...], [...]]} = OR of ANDs,
the same rows on every engine."""
import uuid

import duckdb
import pandas as pd
import pytest
from sqlalchemy import text

import agg_duck
import datasets
import disk_data

RID = "omopdb"
ROWS = [  # person, dx, age, visit
    (1, "A", 60, "2024-01-10"), (2, "A", 40, "2024-02-10"), (3, "B", 30, "2024-03-10"),
    (4, "C", 70, "2024-04-10"), (5, "B", 80, "2023-05-10"),
]
# (dx = A AND age >= 50) OR (dx = B AND visit in 2024)  -> persons 1, 3
GROUP = {"kind": "any", "groups": [
    [{"column": "dx", "kind": "categorical", "values": ["A"]},
     {"column": "age", "kind": "range", "min": 50, "max": 200}],
    [{"column": "dx", "kind": "categorical", "values": ["B"]},
     {"column": "visit", "kind": "date", "start": "2024-01-01", "end": "2024-12-31"}],
]}
OLDER = {"column": "age", "kind": "range", "min": 35, "max": 200}   # ANDed with the group: person 3 (age 30) drops out


def _frame():
    return pd.DataFrame(ROWS, columns=["person", "dx", "age", "visit"]).assign(
        visit=lambda d: pd.to_datetime(d["visit"]))


def test_pandas_engine():
    assert sorted(datasets.apply_filters(_frame(), [GROUP])["person"]) == [1, 3]
    assert sorted(datasets.apply_filters(_frame(), [GROUP, OLDER])["person"]) == [1]


def test_duckdb_engines(tmp_path):
    path = str(tmp_path / "g.duckdb")
    con = duckdb.connect(path)
    con.execute("CREATE TABLE data (person INT, dx TEXT, age INT, visit DATE)")
    con.executemany("INSERT INTO data VALUES (?, ?, ?, ?)", [list(r) for r in ROWS])
    cols = ["person", "dx", "age", "visit"]
    for filters, expected in (([GROUP], [1, 3]), ([GROUP, OLDER], [1])):
        where, params = disk_data._where(filters, cols)
        got = [r[0] for r in con.execute(
            f"SELECT person FROM data AS src WHERE {where} ORDER BY 1", params).fetchall()]
        assert got == expected
        where, params = agg_duck._where(filters, set(cols))
        got = [r[0] for r in con.execute(f"SELECT person FROM data WHERE {where} ORDER BY 1", params).fetchall()]
        assert got == expected
    con.close()


def test_nested_or_empty_groups_are_rejected(client):
    import main
    with pytest.raises(Exception):
        main.Filter.model_validate({"kind": "any", "groups": []})
    with pytest.raises(Exception):
        main.Filter.model_validate({"kind": "any", "groups": [[{"kind": "any", "groups": [[]]}]]})
    with pytest.raises(Exception):
        main.Filter.model_validate({"kind": "categorical", "values": ["x"]})   # needs a column


@pytest.mark.parametrize("bad, message", [
    ({"column": "a", "kind": "nope"}, "Input should be"),
    ({"column": "a", "kind": "range", "min": 5, "max": 1}, "minimum is above maximum"),
    ({"column": "d", "kind": "date", "start": "2024-02-30"}, "not a valid YYYY-MM-DD date"),
    ({"column": "d", "kind": "date", "last": 3}, "needs both 'last' and 'unit'"),
    ({"column": "d", "kind": "date", "last": 3, "unit": "day", "start": "2024-01-01"}, "not both"),
    ({"column": "d", "kind": "date", "last": 0, "unit": "day"}, "greater than or equal to 1"),
    ({"column": "a", "kind": "categorical", "values": ["x"], "groups": [[]]}, "Only criteria group"),
    ({"kind": "any", "groups": [[]]}, "non-empty group"),
])
def test_filter_model_rejects_bad_shapes(bad, message):
    import main
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match=message):
        main.Filter.model_validate(bad)


def test_filter_model_normalizes_dates():
    import main
    f = main.Filter.model_validate({"column": "d", "kind": "date", "start": "2024-01-05T10:00:00"})
    assert f.start == "2024-01-05"


@pytest.fixture
def people(client, engine):
    table = f"grp_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.execute(text(f'CREATE TABLE public."{table}" (person int, dx text, age int, visit date)'))
        for r in ROWS:
            conn.execute(text(f'INSERT INTO public."{table}" VALUES (:p, :d, :a, CAST(:v AS date))'),
                         {"p": r[0], "d": r[1], "a": r[2], "v": r[3]})
    yield table
    with engine.begin() as conn:
        conn.execute(text(f'DROP TABLE IF EXISTS public."{table}"'))


def test_live_postgres_query_and_compare(client, people):
    opened = client.post("/api/datasets/open", json={"source_ref": {
        "kind": "aurora", "resource_id": RID, "table": people}})
    assert opened.status_code == 200, opened.text
    dataset_id = opened.json()["dataset_id"]

    def count(filters):
        response = client.post(f"/api/datasets/{dataset_id}/query", json={"filters": filters})
        assert response.status_code == 200, response.text
        return response.json()["filtered"]
    assert count([GROUP]) == 2
    assert count([GROUP, OLDER]) == 1
    # Compare: group A = the criteria group, B = everyone else.
    compared = client.post(f"/api/datasets/{dataset_id}/compare", json={
        "filters_a": [GROUP], "filters_b": [], "b_is_rest": True})
    assert compared.status_code == 200, compared.text
    body = compared.json()
    assert body["a_n"] == 2 and body["b_n"] == 3


def test_a_column_named_like_an_internal_marker_is_left_alone():
    frame = pd.DataFrame({"__studio_row": [10, 20, 30], "dx": ["A", "B", "A"]})
    group = {"kind": "any", "groups": [[{"column": "__studio_row", "kind": "categorical", "values": ["10"]}]]}
    assert datasets.apply_filters(frame, [group])["__studio_row"].tolist() == [10]
    # Duplicate index labels don't break the positional match either.
    dup = frame.set_index(pd.Index([0, 0, 1]))
    assert datasets.apply_filters(dup, [group])["__studio_row"].tolist() == [10]


def test_group_summary_accepts_criteria_groups(client, people):
    opened = client.post("/api/datasets/open", json={"source_ref": {
        "kind": "aurora", "resource_id": RID, "table": people}})
    dataset_id = opened.json()["dataset_id"]
    response = client.post(f"/api/datasets/{dataset_id}/summary", json={
        "group_by": ["dx"], "filters": [GROUP], "page": 0, "page_size": 50})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["input_rows"] == 2   # persons 1 (A, 60) and 3 (B, 2024 visit)
    assert sorted(map(tuple, body["rows"])) == [("A", 1), ("B", 1)]
