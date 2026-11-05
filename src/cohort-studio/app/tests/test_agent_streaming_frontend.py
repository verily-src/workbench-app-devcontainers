import pytest
from playwright.sync_api import expect

from tests.test_e2e import app_url  # noqa: F401  (fixture)

pytestmark = pytest.mark.e2e

SESSION = "00000000-0000-4000-8000-000000000321"

# The stream is a real chunked ReadableStream. Events are sent in batches the
# test releases one at a time, so the live state between batches is visible.
STREAM_SHIM = """(() => {
  const original = window.fetch.bind(window);
  const encoder = new TextEncoder();
  const batches = %s;
  let controller;
  window.agentStreamRelease = () => {
    const batch = batches.shift();
    if (!batch) return false;
    controller.enqueue(encoder.encode(batch.map(e => JSON.stringify(e) + '\\n').join('')));
    if (!batches.length) controller.close();
    return true;
  };
  window.fetch = async (input, options) => {
    if (String(input) === '/api/agent/chat/stream') {
      return new Response(new ReadableStream({start(value) {
        controller = value;
        window.agentStreamRelease();
      }}), {headers: {'Content-Type': 'application/x-ndjson'}});
    }
    return original(input, options);
  };
})();"""


def mock_api(page):
    def fulfill(route, body):
        route.fulfill(status=200, content_type="application/json", json=body)
    page.route("**/api/config", lambda route: fulfill(route, {
        "chart_palette": "verily", "llm": {"provider": "anthropic", "providers": {}}}))
    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True, "sources": [], "catalogs_pending": False}))
    page.route("**/api/views/all", lambda route: fulfill(route, {"views": [], "unavailable": []}))
    page.route("**/api/workflows**", lambda route: fulfill(route, {
        "available": True, "jobs": [], "running_count": 0}))
    page.route("**/api/agent/workflows", lambda route: fulfill(route, {"plans": []}))
    page.route("**/api/agent/workflows?*", lambda route: fulfill(route, {"plans": []}))
    page.route("**/api/agent/chat/history?*", lambda route: fulfill(route, {
        "session_id": None, "messages": [], "has_more": False, "next_before_message_id": None}))
    page.route("**/api/agent/chat/sessions", lambda route: fulfill(route, {"sessions": []}))


def open_agent(page, app_url, batches):
    import json
    page.add_init_script(STREAM_SHIM % json.dumps(batches))
    mock_api(page)
    page.goto(app_url)
    page.locator(".topnav-link", has_text="Agent").click()
    box = page.get_by_role("textbox", name="Message the Studio Agent")
    box.fill("How many people have diabetes?")
    page.get_by_role("button", name="Send", exact=True).click()


def progress(stage, **fields):
    return {"type": "progress", "stage": stage, **fields}


def test_live_text_final_reply_and_persistent_timeline(page, app_url):
    reply = "There are 1,204 people with type 2 diabetes in cms_synpuf_100k."
    batches = [
        [{"type": "started", "run_id": "00000000-0000-4000-8000-000000000999"},
         progress("model_start", turn=1),
         progress("model_retry_start", turn=1, attempt=1, wait_seconds=3.4, reason="overloaded")],
        [{"type": "text_delta", "turn": 1, "text": "Let me look up "},
         {"type": "text_delta", "turn": 1, "text": "the diabetes concepts."}],
        [progress("model_end", turn=1, tool_calls=["search_concepts"],
                  usage={"total_tokens": 40}, step_usage={"total_tokens": 40}),
         progress("tool_start", turn=1, tool_name="search_concepts", args={"query": "type 2 diabetes"}),
         progress("tool_end", turn=1, tool_name="search_concepts", args={"query": "type 2 diabetes"},
                  summary={"concepts_count": 2, "concept_ids": [201826, 443238]}),
         progress("model_start", turn=2),
         progress("model_end", turn=2, tool_calls=["count_cohort"]),
         progress("tool_start", turn=2, tool_name="count_cohort", args={"source": "cms_synpuf_100k"}),
         progress("tool_end", turn=2, tool_name="count_cohort", error_code="invalid_cohort_spec",
                  args={"source": "cms_synpuf_100k"},
                  summary={"error": "Use demographics.gender_concept_ids."}),
         progress("model_start", turn=3),
         {"type": "text_delta", "turn": 3, "text": "There are 1,204 people"}],
        [{"type": "text_delta", "turn": 3, "text": " with type 2 diabetes in cms_synpuf_100k."},
         progress("model_end", turn=3, tool_calls=[]),
         progress("runtime_limit", turn=3, reason="turn_budget"),
         {"type": "result", "result": {
             "reply": reply, "session_id": SESSION, "trace_id": "t",
             "tool_calls": ["search_concepts", "count_cohort"],
             "tool_results": [{"name": "search_concepts", "status": "completed"},
                              {"name": "count_cohort", "status": "failed"}],
             "limit_reached": False, "actions": [], "workflow_plans": []}},
         {"type": "end"}],
    ]
    open_agent(page, app_url, batches)
    live = page.locator(".studio-agent-live")
    steps = live.get_by_role("list", name="Agent steps")
    expect(steps.get_by_role("listitem").filter(has_text="Provider busy — retrying in 3s")).to_be_visible()
    expect(page.locator(".studio-agent-progress")).to_contain_text("Provider busy — retrying in 3s")

    page.evaluate("window.agentStreamRelease()")
    expect(live.locator(".studio-agent-bubble")).to_have_text("Let me look up the diabetes concepts.")
    assert live.locator(".studio-agent-bubble").get_attribute("aria-live") == "off"

    page.evaluate("window.agentStreamRelease()")
    # A new model step replaces the live text; earlier narration stays in the timeline.
    expect(live.locator(".studio-agent-bubble")).to_have_text("There are 1,204 people")
    expect(steps.locator("li.tool").filter(has_text="search concepts")).to_contain_text(
        "concept ids 201826, 443238")
    expect(steps.get_by_role("listitem").filter(has_text="Model step 1")).to_contain_text(
        "Let me look up the diabetes concepts.")
    failed = steps.locator("li.tool").filter(has_text="count cohort")
    expect(failed).to_contain_text("Failed")
    expect(failed).to_contain_text("Use demographics.gender_concept_ids.")

    page.evaluate("window.agentStreamRelease()")
    expect(page.locator(".studio-agent-live")).to_have_count(0)
    final = page.locator(".studio-agent-message.assistant").last
    expect(final.locator(".studio-agent-bubble")).to_have_text(reply)
    timeline = final.locator("details.studio-agent-timeline")
    expect(timeline.locator("summary")).to_contain_text("3 model steps, 2 tool calls, 1 failed")
    timeline.locator("summary").click()
    items = timeline.get_by_role("list", name="Agent steps").get_by_role("listitem")
    expect(items.filter(has_text="Step limit reached")).to_be_visible()
    expect(items.filter(has_text="Provider busy — retrying in 3s")).to_be_visible()
    expect(items.and_(timeline.locator("li.tool")).filter(has_text="count cohort")).to_contain_text("Failed")
    expect(items.and_(timeline.locator("li.tool")).filter(has_text="search concepts")).to_contain_text("Completed")
    # The timeline replaces the plain tool-results list for streamed replies.
    expect(final.locator("details[aria-label='Tool results']")).to_have_count(0)


def test_partial_and_error_keep_timeline_and_server_message(page, app_url):
    message = ("The provider is temporarily overloaded, even after automatic retries. "
               "Wait a minute and retry, or choose a different model in Settings.")
    batches = [
        [{"type": "started", "run_id": "00000000-0000-4000-8000-000000000998"},
         progress("model_start", turn=1),
         {"type": "text_delta", "turn": 1, "text": "Checking sources"},
         progress("model_end", turn=1, tool_calls=["list_sources"]),
         progress("tool_start", turn=1, tool_name="list_sources", args={}),
         progress("tool_end", turn=1, tool_name="list_sources", args={}, summary={"sources_count": 3}),
         progress("model_start", turn=2)],
        [{"type": "partial", "downloads": [], "actions": [], "workflow_plans": []},
         {"type": "error", "message": message},
         {"type": "end"}],
    ]
    open_agent(page, app_url, batches)
    expect(page.locator(".studio-agent-live .studio-agent-bubble")).to_have_text("Checking sources")
    page.evaluate("window.agentStreamRelease()")
    expect(page.get_by_role("alert")).to_have_text(message)
    final = page.locator(".studio-agent-message.assistant").last
    expect(final.locator(".studio-agent-bubble")).to_have_text(message)
    timeline = final.locator("details.studio-agent-timeline")
    timeline.locator("summary").click()
    items = timeline.get_by_role("list", name="Agent steps").get_by_role("listitem")
    expect(items.and_(timeline.locator("li.tool")).filter(has_text="list sources")).to_contain_text("sources count 3")
    expect(items.filter(has_text="Run failed")).to_contain_text("temporarily overloaded")
    expect(items.filter(has_text="Model step 2")).to_contain_text("Failed")
