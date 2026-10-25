import pytest
from playwright.sync_api import Page, expect

from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e


def test_source_picker_cascades_without_autoload_and_keeps_datasource(
        page: Page, app_url: str):
    sources = [
        {"kind": "aurora", "id": "clinical-a", "label": "clinical-a · Aurora"},
        {"kind": "aurora", "id": "clinical-b", "label": "clinical-b · Aurora"},
        {"kind": "s3", "id": "lake", "label": "lake · S3"},
    ]
    opened = []

    def fulfill(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", json=body)

    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True, "sources": sources, "catalogs_pending": False,
    }))
    page.route("**/api/workflows**", lambda route: fulfill(route, {
        "available": False, "jobs": [], "running_count": 0,
    }))
    page.route("**/api/views/all", lambda route: fulfill(route, {
        "views": [], "unavailable": [],
    }))

    def list_tables(route):
        params = dict(item.split("=", 1) for item in route.request.url.split("?", 1)[1].split("&"))
        resource_id = params.get("resource_id", "")
        if resource_id == "clinical-a":
            body = [
                {"name": "cdm.person", "schema": "cdm", "table": "person", "detail": "table"},
                {"name": "public.samples", "schema": "public", "table": "samples", "detail": "table"},
            ]
        elif resource_id == "clinical-b":
            body = [{"name": "public.events", "schema": "public",
                     "table": "events", "detail": "table"}]
        else:
            body = [
                {"name": "exports/result.csv", "detail": "file"},
                {"name": "exports/nested/details.csv", "detail": "file"},
                {"name": "other/summary.csv", "detail": "file"},
            ]
        fulfill(route, body)

    page.route("**/api/tables?**", list_tables)

    def open_dataset(route):
        opened.append(route.request.post_data_json)
        fulfill(route, {"dataset_id": "opened", "source": "opened", "rows": 1,
                        "columns": [], "sampled": False, "query_scope": "loaded"})

    page.route("**/api/datasets/open", open_dataset)
    page.route("**/api/datasets/opened/query", lambda route: fulfill(route, {
        "total": 1, "filtered": 1, "charts": [],
        "rows": {"page": 0, "page_size": 50, "columns": [], "data": [[]]},
        "scope": "loaded", "sampled": False,
    }))
    page.goto(app_url)

    page.get_by_label("Source type").select_option("aurora")
    expect(page.get_by_label("Datasource")).to_be_enabled()
    expect(page.get_by_label("Datasource").locator("option")).to_have_count(3)
    page.get_by_label("Datasource").select_option("aurora:clinical-a")
    expect(page.get_by_label("Schema")).to_be_visible()
    expect(page.get_by_label("Schema")).to_have_value("")
    expect(page.get_by_label("Table")).to_be_disabled()
    page.get_by_label("Schema").select_option("cdm")
    expect(page.get_by_label("Table").locator("option")).to_have_count(2)
    expect(page.get_by_label("Table").locator("option").nth(1)).to_have_text("person (table)")
    expect(page.get_by_label("Datasource")).to_have_value("aurora:clinical-a")
    expect(page.get_by_role("button", name="OMOP", exact=True)).to_be_visible()
    expect(page.get_by_text("Saved views", exact=True)).to_be_visible()
    assert opened == []

    page.get_by_label("Schema").select_option("public")
    expect(page.get_by_label("Datasource")).to_have_value("aurora:clinical-a")
    expect(page.get_by_label("Table")).to_have_value("")
    assert opened == []

    page.get_by_label("Source type").select_option("s3")
    expect(page.get_by_label("Datasource")).to_have_value("")
    expect(page.get_by_label("Schema")).to_have_count(0)
    expect(page.get_by_label("Table")).to_have_count(0)
    page.get_by_label("Datasource").select_option("s3:lake")
    expect(page.get_by_label("File folder")).to_have_value("")
    page.get_by_label("File folder").select_option("exports/nested")
    expect(page.get_by_label("Table").locator("option")).to_have_count(2)
    expect(page.get_by_label("Table").locator("option").nth(1)).to_have_text(
        "details.csv (file)")
    page.get_by_label("File folder").select_option("exports")
    expect(page.get_by_label("Table").locator("option")).to_have_count(3)
    expect(page.get_by_label("Table").locator("option").nth(1)).to_have_text(
        "result.csv (file)")
    expect(page.get_by_label("Schema")).to_have_count(0)
    assert opened == []

    page.get_by_label("File folder").select_option("")
    page.get_by_label("Table").select_option("other/summary.csv")
    page.get_by_role("button", name="Load file").click()
    expect(page.locator(".tab.active")).to_contain_text("summary.csv")
    assert opened == [{"kind": "s3", "resource_id": "lake",
                       "table": "other/summary.csv"}]
