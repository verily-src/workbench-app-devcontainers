"""End to end: set an extract's refresh schedule in the tab, let the scheduler
run it against real PostgreSQL, and see the outcome in the extract bar."""
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


def _wait_status(table, status, timeout=30):
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


def test_schedule_extract_refresh_and_see_last_run(page: Page, sched_app, monkeypatch):
    url, engine = sched_app
    monkeypatch.setattr(main.extract_scheduler, "resources", lambda: [RID])
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE public.sched_source AS "
                          "SELECT g AS person_id FROM generate_series(1, 25) AS g"))
    recipe = {"kind": "aurora", "resource_id": RID, "table": "sched_source"}
    extracts.write({"df": pd.DataFrame({"person_id": range(25)})}, RID, "sched_cohort",
                   "Scheduled cohort", recipe)
    db.list_aurora_tables.invalidate()

    page.clock.install()
    page.goto(url)
    page.get_by_label("Source type", exact=True).select_option("aurora")
    page.get_by_label("Datasource", exact=True).select_option(f"aurora:{RID}")
    table = page.get_by_label("Table", exact=True)
    expect(table.locator("option", has_text="sched_cohort")).to_have_count(1, timeout=15000)
    values = table.locator("option").evaluate_all("els => els.map(e => e.value)")
    table.select_option(next(v for v in values if v.endswith("sched_cohort")))
    page.get_by_role("button", name="Load table").click()
    bar = page.get_by_role("group", name="Extract")
    expect(bar).to_have_attribute("title", re.compile("25 rows"), timeout=30000)

    # Daily at a set time: the label shows the schedule and the time left.
    bar.get_by_role("button", name="Refresh schedule").click()
    editor = page.get_by_role("group", name="Refresh schedule")
    editor.get_by_label("Repeat").select_option("daily")
    editor.get_by_label("Time").fill("06:30")
    editor.get_by_role("button", name="Save schedule").click()
    expect(editor).to_be_hidden()
    schedule_button = bar.get_by_role("button", name="Refresh schedule")
    expect(schedule_button).to_contain_text(re.compile(r"Daily at 06:30 · next in \d+[mh]"))
    info = extracts.info(RID, "sched_cohort")
    assert info["schedule"]["every"] == "daily" and info["schedule"]["hour"] == 6
    assert info["schedule"]["minute"] == 30 and info["schedule"]["tz"]

    # Switch to hourly; then run the scheduler as if the next run were due.
    schedule_button.click()
    editor.get_by_label("Repeat").select_option("hourly")
    editor.get_by_label("Minute past the hour").fill("15")
    editor.get_by_role("button", name="Save schedule").click()
    expect(schedule_button).to_contain_text(re.compile(r"Hourly at :15 · next in"))
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO public.sched_source SELECT g FROM generate_series(26, 40) g"))
    info = extracts.info(RID, "sched_cohort")
    assert ("schedres", "sched_cohort", "submitted") in _tick_at(info["next_run_at"])
    _wait_status("sched_cohort", "ok")
    page.clock.fast_forward(61_000)          # the tab polls the extract while scheduled
    expect(bar).to_have_attribute("title", re.compile("40 rows"), timeout=10000)
    expect(page.locator(".hero .count")).to_have_text("40", timeout=10000)  # the tab requeried
    schedule_button.click()
    expect(editor).to_contain_text("Last scheduled run: ok")
    page.keyboard.press("Escape")

    # A failing run keeps the old rows and shows why.
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE public.sched_source"))
    info = extracts.info(RID, "sched_cohort")
    _tick_at(info["next_run_at"])
    failed = _wait_status("sched_cohort", "failed")
    assert failed["rows"] == 40
    page.clock.fast_forward(61_000)
    warning = bar.get_by_role("status").filter(has_text="Scheduled refresh failed")
    expect(warning).to_be_visible(timeout=10000)
    expect(warning).to_have_attribute("title", re.compile(r"\S"))

    # Off clears it.
    schedule_button.click()
    editor.get_by_label("Repeat").select_option("off")
    editor.get_by_role("button", name="Save schedule").click()
    expect(schedule_button).to_have_text(re.compile(r"^Schedule"))
    assert extracts.info(RID, "sched_cohort")["next_run_at"] is None
