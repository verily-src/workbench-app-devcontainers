"""Studio Agent update_dashboard, aggregate and compare_cohorts tools."""
import json
import time

import duckdb
import pandas as pd
import pytest
from sqlalchemy import text

import agent_artifacts
import agent_mode_api
import agent_store as store_module
import datasets
import main
from tests.test_agent_store import agent_store  # noqa: F401  (fixture)
from tests.test_studio_agent_api import workspace  # noqa: F401  (fixture)

OWNER = "analysis-owner"
VALUES_REF = {"kind": "aurora", "resource_id": "omopdb", "schema": "public", "table": "values"}
PERSON = {"kind": "aurora", "resource_id": "omopdb", "schema": "cdm", "table": "person"}
METRICS = [{"op": "count"}, {"op": "count", "column": "value"}, {"op": "mean", "column": "value"},
           {"op": "median", "column": "value"}, {"op": "min", "column": "value"},
           {"op": "max", "column": "value"}, {"op": "distinct", "column": "pid"}]


@pytest.fixture
def frame():
    return pd.DataFrame({"grp": ["A", "A", "B", None, "B", "B"],
                         "value": [1.0, 3.0, 5.0, 4.0, None, 9.0],
                         "pid": [1, 1, 2, 3, 4, 4]})


@pytest.fixture
def ops(monkeypatch):
    monkeypatch.setattr(main, "datasources", lambda: {"ready": True, "sources": []})
    agent_mode_api._dashboards.clear()
    yield agent_mode_api.Operations(OWNER)
    agent_mode_api._dashboards.clear()


def _register(dataset_id, filters=(), charts=()):
    agent_mode_api._dashboards[dataset_id] = {
        "owner": OWNER, "title": "Values", "source_ref": VALUES_REF,
        "filters": list(filters), "charts": list(charts), "created": time.monotonic()}


def _memory(frame):
    return datasets.open_dataset(frame, "values")


def _disk(frame, tmp_path):
    path = str(tmp_path / "values.duckdb")
    con = duckdb.connect(path)
    con.register("frame", frame)
    con.execute("CREATE TABLE data AS SELECT * FROM frame")
    con.close()
    return datasets.open_dataset(frame, "values", disk_source={
        "path": path, "table": "data", "columns": list(frame.columns), "rows": len(frame)})


@pytest.fixture
def postgres_values(engine, monkeypatch):
    import database
    monkeypatch.setattr(database, "get_engine_for_resource", lambda rid: engine)
    with engine.begin() as con:
        con.execute(text("CREATE TABLE public.agent_values (grp text, value double precision, pid bigint)"))
        con.execute(text("INSERT INTO public.agent_values VALUES ('A',1,1),('A',3,1),('B',5,2),"
                         "(NULL,4,3),('B',NULL,4),('B',9,4)"))
    yield lambda: main._open_source({"kind": "aurora", "resource_id": "omopdb",
                                     "schema": "public", "table": "agent_values"})
    with engine.begin() as con:
        con.execute(text("DROP TABLE public.agent_values"))


@pytest.mark.parametrize("path", ["memory", "disk", "postgres"])
def test_aggregate_runs_on_each_query_path(path, frame, ops, tmp_path, request):
    opened = (_memory(frame) if path == "memory" else _disk(frame, tmp_path) if path == "disk"
              else request.getfixturevalue("postgres_values")())
    did = opened["dataset_id"]
    _register(did)
    try:
        result = ops.aggregate(did, ["grp"], json.dumps(METRICS), "[]", 25)
        assert result["columns"] == ["grp", "rows", "count(value)", "mean(value)", "median(value)",
                                     "min(value)", "max(value)", "distinct(pid)"]
        assert result["rows"] == [["B", 3, 2, 7.0, 7.0, 5.0, 9.0, 2],
                                  ["A", 2, 2, 2.0, 2.0, 1.0, 3.0, 1],
                                  [None, 1, 1, 4.0, 4.0, 4.0, 4.0, 1]]
        assert result["total_groups"] == 3 and result["rows_considered"] == 6
        assert not result["truncated"]
        assert result["scope"] == ("database" if path == "postgres" else "loaded")
        assert result["sampled"] is False and result["scope_note"]
        limited = ops.aggregate(did, ["grp"], '[{"op":"count"}]',
                                '[{"column":"value","kind":"range","min":2,"max":10}]', 1)
        assert limited["rows"] == [["B", 2]] and limited["truncated"]
        assert limited["total_groups"] == 3 and limited["rows_considered"] == 4
        overall = ops.aggregate(did, [], '[{"op":"mean","column":"value"}]', "[]", 25)
        assert overall["rows"] == [[6, 4.4]] and overall["total_groups"] == 1
    finally:
        datasets.close_dataset(did)


def test_aggregate_applies_saved_filters_and_validates(frame, ops):
    opened = _memory(frame)
    did = opened["dataset_id"]
    _register(did, filters=[{"column": "grp", "kind": "categorical", "values": ["A"]}])
    try:
        result = ops.aggregate(did, ["grp"], '[{"op":"count"}]', "[]", 25)
        assert result["rows"] == [["A", 2]] and result["filters"][0]["values"] == ["A"]
        for metrics in ('[{"op":"mean"}]', '[{"op":"sum","column":"value"}]',
                        '[{"op":"count","column":"value","extra":1}]', "[]",
                        '[{"op":"min","column":"value"},{"op":"min","column":"value"}]'):
            with pytest.raises(ValueError):
                ops.aggregate(did, [], metrics, "[]", 25)
        with pytest.raises(ValueError, match="Unknown column"):
            ops.aggregate(did, ["missing"], '[{"op":"count"}]', "[]", 25)
        with pytest.raises(ValueError, match="your Agent session"):
            agent_mode_api.Operations("someone-else").aggregate(did, [], '[{"op":"count"}]', "[]", 25)
    finally:
        datasets.close_dataset(did)


@pytest.mark.parametrize("path", ["memory", "disk", "postgres"])
def test_compare_cohorts_reports_counts_and_selected_columns(path, frame, ops, tmp_path, request):
    opened = (_memory(frame) if path == "memory" else _disk(frame, tmp_path) if path == "disk"
              else request.getfixturevalue("postgres_values")())
    did = opened["dataset_id"]
    _register(did)
    try:
        result = ops.compare_cohorts(
            did, '[{"column":"grp","kind":"categorical","values":["A"]}]',
            '[{"column":"grp","kind":"categorical","values":["B"]}]', ["value"])
        assert (result["a_n"], result["b_n"], result["n_overlap"]) == (2, 3, 0)
        assert [r["column"] for r in result["results"]] == ["value"]
        numeric = result["results"][0]
        assert numeric["a"]["n"] == 2 and numeric["b"]["n"] == 2
        assert result["scope"] == ("database" if path == "postgres" else "loaded")
        with pytest.raises(ValueError, match="at least one group"):
            ops.compare_cohorts(did, "[]", "[]", ["value"])
        with pytest.raises(ValueError, match="Unknown column"):
            ops.compare_cohorts(did, '[{"column":"pid","kind":"range","min":1,"max":2}]', "[]",
                                ["missing"])
    finally:
        datasets.close_dataset(did)


def test_update_dashboard_refines_in_place(frame, ops, agent_store, monkeypatch):
    monkeypatch.setattr(store_module, "AgentStore", lambda: agent_store)
    opened = _memory(frame)
    did = opened["dataset_id"]
    original = [{"column": "value", "kind": "range", "min": 0.0, "max": 10.0},
                {"column": "grp", "kind": "categorical", "values": ["A", "B"]}]
    _register(did, filters=original, charts=[{"kind": "bar", "x": "grp"}])
    agent_artifacts.save(OWNER, {"dataset_id": did, "title": "Values",
        "source_ref": VALUES_REF, "filters": original,
        "charts": [{"kind": "bar", "x": "grp"}]})
    try:
        for _ in range(4):
            ops.actions.append({"dataset": {"dataset_id": "other"}, "title": "x"})
        result = ops.update_dashboard(
            did, '[{"kind":"bar","x":"grp"},{"kind":"histogram","x":"value"}]',
            '[{"column":"value","kind":"range","min":4,"max":10}]', ["grp"])
        assert result["status"] == "ready_to_apply"
        assert result["filters"] == [{"column": "value", "kind": "range", "min": 4.0, "max": 10.0}]
        assert result["filtered"] == 3 and len(result["charts"]) == 2
        action = ops.actions[-1]
        assert action["update"] is True and action["dataset"]["dataset_id"] == did
        assert action["charts"] == [{"kind": "bar", "x": "grp"}, {"kind": "histogram", "x": "value"}]
        assert agent_mode_api._dashboards[did]["filters"] == result["filters"]
        assert agent_artifacts.get(OWNER, did)["filters"] == result["filters"]
        ops.update_dashboard(did, "[]", '[{"column":"pid","kind":"range","min":1,"max":2}]', [])
        updates = [a for a in ops.actions if a.get("update")]
        assert len(updates) == 1 and len(updates[0]["filters"]) == 2
        with pytest.raises(ValueError, match="at least one change"):
            ops.update_dashboard(did, '[{"kind":"bar","x":"grp"}]', "[]", [])
        with pytest.raises(ValueError, match="without a saved filter"):
            ops.update_dashboard(did, "[]", "[]", ["grp"])
        with pytest.raises(ValueError, match="one added filter per column"):
            ops.update_dashboard(did, "[]", json.dumps([
                {"column": "pid", "kind": "range", "min": 1, "max": 2}] * 2), [])
        with pytest.raises(ValueError, match="your Agent session"):
            agent_mode_api.Operations("someone-else").update_dashboard(did, "[]", "[]", ["grp"])
        with pytest.raises(ValueError, match="eight charts"):
            ops.update_dashboard(did, json.dumps([{"kind": "histogram", "x": "value", "title": f"t{b}"}
                                                  for b in range(5, 12)]), "[]", [])
    finally:
        datasets.close_dataset(did)


def test_live_dashboard_analysis_matches_database(workspace, ref):
    ops = agent_mode_api.Operations("live-analysis-owner")
    ops.inspect_table(json.dumps(PERSON))
    built = ops.build_dashboard(json.dumps(PERSON), "People")
    did = built["dataset_id"]
    result = ops.aggregate(did, ["gender_concept_id"], json.dumps([
        {"op": "mean", "column": "year_of_birth"}, {"op": "median", "column": "year_of_birth"},
        {"op": "min", "column": "year_of_birth"}, {"op": "max", "column": "year_of_birth"},
        {"op": "distinct", "column": "person_id"}]), "[]", 50)
    assert result["scope"] == "database" and result["rows_considered"] == 100
    people = ref["person"]
    expected = people.groupby("gender_concept_id").agg(
        rows=("person_id", "size"), mean=("year_of_birth", "mean"),
        median=("year_of_birth", "median"), min=("year_of_birth", "min"),
        max=("year_of_birth", "max"), distinct=("person_id", "nunique"))
    for gender, rows, mean, median, low, high, distinct in result["rows"]:
        row = expected.loc[int(gender)]
        assert (rows, distinct) == (row["rows"], row["distinct"])
        assert mean == pytest.approx(row["mean"]) and median == pytest.approx(row["median"])
        assert (low, high) == (row["min"], row["max"])
    compared = ops.compare_cohorts(
        did, '[{"column":"gender_concept_id","kind":"categorical","values":["8507"]}]',
        '[{"column":"gender_concept_id","kind":"categorical","values":["8532"]}]',
        ["year_of_birth"])
    assert compared["a_n"] == int((people.gender_concept_id == 8507).sum())
    assert compared["b_n"] == int((people.gender_concept_id == 8532).sum())
    assert compared["scope"] == "database"
    updated = ops.update_dashboard(did, '[{"kind":"histogram","x":"year_of_birth"}]',
        '[{"column":"year_of_birth","kind":"range","min":1900,"max":1950}]', [])
    assert updated["filtered"] == int(people.year_of_birth.between(1900, 1950).sum())
    assert ops.actions[-1]["update"] and ops.actions[-1]["dataset"]["query_scope"] == "database"
