import pytest
from playwright.sync_api import Page, expect

from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e


def test_add_postgres_s3_and_athena_sources(page: Page, app_url: str):
    sources = []
    submitted = []

    def fulfill(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", json=body)

    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True, "sources": sources, "catalogs_pending": False,
    }))
    page.route("**/api/workflows**", lambda route: fulfill(route, {
        "available": False, "jobs": [], "running_count": 0,
    }))
    page.route("**/api/tables?**", lambda route: fulfill(route, []))

    def add_source(route):
        body = route.request.post_data_json
        submitted.append(body)
        runtime_id = body["id"] if body["kind"] == "athena" else f"{body['kind']}:{body['id']}"
        source = {"kind": body["kind"], "id": runtime_id,
                  "label": body["label"]}
        sources.append(source)
        fulfill(route, source)

    page.route("**/api/sources", add_source)
    page.goto(app_url)

    def form(kind: str):
        page.get_by_role("button", name="Add data source").click()
        page.get_by_role("dialog").get_by_label("Source type").select_option(kind)

    form("postgres")
    fields = {
        "Source ID": "clinical", "Display name": "Clinical RDS",
        "AWS Secrets Manager connection secret ID": "studio/clinical",
        "AWS region": "us-east-1",
    }
    for label, value in fields.items(): page.get_by_label(label).fill(value)
    page.screenshot(path="/private/tmp/studio-add-source.png")
    page.get_by_role("button", name="Test and add source").click()
    expect(page.get_by_label("Datasource")).to_have_value("postgres:postgres:clinical", timeout=10000)

    expect(page.get_by_label("Datasource")).to_contain_text("Clinical RDS")

    form("s3")
    for label, value in {"Source ID": "lake", "Display name": "Lake",
                         "S3 bucket": "study-data", "Prefix (optional)": "parquet/",
                         "AWS region": "us-east-1"}.items():
        page.get_by_label(label).fill(value)
    page.get_by_role("button", name="Test and add source").click()
    expect(page.get_by_label("Datasource")).to_have_value("s3:s3:lake", timeout=10000)

    form("athena")
    for label, value in {"Source ID": "iceberg", "Display name": "Iceberg",
                         "AWS region": "us-east-1", "Workgroup": "primary",
                         "Query output S3 URI": "s3://results/path/",
                         "Databases (comma separated)": "clinical, genetics"}.items():
        page.get_by_label(label).fill(value)
    page.get_by_role("button", name="Test and add source").click()
    expect(page.get_by_label("Datasource")).to_have_value("athena:iceberg", timeout=10000)

    assert submitted == [
        {"kind": "postgres", "id": "clinical", "label": "Clinical RDS",
         "secret_id": "studio/clinical", "region": "us-east-1"},
        {"kind": "s3", "id": "lake", "label": "Lake", "bucket": "study-data",
         "prefix": "parquet/", "region": "us-east-1"},
        {"kind": "athena", "id": "iceberg", "label": "Iceberg", "region": "us-east-1",
         "workgroup": "primary", "output_location": "s3://results/path/",
         "databases": ["clinical", "genetics"], "catalog": "AwsDataCatalog"},
    ]
