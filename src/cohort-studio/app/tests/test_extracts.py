"""Extracts write every row (no 100k cap), replace atomically, and refresh."""
import time
import uuid

import duckdb
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

import database as db
import datasets
import extracts
import main

ROWS = 150_000  # above the old 100,000-row export cap


@pytest.fixture(scope="module")
def target(pg):
    eng = create_engine(pg["url"]("empty"))
    yield eng
    eng.dispose()


@pytest.fixture
def on_target(target, monkeypatch):
    monkeypatch.setattr(db, "get_engine_for_resource", lambda rid: target)
    return target


def _name():
    return f"x_{uuid.uuid4().hex[:10]}"


def _count(engine, table):
    with engine.connect() as conn:
        return conn.execute(text(f'SELECT count(*) FROM public."{table}"')).scalar_one()


def _tmp_tables(engine):
    with engine.connect() as conn:
        return conn.execute(text(
            "SELECT count(*) FROM pg_tables WHERE schemaname = 'public' "
            "AND tablename LIKE '\\_studio\\_x\\_%'")).scalar_one()


def _frame(n=ROWS, offset=0):
    return pd.DataFrame({"person_id": range(offset, offset + n), "group": ["ab"[i % 2] for i in range(n)]})


def test_in_memory_extract_writes_every_row_and_records_it(on_target):
    table = _name()
    info = extracts.write({"df": _frame()}, "res", table, "My cohort", None)
    assert info["rows"] == ROWS and _count(on_target, table) == ROWS
    assert info["title"] == "My cohort" and info["refreshable"] is False
    assert extracts.info("res", table)["rows"] == ROWS
    assert _tmp_tables(on_target) == 0


def test_same_database_live_join_is_created_in_the_database(on_target, monkeypatch):
    table, src = _name(), _name()
    with on_target.begin() as conn:
        conn.execute(text(f'CREATE TABLE public."{src}" AS SELECT g AS person_id, g % 7 AS bucket '
                          f"FROM generate_series(1, {ROWS}) AS g"))
    live = {"resource_id": "res", "params": {"lo": 0},
            "sql": f'SELECT s.person_id, s.bucket FROM public."{src}" AS s WHERE s.person_id > :lo',
            "columns": {"person_id": "person_id", "bucket": "bucket"}}
    monkeypatch.setattr(extracts, "_write_batches",
                        lambda *a, **k: pytest.fail("same-database joins must not stream rows"))
    recipe = {"kind": "aurora", "resource_id": "res", "table": "person"}
    info = extracts.write({"live_source": live}, "res", table, "Live", recipe)
    assert info["rows"] == ROWS and _count(on_target, table) == ROWS
    assert info["refreshable"] is True


def test_live_source_from_another_database_streams_every_row(on_target, monkeypatch):
    table = _name()
    live = {"resource_id": "other", "params": {},
            "sql": "SELECT g AS person_id FROM pg_catalog.generate_series(1, 150000) AS g",
            "columns": {"person_id": "person_id"}}
    info = extracts.write({"live_source": live}, "res", table, "Streamed", None)
    assert info["rows"] == ROWS and _count(on_target, table) == ROWS


def test_duckdb_backed_join_streams_every_row(on_target, tmp_path):
    path = str(tmp_path / "joined.duckdb")
    con = duckdb.connect(path)
    con.execute(f"CREATE TABLE data AS SELECT range AS person_id, range % 3 AS k FROM range({ROWS})")
    con.close()
    table = _name()
    info = extracts.write({"disk_source": {"path": path, "table": "data",
                                           "columns": ["person_id", "k"]}},
                          "res", table, "Disk", None)
    assert info["rows"] == ROWS and _count(on_target, table) == ROWS


def test_existing_table_that_is_not_an_extract_is_not_overwritten(on_target):
    table = _name()
    with on_target.begin() as conn:
        conn.execute(text(f'CREATE TABLE public."{table}" AS SELECT 1 AS keep'))
    with pytest.raises(extracts.ExtractExists):
        extracts.write({"df": _frame(10)}, "res", table, "t", None)
    assert _count(on_target, table) == 1
    extracts.write({"df": _frame(10)}, "res", table, "t", None, replace=True)
    assert _count(on_target, table) == 10


def test_refresh_reruns_recipe_and_failed_refresh_keeps_old_rows(on_target, monkeypatch):
    table = _name()
    recipe = {"kind": "aurora", "resource_id": "res", "table": "person"}
    extracts.write({"df": _frame(10)}, "res", table, "Cohort", recipe)
    first = extracts.info("res", table)
    opened, closed = [], []

    def open_recipe(r):
        opened.append(r)
        return {"dataset_id": "fresh"}
    info = extracts.refresh("res", table, open_recipe, lambda _id: {"df": _frame(ROWS)},
                            closed.append)
    assert opened == [recipe] and closed == ["fresh"]
    assert info["rows"] == ROWS and _count(on_target, table) == ROWS
    assert info["title"] == "Cohort" and info["refreshed_at"] >= first["refreshed_at"]

    def broken(*_a, **_k):
        raise RuntimeError("source went away")
    monkeypatch.setattr(extracts, "_write_batches", broken)
    with pytest.raises(RuntimeError):
        extracts.refresh("res", table, open_recipe, lambda _id: {"df": _frame(5)}, closed.append)
    assert _count(on_target, table) == ROWS  # old extract intact
    assert closed[-1] == "fresh" and _tmp_tables(on_target) == 0


def test_refresh_without_recipe_and_unknown_table(on_target):
    table = _name()
    extracts.write({"df": _frame(3)}, "res", table, "Upload", None)
    with pytest.raises(extracts.NotRefreshable):
        extracts.refresh("res", table, lambda r: pytest.fail("no recipe"), None, None)
    with pytest.raises(LookupError):
        extracts.refresh("res", _name(), lambda r: None, None, None)


def test_forget_and_name_validation(on_target):
    table = _name()
    extracts.write({"df": _frame(3)}, "res", table, "t", None)
    extracts.forget("res", table)
    assert extracts.info("res", table) is None
    for bad in ("1abc", "a-b", "_studio_x_1", "x" * 64, 'a"; drop'):
        with pytest.raises(ValueError):
            extracts.validate_name(bad)


def _wait(client, job):
    for _ in range(200):
        if job["status"] not in ("queued", "running", "cancelling"):
            return job
        time.sleep(0.05)
        job = client.get(f"/api/data-jobs/{job['job_id']}").json()
    raise AssertionError(job)


def test_extract_and_refresh_jobs_over_the_api(on_target, monkeypatch):
    monkeypatch.setattr(main, "open_dataset", lambda req: {
        "dataset_id": "opened-extract", "source": req.source_ref.table if hasattr(req.source_ref, "table") else "t",
        "rows": 0, "columns": []})
    client = TestClient(main.app)
    table = _name()
    ds = datasets.open_dataset(_frame(), "joined tab")
    try:
        job = client.post("/api/data-jobs/extract", json={
            "dataset_id": ds["dataset_id"], "resource_id": "res", "table": table,
            "title": "Joined cohort"}).json()
        done = _wait(client, job)
        assert done["status"] == "complete", done
        assert done["result"]["extract"]["rows"] == ROWS
        assert done["result"]["extract"]["refreshable"] is False
        assert _count(on_target, table) == ROWS
        assert client.get("/api/extracts/info", params={"resource_id": "res", "table": table}
                          ).json()["extract"]["title"] == "Joined cohort"
        # An uploaded/unsaved source can't be rerun.
        failed = _wait(client, client.post("/api/data-jobs/refresh_extract", json={
            "resource_id": "res", "table": table}).json())
        assert failed["status"] == "failed" and failed["status_code"] == 400
        # A second extract to a plain table's name is refused (409).
        with on_target.begin() as conn:
            conn.execute(text(f'CREATE TABLE public."{table}_plain" AS SELECT 1 AS a'))
        clash = _wait(client, client.post("/api/data-jobs/extract", json={
            "dataset_id": ds["dataset_id"], "resource_id": "res", "table": f"{table}_plain"}).json())
        assert clash["status"] == "failed" and clash["status_code"] == 409
    finally:
        datasets.close_dataset(ds["dataset_id"])
