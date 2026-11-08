"""Parameters: filters follow a named value; changing it updates every bound filter."""
import pytest
from playwright.sync_api import expect

from tests.test_e2e import app_url  # noqa: F401
from tests.ui_helpers import load_table

pytestmark = pytest.mark.e2e


def test_filters_follow_parameters(page, app_url):
    queries = []

    def fulfill(route, body):
        route.fulfill(status=200, content_type="application/json", json=body)

    def query(route):
        queries.append(route.request.post_data_json.get("filters", []))
        fulfill(route, {"total": 5, "filtered": 2, "scope": "database", "sampled": False, "charts": [],
                        "rows": {"page": 0, "page_size": 50, "columns": ["age"], "data": [[60]]}})

    page.route("**/api/datasources", lambda r: fulfill(r, {
        "ready": True, "sources": [{"kind": "aurora", "id": "db", "label": "DB"}], "catalogs_pending": False}))
    page.route("**/api/workflows**", lambda r: fulfill(r, {"available": False, "jobs": [], "running_count": 0}))
    page.route("**/api/views/all", lambda r: fulfill(r, {"views": [], "unavailable": []}))
    page.route("**/api/tables?**", lambda r: fulfill(r, [
        {"name": "public.people", "schema": "public", "table": "people", "detail": "table"}]))
    page.route("**/api/data-jobs/open", lambda r: fulfill(r, {"job_id": "o", "kind": "open", "status": "complete",
        "result": {"dataset_id": "people", "source": "people", "rows": 5, "query_scope": "database",
                   "source_ref": r.request.post_data_json["source_ref"],
                   "columns": [{"name": "age", "dtype": "int64", "filter_kind": "range", "min": 20, "max": 90},
                               {"name": "visit", "dtype": "object", "filter_kind": "date",
                                "min_date": "2023-01-01", "max_date": "2024-12-31"}]}}))
    page.route("**/api/datasets/*/query", query)
    page.goto(app_url)
    load_table(page, "aurora:db", "public.people")

    def wait_for(predicate):
        for _ in range(50):
            if queries and predicate(queries[-1]):
                return queries[-1]
            page.wait_for_timeout(100)
        raise AssertionError(queries[-1:])

    params = page.get_by_role("group", name="Parameters")
    expect(params.get_by_text("Create a value, then select it under Follows in a filter.")).to_be_visible()
    expect(params.get_by_label("New parameter name")).to_have_attribute("placeholder", "e.g. min_age")
    params.get_by_label("New parameter name").fill("1bad")
    expect(params.get_by_role("alert")).to_contain_text("start with a letter")
    params.get_by_label("New parameter name").fill("min_age")
    params.get_by_role("button", name="Add parameter").click()
    params.get_by_label("Parameter min_age", exact=True).fill("60")

    age = page.locator(".filter-group", has_text="age").first
    age.locator("summary").click()
    age.get_by_label("Minimum age follows").select_option("min_age")
    expect(age.get_by_label("Minimum age", exact=True)).to_be_disabled()
    wait_for(lambda f: f == [{"column": "age", "kind": "range", "min": 60, "max": 90, "param": {"min": "min_age"}}])
    # Changing the parameter updates the bound filter.
    params.get_by_label("Parameter min_age", exact=True).fill("70")
    wait_for(lambda f: f and f[0]["min"] == 70)
    # "—" unbinds: the input is editable again and the filter keeps its value.
    age.get_by_label("Minimum age follows").select_option("")
    expect(age.get_by_label("Minimum age", exact=True)).to_be_enabled()
    wait_for(lambda f: f and f[0]["min"] == 70 and "param" not in f[0])
    age.get_by_label("Minimum age follows").select_option("min_age")

    # Date parameter bound to a date filter's start.
    params.get_by_label("New parameter name").fill("index_date")
    params.get_by_label("New parameter type").select_option("date")
    expect(params.get_by_label("New parameter name")).to_have_attribute("placeholder", "e.g. index_date")
    params.get_by_role("button", name="Add parameter").click()
    params.get_by_label("Parameter index_date", exact=True).fill("2024-03-01")
    visit = page.locator(".filter-group", has_text="visit")
    visit.locator("summary").click()
    visit.get_by_label("From visit follows").select_option("index_date")
    wait_for(lambda f: any(x.get("start") == "2024-03-01" and x.get("param") == {"start": "index_date"} for x in f))

    # Removing a parameter unbinds its filters but keeps their last value.
    params.get_by_role("button", name="Remove parameter min_age").click()
    final = wait_for(lambda f: any(x["column"] == "age" and "param" not in x for x in f))
    assert next(x for x in final if x["column"] == "age")["min"] == 70
