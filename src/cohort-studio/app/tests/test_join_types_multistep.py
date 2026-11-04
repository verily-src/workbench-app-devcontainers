"""Joins over real PostgreSQL-typed inputs and 3-step star plans.

Inputs are opened through the API (sql_source.fetch), not hand-made frames,
so date and numeric columns arrive as the app really sees them.
"""
import datetime
import uuid
from decimal import Decimal

import pandas as pd
import pytest

import datasets
import joins


@pytest.fixture
def typed_tables(engine):
    suffix = uuid.uuid4().hex[:8]
    names = {k: f"jt_{k}_{suffix}" for k in ("person", "cond", "drug", "lab")}
    with engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE TABLE public."{names["person"]}" (person_id bigint, born date)')
        conn.exec_driver_sql(f'INSERT INTO public."{names["person"]}" VALUES '
                             "(1, '1950-01-01'), (2, '1960-06-15'), (3, '1970-12-31')")
        conn.exec_driver_sql(f'CREATE TABLE public."{names["cond"]}" '
                             '(person_id bigint, condition_start_date date, threshold numeric)')
        conn.exec_driver_sql(f'INSERT INTO public."{names["cond"]}" VALUES '
                             "(1, '2020-01-10', 10), (1, '2020-05-01', 10), (2, '2021-03-01', 10)")
        conn.exec_driver_sql(f'CREATE TABLE public."{names["drug"]}" '
                             '(person_id bigint, drug_start timestamp)')
        conn.exec_driver_sql(f'INSERT INTO public."{names["drug"]}" VALUES '
                             "(1, '2020-02-01 08:00'), (1, '2019-01-01 08:00'), (2, '2021-04-01 09:00'), (3, '2022-01-01 00:00')")
        conn.exec_driver_sql(f'CREATE TABLE public."{names["lab"]}" (person_id bigint, value numeric)')
        conn.exec_driver_sql(f'INSERT INTO public."{names["lab"]}" VALUES (1, 9.5), (2, 10.5)')
    yield names
    with engine.begin() as conn:
        for name in names.values():
            conn.exec_driver_sql(f'DROP TABLE public."{name}"')


def _open(client, table):
    response = client.post("/api/datasets/open", json={"source_ref": {
        "kind": "aurora", "resource_id": "omopdb", "schema": "public", "table": table}})
    assert response.status_code == 200, response.text
    return response.json()["dataset_id"]


def test_postgres_dates_and_numerics_are_typed_for_joins(client, typed_tables):
    ids = {k: _open(client, v) for k, v in typed_tables.items()}
    try:
        cond = datasets.get(ids["cond"])["df"]
        assert joins._kind(cond["condition_start_date"]) == "time"
        assert joins._kind(cond["threshold"]) == "number"
        assert joins._kind(datasets.get(ids["drug"])["df"]["drug_start"]) == "time"
    finally:
        for identifier in ids.values():
            datasets.close_dataset(identifier)


def test_three_step_star_join_compares_dates_and_numbers_natively(client, typed_tables):
    ids = {k: _open(client, v) for k, v in typed_tables.items()}
    try:
        steps = [
            {"right_id": ids["cond"], "how": "inner", "alias": "cond", "columns": None,
             "conditions": [{"left": "person_id", "op": "=", "right": "person_id"}]},
            # date (step 1) vs timestamp: used to be rejected as text vs time.
            {"right_id": ids["drug"], "how": "left", "alias": "drug", "columns": ["drug_start"],
             "conditions": [{"left": "person_id", "op": "=", "right": "person_id"},
                            {"left": "cond → condition_start_date", "op": "<=", "right": "drug_start"}]},
            # numeric vs numeric: as text, '9.5' < '10' is false.
            {"right_id": ids["lab"], "how": "inner", "alias": "lab", "columns": ["value"],
             "conditions": [{"left": "person_id", "op": "=", "right": "person_id"},
                            {"left": "cond → threshold", "op": ">", "right": "value"}]},
        ]
        checked = joins.validate(ids["person"], steps)
        assert checked["ok"], checked
        assert checked["engine"] == "aurora"
        sql = checked["generated_sql"]["sql"]
        assert 'CAST(l."cond → threshold"' not in sql
        assert 'CAST(l."cond → condition_start_date"' not in sql
        response = client.post("/api/datasets/join", json={"base_id": ids["person"], "steps": steps})
        assert response.status_code == 200, response.text
        joined = response.json()
        frame = datasets.get(joined["dataset_id"])["df"]
        # person 1: two conditions; drugs on/after each start; lab 9.5 < 10 matches.
        # person 2: lab 10.5 is not < 10, so the inner lab step drops them.
        assert sorted(frame["person_id"].tolist()) == [1, 1]
        assert set(frame["lab → value"].astype(float)) == {9.5}
        starts = {str(d)[:10] for d in frame["drug → drug_start"].dropna()}
        assert starts == {"2020-02-01"}
        assert joined["join"]["engine"] == "aurora"
        assert len(joined["join"]["steps"]) == 3
        datasets.close_dataset(joined["dataset_id"])
    finally:
        for identifier in ids.values():
            datasets.close_dataset(identifier)


def test_in_memory_join_on_decimal_and_date_objects():
    left = datasets.open_dataset(pd.DataFrame({
        "id": [1, 2], "limit": [Decimal("10"), Decimal("10")],
        "start": [datetime.date(2020, 1, 1), datetime.date(2021, 1, 1)]}), "left")
    right = datasets.open_dataset(pd.DataFrame({
        "id": [1, 2], "value": [Decimal("9.5"), Decimal("10.5")],
        "seen": [pd.Timestamp("2020-06-01"), pd.Timestamp("2020-06-01")]}), "right")
    try:
        out = joins.run(left["dataset_id"], [{
            "right_id": right["dataset_id"], "how": "inner", "alias": "r", "columns": None,
            "conditions": [{"left": "id", "op": "=", "right": "id"},
                           {"left": "limit", "op": ">", "right": "value"},
                           {"left": "start", "op": "<=", "right": "seen"}]}])
        assert out["df"]["id"].tolist() == [1]
    finally:
        datasets.close_dataset(left["dataset_id"])
        datasets.close_dataset(right["dataset_id"])
