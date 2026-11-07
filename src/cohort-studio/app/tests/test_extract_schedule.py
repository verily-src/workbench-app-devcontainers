"""Scheduled extract refresh: schedule model, next-run times, the claim guard,
catch-up after downtime, and the real refresh job (real PostgreSQL)."""
import time
import uuid
from datetime import datetime, timedelta, timezone

import pandas as pd
import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

import data_jobs
import database as db
import datasets
import extract_schedule
import extracts
import main
from extract_schedule import next_run

UTC = timezone.utc
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
RECIPE = {"kind": "aurora", "resource_id": "res", "table": "person"}


def _new_database(pg):
    if pg["url"]("a") == pg["url"]("b"):
        pytest.skip("needs a local PostgreSQL to create databases")
    name = f"sched_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(f"{pg['dsn']} dbname=postgres", autocommit=True) as conn:
        conn.execute(f"CREATE DATABASE {name}")
    return create_engine(pg["url"](name))


@pytest.fixture(scope="module")
def sched_db(pg):
    eng = _new_database(pg)
    yield eng
    eng.dispose()


@pytest.fixture
def on_db(sched_db, monkeypatch):
    monkeypatch.setattr(db, "get_engine_for_resource", lambda rid: sched_db)
    return sched_db


def _name():
    return f"s_{uuid.uuid4().hex[:10]}"


def _frame(n):
    return pd.DataFrame({"person_id": range(n)})


def _extract(n=3, recipe=RECIPE):
    table = _name()
    extracts.write({"df": _frame(n)}, "res", table, "Cohort", recipe)
    return table


def _count(engine, table):
    with engine.connect() as conn:
        return conn.execute(text(f'SELECT count(*) FROM public."{table}"')).scalar_one()


def _set(table, schedule, now=NOW):
    stored = extract_schedule.ExtractSchedule.model_validate(schedule).stored()
    return extracts.set_schedule("res", table, stored, next_run(stored, now) if stored else None)


def _make_due(engine, table, when):
    with engine.begin() as conn:
        conn.execute(text("UPDATE public._studio_extracts SET next_run_at = :w "
                          "WHERE table_name = :t"), {"w": when, "t": table})


# ---- Next run times ---------------------------------------------------------

def test_next_run_hourly_daily_weekly_are_strictly_after():
    hourly = {"every": "hourly", "minute": 15, "tz": "UTC"}
    assert next_run(hourly, NOW) == NOW.replace(minute=15)
    assert next_run(hourly, NOW.replace(minute=15)) == NOW.replace(hour=13, minute=15)
    daily = {"every": "daily", "hour": 6, "minute": 0, "tz": "UTC"}
    assert next_run(daily, NOW) == datetime(2026, 11, 8, 6, tzinfo=UTC)
    assert next_run(daily, NOW.replace(hour=5)) == datetime(2026, 11, 7, 6, tzinfo=UTC)
    # 2026-11-07 is a Saturday; weekday 0 is Monday.
    weekly = {"every": "weekly", "weekday": 0, "hour": 9, "minute": 30, "tz": "UTC"}
    assert next_run(weekly, NOW) == datetime(2026, 11, 9, 9, 30, tzinfo=UTC)
    saturday = {**weekly, "weekday": 5, "hour": 12, "minute": 0}
    assert next_run(saturday, NOW) == datetime(2026, 11, 14, 12, tzinfo=UTC)


def test_daily_schedule_keeps_local_time_across_dst():
    daily = {"every": "daily", "hour": 6, "minute": 0, "tz": "America/New_York"}
    # US clocks spring forward on 2026-03-08: 06:00 EST is 11:00 UTC, 06:00 EDT 10:00 UTC.
    before = next_run(daily, datetime(2026, 3, 7, 12, tzinfo=UTC))
    after = next_run(daily, before)
    assert before == datetime(2026, 3, 8, 10, tzinfo=UTC)
    assert next_run(daily, datetime(2026, 3, 6, 12, tzinfo=UTC)) == datetime(2026, 3, 7, 11, tzinfo=UTC)
    assert after == datetime(2026, 3, 9, 10, tzinfo=UTC)


@pytest.mark.parametrize("bad", [
    {"every": "daily", "hour": 6, "minute": 60},
    {"every": "daily", "minute": 0},
    {"every": "weekly", "hour": 6},
    {"every": "hourly", "hour": 3},
    {"every": "daily", "hour": 6, "weekday": 2},
    {"every": "daily", "hour": 24},
    {"every": "monthly"},
    {"every": "daily", "hour": 6, "tz": "Mars/Olympus"},
    {"every": "daily", "hour": 6, "cron": "* * * * *"},
])
def test_bad_schedules_are_422(bad):
    client = TestClient(main.app)
    response = client.put("/api/extracts/schedule", json={
        "resource_id": "res", "table": "t", "schedule": bad})
    assert response.status_code == 422, response.text


# ---- Storage ---------------------------------------------------------------

def test_registry_without_schedule_columns_still_reads_and_migrates(pg, monkeypatch):
    legacy = _new_database(pg)
    monkeypatch.setattr(db, "get_engine_for_resource", lambda rid: legacy)
    try:
        with legacy.begin() as conn:
            conn.execute(text(
                "CREATE TABLE public._studio_extracts (table_name text PRIMARY KEY, "
                "title text NOT NULL, recipe jsonb, row_count bigint NOT NULL, "
                "created_at timestamptz NOT NULL, refreshed_at timestamptz NOT NULL)"))
            conn.execute(text("CREATE TABLE public.old_cohort AS SELECT 1 AS person_id"))
            conn.execute(text(
                "INSERT INTO public._studio_extracts VALUES ('old_cohort', 'Old', "
                "CAST(:r AS jsonb), 1, now(), now())"), {"r": '{"kind": "aurora", '
                '"resource_id": "res", "table": "person"}'})
        info = extracts.info("res", "old_cohort")
        assert info["rows"] == 1 and info["refreshable"] is True
        assert info["schedule"] is None and info["next_run_at"] is None
        assert extracts.due("res", NOW) == []          # no columns yet: nothing due
        info = _set("old_cohort", {"every": "daily", "hour": 6, "tz": "UTC"})
        assert info["schedule"] == {"every": "daily", "minute": 0, "hour": 6, "tz": "UTC"}
        assert info["next_run_at"] == "2026-11-08T06:00:00+00:00"
        assert info["title"] == "Old" and info["rows"] == 1
    finally:
        legacy.dispose()


def test_refresh_and_rewrite_keep_the_schedule(on_db):
    table = _extract()
    _set(table, {"every": "hourly", "minute": 5})
    info = extracts.write({"df": _frame(7)}, "res", table, "Cohort", RECIPE, replace=True)
    assert info["rows"] == 7 and info["schedule"]["every"] == "hourly"
    assert info["next_run_at"] == "2026-11-07T12:05:00+00:00"
    off = _set(table, {"every": "off"})
    assert off["schedule"] is None and off["next_run_at"] is None


def test_schedule_endpoint_checks_the_extract(on_db):
    client = TestClient(main.app)
    upload = _extract(recipe=None)
    put = lambda table, schedule: client.put("/api/extracts/schedule", json={  # noqa: E731
        "resource_id": "res", "table": table, "schedule": schedule})
    assert put(upload, {"every": "daily", "hour": 6}).status_code == 400  # can't be rerun
    assert put(upload, {"every": "off"}).status_code == 200
    assert put(_name(), {"every": "daily", "hour": 6}).status_code == 404
    table = _extract()
    out = put(table, {"every": "weekly", "weekday": 2, "hour": 6, "minute": 30,
                      "tz": "Europe/London"}).json()["extract"]
    assert out["schedule"]["tz"] == "Europe/London" and out["next_run_at"] > out["refreshed_at"]


# ---- The scheduler ---------------------------------------------------------

class Submits:
    def __init__(self, finish=True):
        self.calls, self.finish = [], finish

    def __call__(self, resource_id, table, on_done):
        self.calls.append(table)
        if self.finish:
            on_done()


def _scheduler(submit):
    return extract_schedule.Scheduler(submit, lambda: ["res"], clock=lambda: NOW)


def test_missed_runs_become_one_catch_up(on_db):
    table = _extract()
    _set(table, {"every": "hourly", "minute": 0}, now=NOW - timedelta(days=3))
    submit = Submits()
    scheduler = _scheduler(submit)
    outcomes = scheduler.tick()
    assert (("res", table, "submitted") in outcomes) and submit.calls.count(table) == 1
    info = extracts.info("res", table)
    assert info["next_run_at"] == "2026-11-07T13:00:00+00:00"   # from now, not from the backlog
    assert info["last_run_status"] == "running"
    scheduler.tick()
    scheduler.tick(NOW + timedelta(minutes=30))
    assert submit.calls.count(table) == 1
    scheduler.tick(NOW + timedelta(hours=1))
    assert submit.calls.count(table) == 2


def test_two_processes_claim_a_run_once(on_db):
    table = _extract()
    _set(table, {"every": "daily", "hour": 6}, now=NOW - timedelta(days=1))
    first, second = Submits(), Submits()
    due = [r for r in extracts.due("res", NOW) if r["table"] == table][0]
    # Both processes read the row as due; only the first conditional UPDATE wins.
    _scheduler(first).tick()
    assert not extracts.claim("res", table, due["next_run_at"], NOW + timedelta(days=1), NOW)
    _scheduler(second).tick()
    assert first.calls.count(table) == 1 and table not in second.calls


def test_running_refresh_is_not_run_twice(on_db):
    table = _extract()
    _set(table, {"every": "hourly", "minute": 0}, now=NOW - timedelta(hours=2))
    submit = Submits()
    with extracts.refresh_lock("res", table):     # e.g. a manual refresh in another process
        assert ("res", table, "skipped") in _scheduler(submit).tick()
        with pytest.raises(extracts.RefreshRunning):
            extracts.refresh("res", table, lambda r: pytest.fail("must not open"), None, None)
    assert table not in submit.calls
    info = extracts.info("res", table)
    assert info["last_run_status"] == "skipped" and "already running" in info["last_run_error"]
    assert not extracts.refresh_running("res", table)

    # A scheduled job still queued in this process is not submitted again.
    queued = Submits(finish=False)
    scheduler = _scheduler(queued)
    _make_due(on_db, table, NOW - timedelta(minutes=1))
    scheduler.tick()
    _make_due(on_db, table, NOW - timedelta(minutes=1))
    assert ("res", table, "skipped") in scheduler.tick()
    assert queued.calls.count(table) == 1


def test_job_cancelled_before_it_started_is_due_at_next_start(on_db):
    table = _extract()
    _set(table, {"every": "weekly", "weekday": 0, "hour": 6}, now=NOW - timedelta(days=7))
    scheduler = _scheduler(Submits(finish=False))   # queued; shutdown cancels it unstarted
    scheduler.tick()
    assert extracts.info("res", table)["next_run_at"] > NOW.isoformat()
    scheduler.recover_pending()
    info = extracts.info("res", table)
    assert info["next_run_at"] == NOW.isoformat() and info["last_run_status"] == "failed"
    assert scheduler.pending == set()


def test_run_lost_to_a_killed_app_is_due_again(on_db):
    table = _extract()
    _set(table, {"every": "daily", "hour": 6}, now=NOW - timedelta(days=1))
    # The app was killed mid-run: still "running", next run already moved on.
    due = [r for r in extracts.due("res", NOW) if r["table"] == table][0]
    started = NOW - timedelta(hours=2)
    assert extracts.claim("res", table, due["next_run_at"], NOW + timedelta(hours=18), started)
    submit = Submits()
    with extracts.refresh_lock("res", table):     # another process is still refreshing
        _scheduler(submit).tick()
    assert extracts.info("res", table)["last_run_status"] == "running"
    recent = _extract()
    _set(recent, {"every": "daily", "hour": 6}, now=NOW - timedelta(days=1))
    due = [r for r in extracts.due("res", NOW) if r["table"] == recent][0]
    extracts.claim("res", recent, due["next_run_at"], NOW + timedelta(hours=18),
                   NOW - timedelta(minutes=5))   # may still be queued in another process
    scheduler = _scheduler(submit)
    scheduler.tick()
    info = extracts.info("res", table)
    assert info["last_run_status"] == "failed" and info["next_run_at"] == NOW.isoformat()
    assert extracts.info("res", recent)["last_run_status"] == "running"
    scheduler.tick()                              # and the catch-up runs
    assert submit.calls.count(table) == 1 and recent not in submit.calls


def test_busy_admission_retries_soon(on_db):
    table = _extract()
    _set(table, {"every": "weekly", "weekday": 0, "hour": 6}, now=NOW - timedelta(days=7))

    def busy(*_a):
        raise data_jobs.Busy("Two data jobs are already active for this session.")
    assert ("res", table, "busy") in _scheduler(busy).tick()
    info = extracts.info("res", table)
    assert info["last_run_status"] == "skipped"
    assert info["next_run_at"] == (NOW + extract_schedule.RETRY_BUSY).isoformat()


def test_unreachable_database_backs_off(monkeypatch):
    calls = []

    def broken(rid):
        calls.append(rid)
        raise RuntimeError("connection refused")
    monkeypatch.setattr(db, "get_engine_for_resource", broken)
    scheduler = _scheduler(Submits())
    assert scheduler.tick() == [] and scheduler.tick() == []
    assert calls == ["res"]


# ---- The real refresh job --------------------------------------------------

def _wait_status(table, status, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        info = extracts.info("res", table)
        if info["last_run_status"] == status:
            return info
        time.sleep(0.05)
    raise AssertionError(extracts.info("res", table))


def _open_frame(n):
    def open_dataset(req):
        return datasets.open_dataset(_frame(n), "refreshed")
    return open_dataset


def test_scheduled_job_refreshes_and_records_failures(on_db, monkeypatch):
    table = _extract(3)
    _set(table, {"every": "daily", "hour": 6}, now=NOW - timedelta(days=2))
    monkeypatch.setattr(main.extract_scheduler, "resources", lambda: ["res"])
    monkeypatch.setattr(main.extract_scheduler, "clock", lambda: NOW)
    before = len(datasets._store)
    monkeypatch.setattr(main, "open_dataset", _open_frame(40))
    assert ("res", table, "submitted") in main.extract_scheduler.tick()
    info = _wait_status(table, "ok")
    assert _count(on_db, table) == 40 and info["rows"] == 40 and info["last_run_error"] is None
    assert info["next_run_at"] == "2026-11-08T06:00:00+00:00"
    assert len(datasets._store) == before      # the scheduled run opens no tab

    def broken(req):
        raise RuntimeError("source table went away")
    monkeypatch.setattr(main, "open_dataset", broken)
    _make_due(on_db, table, NOW - timedelta(minutes=1))
    main.extract_scheduler.tick()
    info = _wait_status(table, "failed")
    assert "source table went away" in info["last_run_error"]
    assert _count(on_db, table) == 40          # the old rows stay


def test_cancelled_scheduled_run_catches_up_next_start(on_db, monkeypatch):
    table = _extract(3)
    _set(table, {"every": "daily", "hour": 6}, now=NOW - timedelta(days=2))
    monkeypatch.setattr(main.extract_scheduler, "resources", lambda: ["res"])
    monkeypatch.setattr(main.extract_scheduler, "clock", lambda: NOW)
    import query_cancellation

    def stopped(req):
        raise query_cancellation.Cancelled("app stopping")
    monkeypatch.setattr(main, "open_dataset", stopped)
    main.extract_scheduler.tick()
    info = _wait_status(table, "failed")
    assert info["next_run_at"] == NOW.isoformat()   # due again on the next check


def test_lifespan_runs_the_scheduler_with_startup_catch_up(on_db, monkeypatch):
    table = _extract(3)
    _set(table, {"every": "daily", "hour": 6}, now=NOW - timedelta(days=5))
    monkeypatch.setenv("STUDIO_EXTRACT_SCHEDULER", "on")
    monkeypatch.setattr(main.extract_scheduler, "resources", lambda: ["res"])
    monkeypatch.setattr(main.extract_scheduler, "clock", lambda: NOW)
    monkeypatch.setattr(main, "open_dataset", _open_frame(11))
    with TestClient(main.app):
        assert main.extract_scheduler.task is not None
        info = _wait_status(table, "ok")
    assert main.extract_scheduler.task is None
    assert info["rows"] == 11 and info["next_run_at"] == "2026-11-08T06:00:00+00:00"
