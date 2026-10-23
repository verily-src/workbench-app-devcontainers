import json
import os
import re
from urllib.request import Request, urlopen

import pytest
from playwright.sync_api import Page, expect


pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def local_url():
    value = os.environ.get("STUDIO_LOCAL_URL", "").rstrip("/")
    if not value:
        pytest.skip("Set STUDIO_LOCAL_URL to the running compose.local.yaml app.")
    return value


def _get(url):
    with urlopen(url, timeout=10) as response:
        return json.load(response)


def _post(url, payload):
    request = Request(url, json.dumps(payload).encode(),
                      {"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def test_local_postgres_source_picker_recommendation_and_join(
        page: Page, local_url: str):
    assert _get(f"{local_url}/api/health")["ok"] is True
    sources = _get(f"{local_url}/api/datasources")["sources"]
    local = next(source for source in sources if source["id"] == "local-postgres")
    tables = _get(f"{local_url}/api/tables?kind=aurora&resource_id=local-postgres")
    by_ref = {(item["schema"], item["table"]): item for item in tables}
    assert ("cdm", "person") in by_ref
    assert ("genetics_demo", "samples") in by_ref
    assert ("genetics_demo", "genotypes") in by_ref
    assert ("genetics_demo", "variants") in by_ref
    assert _get(f"{local_url}/api/omop/local-postgres")["cdm"] is True

    recommendation = _post(f"{local_url}/api/joins/recommend", {
        "left": {"kind": "aurora", "resource_id": local["id"],
                 "table": "person", "schema": "cdm"},
        "right": {"kind": "aurora", "resource_id": local["id"],
                  "table": "samples", "schema": "genetics_demo"},
    })
    assert any(candidate["method"] in {"exact_name", "foreign_key"}
               and candidate["keys"] == [{"left": "person_id", "right": "person_id"}]
               for candidate in recommendation["candidates"])

    page.goto(local_url)
    expect(page.get_by_text("No data loaded")).to_be_visible(timeout=15000)
    page.get_by_role("button", name="Join tables").click()
    expect(page.locator("aside .section-label").filter(
        has_text="Filters")).to_have_count(0)
    panel = page.locator(".join-panel")
    expect(panel.get_by_label("Join datasource")).to_have_value(
        "aurora:local-postgres")
    expect(panel.get_by_label("Join schema").locator(
        "option", has_text="genetics_demo")).to_have_count(1, timeout=15000)
    expect(panel.get_by_role("combobox", name="Source table to add")) \
        .to_have_value("")
    page.evaluate("window.scrollTo(0, 0)")
    page.screenshot(path="/tmp/local-join-source-picker-empty.png", full_page=True)

    def add_table(schema, table, expected_steps):
        panel.get_by_label("Join schema").select_option(schema)
        picker = panel.get_by_role("combobox", name="Source table to add")
        picker.fill(table)
        option = panel.get_by_role("option", name=re.compile(
            rf"^{re.escape(schema)}\.{re.escape(table)}"))
        expect(option).to_be_visible(timeout=10000)
        option.click()
        expect(picker).to_have_value(f"{schema}.{table}")
        add_button = panel.get_by_role("button", name="Add table")
        expect(add_button).to_be_enabled(timeout=10000)
        add_button.click()
        expect(panel.locator(".join-step")).to_have_count(expected_steps,
                                                          timeout=15000)

    add_table("cdm", "person", 1)
    add_table("genetics_demo", "samples", 1)
    first_step = panel.locator(".join-step").nth(0)
    matching_key = first_step.get_by_role(
        "button", name=re.compile(r"person_id = person_id.*matching names"))
    expect(matching_key).to_be_visible(timeout=15000)
    matching_key.click()
    expect(first_step.locator(".join-cond select").nth(0)).to_have_value("person_id")
    expect(first_step.locator(".join-cond select").nth(2)).to_have_value("person_id")

    add_table("genetics_demo", "genotypes", 2)
    sample_fk = panel.locator(".join-step").nth(1).get_by_role(
        "button", name=re.compile(r"sample_id = sample_id.*foreign key"))
    expect(sample_fk).to_be_visible(timeout=15000)
    sample_fk.click()
    expect(panel.locator(".join-step").nth(1).locator(".join-cond select").nth(0)
           ).to_have_value("genetics_demo.samples → sample_id")
    expect(panel.locator(".join-step").nth(1).locator(".join-cond select").nth(2)
           ).to_have_value("sample_id")

    add_table("genetics_demo", "variants", 3)
    variant_fk = panel.locator(".join-step").nth(2).get_by_role(
        "button", name=re.compile(r"variant_id = variant_id.*foreign key"))
    expect(variant_fk).to_be_visible(timeout=15000)
    page.evaluate("window.scrollTo(0, 0)")
    page.screenshot(path="/tmp/local-join-recommendation.png", full_page=True)
    variant_fk.click()
    expect(panel.locator(".join-step").nth(2).locator(".join-cond select").nth(0)
           ).to_have_value("genetics_demo.genotypes → variant_id")
    expect(panel.locator(".join-step").nth(2).locator(".join-cond select").nth(2)
           ).to_have_value("variant_id")

    with page.expect_response(lambda response:
            response.url.endswith("/api/datasets/join/preview")
            and response.request.method == "POST") as preview_response:
        panel.get_by_role("button", name="Preview").click()
    preview = preview_response.value.json()
    assert preview["engine"] == "aurora"
    assert preview["base_rows"] == 100
    assert [step["rows"] for step in preview["steps"]] == [100, 2_000, 2_000]
    assert preview["total_rows"] == 2_000

    with page.expect_response(lambda response:
            response.url.endswith("/api/datasets/join")
            and response.request.method == "POST") as joined_response:
        panel.get_by_role("button", name="Join into new tab").click()
    result = joined_response.value.json()
    assert result["query_scope"] == "database"
    assert result["join"]["engine"] == "aurora"
    assert result["join"]["total_rows"] == 2_000
    result_tab = page.locator(".tab.active")
    expect(result_tab).to_contain_text(
        "cdm.person + genetics_demo.samples + genetics_demo.genotypes + genetics_demo.variants")
    expect(page.locator(".hero .count")).to_contain_text("2,000", timeout=15000)
    response = page.request.post(
        f"{local_url}/api/datasets/{result['dataset_id']}/query",
        data={"entity_column": "person_id", "page": 0, "page_size": 20})
    assert response.ok, response.text()
    query = response.json()
    assert query["total"] == query["filtered"] == 2_000
    assert query["entity"] == {"column": "person_id", "total": 100,
                               "filtered": 100}
    variant_column = next(column["name"] for column in result["columns"]
                          if column["name"].endswith("variant_id"))
    variant_response = page.request.post(
        f"{local_url}/api/datasets/{result['dataset_id']}/query",
        data={"entity_column": variant_column, "page": 0, "page_size": 20})
    assert variant_response.ok, variant_response.text()
    assert variant_response.json()["entity"] == {
        "column": variant_column, "total": 20, "filtered": 20,
    }
    page.evaluate("window.scrollTo(0, 0)")
    page.screenshot(path="/tmp/local-join-result.png", full_page=True)
