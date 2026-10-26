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
    uncertain_plan = {
        **ready_plan, "id": "plan-uncertain", "workflow": "uncertain-submission",
        "status": "submission_unknown", "errors": ["Check the workflow service before retrying."],
    }
    unverifiable_plan = {
        **ready_plan, "id": "plan-unverifiable", "workflow": "unverifiable-results",
        "status": "completed", "run": {"run_id": "run-2", "status": "COMPLETED"},
    }
    messages = list(history)
    stored_plans = [ready_plan, blocked_plan, uncertain_plan, unverifiable_plan]
    chat_requests = []
    approval_requests = []
    status_requests = []
    results_requests = []

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

    page.route("**/api/agent/workflows", lambda route: fulfill(route, {
        "plans": stored_plans,
    }))
    page.route("**/api/agent/chat/sessions", lambda route: fulfill(route, {
        "sessions": [{"session_id": session_id, "title": "Liver cohort analysis",
                      "updated_at": "2026-10-26T12:00:00Z"}],
    }))

    def chat(route):
        body = route.request.post_data_json
        chat_requests.append(body)
        if body["message"] == "Run into the agent limit":
            reply_limited = "I wasn't able to finish that in a reasonable number of steps — try narrowing the request."
            messages.extend([
                {"role": "user", "content": body["message"], "message_id": 5},
                {"role": "assistant", "content": reply_limited, "message_id": 6},
            ])
            fulfill(route, {"reply": reply_limited, "session_id": session_id,
                "trace_id": "trace-2", "tool_calls": ["inspect_table"],
                "tool_results": [{"name": "inspect_table", "status": "failed"}],
                "limit_reached": True, "actions": [], "workflow_plans": []})
            return
        messages.extend([
            {"role": "user", "content": body["message"], "message_id": 3},
            {"role": "assistant", "content": reply, "message_id": 4},
        ])
        fulfill(route, {"reply": reply, "session_id": session_id, "trace_id": "trace-1",
                        "tool_calls": ["count_cohort", "prepare_dashboard"],
                        "tool_results": [{"name": "count_cohort", "status": "completed"},
                                         {"name": "prepare_dashboard", "status": "completed"}],
                        "actions": [action], "workflow_plans": [ready_plan, blocked_plan]})

    page.route("**/api/agent/chat", chat)

    def approve(route):
        approval_requests.append(route.request.post_data_json)
        submitted = {**ready_plan, "status": "submitted", "run": {
            "run_id": "run-1", "status": "SUBMITTED"}}
        stored_plans[0] = submitted
        fulfill(route, submitted)

    page.route("**/api/agent/workflows/*/approve", approve)

    def status(route):
        status_requests.append(route.request.url)
        if "plan-uncertain" in route.request.url:
            checked = {**uncertain_plan, "status": "completed", "errors": [],
                       "run": {"run_id": "run-2", "status": "COMPLETED"}}
            stored_plans[2] = checked
            fulfill(route, checked)
            return
        completed = {**ready_plan, "status": "completed", "run": {
            "run_id": "run-1", "status": "COMPLETED"}}
        stored_plans[0] = completed
        fulfill(route, completed)

    page.route("**/api/agent/workflows/*/status", status)
    def open_results(route):
        results_requests.append(route.request.url)
        if "plan-unverifiable" in route.request.url:
            route.fulfill(status=409, content_type="application/json",
                          json={"detail": "Workflow results could not be verified."})
            return
        result_action = {**action, "dataset": {**action["dataset"],
                                                  "dataset_id": "verified-result"}}
        fulfill(route, {"action": result_action, "verification": {
            "verified": True, "run_id": "run-1", "rows": 2,
            "integrity": "Counts and schema checked", "summary_sha256": "abc123",
        }})

    page.route("**/api/agent/workflows/*/results/open", open_results)
    page.route("**/api/datasets/*/query", lambda route: fulfill(route, {
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
    tool_results = page.locator("details[aria-label='Tool results']")
    expect(tool_results.locator("summary")).to_contain_text("Tool results (2)")
    tool_results.locator("summary").click()
    expect(page.get_by_text("count_cohort · Completed", exact=True)).to_be_visible()
    expect(page.get_by_text("prepare_dashboard · Completed", exact=True)).to_be_visible()
    plan_card = page.locator(".workflow-plan", has_text="cohort-summary")
    expect(plan_card.get_by_text("person_id → joined.person_id")).to_be_visible()
    expect(plan_card.get_by_text("tissue → samples.tissue")).to_be_visible()
    expect(plan_card.get_by_role("button", name="Run workflow", exact=True)).to_be_enabled()
    blocked = page.locator(".workflow-plan", has_text="blocked-analysis")
    expect(blocked.get_by_role("button", name="Blocked", exact=True)).to_be_disabled()
    page.get_by_role("button", name="Open dashboard", exact=True).click()
    expect(page.locator(".tab.active")).to_contain_text("Liver cohort dashboard")
    expect(page.locator(".chip", has_text="tissue: liver")).to_be_visible()
    page.locator(".topnav-link", has_text="Agent").click()
    plan_card = page.locator(".workflow-plan", has_text="cohort-summary")
    expect(plan_card).to_be_visible()
    plan_card.get_by_role("button", name="Run workflow", exact=True).click()
    expect(plan_card.get_by_text("Status: SUBMITTED")).to_be_visible()
    assert len(approval_requests) == 1
    expect(plan_card.get_by_text("Status: COMPLETED")).to_be_visible(timeout=5000)
    assert status_requests

    plan_card.get_by_role("button", name="Open results", exact=True).click()
    expect(page.get_by_text("Verified workflow results", exact=True)).to_be_visible()
    expect(page.get_by_text("Run run-1", exact=True)).to_be_visible()
    expect(page.get_by_text("2 people", exact=True)).to_be_visible()
    expect(page.get_by_text("2 strata", exact=True)).to_be_visible()
    expect(page.get_by_text("Integrity: Counts and schema checked", exact=True)).to_be_visible()
    assert page.get_by_text("abc123", exact=True).count() == 0
    assert len(results_requests) == 1
    page.locator(".tab:not(.active)").click()
    expect(page.get_by_text("Verified workflow results", exact=True)).to_have_count(0)
    page.locator(".tab:not(.active)").click()
    expect(page.get_by_text("Verified workflow results", exact=True)).to_be_visible()
    expect(page.locator(".tab.active")).to_contain_text("Liver cohort dashboard")
    page.get_by_role("button", name="Dismiss verification details").click()

    page.locator(".topnav-link", has_text="Agent").click()
    expect(page.locator(".workflow-plan", has_text="cohort-summary")).to_be_visible()
    assert page.locator(".workflow-plan").count() == 4
    uncertain = page.locator(".workflow-plan", has_text="uncertain-submission")
    expect(uncertain.get_by_text("Status: Submission needs checking")).to_be_visible()
    expect(uncertain.get_by_text("Check the workflow service before retrying.")).to_be_visible()
    expect(uncertain.get_by_role("button", name="Run workflow", exact=True)).to_have_count(0)
    assert not any("plan-uncertain" in url for url in status_requests)
    uncertain.get_by_role("button", name="Check run", exact=True).click()
    expect(uncertain.get_by_text("Status: COMPLETED")).to_be_visible()
    expect(uncertain.get_by_role("button", name="Open results", exact=True)).to_be_enabled()
    assert sum("plan-uncertain" in url for url in status_requests) == 1
    unverifiable = page.locator(".workflow-plan", has_text="unverifiable-results")
    unverifiable.get_by_role("button", name="Open results", exact=True).click()
    expect(unverifiable.get_by_role("alert")).to_contain_text("No dashboard was opened")
    expect(page.get_by_text("Verified workflow results", exact=True)).to_have_count(0)
    assert len(results_requests) == 2
    expect(page.get_by_text("Earlier answer", exact=True)).to_be_visible()
    expect(page.get_by_text(reply, exact=True)).to_be_visible()
    assert chat_requests == [{"message": "Analyze the liver cohort and prepare a summary workflow",
                              "session_id": session_id, "new_session": False}]
    box.fill("Run into the agent limit")
    page.get_by_role("button", name="Send", exact=True).click()
    failed_steps = page.locator("details[aria-label='Tool results']").last
    failed_steps.locator("summary").click()
    expect(page.get_by_text("inspect_table · Failed", exact=True)).to_be_visible()
    expect(page.get_by_text("The agent stopped before completing the request. Review the failed steps before retrying.", exact=True)).to_be_visible()
    assert chat_requests[-1] == {"message": "Run into the agent limit",
                                 "session_id": session_id, "new_session": False}
