import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import agent_store as store_module
from agent_store import AgentStoreError
import main
from tests.test_agent_store import agent_store


def _add_session(store, owner, scope, message, session_id=None):
    turn = store.begin(session_id=session_id, owner=owner, scope=scope,
                       system_prompt="system", user_message=message,
                       provider="test", model="test-model")
    store.finish(turn, "Stored answer")
    return turn.session_id


def test_session_list_is_owner_scope_and_retention_bound(agent_store, monkeypatch):
    monkeypatch.setattr(store_module, "AgentStore", lambda: agent_store)
    cookie = "a" * 64
    owner = hashlib.sha256(cookie.encode()).hexdigest()
    first_id = _add_session(agent_store, owner, "workspace:agent-mode",
                            "  First   conversation " + "x" * 100)
    _add_session(agent_store, owner, "workspace:agent-mode", "Second turn",
                 session_id=first_id)
    _add_session(agent_store, owner, "workspace:other", "Other workspace")
    _add_session(agent_store, hashlib.sha256(b"other-cookie").hexdigest(),
                 "workspace:agent-mode", "Other owner")
    stale_id = _add_session(agent_store, owner, "workspace:agent-mode", "Expired title")
    with agent_store.engine.begin() as conn:
        conn.execute(text("""
            UPDATE _studio_agent.sessions SET updated_at = :old
            WHERE session_id = :sid
        """), {"old": datetime.now(timezone.utc) - timedelta(days=31),
               "sid": stale_id})

    client = TestClient(main.app)
    client.cookies.set("studio_chat_owner", cookie)
    response = client.get("/api/agent/chat/sessions")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) == {"sessions"}
    assert len(payload["sessions"]) == 1
    summary = payload["sessions"][0]
    assert summary["session_id"] == str(first_id)
    assert summary["title"] == ("First conversation " + "x" * 61)
    assert len(summary["title"]) == 80
    assert summary["updated_at"]

    stale_history = client.get("/api/agent/chat/history",
                               params={"session_id": stale_id})
    assert stale_history.status_code == 200, stale_history.text
    assert [message["content"] for message in stale_history.json()["messages"]] == [
        "Expired title", "Stored answer"]

    client.cookies.set("studio_chat_owner", "b" * 64)
    outsider = client.get("/api/agent/chat/sessions")
    assert outsider.status_code == 200
    assert outsider.json() == {"sessions": []}


def test_session_list_is_bounded_to_fifty(agent_store, monkeypatch):
    monkeypatch.setattr(store_module, "AgentStore", lambda: agent_store)
    cookie = "c" * 64
    owner = hashlib.sha256(cookie.encode()).hexdigest()
    for index in range(55):
        _add_session(agent_store, owner, "workspace:agent-mode", f"Conversation {index}")
    client = TestClient(main.app)
    client.cookies.set("studio_chat_owner", cookie)
    response = client.get("/api/agent/chat/sessions")
    assert response.status_code == 200, response.text
    assert len(response.json()["sessions"]) == 50

    with pytest.raises(AgentStoreError, match="limit must be between 1 and 50"):
        agent_store.list_sessions(owner=hashlib.sha256(cookie.encode()).hexdigest(),
                                  scope="workspace:agent-mode", limit=51)
