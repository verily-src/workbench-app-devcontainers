"""Date filters: absolute (start/end, end inclusive) and relative (last N units),
the same result on every engine."""
import uuid
from datetime import date

import duckdb
import pandas as pd
import pytest
from sqlalchemy import text

import agg_duck
import datasets
import disk_data
import filter_rules
import queries

RID = "omopdb"
DAYS = ["2024-01-01", "2024-01-31", "2024-02-01", "2024-06-15", "2025-01-01"]


def test_relative_start_handles_months_and_leap_days():
    today = date(2024, 3, 31)
    assert filter_rules.relative_start(7, "day", today) == date(2024, 3, 24)
    assert filter_rules.relative_start(2, "week", today) == date(2024, 3, 17)
    assert filter_rules.relative_start(1, "month", today) == date(2024, 2, 29)   # clamps to Feb 29
    assert filter_rules.relative_start(1, "year", date(2024, 2, 29)) == date(2023, 2, 28)
    with pytest.raises(ValueError):
        filter_rules.relative_start(0, "day", today)
    with pytest.raises(ValueError):
        filter_rules.relative_start(3, "decade", today)


def test_bounds_end_is_inclusive_and_order_is_checked():
    assert filter_rules.date_bounds({"start": "2024-01-31", "end": "2024-02-01"}) == (
        date(2024, 1, 31), date(2024, 2, 2))
    with pytest.raises(ValueError, match="before its start"):
        filter_rules.date_bounds({"start": "2024-02-01", "end": "2024-01-01"})
    with pytest.raises(ValueError, match="not a valid date"):
        filter_rules.date_bounds({"start": "2024-13-01"})


def test_date_columns_are_detected_and_profiled():
    df = pd.DataFrame({"visit": pd.to_datetime(DAYS), "day": [date.fromisoformat(d) for d in DAYS],
                       "n": range(5)})
    kinds = queries.infer_filter_kinds(df)
    assert kinds["visit"] == "date" and kinds["day"] == "date"
    profile = {c["name"]: c for c in datasets.profile_columns(df)}
    assert profile["visit"]["min_date"] == "2024-01-01" and profile["visit"]["max_date"] == "2025-01-01"


FEB = {"column": "visit", "kind": "date", "start": "2024-01-31", "end": "2024-02-01"}
OPEN_END = {"column": "visit", "kind": "date", "start": "2024-06-01"}


def test_pandas_engine():
    df = pd.DataFrame({"visit": pd.to_datetime(DAYS)})
    assert len(datasets.apply_filters(df, [FEB])) == 2
    assert len(datasets.apply_filters(df, [OPEN_END])) == 2


def test_duckdb_engines(tmp_path):
    path = str(tmp_path / "d.duckdb")
    con = duckdb.connect(path)
    con.execute("CREATE TABLE data (visit DATE)")
    con.executemany("INSERT INTO data VALUES (?)", [[d] for d in DAYS])
    for f, expected in ((FEB, 2), (OPEN_END, 2)):
        where, params = disk_data._where([f], ["visit"])
        assert con.execute(f"SELECT count(*) FROM data AS src WHERE {where}", params).fetchone()[0] == expected
        where, params = agg_duck._where([f], {"visit"})
        assert con.execute(f"SELECT count(*) FROM data WHERE {where}", params).fetchone()[0] == expected
    con.close()
    profile = disk_data.profile_columns({"path": path, "table": "data", "scan_bytes": 1},
                                        [{"name": "visit", "filter_kind": "date"}])
    assert profile[0]["min_date"] == "2024-01-01" and profile[0]["max_date"] == "2025-01-01"


@pytest.fixture
def visits(client, engine):
    table = f"visits_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.execute(text(f'CREATE TABLE public."{table}" (visit_id int, visit date, seen_at timestamptz)'))
        for i, d in enumerate(DAYS):
            conn.execute(text(f'INSERT INTO public."{table}" VALUES (:i, CAST(:d AS date), CAST(:t AS timestamptz))'),
                         {"i": i, "d": d, "t": d})
    yield table
    with engine.begin() as conn:
        conn.execute(text(f'DROP TABLE IF EXISTS public."{table}"'))


def test_live_postgres_engine_through_the_api(client, visits):
    opened = client.post("/api/datasets/open", json={"source_ref": {
        "kind": "aurora", "resource_id": RID, "table": visits}})
    assert opened.status_code == 200, opened.text
    body = opened.json()
    columns = {c["name"]: c for c in body["columns"]}
    assert columns["visit"]["filter_kind"] == "date"
    assert columns["visit"]["min_date"] == "2024-01-01" and columns["visit"]["max_date"] == "2025-01-01"
    assert columns["seen_at"]["filter_kind"] == "date"

    def count(filters):
        response = client.post(f"/api/datasets/{body['dataset_id']}/query", json={"filters": filters})
        assert response.status_code == 200, response.text
        return response.json()["filtered"]

    assert count([FEB]) == 2
    assert count([OPEN_END]) == 2
    assert count([{**FEB, "column": "seen_at"}]) == 2
    # Relative: everything in the fixture is long before "the last 30 days".
    assert count([{"column": "visit", "kind": "date", "last": 30, "unit": "day"}]) == 0
    assert count([{"column": "visit", "kind": "date", "last": 100, "unit": "year"}]) == 5
    bad = client.post(f"/api/datasets/{body['dataset_id']}/query", json={"filters": [
        {"column": "visit", "kind": "date", "start": "2024-02-01", "end": "2024-01-01"}]})
    assert bad.status_code == 400 and "before its start" in bad.text
