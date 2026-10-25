import pytest
from playwright.sync_api import expect
from tests.test_e2e import app_url, loaded_page

pytestmark = pytest.mark.e2e


def test_chat_restores_and_sends_session_id(loaded_page):
    page = loaded_page
    session = "00000000-0000-4000-8000-000000000001"
    messages = [{"role": "user", "content": "Earlier question", "message_id": 1},
                {"role": "assistant", "content": "Preserved answer", "message_id": 2}]
    page.route("**/chat/history?*", lambda route: route.fulfill(json={
        "session_id": session, "messages": messages, "has_more": False,
        "next_before_message_id": None}))
    received = []
    def chat(route):
        received.append(route.request.post_data_json)
        route.fulfill(json={"session_id": session, "reply": "New answer", "actions": [],
                            "filters": [], "charts": []})
    page.route("**/chat", chat)
    page.get_by_role("button", name="Chat", exact=True).click()
    expect(page.get_by_text("Preserved answer", exact=True)).to_be_visible()
    page.get_by_placeholder("Ask about the data…").fill("Next question")
    page.get_by_role("button", name="Send", exact=True).click()
    expect(page.get_by_text("New answer", exact=True)).to_be_visible()
    assert received[0]["session_id"] == session
    page.screenshot(path="/private/tmp/cohort-chat-history.png")


def test_late_chat_reply_cannot_update_another_dataset(loaded_page):
    from tests.test_e2e import PHENO_CSV
    page = loaded_page
    page.locator('input[type="file"]').set_input_files(PHENO_CSV)
    expect(page.locator(".tabs > span")).to_have_count(2)
    page.locator(".tabs > span").first.click()
    page.route("**/chat/history?*", lambda route: route.fulfill(json={
        "session_id": None, "messages": [], "has_more": False,
        "next_before_message_id": None}))
    pending = []
    page.route("**/chat", lambda route: pending.append(route))
    page.get_by_role("button", name="Chat", exact=True).click()
    page.get_by_placeholder("Ask about the data…").fill("Plot tissue")
    page.get_by_role("button", name="Send", exact=True).click()
    expect(page.get_by_text("Working…", exact=True)).to_be_visible()
    page.locator(".tabs > span").first.get_by_role("button").click()
    expect(page.locator(".tabs > span")).to_have_count(1)
    pending[0].fulfill(json={"reply": "Late reply", "session_id": "00000000-0000-4000-8000-000000000001",
                             "filters": [], "charts": [{"kind": "bar", "x": "tissue"}], "actions": []})
    expect(page.get_by_role("button", name="Chat", exact=True)).to_be_visible()
    page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
    expect(page.locator(".chart-grid").get_by_text("tissue", exact=True)).to_have_count(0)


def test_inline_ask_opens_chat_with_draft_and_applies_filters(loaded_page):
    page = loaded_page
    history = [{"role": "user", "content": "Previous question", "message_id": 1},
               {"role": "assistant", "content": "Previous answer", "message_id": 2}]
    page.route("**/chat/history?*", lambda route: route.fulfill(json={
        "session_id": None, "messages": history, "has_more": False,
        "next_before_message_id": None}))
    calls = []
    def chat(route):
        calls.append(route.request.post_data_json)
        route.fulfill(json={"session_id": None, "reply": "Filtered to liver", "actions": [],
                            "filters": [{"column": "tissue", "kind": "categorical",
                                         "values": ["liver"]}], "charts": []})
    page.route("**/chat", chat)
    ask_calls = []
    page.route("**/ask", lambda route: ask_calls.append(route.request.url))

    page.get_by_placeholder("Ask the assistant…").fill("Keep liver samples")
    page.get_by_role("button", name="Open chat", exact=True).click()
    expect(page.get_by_text("Previous answer", exact=True)).to_be_visible()
    ask_input = page.get_by_placeholder("Ask about the data…")
    expect(ask_input).to_have_value("Keep liver samples")
    expect(page.get_by_role("button", name="Open chat", exact=True)).to_have_count(0)
    ask_input.fill("Keep liver samples")
    page.get_by_role("button", name="Send", exact=True).click()
    expect(page.get_by_text("Filtered to liver", exact=True)).to_be_visible()
    expect(page.locator(".chip", has_text="tissue: liver")).to_be_visible()
    assert len(calls) == 1
    assert calls[0]["message"] == "Keep liver samples"
    assert "history" not in calls[0]
    expect(page.get_by_text("Previous answer", exact=True)).to_be_visible()
    assert ask_calls == []
