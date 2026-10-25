import pytest
from playwright.sync_api import expect
from tests.test_e2e import app_url, FIXTURE_CSV

pytestmark = pytest.mark.e2e


def test_workflow_picker_is_separate_from_s3_destination(page, app_url):
    def fulfill(route, value):
        route.fulfill(json=value)
    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True, "catalogs_pending": False, "sources": [
            {"kind": "s3", "id": "results-folder", "label": "Results S3"}]}))
    page.route("**/api/workflows", lambda route: fulfill(route, {
        "available": True, "jobs": [], "running_count": 0}))
    page.route("**/api/workflows/registry", lambda route: fulfill(route, {
        "available": True, "workflows": [{"id": "demo-run", "name": "Demo analysis"}]}))
    page.goto(app_url)
    page.locator('input[type="file"]').set_input_files(FIXTURE_CSV)
    page.get_by_role("button", name="Run workflow", exact=False).click()
    workflow = page.get_by_label("Workflow", exact=True)
    destination = page.get_by_label("Input S3 folder", exact=True)
    expect(workflow).to_have_value("demo-run")
    expect(destination).to_have_value("results-folder")
    assert workflow.bounding_box()["y"] < destination.bounding_box()["y"]
    expect(page.get_by_label("Output S3 folder")).to_have_value("results-folder")
    expect(page.get_by_role("button", name="Submit job")).to_be_enabled()
