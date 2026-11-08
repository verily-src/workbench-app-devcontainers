import pytest
from playwright.sync_api import expect

from tests.test_e2e import app_url  # noqa: F401
from tests.ui_helpers import load_table

pytestmark = pytest.mark.e2e


def test_sampled_suggestions_do_not_limit_full_source_filters(page, app_url):
    requests = []
    def reply(route, data):
        route.fulfill(status=200, content_type="application/json", json=data)
    page.route("**/api/datasources", lambda r: reply(r, {"ready": True, "sources": [
        {"kind": "aurora", "id": "db", "label": "DB"}], "catalogs_pending": False}))
    page.route("**/api/workflows**", lambda r: reply(r, {"available": False, "jobs": [], "running_count": 0}))
    page.route("**/api/views/all", lambda r: reply(r, {"views": [], "unavailable": []}))
    page.route("**/api/tables?**", lambda r: reply(r, [{"name": "public.big", "schema": "public", "table": "big"}]))
    page.route("**/api/data-jobs/open", lambda r: reply(r, {"job_id": "open", "kind": "open", "status": "complete",
        "result": {"dataset_id": "big", "source": "big", "rows": 100000, "query_scope": "database",
                   "source_ref": r.request.post_data_json["source_ref"], "columns": [
                       {"name": "amount", "dtype": "int64", "filter_kind": "range", "min": 10, "max": 20, "profile_sampled": True},
                       {"name": "visit_date", "dtype": "datetime64", "filter_kind": "date", "min_date": "2024-01-01", "max_date": "2024-02-01", "profile_sampled": True},
                       {"name": "group", "dtype": "object", "filter_kind": "categorical", "values": ["preview"], "profile_sampled": True},
                       {"name": "later_value", "dtype": "object", "filter_kind": "none", "profile_sampled": True}]}}))
    def query(route):
        requests.append(route.request.post_data_json)
        reply(route, {"total": 1000000, "filtered": 1000, "scope": "database", "charts": [],
                      "rows": {"page": 0, "page_size": 50, "columns": ["amount", "visit_date", "group"], "data": []}})
    page.route("**/api/datasets/big/query", query)
    page.goto(app_url)
    load_table(page, "aurora:db", "public.big")
    expect(page.get_by_text("Preview rows can miss fields. Use Dataset settings → Columns to enable a filter.")).to_be_visible()
    page.get_by_role("button", name="Dataset settings").click()
    drawer = page.get_by_role("dialog", name="Dataset settings")
    row = drawer.locator(".column-setting-row", has_text="later_value")
    row.get_by_label("Filter").select_option("categorical")
    expect(row.get_by_label("Filter")).to_have_value("categorical")
    drawer.get_by_role("button", name="Close dataset settings").click()
    amount = page.locator(".filter-group", has_text="amount")
    amount.locator("summary").click()
    expect(amount).to_contain_text("Filter suggestions are based on preview rows")
    expect(amount.get_by_label("Minimum amount")).to_have_value("")
    expect(amount.get_by_label("Maximum amount")).to_have_value("")
    amount.get_by_label("Minimum amount").fill("900")
    expect(page.locator(".chips")).to_contain_text("900")
    page.wait_for_timeout(700)
    found = next(f for f in requests[-1]["filters"] if f["column"] == "amount")
    assert found["min"] == 900
    assert found["max"] > 1e300
    date = page.locator(".filter-group", has_text="visit_date")
    date.locator("summary").click()
    expect(date.get_by_label("From visit_date")).not_to_have_attribute("min", "2024-01-01")
    date.get_by_label("From visit_date").fill("2023-01-01")
    expect(page.locator(".chips")).to_contain_text("2023-01-01")
    group = page.locator(".filter-group", has_text="group")
    group.locator("summary").click()
    expect(group).to_contain_text("Filter suggestions are based on preview rows")
    group.get_by_label("Custom filter value").fill("outside-preview")
    group.get_by_role("button", name="Add", exact=True).click()
    expect(page.locator(".chips")).to_contain_text("outside-preview")
    page.wait_for_timeout(700)
    assert next(f for f in requests[-1]["filters"] if f["column"] == "group")["values"] == ["outside-preview"]
    assert next(f for f in requests[-1]["filters"] if f["column"] == "visit_date")["start"] == "2023-01-01"
