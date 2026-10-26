import pytest
from playwright.sync_api import expect

from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e


def test_studio_agent_history_actions_and_explicit_workflow_approval(page, app_url):
    session_id = "00000000-0000-4000-8000-000000000123"
    history = [{"role": "user", "content": "Earlier analysis", "message_id": 1},
               {"role": "assistant", "content": "Earlier answer", "message_id": 2}]
    reply = "The liver cohort has two rows. I prepared a dashboard and a workflow plan."
    action = {
        "title": "Liver cohort dashboard",
        "dataset": {"dataset_id": "agent-result", "source": "agent result",
                    "source_ref": {"kind": "aurora", "resource_id": "clinical",
                                   "schema": "public", "table": "person"},
                    "rows": 2, "query_scope": "database",
                    "columns": [{"name": "person_id", "dtype": "int64",
                                 "filter_kind": "none"},
                                {"name": "tissue", "dtype": "text",
                                 "filter_kind": "categorical", "values": ["liver"]}]},
        "filters": [{"column": "tissue", "kind": "categorical", "values": ["liver"]}],
        "charts": [{"kind": "bar", "x": "tissue"}],
    }
    ready_plan = {
        "id": "plan-ready", "workflow": "cohort-summary", "dataset_id": "agent-result",
        "rows": 2, "required_columns": ["person_id", "tissue"],
        "column_mapping": {"person_id": "joined.person_id", "tissue": "samples.tissue"},
        "input_resource_id": "clinical", "output_resource_id": "results",
        "output_path": "cohorts/run-1", "status": "ready", "errors": [],
    }
    blocked_plan = {
        **ready_plan, "id": "plan-blocked", "workflow": "blocked-analysis",
        "status": "blocked", "errors": ["Required column is missing."],
    }
    messages = list(history)
    chat_requests = []
    approval_requests = []
    status_requests = []

    def fulfill(route, body):
        route.fulfill(status=200, content_type="application/json", json=body)

    page.route("**/api/config", lambda route: fulfill(route, {
        "chart_palette": "verily", "llm": {"provider": "anthropic", "providers": {}}
    }))
    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True, "sources": [{"kind": "aurora", "id": "clinical",
                                     "label": "Clinical"}], "catalogs_pending": False,
    }))
    page.route("**/api/workflows**", lambda route: fulfill(route, {
        "available": True, "jobs": [], "running_count": 0,
    }))
    page.route("**/api/views/all", lambda route: fulfill(route, {
        "views": [], "unavailable": [],
    }))

    def history_route(route):
        fulfill(route, {"session_id": session_id, "messages": messages,
                        "has_more": False, "next_before_message_id": None})

    page.route("**/api/agent/chat/history?*", history_route)

    def chat(route):
        body = route.request.post_data_json
        chat_requests.append(body)
        messages.extend([
            {"role": "user", "content": body["message"], "message_id": 3},
            {"role": "assistant", "content": reply, "message_id": 4},
        ])
        fulfill(route, {"reply": reply, "session_id": session_id, "trace_id": "trace-1",
                        "tool_calls": ["count_cohort", "prepare_dashboard"],
                        "actions": [action], "workflow_plans": [ready_plan, blocked_plan]})

    page.route("**/api/agent/chat", chat)

    def approve(route):
        approval_requests.append(route.request.post_data_json)
        fulfill(route, {"status": "submitted", "run": {
            "run_id": "run-1", "status": "SUBMITTED"}})

    page.route("**/api/agent/workflows/*/approve", approve)

    def status(route):
        status_requests.append(route.request.url)
        fulfill(route, {"status": "completed", "run": {
            "run_id": "run-1", "status": "COMPLETED"}})

    page.route("**/api/agent/workflows/*/status", status)
    page.route("**/api/datasets/agent-result/query", lambda route: fulfill(route, {
        "total": 2, "filtered": 2, "scope": "database", "sampled": False,
        "charts": [{"kind": "bar", "x": "tissue", "data": [{"category": "liver",
                   "all": 2, "selected": 2}]}],
        "rows": {"page": 0, "page_size": 50, "columns": ["person_id", "tissue"],
                 "data": [[1, "liver"], [2, "liver"]]},
    }))

    page.goto(app_url)
    page.locator(".topnav-link", has_text="Agent").click()
    expect(page.get_by_text("Earlier answer", exact=True)).to_be_visible()
    box = page.get_by_role("textbox", name="Message the Studio Agent")
    box.fill("Analyze the liver cohort and prepare a summary workflow")
    page.get_by_role("button", name="Send", exact=True).click()
    expect(page.get_by_text(reply, exact=True)).to_be_visible()
    expect(page.get_by_text("Completed steps")).to_be_visible()
    plan_card = page.locator(".workflow-plan", has_text="cohort-summary")
    expect(plan_card.get_by_text("person_id → joined.person_id")).to_be_visible()
    expect(plan_card.get_by_text("tissue → samples.tissue")).to_be_visible()
    expect(plan_card.get_by_role("button", name="Run workflow", exact=True)).to_be_enabled()
    blocked = page.locator(".workflow-plan", has_text="blocked-analysis")
    expect(blocked.get_by_role("button", name="Blocked", exact=True)).to_be_disabled()
    plan_card.get_by_role("button", name="Run workflow", exact=True).click()
    expect(plan_card.get_by_text("Status: SUBMITTED")).to_be_visible()
    expect(plan_card.get_by_role("button", name="Workflow submitted")).to_be_disabled()
    assert len(approval_requests) == 1
    expect(plan_card.get_by_text("Status: COMPLETED")).to_be_visible(timeout=5000)
    assert status_requests

    page.get_by_role("button", name="Open dashboard", exact=True).click()
    expect(page.locator(".tab.active")).to_contain_text("Liver cohort dashboard")
    expect(page.locator(".chip", has_text="tissue: liver")).to_be_visible()
    page.locator(".topnav-link", has_text="Agent").click()
    expect(page.get_by_text("Earlier answer", exact=True)).to_be_visible()
    expect(page.get_by_text(reply, exact=True)).to_be_visible()
    assert chat_requests == [{"message": "Analyze the liver cohort and prepare a summary workflow",
                              "session_id": session_id}]
