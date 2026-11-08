"""Legacy saved parameters remain usable when the parameter editor is hidden."""
import pytest
from playwright.sync_api import expect

from tests.test_e2e import app_url  # noqa: F401

pytestmark = pytest.mark.e2e


def test_saved_parameter_filter_is_applied_and_preserved(page, app_url):
    queries, saves = [], []
    source = {"kind": "aurora", "resource_id": "db", "table": "people"}
    bound = {"column": "age", "kind": "range", "min": 70, "max": 90,
             "param": {"min": "min_age"}}
    params = [{"name": "min_age", "kind": "number", "value": 70}]
    def ok(route, body):
        route.fulfill(status=200, json=body)
    page.route("**/api/datasources", lambda r: ok(r, {"ready": True, "sources": [
        {"kind": "aurora", "id": "db", "label": "DB"}], "catalogs_pending": False}))
    page.route("**/api/views/all", lambda r: ok(r, {"views": [
        {"name": "Legacy", "kind": "aurora", "resource_id": "db", "store_label": "DB"}], "unavailable": []}))
    page.route("**/api/views/one?**", lambda r: ok(r, {"version": 2, "active": 0, "datasets": [{
        "source": source, "title": "People", "filters": [bound], "charts": [], "cohorts": [], "parameters": params}]}))
    page.route("**/api/data-jobs/open", lambda r: ok(r, {"job_id": "o", "status": "complete", "result": {
        "dataset_id": "people", "source": "people", "rows": 5, "query_scope": "database", "source_ref": source,
        "columns": [{"name": "age", "dtype": "int64", "filter_kind": "range", "min": 20, "max": 90}]}}))
    def query(route):
        queries.append(route.request.post_data_json.get("filters", []))
        ok(route, {"total": 5, "filtered": 2, "scope": "database", "charts": [],
                   "rows": {"page": 0, "page_size": 50, "columns": ["age"], "data": [[70]]}})
    page.route("**/api/datasets/*/query", query)
    def save(route):
        saves.append(route.request.post_data_json)
        ok(route, {"name": "Copy"})
    page.route("**/api/views", save)
    page.goto(app_url)
    page.get_by_role("button", name="Legacy", exact=True).click()
    expect(page.locator(".tab.active")).to_contain_text("People")
    expect(page.get_by_role("group", name="Parameters", exact=True)).to_have_count(0)
    page.locator(".filter-group", has_text="age").first.locator("summary").click()
    expect(page.get_by_label("Minimum age", exact=True)).to_have_value("70")
    expect(page.get_by_label("Minimum age follows")).to_have_value("min_age")
    page.wait_for_function("() => document.querySelector('.hero') !== null")
    assert any(f and f[0].get("min") == 70 and f[0].get("param") == {"min": "min_age"} for f in queries)
    page.get_by_label("Saved view name").fill("Copy")
    with page.expect_response("**/api/views"):
        page.locator(".view-save").get_by_role("button", name="Save dashboard", exact=True).click()
    assert saves[-1]["datasets"][0]["parameters"] == params
    assert saves[-1]["datasets"][0]["filters"][0]["param"] == {"min": "min_age"}
