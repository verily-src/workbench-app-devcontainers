"""Extracts write every row (no 100k cap), replace atomically, and refresh."""
import time
import threading
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
    assert extracts.info("res", table)["recipe"] == recipe  # Data Builder reopens it


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
    ds = datasets.open_dataset(_frame(), "joined tab", capped=False)
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


def test_partial_source_cannot_create_or_refresh_extract(on_target):
    table = _name()
    recipe = {"kind": "aurora", "resource_id": "res", "table": "person"}
    extracts.write({"df": _frame(10)}, "res", table, "Existing", recipe)
    closed = []
    for partial in ({"df": _frame(3), "capped": True},
                    {"disk_source": {"path": "unused"}, "capped": True}):
        with pytest.raises(extracts.IncompleteSource):
            extracts.refresh("res", table, lambda _: {"dataset_id": "partial"},
                             lambda _: partial, closed.append)
        assert _count(on_target, table) == 10
    assert closed == ["partial", "partial"]

    ds = datasets.open_dataset(_frame(3), "partial join", capped=True)
    try:
        client = TestClient(main.app)
        new_table = _name()
        job = _wait(client, client.post("/api/data-jobs/extract", json={
            "dataset_id": ds["dataset_id"], "resource_id": "res", "table": new_table}).json())
        assert job["status"] == "failed" and job["status_code"] == 413
        with on_target.connect() as conn:
            assert not extracts._table_exists(conn, new_table)
    finally:
        datasets.close_dataset(ds["dataset_id"])


def test_new_plain_table_created_during_extract_is_preserved(on_target):
    table = _name()

    def create_destination(_rows):
        with on_target.begin() as conn:
            conn.execute(text(f'CREATE TABLE public."{table}" AS SELECT 42 AS keep'))

    with pytest.raises(extracts.ExtractExists):
        extracts.write({"df": _frame(3)}, "res", table, "Extract", None,
                       progress=create_destination)
    with on_target.connect() as conn:
        assert conn.execute(text(f'SELECT keep FROM public."{table}"')).scalar_one() == 42
    assert extracts.info("res", table) is None
    assert _tmp_tables(on_target) == 0


def test_concurrent_new_extracts_do_not_overwrite_each_other(on_target):
    table = _name()
    staged = threading.Barrier(2)
    outcomes = []

    def create(n):
        try:
            extracts.write({"df": _frame(n)}, "res", table, "Concurrent", None,
                           progress=lambda _: staged.wait(timeout=10))
            outcomes.append(("created", n))
        except extracts.ExtractExists:
            outcomes.append(("conflict", n))

    threads = [threading.Thread(target=create, args=(n,)) for n in (3, 5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert all(not thread.is_alive() for thread in threads)
    assert sorted(kind for kind, _ in outcomes) == ["conflict", "created"]
    assert _count(on_target, table) == next(n for kind, n in outcomes if kind == "created")


def test_recreated_table_does_not_inherit_extract_identity(on_target):
    table = _name()
    recipe = {"kind": "aurora", "resource_id": "res", "table": "person"}
    extracts.write({"df": _frame(3)}, "res", table, "Original", recipe)
    with on_target.begin() as conn:
        conn.execute(text(f'DROP TABLE public."{table}"'))
        conn.execute(text(f'CREATE TABLE public."{table}" AS SELECT 42 AS keep'))
    with pytest.raises(extracts.ExtractExists):
        extracts.write({"df": _frame(4)}, "res", table, "New", recipe)
    with pytest.raises(extracts.ExtractExists):
        extracts.refresh("res", table, lambda _: {"dataset_id": "fresh"},
                         lambda _: {"df": _frame(4)}, lambda _: None)
    with on_target.connect() as conn:
        assert conn.execute(text(f'SELECT keep FROM public."{table}"')).scalar_one() == 42
    extracts.write({"df": _frame(4)}, "res", table, "New", recipe, replace=True)
    assert _count(on_target, table) == 4
    extracts.refresh("res", table, lambda _: {"dataset_id": "fresh"},
                     lambda _: {"df": _frame(5)}, lambda _: None)
    assert _count(on_target, table) == 5


def test_table_recreated_during_extract_is_preserved(on_target):
    table = _name()
    extracts.write({"df": _frame(3)}, "res", table, "Original", None)

    def replace_destination(_rows):
        with on_target.begin() as conn:
            conn.execute(text(f'DROP TABLE public."{table}"'))
            conn.execute(text(f'CREATE TABLE public."{table}" AS SELECT 42 AS keep'))

    with pytest.raises(extracts.ExtractExists):
        extracts.write({"df": _frame(4)}, "res", table, "New", None,
                       progress=replace_destination)
    with on_target.connect() as conn:
        assert conn.execute(text(f'SELECT keep FROM public."{table}"')).scalar_one() == 42


def test_legacy_unmarked_extract_needs_explicit_replacement(on_target):
    table = _name()
    recipe = {"kind": "aurora", "resource_id": "res", "table": "person"}
    extracts.write({"df": _frame(3)}, "res", table, "Original", recipe)
    with on_target.begin() as conn:
        conn.execute(text(f'COMMENT ON TABLE public."{table}" IS NULL'))
    assert extracts.info("res", table)["recipe"] == recipe
    with pytest.raises(extracts.ExtractExists, match="cannot be verified"):
        extracts.refresh("res", table, lambda _: {"dataset_id": "fresh"},
                         lambda _: {"df": _frame(4)}, lambda _: None)
    assert _count(on_target, table) == 3
    identity = extracts.info("res", table)["identity_token"]
    extracts.refresh("res", table, lambda _: {"dataset_id": "fresh"},
                     lambda _: {"df": _frame(4)}, lambda _: None,
                     replace_unverified=True, identity_token=identity)
    extracts.refresh("res", table, lambda _: {"dataset_id": "fresh"},
                     lambda _: {"df": _frame(5)}, lambda _: None)
    assert _count(on_target, table) == 5


def test_legacy_confirmation_does_not_authorize_a_different_table(on_target):
    table = _name()
    recipe = {"kind": "aurora", "resource_id": "res", "table": "person"}
    extracts.write({"df": _frame(3)}, "res", table, "Original", recipe)
    with on_target.begin() as conn:
        conn.execute(text(f'COMMENT ON TABLE public."{table}" IS NULL'))
    identity = extracts.info("res", table)["identity_token"]
    with on_target.begin() as conn:
        conn.execute(text(f'DROP TABLE public."{table}"'))
        conn.execute(text(f'CREATE TABLE public."{table}" AS SELECT 42 AS keep'))
    with pytest.raises(extracts.ExtractExists, match="changed"):
        extracts.refresh("res", table, lambda _: {"dataset_id": "fresh"},
                         lambda _: {"df": _frame(4)}, lambda _: None,
                         replace_unverified=True, identity_token=identity)
    with on_target.connect() as conn:
        assert conn.execute(text(f'SELECT keep FROM public."{table}"')).scalar_one() == 42


def test_legacy_confirmation_rechecks_registry_at_swap(on_target):
    table = _name()
    recipe = {"kind": "aurora", "resource_id": "res", "table": "person"}
    extracts.write({"df": _frame(3)}, "res", table, "Original", recipe)
    with on_target.begin() as conn:
        conn.execute(text(f'COMMENT ON TABLE public."{table}" IS NULL'))
    identity = extracts.info("res", table)["identity_token"]

    def change_registry(_rows):
        with on_target.begin() as conn:
            conn.execute(text("UPDATE public._studio_extracts SET created_at = created_at + interval '1 second' "
                              "WHERE table_name = :table"), {"table": table})

    with pytest.raises(extracts.ExtractExists, match="changed"):
        extracts.refresh("res", table, lambda _: {"dataset_id": "fresh"},
                         lambda _: {"df": _frame(4)}, lambda _: None,
                         progress=change_registry, replace_unverified=True, identity_token=identity)
    assert _count(on_target, table) == 3


def test_queued_confirmed_refresh_rejects_replaced_table(on_target, monkeypatch):
    table = _name()
    recipe = {"kind": "aurora", "resource_id": "res", "table": "person"}
    extracts.write({"df": _frame(3)}, "res", table, "Original", recipe)
    with on_target.begin() as conn:
        conn.execute(text(f'COMMENT ON TABLE public."{table}" IS NULL'))
    client = TestClient(main.app)
    identity = client.get("/api/extracts/info", params={"resource_id": "res", "table": table}).json()["extract"]["identity_token"]
    with on_target.begin() as conn:
        conn.execute(text(f'DROP TABLE public."{table}"'))
        conn.execute(text(f'CREATE TABLE public."{table}" AS SELECT 42 AS keep'))
    source = datasets.open_dataset(_frame(4), "fresh", capped=False)
    monkeypatch.setattr(main, "open_dataset", lambda _: source)
    job = _wait(client, client.post("/api/data-jobs/refresh_extract", json={
        "resource_id": "res", "table": table, "replace_unverified": True,
        "identity_token": identity}).json())
    assert job["status"] == "failed" and job["status_code"] == 409
    with on_target.connect() as conn:
        assert conn.execute(text(f'SELECT keep FROM public."{table}"')).scalar_one() == 42


def _column_type(engine, table, column):
    with engine.connect() as conn:
        return conn.execute(text(
            "SELECT data_type FROM information_schema.columns WHERE table_schema = 'public' "
            "AND table_name = :t AND column_name = :c"), {"t": table, "c": column}).scalar_one()


def test_duckdb_nullable_bigint_ids_stay_exact(on_target, tmp_path):
    path = str(tmp_path / "ids.duckdb")
    con = duckdb.connect(path)
    con.execute("CREATE TABLE data AS SELECT * FROM (VALUES (9007199254740993::BIGINT, 1.25::DECIMAL(10,2)), "
                "(NULL, NULL)) AS t(id, amount)")
    con.close()
    table = _name()
    extracts.write({"disk_source": {"path": path, "table": "data", "columns": ["id", "amount"]}},
                   "res", table, "ids", None)
    with on_target.connect() as conn:
        rows = conn.execute(text(f'SELECT id, amount FROM public."{table}" ORDER BY id NULLS LAST')).all()
    assert rows[0][0] == 9007199254740993 and str(rows[0][1]) == "1.25" and rows[1] == (None, None)
    assert _column_type(on_target, table, "id") == "bigint"
    assert _column_type(on_target, table, "amount") == "numeric"


def test_streamed_live_rows_keep_integer_and_numeric_types(on_target):
    table = _name()
    live = {"resource_id": "other", "params": {},
            "sql": "SELECT * FROM (VALUES (9007199254740993::bigint, 1.25::numeric(10,2)), "
                   "(NULL::bigint, NULL::numeric)) AS t(id, amount)",
            "columns": {"id": "id", "amount": "amount"}}
    extracts.write({"live_source": live}, "res", table, "ids", None)
    with on_target.connect() as conn:
        rows = conn.execute(text(f'SELECT id, amount FROM public."{table}" ORDER BY id NULLS LAST')).all()
    assert rows[0][0] == 9007199254740993 and str(rows[0][1]) == "1.25" and rows[1] == (None, None)
    assert _column_type(on_target, table, "id") == "bigint"


def test_cancelled_extract_keeps_the_old_table(on_target):
    import query_cancellation
    table = _name()
    extracts.write({"df": _frame(10)}, "res", table, "t", None)
    scope = query_cancellation.Scope()
    token = query_cancellation.current.set(scope)
    try:
        with pytest.raises(query_cancellation.Cancelled):
            extracts.write({"df": _frame(ROWS)}, "res", table, "t", None,
                           progress=lambda rows: scope.cancel())
    finally:
        query_cancellation.current.reset(token)
    assert _count(on_target, table) == 10 and _tmp_tables(on_target) == 0


def test_capped_bigquery_sample_is_not_extracted(on_target):
    """A large BigQuery table opens as a ROW_CAP sample in memory; an extract of it
    would miss rows, so the job fails with 400 and writes no table. A capped
    in-memory join (every row already in memory) still extracts."""
    client = TestClient(main.app)
    table = _name()
    ds = datasets.open_dataset(_frame(10), "pub / big", capped=True)
    datasets.get(ds["dataset_id"])["source_ref"] = {"kind": "bq", "resource_id": "bq:pub", "table": "big"}
    try:
        failed = _wait(client, client.post("/api/data-jobs/extract", json={
            "dataset_id": ds["dataset_id"], "resource_id": "res", "table": table}).json())
        assert failed["status"] == "failed" and failed["status_code"] == 400, failed
        assert "sample" in failed["error"]
        with on_target.connect() as conn:
            assert not extracts._table_exists(conn, table)
    finally:
        datasets.close_dataset(ds["dataset_id"])
