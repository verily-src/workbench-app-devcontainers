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

    page.route("**/api/datasets/open", open_source)
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

    sql_details = panel.locator("details.join-evidence", has_text="Generated SQL")
    expect(sql_details).to_be_visible(timeout=10000)
    sql_details.locator("summary").click()
    sql_text = panel.get_by_label("Generated SQL", exact=True)
    expect(sql_text).to_contain_text("WHERE person_id = 1")
    expect(sql_text).not_to_contain_text(":person_id")
    panel.get_by_role("button", name="Copy SQL source").click()
    expect(page.get_by_role("status")).to_contain_text("SQL source copied.")
    assert page.evaluate("window.__copiedSql") == "SELECT person_id FROM public.person WHERE person_id = 1"
    page.evaluate("window.__denyClipboard = true")
    panel.get_by_role("button", name="Copy SQL source").click()
    expect(page.get_by_role("status")).to_contain_text("Clipboard access is unavailable.")
    expect(sql_text).to_contain_text("WHERE person_id = 1")
