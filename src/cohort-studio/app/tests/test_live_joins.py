import uuid

import pandas as pd
import pytest
from sqlalchemy import text

import datasets
import joins


def _source_tables(engine):
    suffix = uuid.uuid4().hex[:10]
    left, right, third = (f"live_left_{suffix}", f"live_right_{suffix}",
                          f"live_third_{suffix}")
    with engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE TABLE public."{left}" '
                             '(entity_id bigint, left_value bigint)')
        conn.exec_driver_sql(f'INSERT INTO public."{left}" '
                             'SELECT n, n * 10 FROM generate_series(1, 120001) n')
        conn.exec_driver_sql(f'INSERT INTO public."{left}" VALUES (NULL, 0)')
        conn.exec_driver_sql(f'CREATE TABLE public."{right}" '
                             '(entity_id bigint, tag text)')
        conn.exec_driver_sql(f'INSERT INTO public."{right}" VALUES '
                             "(1, 'early'), (120001, 'late'), "
                             "(120001, 'late'), (NULL, 'null-key')")
        conn.exec_driver_sql(f'CREATE TABLE public."{third}" '
                             '(entity_id bigint, group_label text)')
        conn.exec_driver_sql(f'INSERT INTO public."{third}" VALUES '
                             "(1, 'first'), (120001, 'last')")
    resource = "live-join-test"
    datasets._store.clear()
    left_id = datasets.open_dataset(
        pd.DataFrame({"entity_id": [1, 2], "left_value": [10, 20]}),
        left, origin={"kind": "aurora", "resource_id": resource,
                      "schema": "public", "table": left}, capped=True)["dataset_id"]
    right_id = datasets.open_dataset(
        pd.DataFrame({"entity_id": [1, 120001], "tag": ["early", "late"]}),
        right, origin={"kind": "aurora", "resource_id": resource,
                       "schema": "public", "table": right}, capped=True)["dataset_id"]
    third_id = datasets.open_dataset(
        pd.DataFrame({"entity_id": [1, 120001], "group_label": ["first", "last"]}),
        third, origin={"kind": "aurora", "resource_id": resource,
                       "schema": "public", "table": third}, capped=True)["dataset_id"]
    return (left_id, right_id, third_id, left, right, third)


def _step(right_id, alias, columns):
    return {"right_id": right_id, "how": "left", "alias": alias,
            "columns": columns,
            "conditions": [{"left": "entity_id", "op": "=", "right": "entity_id"}]}


def test_live_aurora_join_queries_full_source_and_aggregates(engine, monkeypatch):
    monkeypatch.setattr(joins.db, "get_engine_for_resource", lambda _rid: engine)
    left_id, right_id, _third_id, left, right, third = _source_tables(engine)
    try:
        first = joins.run(left_id, [_step(right_id, "right", ["tag"])])
        assert first["stats"]["engine"] == "aurora"
        assert first["stats"]["truncated"] is False
        assert first["stats"]["total_rows"] == 120003
        assert first["live_source"]["resource_id"] == "live-join-test"

        opened = datasets.open_dataset(first["df"], "live join",
                                       capped=first["stats"]["truncated"],
                                       live_source=first["live_source"])
        assert opened["query_scope"] == "database"
        assert opened["database"] is True
        assert opened["sampled"] is False
        entity_profile = next(c for c in opened["columns"] if c["name"] == "entity_id")
        assert (entity_profile["min"], entity_profile["max"]) == (1, 120001)
        out = datasets.query(
            opened["dataset_id"],
            [{"column": "right → tag", "kind": "categorical", "values": ["late"]}],
            [{"kind": "bar", "x": "right → tag"},
             {"kind": "histogram", "x": "entity_id"}],
            page=0, page_size=10, entity_column="entity_id")
        assert out["scope"] == "database" and out["sampled"] is False
        assert (out["total"], out["filtered"]) == (120003, 2)
        assert out["entity"] == {"column": "entity_id", "total": 120001,
                                 "filtered": 1}
        assert [row[0] for row in out["rows"]["data"]] == [120001, 120001]
        bar = out["charts"][0]
        assert bar["data"] == [
            {"category": "late", "all": 2, "selected": 2},
            {"category": "early", "all": 1, "selected": 0},
        ]
        hist = out["charts"][1]["data"]
        assert sum(bin_["all"] for bin_ in hist) == 120002
        assert sum(bin_["selected"] for bin_ in hist) == 2

        chained = joins.run(opened["dataset_id"],
                             [_step(_third_id, "third", ["group_label"])])
        assert chained["stats"]["engine"] == "aurora"
        second = datasets.open_dataset(
            chained["df"], "chained live join", capped=True,
            live_source=chained["live_source"])
        chained_out = datasets.query(
            second["dataset_id"],
            [{"column": "third → group_label", "kind": "categorical",
              "values": ["last"]}], [], page=0, page_size=5,
            entity_column="entity_id")
        assert (chained_out["filtered"], chained_out["entity"]["filtered"]) == (2, 1)

        long_alias = "a" * 70
        long_join = joins.run(left_id, [_step(right_id, long_alias, ["tag"])])
        long_dataset = datasets.open_dataset(
            long_join["df"], "long-name live join", capped=True,
            live_source=long_join["live_source"])
        nested = joins.run(long_dataset["dataset_id"],
                           [_step(_third_id, "third", ["group_label"])])
        assert nested["stats"]["total_rows"] == 120003
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql(f'DROP TABLE IF EXISTS public."{third}"')
            conn.exec_driver_sql(f'DROP TABLE IF EXISTS public."{right}"')
            conn.exec_driver_sql(f'DROP TABLE IF EXISTS public."{left}"')
        datasets._store.clear()


def test_live_query_rejects_unknown_columns(engine, monkeypatch):
    monkeypatch.setattr(joins.db, "get_engine_for_resource", lambda _rid: engine)
    left_id, right_id, _, left, right, third = _source_tables(engine)
    try:
        joined = joins.run(left_id, [_step(right_id, "right", ["tag"])])
        dataset = datasets.open_dataset(joined["df"], "live join", capped=True,
                                       live_source=joined["live_source"])
        with pytest.raises(ValueError, match="Unknown filter column"):
            datasets.query(dataset["dataset_id"],
                           [{"column": "missing", "kind": "categorical",
                             "values": ["x"]}], [], entity_column="entity_id")
        with pytest.raises(ValueError, match="Unknown entity column"):
            datasets.query(dataset["dataset_id"], [], [], entity_column="missing")
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql(f'DROP TABLE IF EXISTS public."{third}"')
            conn.exec_driver_sql(f'DROP TABLE IF EXISTS public."{right}"')
            conn.exec_driver_sql(f'DROP TABLE IF EXISTS public."{left}"')
        datasets._store.clear()
