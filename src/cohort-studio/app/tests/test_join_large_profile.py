import time

import pandas as pd
import pytest

import datasets
import joins
import live_query
import query_cancellation


@pytest.mark.parametrize("threshold", [1_000_000, 2_000_000])
def test_large_live_join_opens_without_full_profiling(client, engine, monkeypatch, threshold):
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE public.join_profile_left AS SELECT n AS id, 1 AS k, CASE WHEN n <= 100 THEN NULL ELSE 'later' END AS later_value FROM generate_series(1, 1000) n")
        conn.exec_driver_sql("CREATE TABLE public.join_profile_right AS SELECT n AS id, 1 AS k FROM generate_series(1, 1000) n")
    monkeypatch.setattr(live_query.db, "get_engine_for_resource", lambda _rid: engine)
    monkeypatch.setattr(live_query, "TIMEOUT_MS", 1)
    monkeypatch.setattr(joins, "LARGE_JOIN_PROFILE_ROWS", threshold)
    ids = []
    try:
        for side in ("left", "right"):
            columns = {"id": "id", "k": "k", **({"later_value": "later_value"} if side == "left" else {})}
            frame = pd.DataFrame({"id": [1], "k": [1], **({"later_value": [None]} if side == "left" else {})})
            source = {"resource_id": "omopdb", "sql": f"SELECT * FROM public.join_profile_{side}",
                      "columns": columns, "params": {}}
            opened = datasets.open_dataset(frame, side,
                                           live_source=source, profile_source=False)
            ids.append(opened["dataset_id"])
            datasets.get(ids[-1])["source_ref"] = {"kind": "aurora", "resource_id": "omopdb",
                                                     "table": f"join_profile_{side}", "schema": "public"}
        started = client.post("/api/data-jobs/join", json={
            "left_id": ids[0], "right_id": ids[1], "left_on": "k", "right_on": "k", "how": "inner"})
        assert started.status_code == 202, started.text
        job_id = started.json()["job_id"]
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            job = client.get(f"/api/data-jobs/{job_id}").json()
            if job["status"] in ("complete", "failed"):
                break
            time.sleep(.05)
        assert job["status"] == "complete", job
        result = job["result"]
        ids.append(result["dataset_id"])
        assert result["query_scope"] == "database"
        assert result["join"]["total_rows"] == 1_000_000
        assert all(column.get("profile_sampled") for column in result["columns"])
        assert max(datasets.get(ids[-1])["df"]["id"]) < 900
        assert next(col for col in result["columns"] if col["name"] == "later_value")["filter_kind"] == "none"
        monkeypatch.setattr(live_query, "TIMEOUT_MS", 15000)
        response = client.post(f"/api/datasets/{ids[-1]}/query", json={"filters": [], "charts": []})
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 1_000_000
        response = client.post(f"/api/datasets/{ids[-1]}/query", json={
            "filters": [{"kind": "range", "column": "id", "min": 900, "max": 900}],
            "charts": [{"kind": "bar", "x": "k"}, {"kind": "histogram", "x": "id"}], "refresh": True})
        assert response.status_code == 200, response.text
        assert response.json()["filtered"] == 1000
        assert len(response.json()["charts"]) == 2
        assert all(col.get("profile_sampled") for col in response.json()["columns"])
        datasets.get(ids[-1])["profile_sampled"] = False
        monkeypatch.setattr(live_query, "TIMEOUT_MS", 1)
        saved = client.patch(f"/api/datasets/{ids[-1]}/columns", json={"columns": [
            {"name": "id", "label": "Person"}]})
        assert saved.status_code == 200, saved.text
        assert all(col.get("profile_sampled") for col in saved.json()["columns"])
        assert datasets.get(ids[-1])["profile_sampled"] is True
        monkeypatch.setattr(live_query, "TIMEOUT_MS", 15000)
        settings = client.patch(f"/api/datasets/{ids[-1]}/columns", json={"columns": [
            {"name": "later_value", "filter_kind": "categorical"}]})
        assert settings.status_code == 200, settings.text
        assert next(col for col in settings.json()["columns"] if col["name"] == "later_value")["filter_kind"] == "categorical"
        response = client.post(f"/api/datasets/{ids[-1]}/query", json={
            "filters": [{"kind": "categorical", "column": "later_value", "values": ["later"]}], "charts": []})
        assert response.status_code == 200, response.text
        assert response.json()["filtered"] == 900_000
        monkeypatch.setattr(live_query, "TIMEOUT_MS", 1)
        reopened = client.post("/api/datasets/open", json={"source_ref": result["source_ref"]})
        assert reopened.status_code == 200, reopened.text
        ids.append(reopened.json()["dataset_id"])
        assert all(col.get("profile_sampled") for col in reopened.json()["columns"])
        derived = client.post(f"/api/datasets/{ids[-1]}/derive", json={
            "op": "formula", "name": "ratio", "left": "k", "operator": "/", "right": "2"})
        assert derived.status_code == 200, derived.text
        assert all(col.get("profile_sampled") for col in derived.json()["columns"])
        derived_reopen = client.post("/api/datasets/open", json={"source_ref": derived.json()["source_ref"]})
        assert derived_reopen.status_code == 200, derived_reopen.text
        ids.append(derived_reopen.json()["dataset_id"])
        assert all(col.get("profile_sampled") for col in derived_reopen.json()["columns"])
        assert datasets.get(ids[-1])["bounded_join_profile"] is True
    finally:
        for dataset_id in ids:
            datasets.close_dataset(dataset_id)
        with engine.begin() as conn:
            conn.exec_driver_sql("DROP TABLE public.join_profile_left, public.join_profile_right")


def test_join_profile_only_falls_back_on_statement_timeout(engine, monkeypatch):
    monkeypatch.setattr(live_query.db, "get_engine_for_resource", lambda _rid: engine)
    source = {"resource_id": "omopdb", "sql": "SELECT x FROM public.missing_profile_table",
              "columns": {"x": "x"}, "params": {}}
    profiles = [{"name": "x", "filter_kind": "range", "dtype": "int64", "min": 0, "max": 1}]
    with pytest.raises(Exception, match="missing_profile_table"):
        live_query.profile_columns(source, profiles, bounded_join=True)
    scope = query_cancellation.Scope()
    scope.cancel()
    token = query_cancellation.current.set(scope)
    try:
        with pytest.raises(query_cancellation.Cancelled):
            live_query.profile_columns(source, profiles, bounded_join=True)
    finally:
        query_cancellation.current.reset(token)


def test_join_profile_stops_at_total_budget(engine, monkeypatch):
    monkeypatch.setattr(live_query.db, "get_engine_for_resource", lambda _rid: engine)
    monkeypatch.setattr(live_query, "JOIN_PROFILE_BUDGET_S", 0)
    source = {"resource_id": "omopdb", "sql": "SELECT 1 AS x", "columns": {"x": "x"}, "params": {}}
    profiles = [{"name": "x", "filter_kind": "range", "dtype": "int64", "min": 0, "max": 1}]
    assert live_query.profile_columns(source, profiles, bounded_join=True) == [{**profiles[0], "profile_sampled": True}]
