import re
import pytest
from playwright.sync_api import Page, expect

from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e


SOURCES = [
    {"kind": "postgres", "id": "postgres:rds-clinical", "label": "Clinical RDS"},
    {"kind": "s3", "id": "lake-files", "label": "Parquet files", "uuid": "s3-uuid"},
    {"kind": "athena", "id": "iceberg-catalog", "label": "Athena Iceberg"},
]


def _fulfill(route, body, status=200):
    route.fulfill(status=status, content_type="application/json", json=body)


def _fulfill_job(route, kind, result):
    """Reply to a /api/data-jobs/<kind> submission with an already-complete job."""
    _fulfill(route, {"job_id": f"{kind}-job", "kind": kind, "status": "complete",
                     "result": result})


def _open_result(dataset_id, ref, column):
    return {"dataset_id": dataset_id, "source": f"Connector / {ref['kind']} / {column}",
            "rows": 2, "columns": [{"name": column, "dtype": "int64",
                                      "filter_kind": "none"}],
            "source_ref": ref, "query_scope": "database"}


def test_postgres_athena_and_s3_use_shared_datasource_open_flow(page: Page, app_url: str):
    opened = []

    page.route("**/api/datasources", lambda route: _fulfill(route, {
        "ready": True, "sources": SOURCES, "catalogs_pending": False,
    }))
    page.route("**/api/workflows**", lambda route: _fulfill(route, {
        "available": False, "jobs": [], "running_count": 0,
    }))

    def tables(route):
        url = route.request.url
        if "kind=postgres" in url:
            body = [{"name": "cdm.person", "schema": "cdm", "table": "person", "detail": "2 rows"}]
        elif "kind=athena" in url:
            body = [{"name": "clinical.person", "schema": "clinical", "table": "person", "detail": "iceberg"}]
        else:
            body = [{"name": "clinical/person.parquet", "detail": "parquet"}]
        _fulfill(route, body)

    page.route("**/api/tables?**", tables)

    def open_table(route):
        body = route.request.post_data_json
        opened.append(body)
        if body.get("source_ref"):
            ref = body["source_ref"]
            _fulfill_job(route, "open", _open_result(f"{ref['kind']}-tab", ref, "person_id"))
        else:
            ref = {"kind": body["kind"], "resource_id": body["resource_id"],
                   "table": body["table"], "uuid": "s3-uuid"}
            _fulfill_job(route, "open", _open_result("s3-tab", ref, "person_id"))

    page.route("**/api/data-jobs/open", open_table)
    page.route("**/api/datasets/*/query", lambda route: _fulfill(route, {
        "total": 2, "filtered": 2, "scope": "database", "sampled": False,
        "charts": [], "rows": {"page": 0, "page_size": 50,
                                  "columns": ["person_id"], "data": [[1], [2]]},
    }))

    page.goto(app_url)
    page.get_by_label("Source type").select_option("postgres")
    source_picker = page.get_by_label("Datasource", exact=True)
    expect(source_picker.locator(
        "option", has_text="Clinical RDS")).to_be_attached(timeout=10000)
    source_picker.select_option("postgres:postgres:rds-clinical")
    table_select = page.get_by_label("Table", exact=True)
    expect(table_select.locator("option", has_text="person")).to_be_attached(timeout=10000)
    table_select.select_option("cdm.person")
    page.get_by_role("button", name="Load table").click()
    expect(page.locator(".tab", has_text="person")).to_be_visible(timeout=10000)
    assert opened[-1]["source_ref"] == {
        "kind": "postgres", "resource_id": "postgres:rds-clinical",
        "table": "person", "schema": "cdm",
    }

    page.get_by_label("Source type").select_option("athena")
    page.get_by_label("Datasource", exact=True).select_option("athena:iceberg-catalog")
    expect(table_select.locator("option", has_text="person")).to_be_attached(timeout=10000)
    table_select.select_option("clinical.person")
    page.get_by_role("button", name="Load table").click()
    expect(page.locator(".tab", has_text="person")).to_be_visible(timeout=10000)
    assert opened[-1]["source_ref"] == {
        "kind": "athena", "resource_id": "iceberg-catalog",
        "table": "person", "schema": "clinical",
    }

    page.get_by_label("Source type").select_option("s3")
    page.get_by_label("Datasource", exact=True).select_option("s3:lake-files")
    expect(table_select.locator("option", has_text="clinical/person.parquet")).to_be_attached(timeout=10000)
    table_select.select_option("clinical/person.parquet")
    page.get_by_role("button", name="Load file").click()
    expect(page.locator(".tab", has_text="person.parquet")).to_be_visible(timeout=10000)
    assert opened[-1] == {"kind": "s3", "resource_id": "lake-files",
                          "table": "clinical/person.parquet"}


def test_join_builder_adds_postgres_and_athena_with_schema_refs(page: Page, app_url: str):
    opened = []
    join_bodies = []
    page.route("**/api/datasources", lambda route: _fulfill(route, {
        "ready": True, "sources": SOURCES, "catalogs_pending": False,
    }))
    page.route("**/api/workflows**", lambda route: _fulfill(route, {
        "available": False, "jobs": [], "running_count": 0,
    }))

    def tables(route):
        if "kind=postgres" in route.request.url:
            body = [{"name": "cdm.person", "schema": "cdm", "table": "person", "detail": "2 rows"}]
        elif "kind=athena" in route.request.url:
            body = [{"name": "clinical.samples", "schema": "clinical", "table": "samples", "detail": "iceberg"}]
        else:
            body = []
        _fulfill(route, body)

    page.route("**/api/tables?**", tables)

    def open_table(route):
        ref = route.request.post_data_json["source_ref"]
        opened.append(ref)
        _fulfill_job(route, "open", _open_result(f"{ref['kind']}-{len(opened)}", ref, "person_id"))

    page.route("**/api/data-jobs/open", open_table)
    page.route("**/api/datasets/*/query", lambda route: _fulfill(route, {
        "total": 2, "filtered": 2, "scope": "loaded", "sampled": False,
        "charts": [], "rows": {"page": 0, "page_size": 50,
                                  "columns": ["person_id"], "data": [[1], [2]]},
    }))
    page.route("**/api/joins/recommend", lambda route: _fulfill(route, {
        "candidates": [], "warnings": [],
        "jev": {"status": "not_configured", "configured": False, "model": ""},
    }))
    page.route("**/api/datasets/join/suggest?**", lambda route: _fulfill(route, []))
    page.route("**/api/datasets/join/validate", lambda route: _fulfill(route, {
        "ok": True, "engine": "duckdb", "engine_reason": "",
        "capped_inputs": [], "problems": [],
        "steps": [{"problems": [], "notes": [],
                    "conditions": [{"problem": None, "note": None}] }],
    }))

    def join(route):
        body = route.request.post_data_json
        join_bodies.append(body)
        _fulfill_job(route, "join", {"dataset_id": "mixed-join", "source": "Clinical join",
                         "rows": 2, "columns": [{"name": "person_id", "dtype": "int64",
                                                    "filter_kind": "none"}],
                         "source_ref": {"kind": "join", "base": opened[0], "steps": [
                             {"source": opened[1], "how": "left",
                              "conditions": body["steps"][0]["conditions"],
                              "columns": None, "alias": "samples"}]},
                         "query_scope": "loaded", "join": {"engine": "duckdb",
                         "base_rows": 2, "rows": 2, "total_rows": 2,
                         "truncated": False, "steps": [], "notes": [],
                         "capped_inputs": []}})

    page.route("**/api/data-jobs/join", join)
    page.goto(app_url)
    page.get_by_role("button", name="Join tables").click()   # opens Data Builder
    canvas = page.locator(".jc")
    canvas.get_by_role("button", name=re.compile("^Clinical RDS")).click()
    canvas.get_by_role("button", name="Add cdm.person to canvas").click()
    expect(canvas.locator(".jc-node")).to_have_count(1, timeout=10000)
    canvas.get_by_role("button", name=re.compile("^Athena Iceberg")).click()
    canvas.get_by_role("button", name="Add clinical.samples to canvas").click()
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
    expect(page.locator(".tab", has_text="person + samples")).to_be_visible(timeout=10000)
    assert opened == [
        {"kind": "postgres", "resource_id": "postgres:rds-clinical",
         "schema": "cdm", "table": "person"},
        {"kind": "athena", "resource_id": "iceberg-catalog",
         "schema": "clinical", "table": "samples"},
    ]
    assert join_bodies[0]["steps"][0]["conditions"] == [
        {"left": "person_id", "op": "=", "right": "person_id"}]
    assert join_bodies[0]["allow_loaded"] is True
