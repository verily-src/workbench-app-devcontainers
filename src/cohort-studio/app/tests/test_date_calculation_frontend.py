"""Calculated fields: examples, help, @parameters resolved at creation, clear errors."""
import pytest
from playwright.sync_api import expect

from tests.test_e2e import app_url  # noqa: F401
from tests.ui_helpers import menu

pytestmark = pytest.mark.e2e

COLUMNS = [{"name": "person_id", "dtype": "int64", "filter_kind": "range", "min": 1, "max": 5},
           {"name": "birth_date", "dtype": "object", "filter_kind": "date",
            "min_date": "1950-01-01", "max_date": "2010-12-31"}]


def test_expression_examples_parameters_and_errors(page, app_url):
    derives = []

    def fulfill(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", json=body)

    def derive(route):
        spec = route.request.post_data_json
        derives.append(spec)
        if "hour" in spec["expression"]:
            fulfill(route, {"detail": [{"msg": "Value error, Unknown unit 'hour': use day, week, month or year."}]},
                    status=422)
            return
        fulfill(route, {"dataset_id": "people", "source": "people", "name": spec["name"], "rows": 5,
                        "query_scope": "database", "source_ref": None,
                        "columns": COLUMNS + [{"name": spec["name"], "dtype": "object", "filter_kind": "date",
                                               "min_date": "1960-01-01", "max_date": "2010-01-01"}]})

    page.route("**/api/datasources", lambda r: fulfill(r, {
        "ready": True, "sources": [{"kind": "aurora", "id": "db", "label": "DB"}], "catalogs_pending": False}))
    page.route("**/api/workflows**", lambda r: fulfill(r, {"available": False, "jobs": [], "running_count": 0}))
    page.route("**/api/views/all", lambda r: fulfill(r, {"views": [], "unavailable": []}))
    page.route("**/api/tables?**", lambda r: fulfill(r, [
        {"name": "public.people", "schema": "public", "table": "people", "detail": "table"}]))
    page.route("**/api/data-jobs/open", lambda r: fulfill(r, {"job_id": "o", "kind": "open", "status": "complete",
        "result": {"dataset_id": "people", "source": "people", "rows": 5, "query_scope": "database",
                   "source_ref": r.request.post_data_json["source_ref"], "columns": COLUMNS}}))
    page.route("**/api/datasets/*/query", lambda r: fulfill(r, {
        "total": 5, "filtered": 5, "scope": "database", "sampled": False, "charts": [],
        "rows": {"page": 0, "page_size": 50, "columns": ["person_id"], "data": [[1]]}}))
    page.route("**/api/datasets/*/derive", derive)
    page.goto(app_url)
    page.get_by_label("Source type", exact=True).select_option("aurora")
    page.get_by_label("Datasource", exact=True).select_option("aurora:db")
    page.get_by_label("Schema", exact=True).select_option("public")
    page.get_by_label("Table", exact=True).select_option("public.people")
    page.get_by_role("button", name="Load table").click()

    params = page.get_by_role("group", name="Parameters")
    params.get_by_label("New parameter name").fill("index_date")
    params.get_by_label("New parameter type").select_option("date")
    params.get_by_role("button", name="Add parameter").click()
    params.get_by_label("Parameter index_date", exact=True).fill("2024-03-01")
    params.get_by_label("New parameter name").fill("cut")
    params.get_by_label("New parameter type").select_option("number")
    params.get_by_role("button", name="Add parameter").click()
    params.get_by_label("Parameter cut", exact=True).fill("6.5")

    menu(page, "Add to this view").get_by_role("button", name="+ Calculated field").click()
    panel = page.locator(".derive-panel")
    panel.get_by_label("Operation").select_option("expression")
    panel.get_by_text("Functions and syntax").click()
    expect(panel.locator(".derive-help")).to_contain_text("DATEDIFF(unit, start, end)")
    expect(panel.locator(".derive-help")).to_contain_text("CASE WHEN")
    expect(panel).to_contain_text("@index_date = 2024-03-01")

    # An example fills the expression and, when empty, the column name.
    panel.get_by_role("group", name="Expression examples").get_by_role("button", name="Age at index").click()
    expect(panel.get_by_label("Calculation expression")).to_have_value("AGE_AT(birth_date, @index_date)")
    expect(panel.get_by_label("New column name")).to_have_value("age_at_index")

    # An unknown parameter is caught before any request.
    panel.get_by_label("Calculation expression").fill("DATEDIFF(day, birth_date, @nope)")
    panel.get_by_role("button", name="Add column").click()
    expect(panel.get_by_role("alert")).to_have_text("Unknown parameter @nope. Add it under Parameters first.")
    assert derives == []

    # Server validation errors are shown without pydantic's prefix.
    panel.get_by_label("Calculation expression").fill("DATEDIFF(hour, birth_date, @index_date)")
    panel.get_by_role("button", name="Add column").click()
    expect(panel.get_by_role("alert")).to_have_text(
        "Failed: Unknown unit 'hour': use day, week, month or year.")

    # The parameter is resolved now; the spec keeps the @reference and its value.
    panel.get_by_label("New column name").fill("index_month")
    panel.get_by_label("Calculation expression").fill("DATE_TRUNC(month, COALESCE(birth_date, @index_date))")
    panel.get_by_role("button", name="Add column").click()
    expect(panel.get_by_text('Added "index_month".')).to_be_visible()
    assert derives[-1] == {"op": "expression", "name": "index_month",
                           "expression": "DATE_TRUNC(month, COALESCE(birth_date, @index_date))",
                           "parameters": [{"name": "index_date", "kind": "date", "value": "2024-03-01"}]}
    # The new date column is date-filterable.
    group = page.locator(".filter-group", has_text="index_month")
    group.locator("summary").click()
    expect(group).to_contain_text("Data from 1960-01-01 to 2010-01-01")
    # Number parameters are sent as numbers.
    panel.get_by_label("New column name").fill("high")
    panel.get_by_label("Calculation expression").fill("IF(person_id > @cut, 'high', 'low')")
    panel.get_by_role("button", name="Add column").click()
    expect(panel.get_by_text('Added "high".')).to_be_visible()
    assert derives[-1]["parameters"] == [{"name": "cut", "kind": "number", "value": 6.5}]
