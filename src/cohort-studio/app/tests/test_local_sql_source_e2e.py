import re
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
    # Data Builder, SQL mode: preview the query, then open it as a tab.
    page.get_by_role("button", name="Join tables").click()
    canvas = page.locator(".jc")
    canvas.get_by_role("radio", name="SQL", exact=True).click()
    sql = canvas.get_by_role("region", name="SQL builder")
    sql.get_by_label("SQL database").select_option("local-postgres")
    canvas.get_by_role("textbox", name="Join name").fill("People with samples")
    sql.get_by_label("Data Builder SQL").fill(query)
    with page.expect_response(lambda response: response.url.endswith("/api/sql/preview")
                              and response.request.method == "POST") as sql_preview:
        canvas.get_by_role("button", name="Preview", exact=True).click()
    preview = sql_preview.value.json()
    assert preview["columns"] == ["person_id", "sample_id", "demo_group"]
    assert preview["rows"] == 20 and preview["truncated"] is True
    expect(sql.get_by_role("table", name="SQL result rows")).to_contain_text("SYN_SAMPLE_00001")

    with page.expect_request(lambda request: request.url.endswith("/api/data-jobs/open")
                             and request.method == "POST") as sql_open:
        canvas.get_by_role("button", name="Save & open in Explore").click()
    sql_ref = sql_open.value.post_data_json["source_ref"]
    assert sql_ref["kind"] == "sql"
    assert sql_ref["resource_id"] == "local-postgres"
    assert "JOIN genetics_demo.samples" in sql_ref["sql"]
    expect(page.locator(".tab.active")).to_contain_text("People with samples", timeout=15000)

    # Join the SQL tab with a table in Data Builder (visual mode).
    page.locator(".tab-join").click()
    expect(canvas.locator(".jc-node")).to_have_count(1, timeout=15000)
    canvas.get_by_role("button", name=re.compile("^local-postgres")).click()
    canvas.get_by_role("button", name="Add genetics_demo.genotypes to canvas").click()
    expect(canvas.locator(".jc-node")).to_have_count(2, timeout=15000)
    config = canvas.get_by_role("region", name="Join configuration")
    for label in ("Left field, clause 1", "Right field, clause 1"):
        box = config.get_by_role("combobox", name=label)
        box.fill("sample_id")
        box.press("Enter")
    config.get_by_role("button", name="Apply").click()

    with page.expect_request(lambda request: request.url.endswith("/api/data-jobs/join_preview")):
        canvas.get_by_role("button", name="Preview", exact=True).click()
    expect(canvas.get_by_label("Row counts")).to_contain_text("2,000", timeout=30000)

    with page.expect_request(lambda request: request.url.endswith("/api/data-jobs/join")) as join_request:
        canvas.get_by_role("button", name="Save & open in Explore").click()
    assert join_request.value.post_data_json["steps"][0]["right_id"]
    expect(page.locator(".tab.active")).to_be_visible(timeout=30000)
    page.wait_for_timeout(1500)  # the session autosave is debounced
    joined_ref = page.evaluate("""() => {
        const saved = JSON.parse(localStorage.getItem(Object.keys(localStorage)
          .find((k) => k.startsWith('studio-session-v1:')) || '') || 'null');
        return saved && saved.datasets && saved.datasets[saved.datasets.length - 1].source;
    }""")
    assert joined_ref and joined_ref["kind"] == "join"
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
