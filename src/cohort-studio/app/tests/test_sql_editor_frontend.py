import pytest
from playwright.sync_api import Page, expect

from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e


def test_sql_editor_highlights_lints_and_formats(page: Page, app_url: str):
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
    page.get_by_role("button", name="Join tables").click()   # opens Data Builder
    page.locator(".jc").get_by_role("radio", name="SQL", exact=True).click()
    panel = page.get_by_role("region", name="SQL builder")
    editor = panel.get_by_label("Data Builder SQL")
    check = panel.get_by_role("status", name="SQL check")

    editor.fill("SELECT person_id, 'x' FROM cdm.person WHERE (year_of_birth > 1950")
    expect(check).to_contain_text("not valid PostgreSQL SQL", timeout=5000)   # server verdict wins
    expect(panel.locator(".sql-kw", has_text="SELECT")).to_have_count(1)
    expect(panel.locator(".sql-str")).to_have_text("'x'")

    # PostgreSQL string forms the quick client check can't judge: server decides.
    editor.fill("SELECT $$($$ AS value FROM cdm.person")
    expect(check).to_contain_text("Valid read-only SELECT", timeout=5000)
    editor.fill("SELECT E'it\\'s' AS value FROM cdm.person")
    expect(check).to_contain_text("Valid read-only SELECT", timeout=5000)
    expect(panel.locator(".sql-str")).to_have_text("E'it\\'s'")

    editor.fill("SELECT person_id FROM person")
    expect(check).to_contain_text("Use schema-qualified table names", timeout=5000)

    editor.fill("SELECT person_id\nFROM cdm.person\nWHERE year_of_birth >")
    expect(check).to_contain_text("Line 3", timeout=5000)
    expect(panel.locator(".sql-line-error")).to_have_count(1)

    editor.fill("select person_id from cdm.person where year_of_birth > 1950")
    expect(check).to_contain_text("Valid read-only SELECT", timeout=5000)
    panel.get_by_role("button", name="Format SQL").click()
    expect(editor).to_have_value("SELECT\n  person_id\nFROM cdm.person\nWHERE\n  year_of_birth > 1950")
    page.screenshot(path="/private/tmp/cohort-sql-editor.png")
