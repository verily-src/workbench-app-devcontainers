import pytest
from playwright.sync_api import Page, expect

from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e


def test_sql_result_rename_persists_in_saved_view_and_reopens(page: Page, app_url: str):
    saved = []
    opened = []
    views = []

    def fulfill(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", json=body)

    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True, "catalogs_pending": False,
        "sources": [{"kind": "aurora", "id": "db-main", "label": "Clinical database"}],
    }))
    page.route("**/api/workflows**", lambda route: fulfill(route, {
        "available": False, "jobs": [], "running_count": 0,
    }))
    page.route("**/api/tables?**", lambda route: fulfill(route, []))
    page.route("**/api/views/all", lambda route: fulfill(route, {
        "views": views, "unavailable": [],
    }))

    def preview_sql(route):
        fulfill(route, {
            "source_ref": {"kind": "sql", "resource_id": "db-main",
                           "sql": "SELECT 1 AS person_id", "name": "SQL result"},
            "columns": ["person_id"], "sample": [[1]], "rows": 1, "truncated": False,
        })

    page.route("**/api/sql/preview", preview_sql)

    def open_source(route):
        source_ref = route.request.post_data_json["source_ref"]
        opened.append(source_ref)
        index = len(opened)
        fulfill(route, {
            "dataset_id": "sql-result" if index == 1 else "sql-reopened",
            "source": f"db-main / SQL result {index}", "rows": 1,
            "columns": [{"name": "person_id", "filter_kind": "none"}],
            "source_ref": source_ref, "query_scope": "database",
        })

    page.route("**/api/datasets/open", open_source)
    page.route("**/api/datasets/*/query", lambda route: fulfill(route, {
        "total": 1, "filtered": 1, "scope": "database", "charts": [],
        "rows": {"page": 0, "page_size": 50, "columns": ["person_id"], "data": [[1]]},
    }))

    def save_view(route):
        body = route.request.post_data_json
        saved.append(body)
        views[:] = [{"name": body["name"], "kind": body["kind"],
                     "resource_id": body["resource_id"], "store_label": "Clinical database"}]
        fulfill(route, {"name": body["name"]})

    page.route("**/api/views", save_view)
    page.route("**/api/views/one?**", lambda route: fulfill(route, {
        "version": 2, "active": 0,
        "datasets": [{"source": saved[0]["datasets"][0]["source"],
                      "title": saved[0]["datasets"][0]["title"],
                      "filters": [], "charts": [], "cohorts": []}],
    }))

    page.goto(app_url)
    page.get_by_role("button", name="Join tables").click()
    page.get_by_role("button", name="SQL", exact=True).click()
    page.get_by_label("SQL query").fill("SELECT 1 AS person_id")
    page.get_by_role("button", name="Preview SQL").click()
    page.get_by_role("button", name="Open SQL result").click()
    tab = page.locator(".tab.active")
    expect(tab).to_contain_text("SQL result", timeout=10000)

    page.get_by_role("button", name="Rename SQL result").click()
    name = page.get_by_label("Name for SQL result")
    expect(name).to_have_attribute("maxlength", "128")
    name.fill("Draft")
    name.press("Escape")
    expect(page.get_by_label("Name for SQL result")).to_have_count(0)
    expect(page.locator(".tab.active")).to_contain_text("SQL result")
    page.get_by_role("button", name="Rename SQL result").click()
    name = page.get_by_label("Name for SQL result")
    name.fill("   ")
    expect(page.get_by_role("button", name="Save tab name")).to_be_disabled()
    name.fill("  Renamed SQL result  ")
    name.press("Enter")
    expect(page.locator(".tab.active")).to_contain_text("Renamed SQL result")

    page.get_by_label("Saved view name").fill("SQL recipe")
    page.locator(".view-save").get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_text("SQL recipe", exact=True)).to_be_visible()
    recipe = saved[0]["datasets"][0]
    assert recipe["title"] == "Renamed SQL result"
    assert recipe["source"]["name"] == "Renamed SQL result"

    with page.expect_response(lambda response:
            response.url.endswith("/api/datasets/sql-reopened/query")):
        page.locator(".view-list").get_by_role("button", name="SQL recipe", exact=True).click()
    expect(page.locator(".tab.active")).to_contain_text("Renamed SQL result")
    assert opened[-1]["name"] == "Renamed SQL result"
