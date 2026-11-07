import threading

import pytest

import data_jobs
import view_jobs


class _HeldPool:
    """Executor that holds submitted work until the test runs it."""

    def __init__(self):
        self.calls = []
        self._shutdown = False

    def submit(self, fn, *args):
        self.calls.append((fn, args))

    def shutdown(self, wait=False, cancel_futures=False):
        self._shutdown = True

    def run_all(self):
        for fn, args in self.calls:
            fn(*args)


@pytest.fixture
def held_view_pool(monkeypatch):
    pool = _HeldPool()
    monkeypatch.setattr(view_jobs, "_executor", pool)
    monkeypatch.setattr(view_jobs, "_jobs", {})
    return pool


def test_view_job_failed_by_shutdown_never_reverts_to_running(held_view_pool):
    ran = []
    job = view_jobs.submit("report", 1, lambda progress: ran.append(True), owner="alice")
    view_jobs.shutdown(wait=False)
    assert view_jobs.get(job["job_id"], owner="alice")["status"] == "failed"
    held_view_pool.run_all()
    stored = view_jobs.get(job["job_id"], owner="alice")
    assert stored["status"] == "failed"
    assert stored["error"] == "App stopped before this job started."
    assert ran == []


def test_view_job_progress_after_failure_does_not_revive_it(held_view_pool):
    captured = {}

    def work(progress):
        captured["progress"] = progress
        raise RuntimeError("store unavailable")

    job = view_jobs.submit("report", 2, work, owner="alice")
    held_view_pool.run_all()
    captured["progress"](1)
    stored = view_jobs.get(job["job_id"], owner="alice")
    assert stored["status"] == "failed" and stored["completed_sources"] == 0


def test_view_job_statuses_are_plain_strings_in_api_json(held_view_pool):
    job = view_jobs.submit("report", 0, lambda progress: {"materialized_sources": 0}, owner="alice")
    held_view_pool.run_all()
    stored = view_jobs.get(job["job_id"], owner="alice")
    assert type(stored["status"]) is str and stored["status"] == "complete"


def test_data_job_terminal_states_never_revert(tmp_path):
    manager = data_jobs.DataJobs(tmp_path / "jobs.sqlite3", workers=1, capacity=2)
    release = threading.Event()
    try:
        job = manager.submit("open", "alice", lambda: release.wait(5) and None, lambda _: None)
        manager.cancel(job["job_id"], "alice")
        release.set()
        manager.pool.shutdown(wait=True)
        assert manager.get(job["job_id"], "alice")["status"] == "cancelled"
        for status in ("running", "complete", "failed", "queued"):
            assert manager.state(job["job_id"], status) is False
        assert manager.get(job["job_id"], "alice")["status"] == "cancelled"
    finally:
        release.set()
        manager.shutdown()


def test_data_job_restart_interrupts_only_unfinished_or_unreadable_jobs(tmp_path):
    path = tmp_path / "jobs.sqlite3"
    manager = data_jobs.DataJobs(path)
    with manager.connect() as db:
        for job_id, status in (("a", "running"), ("b", "complete"), ("c", "failed"), ("d", "cancelled")):
            db.execute("INSERT INTO jobs VALUES (?,?,?,?,0)", (job_id, "alice", "open", status))
    manager.shutdown()
    reopened = data_jobs.DataJobs(path)
    try:
        assert {job_id: reopened.get(job_id, "alice")["status"] for job_id in "abcd"} == {
            "a": "interrupted", "b": "interrupted", "c": "failed", "d": "cancelled"}
    finally:
        reopened.shutdown()


def test_data_job_transition_table_matches_enum():
    assert set(data_jobs.TRANSITIONS) == set(data_jobs.JobStatus)
    for status in (data_jobs.JobStatus.FAILED, data_jobs.JobStatus.CANCELLED,
                   data_jobs.JobStatus.INTERRUPTED):
        assert not data_jobs.TRANSITIONS[status]
