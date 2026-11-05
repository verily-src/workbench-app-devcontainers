"""Offline checks for scripts/evaluate_agent_live.py: task file, evaluator and safety guard."""
import importlib.util
import json
from pathlib import Path
import socket

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


@pytest.fixture(scope="module")
def harness():
    spec = importlib.util.spec_from_file_location("evaluate_agent_live", SCRIPTS / "evaluate_agent_live.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("The harness self-test must not open network connections.")
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


def test_self_test_passes_on_canned_streams(harness):
    assert harness.self_test() == []


def test_main_self_test_exit_code(harness, capsys):
    assert harness.main(["--self-test"]) == 0
    assert "Self-test: PASS" in capsys.readouterr().out


def test_every_task_has_passing_and_failing_fixture(harness):
    tasks = {t["id"] for t in harness.load_tasks(harness.DEFAULT_TASKS)}
    cases = json.loads(harness.DEFAULT_FIXTURES.read_text())["cases"]
    assert tasks == {c["task"] for c in cases if c["expect_pass"]}
    assert any(not c["expect_pass"] and "no_workflow_launched" in c.get("expect_failed", []) for c in cases)


def test_guard_blocks_approval_before_io(harness):
    client = harness.ApiClient("http://127.0.0.1:9")
    with pytest.raises(harness.UnsafeRequest):
        client._open("POST", "/api/agent/workflows/plan-1/approve", {})
    with pytest.raises(harness.UnsafeRequest):
        client._open("PUT", "/api/config", {})


def test_launched_plan_fails_any_task(harness):
    task = {"id": "t", "turns": [{"message": "hi", "checks": []}]}
    turn = harness.collect_turn(iter([
        {"type": "result", "result": {"reply": "ok", "workflow_plans": [{"id": "p", "status": "running"}]}},
        {"type": "end"}]))
    passed, checks = harness.evaluate_task(task, [turn])
    assert not passed
    assert [c["check"] for c in checks if not c["ok"]] == ["no_workflow_launched"]


def test_task_file_validation_rejects_bad_checks(harness):
    problems = harness.validate_tasks([
        {"id": "dup", "turns": [{"message": "x", "checks": [{"type": "nope"}]}]},
        {"id": "dup", "turns": [{"message": "x", "checks": [{"type": "same_session"}, {"type": "count"}]}]},
    ])
    joined = " | ".join(problems)
    assert "duplicate task id dup" in joined
    assert "unknown check nope" in joined
    assert "same_session on first turn" in joined
    assert "count needs expected" in joined


def test_user_cookies_and_owner_cookie_are_both_kept(harness):
    from email.message import Message
    client = harness.ApiClient("http://127.0.0.1:9", headers={"Cookie": "proxy=1"}, cookies={"wb": "abc"})
    headers = Message()
    headers["Set-Cookie"] = "studio_chat_owner=" + "a" * 64 + "; HttpOnly; SameSite=Strict; Path=/"
    client._remember(headers)
    assert client.cookies == {"proxy": "1", "wb": "abc", "studio_chat_owner": "a" * 64}
    assert "Cookie" not in client.headers
