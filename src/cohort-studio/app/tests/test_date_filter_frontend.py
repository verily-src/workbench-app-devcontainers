"""Date filters in Explore: Between two dates, or the last N units; chips describe them."""
import pytest
from playwright.sync_api import expect

from tests.test_e2e import app_url  # noqa: F401
from tests.ui_helpers import load_table

pytestmark = pytest.mark.e2e


def test_date_filter_between_and_last(page, app_url):
    queries = []

    def fulfill(route, body):
        route.fulfill(status=200, content_type="application/json", json=body)

    def query(route):
        queries.append(route.request.post_data_json.get("filters", []))
        fulfill(route, {"total": 10, "filtered": 4, "scope": "database", "sampled": False, "charts": [],
                        "rows": {"page": 0, "page_size": 50, "columns": ["visit_date"], "data": [["2024-02-01"]]}})

    page.route("**/api/datasources", lambda r: fulfill(r, {
        "ready": True, "sources": [{"kind": "aurora", "id": "db", "label": "DB"}], "catalogs_pending": False}))
    page.route("**/api/workflows**", lambda r: fulfill(r, {"available": False, "jobs": [], "running_count": 0}))
    page.route("**/api/views/all", lambda r: fulfill(r, {"views": [], "unavailable": []}))
    page.route("**/api/tables?**", lambda r: fulfill(r, [
        {"name": "public.visits", "schema": "public", "table": "visits", "detail": "table"}]))
    page.route("**/api/data-jobs/open", lambda r: fulfill(r, {"job_id": "o", "kind": "open", "status": "complete",
        "result": {"dataset_id": "visits", "source": "visits", "rows": 10, "query_scope": "database",
                   "source_ref": r.request.post_data_json["source_ref"],
                   "columns": [{"name": "visit_date", "dtype": "object", "filter_kind": "date",
                                "min_date": "2023-01-05", "max_date": "2024-12-30"}]}}))
    page.route("**/api/datasets/*/query", query)
    page.goto(app_url)
    load_table(page, "aurora:db", "public.visits")
    group = page.locator(".filter-group", has_text="visit_date")
    group.locator("summary").click()
    expect(group).to_contain_text("Data from 2023-01-05 to 2024-12-30")
    group.get_by_label("From visit_date").fill("2024-01-01")
    group.get_by_label("To visit_date").fill("2024-03-31")
    expect(page.locator(".chips .chip").first).to_have_text("visit_date: 2024-01-01 – 2024-03-31 ✕")

    def last_filters():
        for _ in range(50):
            if queries and queries[-1]:
                return queries[-1]
            page.wait_for_timeout(100)
        return queries[-1]
    assert last_filters() == [{"column": "visit_date", "kind": "date", "start": "2024-01-01", "end": "2024-03-31"}]

    group.get_by_role("radio", name="Last").click()
    # Clearing the count while typing keeps the Last controls.
    group.get_by_label("Last visit_date count").fill("")
    expect(group.get_by_label("Last visit_date count")).to_be_visible()
    expect(group.get_by_role("radio", name="Last")).to_have_attribute("aria-checked", "true")
    group.get_by_label("Last visit_date count").fill("6")
    group.get_by_label("Last visit_date unit").select_option("month")
    expect(page.locator(".chips .chip").first).to_have_text("visit_date: last 6 months ✕")
    page.wait_for_timeout(600)
    assert queries[-1] == [{"column": "visit_date", "kind": "date", "last": 6, "unit": "month"}]
    # A saved cohort with another relative range updates the controls.
    page.locator(".cohort-name").fill("Six months")
    page.get_by_role("button", name="Save cohort").click()
    group.get_by_label("Last visit_date count").fill("2")
    expect(page.locator(".chips .chip").first).to_have_text("visit_date: last 2 months ✕")
    page.get_by_role("button", name="Apply cohort Six months").click()
    expect(group.get_by_label("Last visit_date count")).to_have_value("6")
    expect(group.get_by_label("Last visit_date unit")).to_have_value("month")
    group.get_by_role("button", name="Clear").click()
    expect(page.locator(".chips")).to_have_count(0)
