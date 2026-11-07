"""Refresh tables lists the datasource again and asks the server to bypass its cache."""
from playwright.sync_api import expect

from tests.test_e2e import app_url  # noqa: F401  (fixture)
from tests.ui_helpers import open_data_builder


def test_refresh_tables_lists_new_schema(page, app_url):
    calls = []

    def fulfill(route, value):
        route.fulfill(status=200, content_type="application/json", json=value)

    def tables(route):
        calls.append(route.request.url)
        listed = [{"name": "cms_synpuf_100k.person", "table": "person",
                   "schema": "cms_synpuf_100k", "detail": "table"}]
        if "refresh=true" in route.request.url:
            listed.append({"name": "eunomia_gibleed.person", "table": "person",
                           "schema": "eunomia_gibleed", "detail": "table"})
        fulfill(route, listed)

    page.route("**/api/datasources", lambda r: fulfill(r, {
        "ready": True, "sources": [{"kind": "aurora", "id": "omop", "label": "omop · Aurora"}],
        "catalogs_pending": False}))
    page.route("**/api/tables?**", tables)
    page.route("**/api/workflows**", lambda r: fulfill(r, {"available": False, "jobs": [], "running_count": 0}))
    page.route("**/api/views/all", lambda r: fulfill(r, {"views": [], "unavailable": []}))
    page.goto(app_url)
    canvas = open_data_builder(page)
    expect(canvas.get_by_role("group", name="Schema cms_synpuf_100k")).to_be_visible()
    expect(canvas.get_by_role("group", name="Schema eunomia_gibleed")).to_have_count(0)
    canvas.get_by_role("button", name="Refresh list").click()
    expect(canvas.get_by_role("group", name="Schema eunomia_gibleed")).to_have_count(1)
    assert "refresh=true" not in calls[0] and "refresh=true" in calls[-1]
