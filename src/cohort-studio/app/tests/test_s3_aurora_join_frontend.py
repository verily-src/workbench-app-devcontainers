import pytest
from playwright.sync_api import expect

from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e


def test_join_panel_exposes_s3_files_for_aurora_join_with_full_source_consent(page, app_url):
    sources = [
        {"kind": "aurora", "id": "clinical", "label": "Clinical"},
        {"kind": "s3", "id": "lake", "label": "Genetics files", "uuid": "lake-uuid"},
    ]
    opened, join_requests = [], []

    def fulfill(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", json=body)

    page.route("**/api/config", lambda route: fulfill(route, {
        "chart_palette": "verily", "llm": {"provider": "anthropic", "providers": {}},
    }))
    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True, "sources": sources, "catalogs_pending": False,
    }))
    page.route("**/api/workflows**", lambda route: fulfill(route, {
        "available": False, "jobs": [], "running_count": 0,
    }))
    page.route("**/api/views/all", lambda route: fulfill(route, {"views": [], "unavailable": []}))

    def tables(route):
        if "kind=s3" in route.request.url:
            result = [{"name": "demo/samples.parquet", "detail": "Parquet file"}]
        else:
            result = [{"name": "cdm.person", "schema": "cdm", "table": "person",
                       "detail": "Aurora table"},
                      {"name": "cdm.condition_occurrence_with_a_long_table_name", "schema": "cdm",
                       "table": "condition_occurrence_with_a_long_table_name", "detail": "Aurora table"}]
        fulfill(route, result)

    page.route("**/api/tables?**", tables)

    def open_source(route):
        ref = route.request.post_data_json["source_ref"]
        opened.append(ref)
        dataset_id = f"source-{len(opened)}"
        fulfill(route, {"job_id": "open-" + dataset_id, "status": "complete", "result": {"dataset_id": dataset_id, "source": ref["table"], "rows": 2,
            "columns": [{"name": "person_id", "dtype": "int64", "filter_kind": "none"},
                        {"name": "variant", "dtype": "text", "filter_kind": "none"}],
            "source_ref": ref, "query_scope": "database" if ref["kind"] == "aurora" else "loaded"}})

    page.route("**/api/data-jobs/open", open_source)
    page.route("**/api/datasets/*/query", lambda route: fulfill(route, {
        "total": 2, "filtered": 2, "scope": "database", "sampled": False,
        "charts": [], "rows": {"page": 0, "page_size": 50,
            "columns": ["person_id", "variant"], "data": [[1, "v1"], [2, "v2"]]},
    }))
    page.route("**/api/joins/recommend", lambda route: fulfill(route, {
        "candidates": [], "warnings": [],
        "jev": {"status": "not_configured", "configured": False, "model": ""},
    }))
    page.route("**/api/datasets/join/suggest?**", lambda route: fulfill(route, []))
    page.route("**/api/datasets/join/validate", lambda route: fulfill(route, {
        "ok": True, "engine": "duckdb", "engine_reason": "Mixed sources use disk staging.",
        "capped_inputs": [], "problems": [], "steps": [{
            "problems": [], "notes": [], "conditions": [{"problem": None, "note": None}],
        }],
    }))

    def join(route):
        join_requests.append(route.request.post_data_json)
        fulfill(route, {"job_id": "join-result", "status": "complete", "result": {"dataset_id": "aurora-s3-result", "source": "Aurora + S3",
            "rows": 2, "columns": [{"name": "person_id", "dtype": "int64",
                                      "filter_kind": "none"}],
            "query_scope": "loaded", "join": {"engine": "duckdb", "rows": 2}}})

    page.route("**/api/data-jobs/join", join)
    page.goto(app_url)
    page.get_by_role("button", name="Join tables").click()
    panel = page.locator(".join-panel")
    datasource = panel.get_by_label("Join datasource")
    expect(datasource.locator("optgroup[label='S3 files'] option")).to_have_count(1)
    datasource.select_option("aurora:clinical")
    panel.get_by_label("Join schema").select_option("cdm")
    table = panel.get_by_role("combobox", name="Source table to add")
    table.click()
    long_name = panel.get_by_role("option", name="cdm.condition_occurrence_with_a_long_table_name Aurora table")
    expect(long_name).to_be_visible()
    assert long_name.locator('.combo-label').evaluate('(el) => el.scrollWidth <= el.clientWidth')
    table.fill("person")
    table.press("Enter")
    panel.get_by_role("button", name="Add table").click()

    datasource.select_option("s3:lake")
    file_picker = panel.get_by_role("combobox", name="S3 file to add")
    file_picker.fill("samples.parquet")
    file_picker.press("Enter")
    panel.get_by_role("button", name="Add file").click()
    expect(panel.locator(".join-step")).to_have_count(1)
    panel.get_by_label("Left key step 1 condition 1").select_option(label="person_id")
    panel.get_by_label("Right key step 1 condition 1").select_option(label="person_id")
    consent = panel.get_by_label("Allow full-source cross-source join")
    expect(consent).not_to_be_checked()
    expect(panel.get_by_role("button", name="Join into new tab")).to_be_disabled()
    consent.check()
    expect(panel.get_by_role("button", name="Join into new tab")).to_be_enabled()
    panel.get_by_role("button", name="Join into new tab").click()
    expect(page.locator(".tab", has_text="Aurora + S3")).to_be_visible()
    assert opened == [
        {"kind": "aurora", "resource_id": "clinical", "schema": "cdm", "table": "person"},
        {"kind": "s3", "resource_id": "lake", "uuid": "lake-uuid",
         "table": "demo/samples.parquet"},
    ]
    assert join_requests[0]["allow_loaded"] is True
