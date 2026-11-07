import pytest
from playwright.sync_api import Page, expect

from tests.test_e2e import app_url
from tests.ui_helpers import load_table, open_data_builder

pytestmark = pytest.mark.e2e


def test_connections_list_sources_and_tables_without_autoload(
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
        body = route.request.post_data_json
        opened.append(body.get("source_ref", body))
        fulfill(route, {"job_id": "source-picker-open", "status": "complete", "result": {
            "dataset_id": "opened", "source": "opened", "rows": 1,
            "columns": [], "sampled": False, "query_scope": "loaded"}})

    page.route("**/api/data-jobs/open", open_dataset)
    page.route("**/api/datasets/opened/query", lambda route: fulfill(route, {
        "total": 1, "filtered": 1, "charts": [],
        "rows": {"page": 0, "page_size": 50, "columns": [], "data": [[]]},
        "scope": "loaded", "sampled": False,
    }))
    page.goto(app_url)
    expect(page.get_by_text("Saved views", exact=True)).to_be_visible()
    expect(page.get_by_role("group", name="Explore view")).to_have_count(0)
    expect(page.get_by_role("button", name="OMOP", exact=True)).to_have_count(0)

    canvas = open_data_builder(page)
    sources_list = canvas.get_by_role("list", name="Datasources")
    expect(sources_list.get_by_role("button")).to_have_count(3)
    # Connections starts on the first datasource and lists its tables by schema.
    first = canvas.locator('[data-source-key="aurora:clinical-a"]')
    expect(first).to_have_attribute("aria-pressed", "true")
    cdm = canvas.get_by_role("group", name="Schema cdm")
    expect(cdm.locator(".jc-table-pick")).to_have_count(1)
    expect(cdm.locator(".jc-table-pick")).to_have_text("person")
    expect(canvas.get_by_role("group", name="Schema public").locator(".jc-table-pick")).to_have_text("samples")
    # Picking a table shows its details; nothing opens until Open in Explore.
    canvas.locator('li[data-table="cdm.person"] .jc-table-pick').click()
    expect(canvas.get_by_role("region", name="Selected table")).to_contain_text("person")
    assert opened == []

    canvas.locator('[data-source-key="aurora:clinical-b"]').click()
    expect(canvas.get_by_role("region", name="Selected table")).to_have_count(0)
    expect(canvas.locator('li[data-table="public.events"]')).to_have_count(1)
    assert opened == []

    # S3 files group by folder; search narrows the list.
    canvas.locator('[data-source-key="s3:lake"]').click()
    expect(canvas.get_by_role("group", name="Folder exports", exact=True).locator(".jc-table-pick")).to_have_text("result.csv")
    expect(canvas.get_by_role("group", name="Folder exports/nested", exact=True).locator(".jc-table-pick")).to_have_text("details.csv")
    canvas.get_by_role("searchbox", name="Search tables").fill("nested")
    expect(canvas.locator(".jc-table-list .jc-table-pick")).to_have_count(1)
    canvas.get_by_role("searchbox", name="Search tables").fill("")
    assert opened == []

    load_table(page, "s3:lake", "other/summary.csv")
    expect(page.locator(".tab.active")).to_contain_text("summary.csv")
    assert opened == [{"kind": "s3", "resource_id": "lake",
                       "table": "other/summary.csv"}]
