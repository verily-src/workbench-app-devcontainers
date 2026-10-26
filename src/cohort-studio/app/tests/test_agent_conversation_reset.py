import json

import pytest
from urllib.parse import parse_qs, urlparse
from fastapi.testclient import TestClient
from playwright.sync_api import expect

import agent_mode_api
import agent_sessions
import agent_store as store_module
import config
import main
import providers
from tests.test_agent_store import agent_store
from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e


def test_new_session_keeps_old_history_and_owner_scope(agent_store, monkeypatch):
    monkeypatch.setattr(store_module, "AgentStore", lambda: agent_store)
    monkeypatch.setattr(config, "get_llm_config", lambda: {
        "provider": "openai", "model": "test", "api_key": "not-real", "base_url": None,
    })
    monkeypatch.setattr(main, "datasources", lambda: {"ready": True, "sources": []})
    agent_mode_api._dashboards.clear()
    calls = []

    def provider(_provider, _model, _key, _base_url, _system, messages, _impls, **_kwargs):
        calls.append(messages)
        question = messages[-1]["content"]
        return {"reply": f"Answer: {question}", "usage": {}, "tool_calls": [],
                "tool_results": [], "limit_reached": False}

    monkeypatch.setattr(providers, "run", provider)
    client = TestClient(main.app)
    first = client.post("/api/agent/chat", json={"message": "Old question one"})
    assert first.status_code == 200, first.text
    old_id = first.json()["session_id"]
    second = client.post("/api/agent/chat", json={"message": "Old question two"})
    assert second.status_code == 200, second.text
    assert second.json()["session_id"] == old_id
    started = client.post("/api/agent/chat", json={"message": "New question", "new_session": True})
    assert started.status_code == 200, started.text
    new_id = started.json()["session_id"]
    assert new_id != old_id
    assert calls[-1] == [{"role": "user", "content": "New question"}]
    old_history = client.get("/api/agent/chat/history", params={"session_id": old_id})
    assert old_history.status_code == 200, old_history.text
    assert [message["content"] for message in old_history.json()["messages"]] == [
        "Old question one", "Answer: Old question one", "Old question two", "Answer: Old question two",
    ]
    new_history = client.get("/api/agent/chat/history", params={"session_id": new_id})
    assert [message["content"] for message in new_history.json()["messages"]] == [
        "New question", "Answer: New question",
    ]
    resumed = client.post("/api/agent/chat", json={"message": "Continue old conversation", "session_id": old_id})
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["session_id"] == old_id
    assert any(message.get("content") == "Old question one" for message in calls[-1])
    assert client.post("/api/agent/chat", json={"message": "Conflict", "session_id": old_id,
                                                   "new_session": True}).status_code == 422
    with pytest.raises(ValueError, match="Choose an existing conversation"):
        with agent_sessions.bind("direct-owner", "workspace:agent-mode", old_id, new_session=True):
            pass
    outsider = TestClient(main.app)
    assert outsider.get("/api/agent/chat/history", params={"session_id": old_id}).status_code in (403, 404)


def test_agent_session_sidebar_close_open_restore_and_resists_stale_responses(page, app_url):
    old_id = "00000000-0000-4000-8000-000000000011"
    new_id = "00000000-0000-4000-8000-000000000022"
    old_messages = [
        {"role": "user", "content": "Old question", "message_id": 1},
        {"role": "assistant", "content": "Old answer", "message_id": 2},
    ]
    new_messages = [
        {"role": "user", "content": "New question", "message_id": 3},
        {"role": "assistant", "content": "New answer", "message_id": 4},
    ]
    sessions = [{"session_id": old_id, "title": "Study: liver cohort", "updated_at": "2026-10-26T12:00:00Z"}]
    held_session_routes = []
    history_requests = []
    chat_requests = []
    default_history_reads = []

    def fulfill(route, body):
        route.fulfill(status=200, content_type="application/json", json=body)

    page.route("**/api/config", lambda route: fulfill(route, {
        "chart_palette": "verily", "llm": {"provider": "anthropic", "providers": {}}
    }))
    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True, "sources": [], "catalogs_pending": False,
    }))
    page.route("**/api/workflows**", lambda route: fulfill(route, {
        "available": False, "jobs": [], "running_count": 0,
    }))
    page.route("**/api/views/all", lambda route: fulfill(route, {"views": [], "unavailable": []}))
    page.route("**/api/agent/workflows", lambda route: fulfill(route, {"plans": []}))

    def list_sessions(route):
        if not held_session_routes:
            held_session_routes.append(route)
            return
        fulfill(route, {"sessions": sessions})

    page.route("**/api/agent/chat/sessions", list_sessions)

    def history(route):
        history_requests.append(route.request.url)
        requested = parse_qs(urlparse(route.request.url).query).get("session_id", [])
        if requested:
            identifier = requested[0]
        else:
            default_history_reads.append(True)
            identifier = old_id if len(default_history_reads) == 1 else new_id
        msgs = old_messages if identifier == old_id else new_messages
        fulfill(route, {"session_id": identifier, "messages": msgs,
                        "has_more": False, "next_before_message_id": None})

    page.route("**/api/agent/chat/history?*", history)

    def chat(route):
        body = route.request.post_data_json
        chat_requests.append(body)
        sessions[:] = [
            {"session_id": new_id, "title": "New cohort question", "updated_at": "2026-10-26T12:01:00Z"},
            *[session for session in sessions if session["session_id"] != new_id],
        ]
        result = {"reply": "New answer", "session_id": new_id, "trace_id": "trace-new",
                  "tool_calls": [], "actions": [], "workflow_plans": []}
        route.fulfill(status=200, content_type="application/x-ndjson", body="".join(
            json.dumps(event) + "\n" for event in [
                {"type": "started", "run_id": "00000000-0000-4000-8000-000000000456"},
                {"type": "result", "result": result}, {"type": "end"}]))

    page.route("**/api/agent/chat/stream", chat)
    page.goto(app_url)
    page.locator(".topnav-link", has_text="Agent").click()
    expect(page.get_by_text("Old answer", exact=True)).to_be_visible()
    page.get_by_role("button", name="New chat", exact=True).click()
    expect(page.get_by_text("Old answer", exact=True)).to_have_count(0)
    page.get_by_role("textbox", name="Message the Studio Agent").fill("New question")
    page.get_by_role("button", name="Send", exact=True).click()
    expect(page.get_by_text("New answer", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="New cohort question", exact=True)).to_be_visible()
    assert chat_requests == [{"message": "New question", "new_session": True}]

    expect(page.get_by_role("button", name="Study: liver cohort", exact=True)).to_be_visible()
    fulfill(held_session_routes[0], {"sessions": [sessions[-1]]})
    page.wait_for_timeout(100)
    expect(page.get_by_role("button", name="New cohort question", exact=True)).to_be_visible()

    page.get_by_role("button", name="Close Study: liver cohort").click()
    closed = page.locator(".studio-agent-closed-list")
    closed.locator("summary").click()
    expect(closed.get_by_text("Study: liver cohort", exact=True)).to_be_visible()
    closed.get_by_role("button", name="Open", exact=True).click()
    expect(page.get_by_text("Old answer", exact=True)).to_be_visible()
    assert any(f"session_id={old_id}" in url for url in history_requests)

    delayed = []
    def delayed_history(route):
        requested = parse_qs(urlparse(route.request.url).query).get("session_id", [])
        history_requests.append(route.request.url)
        if requested and requested[0] == new_id and not delayed:
            delayed.append(route)
            return
        identifier = requested[0] if requested else new_id
        msgs = old_messages if identifier == old_id else new_messages
        fulfill(route, {"session_id": identifier, "messages": msgs,
                        "has_more": False, "next_before_message_id": None})

    page.unroute("**/api/agent/chat/history?*")
    page.route("**/api/agent/chat/history?*", delayed_history)
    page.get_by_role("button", name="New cohort question", exact=True).click()
    expect(page.get_by_role("button", name="New chat", exact=True)).to_be_disabled()
    expect(page.get_by_role("button", name="Close New cohort question")).to_be_disabled()
    assert delayed
    fulfill(delayed[0], {"session_id": new_id, "messages": new_messages,
                         "has_more": False, "next_before_message_id": None})
    expect(page.get_by_text("New answer", exact=True)).to_be_visible()

    page.evaluate("(ids) => localStorage.setItem('cohort-studio-agent-closed-session-ids', JSON.stringify(ids))", [old_id, new_id])
    page.reload()
    page.locator(".topnav-link", has_text="Agent").click()
    expect(page.get_by_text("New answer", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="New chat", exact=True)).to_be_visible()
    expect(page.get_by_text("Closed chats (2)")).to_be_visible()

    page.evaluate("document.documentElement.setAttribute('data-theme', 'dark'); localStorage.setItem('cohort-studio-theme', 'dark')")
    closed = page.locator(".studio-agent-closed-list")
    closed.locator("summary").click()
    old_row = closed.locator(".studio-agent-session-row").filter(has_text="Study: liver cohort")
    old_row.get_by_role("button", name="Open", exact=True).click()
    expect(page.get_by_text("Old answer", exact=True)).to_be_visible()
    page.set_viewport_size({"width": 1440, "height": 900})
    page.screenshot(path="/private/tmp/studio-agent-sessions-dark.png", full_page=True)
    page.evaluate("document.documentElement.removeAttribute('data-theme'); localStorage.removeItem('cohort-studio-theme')")
    page.screenshot(path="/private/tmp/studio-agent-sessions-desktop.png", full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path="/private/tmp/studio-agent-sessions-mobile.png", full_page=True)
