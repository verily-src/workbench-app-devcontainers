"""End-to-end tests: real `panel serve` process driven by Playwright.

These use the CSV-upload datasource, so they need no workspace, wb CLI,
or Aurora — the same UI code paths (auto-charts, filters, chips, grid,
lineage) are exercised against local data.
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

FIXTURE_CSV = Path(__file__).parent / "fixtures" / "samples.csv"

pytestmark = pytest.mark.e2e


@pytest.fixture
def loaded_page(page: Page, app_url: str) -> Page:
    page.goto(app_url)
    expect(page.get_by_text("Datasource").first).to_be_visible(timeout=15000)
    page.get_by_text("Upload CSV/TSV (local dev)").click()
    page.locator('input[type="file"]').set_input_files(FIXTURE_CSV)
    expect(page.get_by_text(re.compile(r"100.*of.*100.*rows"))).to_be_visible(
        timeout=15000)
    return page


def test_app_serves_and_shows_title(page: Page, app_url: str):
    page.goto(app_url)
    expect(page.get_by_text("Cohort Dashboard").first).to_be_visible(
        timeout=15000)


def test_dataset_opens_as_tab(loaded_page: Page):
    # the loaded dataset gets its own closable tab named after the file
    expect(loaded_page.locator(".bk-tab", has_text="samples.csv")
           ).to_be_visible()


def test_csv_upload_builds_grid_filters_and_auto_charts(loaded_page: Page):
    # Grid shows fixture data
    expect(loaded_page.get_by_text("GTEX-0000")).to_be_visible()
    # Sidebar filters exist for categorical and numeric columns
    expect(loaded_page.locator(".bk-input-group", has_text="tissue").first
           ).to_be_visible()
    expect(loaded_page.locator(".bk-input-group", has_text="rin_score").first
           ).to_be_visible()
    # Charts were generated automatically, without clicking Add
    expect(loaded_page.locator(".chart-card").first).to_be_visible(
        timeout=10000)
    expect(loaded_page.locator(".card-title", has_text="tissue")
           ).to_be_visible()


def test_filter_updates_counts_and_shows_chip(loaded_page: Page):
    tissue_filter = loaded_page.locator(".bk-input-group", has_text="tissue")
    tissue_filter.locator("input").click()
    loaded_page.get_by_role("option", name="liver").click()
    expect(loaded_page.get_by_text(re.compile(r"25.*of.*100.*rows"))
           ).to_be_visible(timeout=10000)
    # Active filter appears as a chip; clicking it removes the filter
    chip = loaded_page.locator(".chip", has_text="tissue: liver")
    expect(chip).to_be_visible()
    chip.click()
    expect(loaded_page.get_by_text(re.compile(r"100.*of.*100.*rows"))
           ).to_be_visible(timeout=10000)


def test_lineage_records_csv_upload(loaded_page: Page):
    loaded_page.locator(".bk-tab", has_text="Lineage").click()
    expect(loaded_page.get_by_text("csv_uploaded").first).to_be_visible(
        timeout=10000)
    expect(loaded_page.get_by_text("samples.csv").first).to_be_visible()


def test_add_chart_by_search(loaded_page: Page):
    search = loaded_page.locator('input[placeholder="Search columns…"]')
    search.click()
    search.fill("age")
    search.press("Enter")
    loaded_page.get_by_role("button", name="Add", exact=True).click()
    expect(loaded_page.locator(".card-title", has_text="age")).to_be_visible(
        timeout=10000)
