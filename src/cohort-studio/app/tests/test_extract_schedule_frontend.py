"""Extract refresh controls and scheduled refresh restrictions."""
import re
import socket
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import psycopg
import pytest
import uvicorn
from playwright.sync_api import Page, expect
from sqlalchemy import create_engine, text

import catalog
import datasets
import db
import extracts
from extract_schedule import next_run
import main
from tests.conftest import remount_mcp_if_started

pytestmark = pytest.mark.e2e

APP_DIR = Path(__file__).parent.parent
RID = "schedres"


@pytest.fixture(scope="module")
def sched_app(pg):
    if not (APP_DIR / "static" / "index.html").exists():
        pytest.skip("frontend is not built")
    if pg["url"]("a") == pg["url"]("b"):
        pytest.skip("needs a local PostgreSQL to create a database")
    name = f"sched_ui_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(f"{pg['dsn']} dbname=postgres", autocommit=True) as conn:
        conn.execute(f"CREATE DATABASE {name}")
    engine = create_engine(pg["url"](name))
    patches = pytest.MonkeyPatch()
    patches.setattr(db, "resources_ready", lambda: True)
    patches.setattr(db, "warm_resource_cache", lambda: None)
    patches.setattr(db, "retry_if_empty", lambda: None)
    patches.setattr(db, "list_aurora_resources", lambda *a, **k: [{"id": RID}])
    patches.setattr(db, "list_s3_folders", lambda *a, **k: [])
    patches.setattr(db, "list_bq_datasets", lambda *a, **k: [])
    patches.setattr(db, "get_engine_for_resource", lambda _rid: engine)
    patches.setattr(catalog, "discover", lambda _folders, *a, **k: ([], False))
    db.list_aurora_tables.invalidate()
    db.fetch_aurora_table.invalidate()
    remount_mcp_if_started()
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(main.app, log_level="error", lifespan="on"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and not server.started:
        time.sleep(0.05)
    assert server.started, "uvicorn did not start"
    try:
        yield f"http://127.0.0.1:{port}", engine
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        datasets._store.clear()
        db.list_aurora_tables.invalidate()
        db.fetch_aurora_table.invalidate()
        patches.undo()
        engine.dispose()


def _wait_status(table, status, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        info = extracts.info(RID, table)
        if info["last_run_status"] == status:
            return info
        time.sleep(0.1)
    raise AssertionError(extracts.info(RID, table))


def _tick_at(iso):
    when = datetime.fromisoformat(iso) + timedelta(seconds=1)
    return main.extract_scheduler.tick(when)


def _load_table(page, name):
    """Open `name` Live from Data Builder once the listing has it."""
    from tests.ui_helpers import load_table
    load_table(page, f"aurora:{RID}", name, timeout=60000)


def test_legacy_extract_requires_confirmation_before_refresh(page: Page, sched_app):
    url, engine = sched_app
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE public.legacy_source AS SELECT 1 AS person_id UNION ALL SELECT 2"))
    recipe = {"kind": "aurora", "resource_id": RID, "table": "legacy_source"}
    extracts.write({"df": pd.DataFrame({"person_id": [1]})}, RID, "legacy_extract", "Legacy", recipe)
    with engine.begin() as conn:
        conn.execute(text("COMMENT ON TABLE public.legacy_extract IS NULL"))
    db.list_aurora_tables.invalidate()
    page.goto(url)
    _load_table(page, "legacy_extract")
    bar = page.get_by_role("group", name="Extract")
    expect(bar).to_contain_text("Table identity unverified", timeout=60000)
    with page.expect_event("dialog") as dialog:
        bar.get_by_role("button", name="Refresh extract").click()
    dialog.value.dismiss()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM public.legacy_extract")).scalar_one() == 1
    with page.expect_event("dialog") as dialog:
        bar.get_by_role("button", name="Refresh extract").click()
    dialog.value.accept()
    try:
        expect(bar).to_have_attribute("title", re.compile("2 rows"), timeout=15000)
    except AssertionError as exc:
        raise AssertionError(page.locator("body").inner_text()) from exc
    assert extracts.info(RID, "legacy_extract")["identity_verified"] is True


def test_existing_schedule_is_disabled(page: Page, sched_app):
    url, engine = sched_app
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE public.sched_source AS SELECT 1 AS person_id"))
    recipe = {"kind": "aurora", "resource_id": RID, "table": "sched_source"}
    extracts.write({"df": pd.DataFrame({"person_id": [1]})}, RID, "sched_cohort", "Cohort", recipe)
    schedule = {"every": "daily", "hour": 6, "minute": 0, "tz": "UTC"}
    extracts.set_schedule(RID, "sched_cohort", schedule, next_run(schedule, datetime.now().astimezone()))
    db.list_aurora_tables.invalidate()
    page.goto(url)
    _load_table(page, "sched_cohort")
    bar = page.get_by_role("group", name="Extract")
    expect(bar).to_contain_text("Scheduled refresh is disabled.", timeout=60000)
    expect(bar.get_by_role("button", name="Refresh schedule")).to_have_count(0)
    expect(bar.get_by_role("button", name="Refresh extract")).to_be_enabled()
    response = page.request.put(f"{url}/api/extracts/schedule", data={
        "resource_id": RID, "table": "sched_cohort", "schedule": {"every": "off"}})
    assert response.status == 403
