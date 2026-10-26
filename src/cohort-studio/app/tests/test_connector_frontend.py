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
            _fulfill(route, _open_result(f"{ref['kind']}-tab", ref, "person_id"))
        else:
            ref = {"kind": body["kind"], "resource_id": body["resource_id"],
                   "table": body["table"], "uuid": "s3-uuid"}
            _fulfill(route, _open_result("s3-tab", ref, "person_id"))

    page.route("**/api/datasets/open", open_table)
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
        _fulfill(route, _open_result(f"{ref['kind']}-{len(opened)}", ref, "person_id"))

    page.route("**/api/datasets/open", open_table)
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
        _fulfill(route, {"dataset_id": "mixed-join", "source": "Clinical join",
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

    page.route("**/api/datasets/join", join)
    page.goto(app_url)
    page.get_by_role("button", name="Join tables").click()
    panel = page.locator(".join-panel")
    panel.get_by_label("Join datasource").select_option("postgres:postgres:rds-clinical")
    expect(panel.get_by_label("Join schema").locator(
        "option", has_text="cdm")).to_have_count(1, timeout=10000)
    panel.get_by_label("Join schema").select_option("cdm")
    table = panel.get_by_role("combobox", name="Source table to add")
    table.fill("person")
    table.press("Enter")
    panel.get_by_role("button", name="Add table").click()
    expect(panel.get_by_label("Start from")).to_have_value("cdm.person")

    panel.get_by_label("Join datasource").select_option("athena:iceberg-catalog")
    expect(panel.get_by_label("Join schema").locator(
        "option", has_text="clinical")).to_have_count(1, timeout=10000)
    panel.get_by_label("Join schema").select_option("clinical")
    table.fill("samples")
    table.press("Enter")
    panel.get_by_role("button", name="Add table").click()
    expect(panel.locator(".join-step")).to_have_count(1)
    panel.get_by_label("Left key step 1 condition 1").select_option(label="person_id")
    panel.get_by_label("Right key step 1 condition 1").select_option(label="person_id")
    expect(panel.get_by_label("Allow full-source cross-source join")).not_to_be_checked()
    expect(panel.get_by_role("button", name="Join into new tab")).to_be_disabled()
    panel.get_by_label("Allow full-source cross-source join").check()
    expect(panel.get_by_role("button", name="Join into new tab")).to_be_enabled(timeout=10000)
    panel.get_by_role("button", name="Join into new tab").click()
    expect(page.locator(".tab", has_text="Clinical join")).to_be_visible(timeout=10000)
    assert opened == [
        {"kind": "postgres", "resource_id": "postgres:rds-clinical",
         "schema": "cdm", "table": "person"},
        {"kind": "athena", "resource_id": "iceberg-catalog",
         "schema": "clinical", "table": "samples"},
    ]
    assert join_bodies[0]["steps"][0]["conditions"] == [
        {"left": "person_id", "op": "=", "right": "person_id"}]
    assert join_bodies[0]["allow_loaded"] is True


def test_s3_source_can_join_loaded_rows_with_explicit_consent(page: Page, app_url: str):
    sources = [
        {"kind": "aurora", "id": "aurora:clinical", "label": "Clinical Aurora"},
        {"kind": "s3", "id": "s3:lake", "label": "Parquet lake", "uuid": "lake-uuid"},
    ]
    opened = []
    join_bodies = []

    page.route("**/api/datasources", lambda route: _fulfill(route, {
        "ready": True, "sources": sources, "catalogs_pending": False,
    }))
    page.route("**/api/workflows**", lambda route: _fulfill(route, {
        "available": False, "jobs": [], "running_count": 0,
    }))

    def tables(route):
        if "kind=s3" in route.request.url:
            result = [{"name": "samples.parquet", "detail": "Parquet file"}]
        else:
            result = [{"name": "cdm.person", "schema": "cdm", "table": "person",
                       "detail": "100 rows"}]
        _fulfill(route, result)

    page.route("**/api/tables?**", tables)

    def open_source(route):
        ref = route.request.post_data_json["source_ref"]
        opened.append(ref)
        _fulfill(route, _open_result(f"opened-{len(opened)}", ref, "person_id"))

    page.route("**/api/datasets/open", open_source)
    page.route("**/api/datasets/*/query", lambda route: _fulfill(route, {
        "total": 2, "filtered": 2, "scope": "loaded", "sampled": True,
        "charts": [], "rows": {"page": 0, "page_size": 50,
                                  "columns": ["person_id"], "data": [[1], [2]]},
    }))
    page.route("**/api/joins/recommend", lambda route: _fulfill(route, {
        "candidates": [], "warnings": [],
        "jev": {"status": "not_configured", "configured": False, "model": ""},
    }))
    page.route("**/api/datasets/join/suggest?**", lambda route: _fulfill(route, []))
    page.route("**/api/datasets/join/validate", lambda route: _fulfill(route, {
        "ok": True, "engine": "duckdb", "engine_reason": "loaded rows",
        "capped_inputs": [], "problems": [], "steps": [],
    }))

    def join(route):
        join_bodies.append(route.request.post_data_json)
        body = route.request.post_data_json
        _fulfill(route, {"dataset_id": "joined-s3", "source": "S3 join",
                         "rows": 2, "columns": [{"name": "person_id", "dtype": "int64",
                                                    "filter_kind": "none"}],
                         "source_ref": {"kind": "join", "base": opened[0], "allow_loaded": True,
                                        "steps": [{"source": opened[1], "how": "inner",
                                                   "conditions": body["steps"][0]["conditions"],
                                                   "columns": None, "alias": "samples"}]},
                         "query_scope": "loaded", "join": {"engine": "duckdb",
                         "base_rows": 2, "rows": 2, "total_rows": 2,
                         "truncated": False, "steps": [], "notes": [], "capped_inputs": []}})

    page.route("**/api/datasets/join", join)
    page.goto(app_url)
    page.get_by_role("button", name="Join tables").click()
    panel = page.locator(".join-panel")
    panel.get_by_label("Join datasource").select_option("aurora:aurora:clinical")
    panel.get_by_label("Join schema").select_option("cdm")
    table = panel.get_by_role("combobox", name="Source table to add")
    table.fill("person")
    table.press("Enter")
    panel.get_by_role("button", name="Add table").click()
    panel.get_by_label("Join datasource").select_option("s3:s3:lake")
    s3_file = panel.get_by_role("combobox", name="S3 file to add")
    s3_file.fill("samples.parquet")
    s3_file.press("Enter")
    panel.get_by_role("button", name="Add file").click()
    expect(panel.locator(".join-step")).to_have_count(1)
    panel.get_by_label("Left key step 1 condition 1").select_option(label="person_id")
    panel.get_by_label("Right key step 1 condition 1").select_option(label="person_id")
    expect(panel.get_by_label("Allow full-source cross-source join")).not_to_be_checked()
    panel.get_by_label("Allow full-source cross-source join").check()
    expect(panel.get_by_role("button", name="Join into new tab")).to_be_enabled(timeout=10000)
    panel.get_by_role("button", name="Join into new tab").click()
    expect(page.locator(".tab", has_text="S3 join")).to_be_visible(timeout=10000)
    assert opened[1] == {"kind": "s3", "resource_id": "s3:lake",
                         "uuid": "lake-uuid", "table": "samples.parquet"}
    assert join_bodies[0]["allow_loaded"] is True
