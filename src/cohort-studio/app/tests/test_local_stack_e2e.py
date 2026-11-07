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
    page.locator(".topnav-link").filter(has_text="Data Builder").click()
    canvas = page.locator(".jc")
    canvas.get_by_role("button", name=re.compile("^local-postgres|^Local")).first.click()
    page.screenshot(path="/tmp/local-join-source-picker-empty.png", full_page=True)

    def add(table, count):
        canvas.get_by_role("button", name=f"Add {table} to canvas").click()
        expect(canvas.locator(".jc-node")).to_have_count(count, timeout=15000)

    def apply_keys(left, right):
        config = canvas.get_by_role("region", name="Join configuration")
        expect(config).to_be_visible(timeout=15000)
        # Recommended keys pre-fill the draft; fill them anyway so the test is deterministic.
        for label, value in (("Left field, clause 1", left), ("Right field, clause 1", right)):
            box = config.get_by_role("combobox", name=label)
            box.fill(value)
            box.press("Enter")
        config.get_by_role("button", name="Apply").click()

    def select(table):
        canvas.locator(".jc-node", has_text=table).get_by_role("button", name=re.compile("Table details")).click()

    add("cdm.person", 1)
    add("genetics_demo.samples", 2)
    apply_keys("person_id", "person_id")
    select("samples")
    add("genetics_demo.genotypes", 3)
    apply_keys("sample_id", "sample_id")
    select("genotypes")
    add("genetics_demo.variants", 4)
    apply_keys("variant_id", "variant_id")
    page.screenshot(path="/tmp/local-join-recommendation.png", full_page=True)

    with page.expect_response(lambda response: "/api/data-jobs/" in response.url
                              and response.request.method == "GET"
                              and response.json().get("kind") == "join_preview"
                              and response.json().get("status") == "complete") as preview_response:
        canvas.get_by_role("button", name="Preview", exact=True).first.click()
    preview = preview_response.value.json()["result"]
    assert preview["engine"] == "aurora"
    assert preview["base_rows"] == 100
    assert [step["rows"] for step in preview["steps"]] == [100, 2_000, 2_000]
    assert preview["total_rows"] == 2_000

    with page.expect_response(lambda response: "/api/data-jobs/" in response.url
                              and response.request.method == "GET"
                              and response.json().get("kind") == "join"
                              and response.json().get("status") == "complete") as joined_response:
        canvas.get_by_role("button", name="Save & open in Explore").click()
    result = joined_response.value.json()["result"]
    assert result["query_scope"] == "database"
    assert result["join"]["engine"] == "aurora"
    assert result["join"]["total_rows"] == 2_000
    expect(page.locator(".tab.active")).to_contain_text("person + samples + genotypes + variants")
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
