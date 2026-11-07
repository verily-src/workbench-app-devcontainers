import pytest
from playwright.sync_api import expect

from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e


def test_join_generated_sql_shows_and_copies_runnable_source(page, app_url):
    sources = [{"kind": "aurora", "id": "clinical", "label": "Clinical Aurora"}]

    def fulfill(route, body):
        route.fulfill(status=200, content_type="application/json", json=body)

    page.add_init_script("""
      window.__copiedSql = '';
      Object.defineProperty(navigator, 'clipboard', { configurable: true, value: {
        writeText: async (value) => { if (window.__denyClipboard) throw new Error('denied'); window.__copiedSql = value; }
      }});
    """)
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
    canvas = page.locator(".jc")
    canvas.get_by_role("button", name="Add person to canvas").click()
    expect(canvas.locator(".jc-node")).to_have_count(1, timeout=10000)
    canvas.get_by_role("button", name="Add visit to canvas").click()
    expect(canvas.locator(".jc-node")).to_have_count(2, timeout=10000)
    config = canvas.get_by_role("region", name="Join configuration")
    for label in ("Left field, clause 1", "Right field, clause 1"):
        box = config.get_by_role("combobox", name=label)
        box.fill("person_id")
        box.press("Enter")
    config.get_by_role("button", name="Apply").click()

    canvas.get_by_role("button", name="Show SQL").click()
    dialog = page.get_by_role("dialog", name="Generated SQL dialog")
    sql_text = dialog.get_by_label("Generated SQL", exact=True)
    expect(sql_text).to_contain_text("WHERE person_id = 1")
    assert "\n" in sql_text.inner_text()
    expect(sql_text).not_to_contain_text(":person_id")
    dialog.get_by_role("button", name="Copy SQL").click()
    expect(dialog.get_by_role("status")).to_contain_text("SQL copied.")
    assert page.evaluate("window.__copiedSql") == "SELECT person_id FROM public.person WHERE person_id = 1"
    page.evaluate("window.__denyClipboard = true")
    dialog.get_by_role("button", name="Copy SQL").click()
    expect(dialog.get_by_role("status")).to_contain_text("Clipboard access is unavailable.")
    expect(sql_text).to_contain_text("WHERE person_id = 1")
