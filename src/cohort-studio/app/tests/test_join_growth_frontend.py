import pytest
from playwright.sync_api import expect

from tests.ui_helpers import add_to_canvas, set_join_keys

from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e


def test_large_growth_preview_requires_confirmation(page, app_url):
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
    page.locator(".topnav-link").filter(has_text="Data Builder").click()
    panel = page.locator(".jc")
    add_to_canvas(panel, "person")
    expect(panel.locator(".jc-node")).to_have_count(1, timeout=10000)
    add_to_canvas(panel, "visit")
    expect(panel.locator(".jc-node")).to_have_count(2, timeout=10000)
    set_join_keys(panel, "person_id", "person_id")

    preview = {"engine": "aurora", "base_rows": 200, "rows": None, "total_rows": None,
               "truncated": False, "sample_only": True, "sample_truncated": False,
               "steps": [{"right_rows": 6000, "rows": 180000, "truncated": False, "rows_before": 200,
                          "growth": 900.0, "fanout": True, "estimated": True}],
               "growth_total": 900.0, "large_growth": True,
               "notes": ["This join produces ~180,000 rows, 900× the 200-row base. Joining several one-to-many tables on the same key multiplies rows; consider filtering, aggregating, or joining fewer tables at once."],
               "capped_inputs": [], "columns": ["person_id"], "sample": [[1]]}
    page.route("**/api/data-jobs/join_preview", lambda route: fulfill(route, {
        "job_id": "pv", "kind": "join_preview", "status": "complete", "result": preview}))
    join_button = panel.get_by_role("button", name="Save & open in Explore")
    expect(join_button).to_be_enabled()
    panel.get_by_role("button", name="Preview", exact=True).first.click()
    expect(panel).to_contain_text("~180,000")
    expect(panel).to_contain_text("multiplies rows")
    expect(join_button).to_be_disabled()
    confirm = panel.get_by_label("Run anyway", exact=False)
    confirm.check()
    expect(join_button).to_be_enabled()
    page.screenshot(path="/private/tmp/cohort-join-growth-confirm.png")
