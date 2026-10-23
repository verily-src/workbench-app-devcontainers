import os

import pytest
from playwright.sync_api import Page, expect
from sqlalchemy import create_engine, text


pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def local_omop_url():
    value = os.environ.get("STUDIO_LOCAL_URL", "").rstrip("/")
    if not value:
        pytest.skip("Set STUDIO_LOCAL_URL to the running compose.local.yaml app.")
    return value


def _gi_bleed_reference_counts():
    port = os.environ.get("STUDIO_LOCAL_PG_PORT", "55432")
    url = os.environ.get(
        "STUDIO_LOCAL_DB_URL",
        f"postgresql+psycopg://cohort_local:cohort_local@127.0.0.1:{port}/cohort_local",
    )
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return conn.execute(text("""
                SELECT count(DISTINCT p.person_id),
                       count(DISTINCT p.person_id) FILTER (
                           WHERE p.gender_concept_id = 8532)
                FROM cdm.condition_occurrence AS c
                JOIN cdm.person AS p USING (person_id)
                JOIN cdm.observation_period AS o USING (person_id)
                WHERE c.condition_concept_id = 192671
                  AND c.condition_start_date BETWEEN o.observation_period_start_date
                                                 AND o.observation_period_end_date
            """)).one()
    finally:
        engine.dispose()


def _is_summary_for(response, *, gender=None, age_min=None):
    if (not response.url.endswith("/api/omop/local-postgres/cohort/summary")
            or response.request.method != "POST"):
        return False
    try:
        spec = response.request.post_data_json["spec"]
    except (KeyError, TypeError):
        return False
    if [192671] != [cid for criterion in spec.get("criteria", [])
                    for cid in criterion.get("concept_ids", [])]:
        return False
    demographics = spec.get("demographics", {})
    if gender is not None and demographics.get("gender_concept_ids") != [gender]:
        return False
    if age_min is not None and demographics.get("age_min") != age_min:
        return False
    if age_min is None and "age_min" in demographics:
        return False
    return True


def test_local_omop_summary_charts_follow_cohort_filters(page: Page,
                                                         local_omop_url: str):
    assert _gi_bleed_reference_counts() == (40, 20)
    page.goto(local_omop_url)
    cohort_open_requests = []
    page.on("request", lambda request: cohort_open_requests.append(request)
            if request.url.endswith("/cohort/open") else None)
    page.locator(".sidebar select").nth(0).select_option("aurora:local-postgres")
    explore = page.get_by_role("group", name="Explore view")
    expect(explore.get_by_role("button", name="Tables")).to_have_attribute(
        "aria-pressed", "true")
    explore.get_by_role("button", name="OMOP").click()
    expect(explore.get_by_role("button", name="OMOP")).to_have_attribute(
        "aria-pressed", "true")

    search = page.get_by_label("Concept name, ID or code")
    search.fill("192671")
    page.get_by_role("button", name="Search concepts").click()
    gi_bleed = page.locator(".omop-result", has_text="192671")
    expect(gi_bleed).to_be_visible(timeout=15000)
    gi_bleed.locator("input").check()

    with page.expect_response(lambda response: _is_summary_for(response)) as summary_response:
        page.get_by_role("button", name="Add criterion (1 concepts)").click()
    summary = summary_response.value.json()
    assert summary["scope"] == "database"
    assert summary["total_persons"] == 100
    assert summary["persons"] == 40
    summary_region = page.get_by_label("OMOP cohort summary")
    expect(summary_region).to_be_visible(timeout=15000)
    expect(summary_region).to_contain_text("40 of 100 persons")
    expect(summary_region.locator(".chart-card .title", has_text="Gender")).to_be_visible()
    expect(summary_region.locator(".chart-card .title", has_text="Age at index")).to_be_visible()
    expect(page.get_by_role("button", name="Open cohort")).to_be_visible()

    with page.expect_response(lambda response: _is_summary_for(
            response, gender=8532)) as female_response:
        page.get_by_label("Gender").select_option("8532")
    female = female_response.value.json()
    assert female["persons"] == 20
    assert sum(item["persons"] for item in female["charts"]["gender"]) == 20
    assert _gi_bleed_reference_counts()[1] == female["persons"]
    expect(summary_region).to_contain_text("20 of 100 persons")

    with page.expect_response(lambda response: _is_summary_for(
            response, gender=8532, age_min=200)) as zero_response:
        page.get_by_label("Minimum age").fill("200")
    zero = zero_response.value.json()
    assert zero["persons"] == 0
    assert all(item["persons"] == 0 for item in zero["charts"]["gender"])
    expect(summary_region).to_contain_text("0 of 100 persons")

    with page.expect_response(lambda response: _is_summary_for(
            response, gender=8532)) as reset_response:
        page.get_by_label("Minimum age").fill("")
    reset = reset_response.value.json()
    assert reset["persons"] == 20
    expect(summary_region).to_contain_text("20 of 100 persons")
    assert cohort_open_requests == []
    summary_region.get_by_role("button", name="Table", exact=True).click()
    expect(summary_region.get_by_role("table", name="Gender", exact=True)).to_contain_text("20")
    summary_region.get_by_role("button", name="Charts", exact=True).click()
    with page.expect_response(lambda response: response.url.endswith("/cohort/open")) as people_response:
        summary_region.get_by_role("button", name="View people", exact=True).click()
    assert people_response.value.json()["rows"] == 20
    expect(explore.get_by_role("button", name="Tables")).to_have_attribute("aria-pressed", "true")
    explore.get_by_role("button", name="OMOP").click()
    page.get_by_label("Clinical table").select_option("person")
    page.get_by_label("Restrict to current cohort", exact=True).uncheck()
    page.get_by_label("Add concept names", exact=True).uncheck()
    with page.expect_response(lambda response: response.url.endswith("/domain/open")) as table_response:
        page.get_by_role("button", name="Open clinical table", exact=True).click()
    assert table_response.value.request.post_data_json["spec"] is None
    assert table_response.value.json()["rows"] == 100
    expect(explore.get_by_role("button", name="Tables")).to_have_attribute("aria-pressed", "true")
    explore.get_by_role("button", name="OMOP").click()
    expect(summary_region).to_contain_text("20 of 100 persons", timeout=15000)
    summary_region.scroll_into_view_if_needed()
    page.screenshot(path="/tmp/local-omop-summary.png", full_page=True)
