"""End-to-end tests: real `panel serve` process driven by Playwright.

These use the CSV-upload datasource, so they need no workspace, wb CLI,
or Aurora — the same UI code paths (filters, charts, grid, export) are
exercised against local data.
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
    expect(page.get_by_text("Datasource")).to_be_visible(timeout=15000)
    page.get_by_text("Upload CSV/TSV (local dev)").click()
    page.locator('input[type="file"]').set_input_files(FIXTURE_CSV)
    expect(page.get_by_text(re.compile(r"100.*of.*100.*rows"))).to_be_visible(
        timeout=15000)
    return page


def test_app_serves_and_shows_title(page: Page, app_url: str):
    page.goto(app_url)
    expect(page.get_by_text("Cohort Dashboard").first).to_be_visible(
        timeout=15000)


def test_csv_upload_builds_grid_and_filters(loaded_page: Page):
    # Grid shows fixture data
    expect(loaded_page.get_by_text("GTEX-0000")).to_be_visible()
    # Categorical filter for tissue and range slider for rin_score exist
    expect(loaded_page.locator(".bk-input-group", has_text="tissue").first
           ).to_be_visible()
    expect(loaded_page.locator(".bk-input-group", has_text="rin_score").first
           ).to_be_visible()


def test_categorical_filter_updates_counts(loaded_page: Page):
    tissue_filter = loaded_page.locator(".bk-input-group", has_text="tissue")
    tissue_filter.locator("input").click()
    loaded_page.get_by_role("option", name="liver").click()
    expect(loaded_page.get_by_text(re.compile(r"25.*of.*100.*rows"))
           ).to_be_visible(timeout=10000)


def test_add_bar_chart_renders(loaded_page: Page):
    kind_select = loaded_page.locator('select:has(option[value="bar"])')
    kind_select.select_option("bar")
    field_select = loaded_page.locator('select:has(option[value="tissue"])').first
    field_select.select_option("tissue")
    loaded_page.get_by_role("button", name="+ Add chart").click()
    expect(loaded_page.get_by_text("bar: tissue")).to_be_visible(timeout=10000)
    # Bokeh canvas appears for the rendered chart
    expect(loaded_page.locator(".bk-Canvas").first).to_be_visible(
        timeout=10000)
