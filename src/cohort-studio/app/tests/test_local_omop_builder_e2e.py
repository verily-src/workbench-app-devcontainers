import os
import re

import pytest
import psycopg
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
    expect(dialog.get_by_role("status").filter(has_text="100 people")).to_be_visible(timeout=20000)
    dialog.get_by_label("Cohort name").fill("GI bleed cohort")
    dialog.get_by_label("Search concepts").fill("192671")
    dialog.get_by_role("button", name="Search", exact=True).click()
    results = dialog.get_by_role("group", name="Concept search results")
    results.get_by_role("checkbox", name=re.compile("192671")).first.check(timeout=15000)
    expect(dialog.get_by_role("button", name="Count people")).to_be_disabled()
    expect(dialog.get_by_role("status").filter(has_text="Preview: 40 people")).to_be_visible(timeout=20000)
    expect(dialog.get_by_role("button", name="Add criterion")).to_be_in_viewport()
    page.screenshot(path="/private/tmp/cohort-omop-search.png")
    dialog.get_by_role("button", name="Add criterion").click()
    expect(dialog.get_by_role("status").filter(has_text="40 people")).to_be_visible(timeout=20000)
    dialog.get_by_label("Gender (OMOP)").select_option("8532")
    expect(dialog.get_by_role("status").filter(has_text="40 people")).to_have_count(0)
    dialog.get_by_label("Minimum age at index").fill("70")
    dialog.get_by_label("Maximum age at index").fill("30")
    expect(dialog.get_by_role("button", name="Count people")).to_be_disabled()
    dialog.get_by_label("Minimum age at index").fill("0")
    dialog.get_by_label("Maximum age at index").fill("120")
    dialog.get_by_label("Birth year from").fill("1900")
    dialog.get_by_label("Birth year through").fill("2100")
    expect(dialog.get_by_role("status").filter(has_text="20 people")).to_be_visible(timeout=20000)
    dialog.get_by_role("button", name="Count people").click()
    expect(dialog.get_by_role("status").filter(has_text="20 people")).to_be_visible(timeout=20000)
    page.screenshot(path="/private/tmp/cohort-omop-builder.png")
    dialog.get_by_role("button", name="Add to Data Builder").click()
    expect(dialog).to_be_hidden(timeout=30000)
    expect(canvas.locator(".jc-node")).to_have_count(1)
    expect(canvas.locator(".jc-node").first).to_contain_text("GI bleed cohort")
    relations = canvas.get_by_role("region", name="OMOP cohort relations")
    expect(relations).to_contain_text("cdm.person", timeout=20000)
    expect(relations).to_contain_text("cdm.condition_occurrence")
    expect(relations).to_contain_text("cdm.observation_period")
    expect(relations).to_contain_text("cdm.concept_ancestor")
    expect(relations).to_contain_text("LEFT JOIN")
    expect(relations).to_contain_text("IN subquery")
    assert relations.bounding_box()["height"] >= 150
    page.screenshot(path="/private/tmp/cohort-omop-relations.png")

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
    assert result["join"]["total_rows"] == 20
    assert result["source_ref"]["base"]["kind"] == "omop_cohort"
    assert result["source_ref"]["base"]["spec"]["criteria"][0]["concept_ids"] == [192671]
    assert result["source_ref"]["base"]["spec"]["demographics"] == {
        "gender_concept_ids": [8532], "age_min": 0, "age_max": 120,
        "year_of_birth_min": 1900, "year_of_birth_max": 2100}
    expect(page.locator(".hero .count")).to_have_text("20", timeout=30000)
    reopened = page.request.post(f"{url}/api/datasets/open", data={"source_ref": result["source_ref"]}, timeout=60000)
    assert reopened.ok, reopened.text()
    restored = reopened.json()
    assert restored["query_scope"] == "database"
    queried = page.request.post(f"{url}/api/datasets/{restored['dataset_id']}/query", data={"page": 0, "page_size": 20})
    assert queried.ok, queried.text()
    assert queried.json()["filtered"] == 20


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
    relations = canvas.get_by_role("region", name="OMOP cohort relations")
    expect(relations).to_contain_text("Exclude; events grouped by person", timeout=20000)
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


def test_omop_measurement_and_index_timing(page):
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
    dialog.get_by_label("Search concepts").fill("192671")
    dialog.get_by_role("button", name="Search", exact=True).click()
    dialog.get_by_role("group", name="Concept search results").get_by_role("checkbox", name=re.compile("192671")).first.check(timeout=15000)
    dialog.get_by_role("button", name="Add criterion").click()
    dialog.get_by_label("Domain", exact=True).select_option("measurement")
    dialog.get_by_label("Search concepts").fill("3006322")
    dialog.get_by_label("Standard concepts only").uncheck()
    with page.expect_request(lambda request: "/concepts?" in request.url and "standard_only=false" in request.url):
        dialog.get_by_role("button", name="Search", exact=True).click()
    dialog.get_by_role("group", name="Concept search results").get_by_role("checkbox", name=re.compile("3006322")).first.check(timeout=15000)
    dialog.get_by_text("Event limits", exact=True).click()
    dialog.get_by_label("Timing relative to index").select_option("after")
    dialog.get_by_label("Minimum value").fill("37")
    dialog.get_by_label("Maximum value").fill("39")
    dialog.get_by_role("button", name="Add criterion").click()
    expect(dialog.get_by_role("button", name="Remove criterion 1")).to_be_disabled()
    dialog.get_by_role("button", name="Edit criterion 2").click()
    expect(dialog.get_by_role("button", name="Count people")).to_be_disabled()
    expect(dialog.get_by_label("Timing relative to index")).to_have_value("after")
    expect(dialog.get_by_label("Minimum value")).to_have_value("37")
    dialog.get_by_label("Minimum value").fill("38")
    dialog.get_by_role("button", name="Update criterion").click()
    with page.expect_request(lambda request: "/cohort/count?" in request.url and request.method == "POST") as sent:
        dialog.get_by_role("button", name="Count people").click()
    criteria = sent.value.post_data_json["criteria"]
    assert criteria[1]["index_relation"] == "after"
    assert (criteria[1]["value_min"], criteria[1]["value_max"]) == (38, 39)
    expect(dialog.get_by_role("status").filter(has_text="0 people")).to_be_visible(timeout=20000)
    dialog.get_by_role("button", name="Edit criterion 1").click()
    dialog.get_by_label("Match", exact=True).select_option("exclude")
    expect(dialog.get_by_text("Remove time-relative criteria before changing the index event.")).to_be_visible()
    expect(dialog.get_by_role("button", name="Update criterion")).to_be_disabled()
    dialog.get_by_role("button", name="Cancel edit").click()
    expect(dialog.get_by_role("status").filter(has_text="0 people")).to_be_visible()


def test_renamed_omop_tables_are_reviewed_and_saved_mapping_is_checked(page):
    url = os.environ.get("STUDIO_LOCAL_URL", "").rstrip("/")
    if not url:
        pytest.skip("Set STUDIO_LOCAL_URL to the running local container app.")
    port = os.environ.get("STUDIO_LOCAL_PG_PORT", "55433")
    dsn = f"postgresql://cohort_local:cohort_local@127.0.0.1:{port}/cohort_local"
    schema = "drift_e2e"
    names = {"person": "persons", "observation_period": "observation_period",
             "condition_occurrence": "condition_occurence", "concept": "concept",
             "concept_ancestor": "concept_ancestor"}
    try:
        with psycopg.connect(dsn) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            conn.execute(f'CREATE SCHEMA "{schema}"')
            for original, actual in names.items():
                conn.execute(f'CREATE TABLE "{schema}"."{actual}" (LIKE cdm."{original}" INCLUDING ALL)')
                conn.execute(f'INSERT INTO "{schema}"."{actual}" SELECT * FROM cdm."{original}"')
        assert page.request.get(f"{url}/api/omop/local-postgres?refresh=true").ok
        page.goto(url)
        page.get_by_role("button", name="Data Builder").click()
        canvas = page.locator(".jc")
        canvas.get_by_role("button", name=re.compile("^local-postgres|^Local")).first.click()
        canvas.get_by_role("button", name="Build OMOP cohort").click()
        dialog = page.get_by_role("dialog", name="Build OMOP cohort")
        dialog.get_by_label("CDM schema").select_option(schema, timeout=20000)
        expect(dialog.get_by_text("person → persons")).to_be_visible(timeout=20000)
        expect(dialog.get_by_text("condition_occurrence → condition_occurence")).to_be_visible()
        expect(dialog.get_by_role("button", name="Count people")).to_be_disabled()
        dialog.get_by_label("I verified these tables contain the corresponding OMOP data").check()
        dialog.get_by_label("Search concepts").fill("192671")
        dialog.get_by_role("button", name="Search", exact=True).click()
        dialog.get_by_role("group", name="Concept search results").get_by_role("checkbox", name=re.compile("192671")).first.check(timeout=15000)
        dialog.get_by_role("button", name="Add criterion").click()
        dialog.get_by_role("button", name="Count people").click()
        expect(dialog.get_by_role("status").filter(has_text="40 people")).to_be_visible(timeout=20000)
        expect(dialog.get_by_text(re.compile(r"Selected features: .*100%"))).to_be_visible()
        dialog.get_by_role("button", name="Add to Data Builder").click()
        expect(dialog).to_be_hidden(timeout=30000)
        relations = canvas.get_by_role("region", name="OMOP cohort relations")
        expect(relations).to_contain_text(f"{schema}.persons", timeout=20000)
        expect(relations).to_contain_text(f"{schema}.condition_occurence")
        with page.expect_response(lambda response: "/api/data-jobs/" in response.url
                                  and response.request.method == "GET"
                                  and response.json().get("kind") == "join"
                                  and response.json().get("status") == "complete", timeout=60000) as opened:
            canvas.get_by_role("button", name="Save & open in Explore").click(timeout=30000)
        ref = opened.value.json()["result"]["source_ref"]["base"]
        assert ref["table_mapping"]["person"] == f"{schema}.persons"
        with psycopg.connect(dsn) as conn:
            conn.execute(f'ALTER TABLE "{schema}".condition_occurence RENAME TO condition_occurrences')
        restored = page.request.post(f"{url}/api/datasets/open", data={"source_ref": ref}, timeout=60000)
        assert not restored.ok and "mappings have changed" in restored.text()
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        page.request.get(f"{url}/api/omop/local-postgres?refresh=true")
