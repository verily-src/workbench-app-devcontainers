import pytest
from playwright.sync_api import Page, expect
from pathlib import Path

from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e

FIXTURE_CSV = Path(__file__).parent / "fixtures" / "samples.csv"


@pytest.fixture
def loaded_workflow_page(page: Page, app_url: str):
    page.goto(app_url)
    expect(page.get_by_text("No data loaded")).to_be_visible(timeout=15000)
    page.locator('input[type="file"]').set_input_files(FIXTURE_CSV)
    expect(page.get_by_text("of 100 rows", exact=False)).to_be_visible(timeout=15000)
    return page


def _stub_launch_routes(page: Page, submitted: list, exports: list):
    def fulfill(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", json=body)

    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True,
        "sources": [
            {"kind": "s3", "id": "input-resource", "label": "Input"},
            {"kind": "s3", "id": "output-resource", "label": "Output"},
        ],
        "catalogs_pending": False,
    }))
    page.route("**/api/workflows/registry", lambda route: fulfill(route, {
        "available": True,
        "workflows": [
            {"id": "cohort-genetics-demo", "name": "Genetics demo",
             "type": "NEXTFLOW", "description": "Synthetic demo"},
            {"id": "hello_world", "name": "Hello world",
             "type": "NEXTFLOW", "description": "Existing workflow"},
        ],
    }))

    def export(route):
        body = route.request.post_data_json
        exports.append(body)
        fulfill(route, {"s3_uri": f"s3://input/{body['path']}",
                        "resource_id": body["resource_id"],
                        "path": body["path"], "rows": 2})

    page.route("**/api/datasets/*/export-cohort", export)

    def submit(route):
        submitted.append(route.request.post_data_json)
        fulfill(route, {"run_id": f"run-{len(submitted)}", "name": "demo",
                        "status": "PENDING"})

    page.route("**/api/workflows/submit", submit)


def _open_launch(page: Page):
    page.get_by_role("button", name="Run workflow ▸").click()
    expect(page.get_by_role("combobox", name="Workflow")).to_have_value(
        "cohort-genetics-demo", timeout=10000)


def test_genetics_workflow_uses_fresh_export_and_nextflow_params(
        loaded_workflow_page: Page):
    page = loaded_workflow_page
    submitted = []
    exports = []
    _stub_launch_routes(page, submitted, exports)
    _open_launch(page)

    page.get_by_label("Output S3 folder").select_option("output-resource")
    path = page.get_by_label("Input CSV path")
    path.fill("cohort-studio/first-cohort.csv")
    page.get_by_label("Job name").fill("genetics-demo-test")
    page.get_by_role("button", name="Write CSV").click()
    expect(page.get_by_text("Wrote 2 rows", exact=False)).to_be_visible()
    submit = page.get_by_role("button", name="Submit job")
    expect(submit).to_be_enabled()

    filter_group = page.locator(".filter-group", has_text="tissue")
    filter_group.locator("summary").click()
    filter_group.get_by_label("liver").check()
    expect(submit).to_be_disabled()

    path.fill("cohort-studio/new-cohort.csv")
    expect(submit).to_be_disabled()
    page.get_by_role("button", name="Write CSV").click()
    expect(page.get_by_text("Wrote 2 rows", exact=False)).to_be_visible()
    page.get_by_label("Input S3 folder").select_option("output-resource")
    expect(submit).to_be_disabled()
    page.get_by_label("Input S3 folder").select_option("input-resource")
    expect(submit).to_be_disabled()
    page.get_by_role("button", name="Write CSV").click()
    expect(page.get_by_text("Wrote 2 rows", exact=False)).to_be_visible()
    submit.click()

    expect(page.get_by_text('Submitted "demo"', exact=False)).to_be_visible()
    assert len(exports) == 3
    assert all(item["workflow"] == "cohort-genetics-demo" for item in exports)
    assert exports[0]["filters"] == []
    assert exports[1]["filters"][0]["values"] == ["liver"]
    assert exports[2]["resource_id"] == "input-resource"
    body = submitted[0]
    assert body["workflow"] == "cohort-genetics-demo"
    assert body["demo_input_resource_id"] == "input-resource"
    assert body["demo_input_csv_path"] == "cohort-studio/new-cohort.csv"
    assert body["params_file_bucket_id"] == "input-resource"
    assert body["params_file_path"].startswith("cohort-studio/params/")
    assert body["params_file_path"].endswith(".json")
    assert body["demo_output_path"].startswith("cohort-studio/genetics-demo/")
    assert "batch_input_bucket_id" not in body


def test_existing_workflow_keeps_batch_csv_submission(
        loaded_workflow_page: Page):
    page = loaded_workflow_page
    submitted = []
    exports = []
    _stub_launch_routes(page, submitted, exports)
    _open_launch(page)
    page.get_by_label("Workflow").select_option("hello_world")
    page.get_by_label("Job name").fill("existing-workflow-test")
    page.get_by_label("Input CSV path").fill("cohort-studio/existing.csv")
    page.get_by_role("button", name="Write CSV").click()
    expect(page.get_by_text("Wrote 2 rows", exact=False)).to_be_visible()
    page.get_by_role("button", name="Submit job").click()

    assert submitted == [{
        "workflow": "hello_world", "output_bucket_id": "input-resource",
        "job_id": "existing-workflow-test",
        "batch_input_bucket_id": "input-resource",
        "batch_input_csv_path": "cohort-studio/existing.csv",
        "column_mapping": "", "row_selection": "",
    }]


def test_workflow_prefers_managed_demo_folders(loaded_workflow_page: Page):
    page = loaded_workflow_page
    _stub_launch_routes(page, [], [])
    page.route("**/api/datasources", lambda route: route.fulfill(json={
        "ready": True, "sources": [
            {"kind": "s3", "id": "external-data", "label": "External"},
            {"kind": "s3", "id": "nextflow_params", "label": "Params"},
            {"kind": "s3", "id": "nextflow_outputs", "label": "Outputs"},
        ], "catalogs_pending": False,
    }))
    _open_launch(page)
    expect(page.get_by_label("Input S3 folder")).to_have_value("nextflow_params")
    expect(page.get_by_label("Output S3 folder")).to_have_value("nextflow_outputs")
