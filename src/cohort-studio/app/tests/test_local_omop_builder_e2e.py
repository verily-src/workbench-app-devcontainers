import os
import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def test_omop_cohort_builds_live_dataset_and_joins(page):
    url = os.environ.get("STUDIO_LOCAL_URL", "").rstrip("/")
    if not url:
        pytest.skip("Set STUDIO_LOCAL_URL to the running local container app.")
    page.goto(url)
    page.get_by_role("button", name="Data Builder").click()
    canvas = page.locator(".jc")
    canvas.get_by_role("button", name=re.compile("^local-postgres|^Local")).first.click()
    canvas.get_by_role("button", name="Build OMOP cohort").click()
    dialog = page.get_by_role("dialog", name="Build OMOP cohort")
    expect(dialog.get_by_label("CDM schema")).to_have_value("cdm", timeout=20000)
    dialog.get_by_label("Cohort name").fill("GI bleed cohort")
    dialog.get_by_label("Search concepts").fill("192671")
    dialog.get_by_role("button", name="Search", exact=True).click()
    results = dialog.get_by_role("group", name="Concept search results")
    results.get_by_role("checkbox", name=re.compile("192671")).first.check(timeout=15000)
    expect(dialog.get_by_role("button", name="Count people")).to_be_disabled()
    dialog.get_by_role("button", name="Add criterion").click()
    dialog.get_by_role("button", name="Count people").click()
    expect(dialog.get_by_role("status").filter(has_text="40 people")).to_be_visible(timeout=20000)
    page.screenshot(path="/private/tmp/cohort-omop-builder.png")
    dialog.get_by_role("button", name="Add to Data Builder").click()
    expect(dialog).to_be_hidden(timeout=30000)
    expect(canvas.locator(".jc-node")).to_have_count(1)
    expect(canvas.locator(".jc-node").first).to_contain_text("GI bleed cohort")

    canvas.get_by_role("button", name="Add genetics_demo.samples to canvas").click()
    expect(canvas.locator(".jc-node")).to_have_count(2, timeout=20000)
    config = canvas.get_by_role("region", name="Join configuration")
    expect(config).to_be_visible(timeout=15000)
    for label in ("Left field, clause 1", "Right field, clause 1"):
        field = config.get_by_role("combobox", name=label)
        field.fill("person_id")
        field.press("Enter")
    config.get_by_role("button", name="Apply").click()
    with page.expect_response(lambda response: "/api/data-jobs/" in response.url
                              and response.request.method == "GET"
                              and response.json().get("kind") == "join"
                              and response.json().get("status") == "complete", timeout=60000) as joined:
        canvas.get_by_role("button", name="Save & open in Explore").click(timeout=30000)
    result = joined.value.json()["result"]
    assert result["query_scope"] == "database"
    assert result["join"]["total_rows"] == 40
    assert result["source_ref"]["base"]["kind"] == "omop_cohort"
    assert result["source_ref"]["base"]["spec"]["criteria"][0]["concept_ids"] == [192671]
    expect(page.locator(".hero .count")).to_have_text("40", timeout=30000)
    reopened = page.request.post(f"{url}/api/datasets/open", data={"source_ref": result["source_ref"]}, timeout=60000)
    assert reopened.ok, reopened.text()
    restored = reopened.json()
    assert restored["query_scope"] == "database"
    queried = page.request.post(f"{url}/api/datasets/{restored['dataset_id']}/query", data={"page": 0, "page_size": 20})
    assert queried.ok, queried.text()
    assert queried.json()["filtered"] == 40


def test_omop_exclusion_builds_expected_population(page):
    url = os.environ.get("STUDIO_LOCAL_URL", "").rstrip("/")
    if not url:
        pytest.skip("Set STUDIO_LOCAL_URL to the running local container app.")
    page.goto(url)
    page.get_by_role("button", name="Data Builder").click()
    canvas = page.locator(".jc")
    canvas.get_by_role("button", name=re.compile("^local-postgres|^Local")).first.click()
    canvas.get_by_role("button", name="Build OMOP cohort").click()
    dialog = page.get_by_role("dialog", name="Build OMOP cohort")
    expect(dialog.get_by_label("CDM schema")).to_have_value("cdm", timeout=20000)
    dialog.get_by_label("Match", exact=True).select_option("exclude")
    dialog.get_by_label("Search concepts").fill("192671")
    dialog.get_by_role("button", name="Search", exact=True).click()
    dialog.get_by_role("group", name="Concept search results").get_by_role("checkbox", name=re.compile("192671")).first.check(timeout=15000)
    dialog.get_by_text("Event limits", exact=True).click()
    dialog.get_by_label("From", exact=True).fill("1900-01-01")
    dialog.get_by_label("Through", exact=True).fill("2100-01-01")
    dialog.get_by_role("button", name="Add criterion").click()
    dialog.get_by_role("button", name="Count people").click()
    expect(dialog.get_by_role("status").filter(has_text="60 people")).to_be_visible(timeout=20000)
    dialog.get_by_role("button", name="Add to Data Builder").click()
    expect(dialog).to_be_hidden(timeout=30000)
    with page.expect_response(lambda response: "/api/data-jobs/" in response.url
                              and response.request.method == "GET"
                              and response.json().get("kind") == "join"
                              and response.json().get("status") == "complete", timeout=60000) as opened:
        canvas.get_by_role("button", name="Save & open in Explore").click(timeout=30000)
    result = opened.value.json()["result"]
    assert result["query_scope"] == "database"
    assert result["join"]["total_rows"] == 60
    assert result["source_ref"]["base"]["spec"]["criteria"][0]["exclude"] is True
    assert result["source_ref"]["base"]["spec"]["criteria"][0]["start"] == "1900-01-01"
    expect(page.locator(".hero .count")).to_have_text("60", timeout=30000)
