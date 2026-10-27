import pytest
from playwright.sync_api import Page, expect

from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e


def test_sql_mode_opens_result_without_visual_join_controls(page: Page, app_url: str):
    opened_sources = []
    wide_sql = "SELECT person_id, gender FROM cdm.person " + "/* " + "wide_column " * 200 + "*/"

    def fulfill(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", json=body)

    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True,
        "sources": [{"kind": "aurora", "id": "fixture", "label": "Aurora fixture"}],
        "catalogs_pending": False,
    }))
    page.route("**/api/workflows**", lambda route: fulfill(route, {
        "available": False, "jobs": [], "running_count": 0,
    }))
    page.route("**/api/tables?**", lambda route: fulfill(route, []))

    source_ref = {"kind": "sql", "resource_id": "fixture",
                  "sql": wide_sql,
                  "name": "person slice"}

    def preview(route):
        body = route.request.post_data_json
        assert body == {"resource_id": "fixture",
                        "sql": wide_sql}
        fulfill(route, {"source_ref": source_ref,
                        "columns": ["person_id", "gender"] + [f"column_{i}" for i in range(60)],
                        "sample": [[7, "Female"] + ["wide value " * 30 for _ in range(60)]],
                        "rows": 2, "truncated": False})

    def open_source(route):
        body = route.request.post_data_json
        opened_sources.append(body["source_ref"])
        fulfill(route, {"dataset_id": "sql-person", "source": "Aurora / person slice",
                        "rows": 2, "columns": [
                            {"name": "person_id", "dtype": "int64", "filter_kind": "none"},
                            {"name": "gender", "dtype": "object", "filter_kind": "categorical"}],
                        "source_ref": body["source_ref"], "query_scope": "database"})

    page.route("**/api/sql/preview", preview)
    def open_source_job(route):
        class JobRoute:
            request = route.request
            def fulfill(self, **kw):
                route.fulfill(status=kw.get('status', 200), content_type='application/json',
                              json={'job_id':'open', 'status':'complete', 'result':kw['json']})
        open_source(JobRoute())
    page.route("**/api/data-jobs/open", open_source_job)
    page.route("**/api/datasets/sql-person/query", lambda route: fulfill(route, {
        "total": 2, "filtered": 2, "scope": "database", "sampled": False,
        "charts": [], "rows": {"page": 0, "page_size": 50,
                                  "columns": ["person_id", "gender"],
                                  "data": [[7, "Female"], [8, "Male"]]},
    }))

    page.goto(app_url)
    expect(page.get_by_text("No data loaded")).to_be_visible(timeout=15000)
    page.get_by_role("button", name="Join tables").click()
    panel = page.locator(".join-panel")
    panel.get_by_role("button", name="SQL", exact=True).click()
    expect(panel.get_by_role("radiogroup", name="Join type")).to_have_count(0)
    expect(panel.get_by_role("button", name="Join into new tab")).to_have_count(0)
    expect(panel.get_by_label("Start from")).to_have_count(0)
    panel.get_by_role("button", name="Table", exact=True).click()
    expect(panel.get_by_role("radiogroup", name="Join type")).to_be_visible()
    panel.get_by_role("button", name="SQL", exact=True).click()
    panel.get_by_label("SQL source name").fill("person slice")
    editor = panel.get_by_label("SQL query")
    editor.fill(wide_sql)
    panel.get_by_role("button", name="Preview SQL").click()
    expect(panel.get_by_label("SQL preview")).to_contain_text("Female", timeout=10000)
    expect(panel.get_by_label("SQL preview")).to_contain_text("2 preview rows")
    for width in (1440, 900):
        page.set_viewport_size({"width": width, "height": 1000})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert panel.evaluate("el => el.scrollWidth <= el.clientWidth")
        box = panel.get_by_label("SQL source name").bounding_box()
        assert box["width"] > 200
        assert page.locator(".sidebar").bounding_box()["x"] == 0
    page.screenshot(path="/private/tmp/cohort-sql-layout.png", full_page=True)


    editor.fill("SELECT person_id FROM cdm.person")
    expect(panel.get_by_label("SQL preview")).to_have_count(0)
    expect(panel.get_by_role("button", name="Create dataset")).to_be_enabled()

    editor.fill(wide_sql)
    panel.get_by_role("button", name="Preview SQL").click()
    expect(panel.get_by_label("SQL preview")).to_be_visible(timeout=10000)
    panel.get_by_role("button", name="Create dataset").click()
    expect(page.locator(".tab", has_text="person slice")).to_be_visible(timeout=10000)
    expect(panel).to_have_count(0)
    expect(page.get_by_text("Female", exact=True)).to_be_visible()
    assert opened_sources == [source_ref]
