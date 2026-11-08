from playwright.sync_api import expect

from tests.test_e2e import app_url  # noqa: F401
from tests.test_dashboard_filters_frontend import _upload, PEOPLE
from tests.test_workflow_launch_frontend import (
    _open_launch, _stub_launch_routes, loaded_workflow_page,  # noqa: F401
)


def test_pending_export_keeps_its_dataset_context(loaded_workflow_page):
    page = loaded_workflow_page
    _stub_launch_routes(page, [], [])
    held = []
    page.route("**/api/datasets/*/export-cohort", lambda route: held.append(route))
    _open_launch(page)
    page.get_by_role("button", name="Write CSV").click()
    page.wait_for_timeout(200)
    assert held
    _upload(page, "people.csv", PEOPLE, 10)
    expect(page.get_by_label("Input CSV path")).to_have_value("cohort-studio/people_csv.csv")
    held[0].fulfill(json={"s3_uri": "s3://input/old.csv", "resource_id": "input-resource",
                          "path": "old.csv", "rows": 2})
    expect(page.get_by_text("Wrote 2 rows for samples.csv", exact=False)).to_contain_text("previous selection")
    expect(page.get_by_role("button", name="Submit job")).to_be_disabled()


def test_pending_submission_identifies_original_dataset(loaded_workflow_page):
    page = loaded_workflow_page
    _stub_launch_routes(page, [], [])
    held = []
    page.route("**/api/workflows/submit", lambda route: held.append(route))
    _open_launch(page)
    page.get_by_label("Workflow").select_option("hello_world")
    page.get_by_role("button", name="Submit job").click()
    page.wait_for_timeout(200)
    assert held
    _upload(page, "people.csv", PEOPLE, 10)
    expect(page.get_by_label("Job name")).to_have_value("cohort-studio-people_csv")
    held[0].fulfill(json={"run_id": "run-1", "name": "demo", "status": "PENDING"})
    expect(page.get_by_text('Submitted "demo" — PENDING (from samples.csv, previous selection).')).to_be_visible()
