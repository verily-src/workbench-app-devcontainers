import os

import pytest
from playwright.sync_api import Page, expect


pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def local_sql_url():
    value = os.environ.get("STUDIO_LOCAL_URL", "").rstrip("/")
    if not value:
        pytest.skip("Set STUDIO_LOCAL_URL to the running compose.local.yaml app.")
    return value


def test_local_sql_source_preview_join_and_reopen(page: Page, local_sql_url: str):
    assert page.request.get(f"{local_sql_url}/api/health").json()["ok"] is True
    query = ("SELECT p.person_id, s.sample_id, s.demo_group "
             "FROM cdm.person AS p JOIN genetics_demo.samples AS s USING (person_id) "
             "ORDER BY p.person_id")

    page.goto(local_sql_url)
    expect(page.get_by_text("No data loaded")).to_be_visible(timeout=15000)
    page.get_by_role("button", name="Join tables").click()
    panel = page.locator(".join-panel")
    panel.get_by_role("button", name="SQL", exact=True).click()
    panel.get_by_label("SQL source name").fill("People with samples")
    panel.get_by_label("SQL query").fill(query)
    with page.expect_response(lambda response: response.url.endswith("/api/sql/preview")
                              and response.request.method == "POST") as sql_preview:
        panel.get_by_role("button", name="Preview SQL").click()
    preview = sql_preview.value.json()
    assert preview["columns"] == ["person_id", "sample_id", "demo_group"]
    assert preview["rows"] == 20 and preview["truncated"] is True
    expect(panel.get_by_label("SQL preview")).to_contain_text("SYN_SAMPLE_00001")

    with page.expect_response(lambda response: response.url.endswith("/api/datasets/open")
                              and response.request.method == "POST") as sql_open:
        panel.get_by_role("button", name="Add SQL source").click()
    sql_ref = sql_open.value.request.post_data_json["source_ref"]
    assert sql_ref["kind"] == "sql"
    assert sql_ref["resource_id"] == "local-postgres"
    assert "JOIN genetics_demo.samples" in sql_ref["sql"]
    expect(panel.get_by_label("Start from")).to_have_value("People with samples")

    panel.get_by_role("button", name="Table", exact=True).click()
    panel.get_by_label("Join schema").select_option("genetics_demo")
    table = panel.get_by_role("combobox", name="Source table to add")
    table.fill("genotypes")
    option = panel.get_by_role("option", name="genetics_demo.genotypes", exact=False)
    expect(option).to_be_visible(timeout=10000)
    option.click()
    panel.get_by_role("button", name="Add table").click()
    expect(panel.locator(".join-step")).to_have_count(1, timeout=15000)
    panel.get_by_label("Left key step 1 condition 1").select_option(label="sample_id")
    panel.get_by_label("Right key step 1 condition 1").select_option(label="sample_id")

    with page.expect_response(lambda response:
            response.url.endswith("/api/datasets/join/preview")
            and response.request.method == "POST") as join_preview:
        panel.get_by_role("button", name="Preview").click()
    assert join_preview.value.json()["engine"] == "aurora"
    assert join_preview.value.json()["total_rows"] == 2000

    with page.expect_response(lambda response: response.url.endswith("/api/datasets/join")
                              and response.request.method == "POST") as joined_response:
        panel.get_by_role("button", name="Join into new tab").click()
    joined = joined_response.value.json()
    joined_ref = joined["source_ref"]
    assert joined["query_scope"] == "database"
    assert joined["rows"] == 2000
    assert joined_ref["base"]["kind"] == "sql"
    assert joined_ref["steps"][0]["source"]["schema"] == "genetics_demo"

    reopened_response = page.request.post(
        f"{local_sql_url}/api/datasets/open", data={"source_ref": joined_ref})
    assert reopened_response.ok, reopened_response.text()
    reopened = reopened_response.json()
    query_response = page.request.post(
        f"{local_sql_url}/api/datasets/{reopened['dataset_id']}/query",
        data={"page": 0, "page_size": 20, "entity_column": "sample_id"})
    assert query_response.ok, query_response.text()
    result = query_response.json()
    assert result["scope"] == "database"
    assert result["total"] == 2000
    assert result["entity"] == {"column": "sample_id", "total": 100,
                                "filtered": 100}
