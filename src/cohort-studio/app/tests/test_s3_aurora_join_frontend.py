import re

import pytest
from playwright.sync_api import expect

from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e


def test_data_builder_joins_s3_files_with_aurora_after_full_source_consent(page, app_url):
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
    page.get_by_role("button", name="Join tables").click()   # opens Data Builder
    canvas = page.locator(".jc")
    # Both datasources are listed as connections; S3 files show beside Aurora tables.
    expect(canvas.get_by_role("button", name=re.compile("^Genetics files"))).to_be_visible()
    canvas.get_by_role("button", name=re.compile("^Clinical")).click()
    expect(canvas.get_by_role("button", name="Add cdm.condition_occurrence_with_a_long_table_name to canvas")).to_be_visible()
    canvas.get_by_role("button", name="Add cdm.person to canvas").click()
    expect(canvas.locator(".jc-node")).to_have_count(1, timeout=10000)
    canvas.get_by_role("button", name=re.compile("^Genetics files")).click()
    canvas.get_by_role("button", name="Add demo/samples.parquet to canvas").click()
    expect(canvas.locator(".jc-node")).to_have_count(2, timeout=10000)
    config = canvas.get_by_role("region", name="Join configuration")
    for label in ("Left field, clause 1", "Right field, clause 1"):
        box = config.get_by_role("combobox", name=label)
        box.fill("person_id")
        box.press("Enter")
    config.get_by_role("button", name="Apply").click()
    consent = canvas.get_by_label("Allow full-source cross-source join")
    expect(consent).not_to_be_checked()
    run = canvas.get_by_role("button", name="Save & open in Explore")
    expect(run).to_be_disabled()
    consent.check()
    expect(run).to_be_enabled(timeout=10000)
    run.click()
    expect(page.locator(".tab", has_text="person + samples.parquet")).to_be_visible(timeout=10000)
    assert opened == [
        {"kind": "aurora", "resource_id": "clinical", "schema": "cdm", "table": "person"},
        {"kind": "s3", "resource_id": "lake", "uuid": "lake-uuid",
         "table": "demo/samples.parquet"},
    ]
    assert join_requests[0]["allow_loaded"] is True
