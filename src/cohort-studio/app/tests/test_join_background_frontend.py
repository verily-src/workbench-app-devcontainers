import pytest
from playwright.sync_api import expect

from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e


def test_join_runs_in_background_across_tab_switches(page, app_url):
    sources = [{"kind": "aurora", "id": "clinical", "label": "Clinical Aurora"}]

    def fulfill(route, body):
        route.fulfill(status=200, content_type="application/json", json=body)

    page.route("**/api/config", lambda route: fulfill(route, {
        "chart_palette": "verily", "llm": {"provider": "anthropic", "providers": {}},
    }))
    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True, "sources": sources, "catalogs_pending": False,
    }))
    page.route("**/api/workflows**", lambda route: fulfill(route, {
        "available": False, "jobs": [], "running_count": 0,
    }))
    page.route("**/api/views/all", lambda route: fulfill(route, {"views": [], "unavailable": []}))
    page.route("**/api/tables?**", lambda route: fulfill(route, [
        {"name": "person", "schema": "public", "table": "person", "detail": "Aurora"},
        {"name": "visit", "schema": "public", "table": "visit", "detail": "Aurora"},
    ]))

    def open_source(route):
        ref = route.request.post_data_json["source_ref"]
        fulfill(route, {"dataset_id": f"open-{ref['table']}", "source": ref["table"],
            "rows": 2, "columns": [{"name": "person_id", "dtype": "int64",
                                    "filter_kind": "none"}],
            "source_ref": ref, "query_scope": "database"})

    def open_source_job(route):
        class JobRoute:
            request = route.request
            def fulfill(self, **kw):
                route.fulfill(status=kw.get('status', 200), content_type='application/json',
                              json={'job_id':'open', 'status':'complete', 'result':kw['json']})
        open_source(JobRoute())
    page.route("**/api/data-jobs/open", open_source_job)
    page.route("**/api/datasets/*/query", lambda route: fulfill(route, {
        "total": 2, "filtered": 2, "scope": "database", "sampled": False,
        "charts": [], "rows": {"page": 0, "page_size": 50,
            "columns": ["person_id"], "data": [[1], [2]]},
    }))
    page.route("**/api/joins/recommend", lambda route: fulfill(route, {
        "candidates": [], "warnings": [],
        "jev": {"status": "not_configured", "configured": False, "model": ""},
    }))
    page.route("**/api/datasets/join/suggest?**", lambda route: fulfill(route, []))
    page.route("**/api/datasets/join/validate", lambda route: fulfill(route, {
        "ok": True, "engine": "aurora", "engine_reason": "Same Aurora source.",
        "generated_sql": {
            "engine": "aurora",
            "sql": "SELECT person_id FROM public.person WHERE person_id = :person_id",
            "copyable_sql": "SELECT person_id FROM public.person WHERE person_id = 1",
            "display_sql": "SELECT\n  person_id\nFROM public.person\nWHERE person_id = 1",
            "parameters": {"person_id": 1},
        },
        "capped_inputs": [], "problems": [], "steps": [{
            "problems": [], "notes": [], "conditions": [{"problem": None, "note": None}],
        }],
    }))
    page.goto(app_url)
    page.get_by_role("button", name="Join tables").click()
    panel = page.locator(".join-panel")
    panel.get_by_label("Join schema").select_option("public")
    picker = panel.get_by_role("combobox", name="Source table to add")
    picker.fill("person")
    picker.press("Enter")
    panel.get_by_role("button", name="Add table").click()
    expect(page.locator(".tab", has_text="person")).to_be_visible(timeout=10000)
    picker.fill("visit")
    picker.press("Enter")
    expect(panel.get_by_role("button", name="Add table")).to_be_enabled(timeout=10000)
    panel.get_by_role("button", name="Add table").click()
    panel.get_by_label("Left key step 1 condition 1").select_option(label="person_id")
    panel.get_by_label("Right key step 1 condition 1").select_option(label="person_id")

    join_state = {"job_id": "join1", "kind": "join", "status": "running",
                  "label": "person + visit (inner on person_id)",
                  "phase": "Joining 2 tables inside the database (PostgreSQL)",
                  "detail": {"engine": "aurora", "sources": 2}, "started": 1, "elapsed": 1.0}
    page.route("**/api/data-jobs/join", lambda route: fulfill(route, join_state))
    page.route("**/api/data-jobs/join1", lambda route: fulfill(route, join_state))
    cancels = []
    page.route("**/api/data-jobs/join1/cancel", lambda route: (cancels.append(1), fulfill(route, join_state)))

    panel.get_by_role("button", name="Join into new tab").click()
    progress = panel.get_by_label("Join progress")
    expect(progress).to_contain_text("Joining person + visit (inner on person_id)")
    expect(progress).to_contain_text("runs in the database")
    expect(progress.locator(".spinner")).to_be_visible()
    join_tab = page.get_by_role("button", name="Join (running)")
    expect(join_tab).to_contain_text("Joining…")
    page.screenshot(path="/private/tmp/cohort-join-running-panel.png")

    # Switch to a data tab: the join keeps running and stays visible.
    page.locator(".tab", has_text="person").locator("span").first.click()
    expect(panel).to_be_hidden()
    expect(page.locator(".dataset-toolbar")).to_be_visible()
    expect(join_tab).to_contain_text("Joining…")
    expect(page.get_by_role("region", name="Data operations")).to_contain_text("Joining person + visit")
    page.screenshot(path="/private/tmp/cohort-join-running-other-tab.png")

    # Return: the same builder and its live status are still there.
    join_tab.click()
    expect(panel).to_be_visible()
    expect(panel.get_by_label("Left key step 1 condition 1")).to_have_value("person_id")
    expect(progress).to_contain_text("Joining 2 tables inside the database (PostgreSQL)")
    progress.get_by_role("button", name="Cancel", exact=True).click()
    page.wait_for_timeout(300)
    assert cancels, "Cancel in the join panel should call the job cancel endpoint"

    join_state.update({"status": "complete", "elapsed": 4.0, "result": {
        "dataset_id": "joined", "source": "person + visit", "rows": 2,
        "columns": [{"name": "person_id", "dtype": "int64", "filter_kind": "none"}],
        "query_scope": "database",
        "join": {"engine": "aurora", "rows": 2, "total_rows": 2, "truncated": False,
                 "capped_inputs": [], "steps": [], "notes": []}}})
    expect(page.locator(".tab", has_text="person + visit")).to_be_visible(timeout=10000)
    expect(panel).to_have_count(0)
    expect(page.get_by_role("button", name="⋈ Join")).to_be_visible()
