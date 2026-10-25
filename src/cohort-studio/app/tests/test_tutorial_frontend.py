import pytest
from playwright.sync_api import Page, expect

from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e


def test_tutorial_navigation_persistence_and_keyboard(page: Page, app_url: str):
    page.goto(app_url)
    tutorial = page.get_by_role("button", name="Tutorial", exact=True)
    expect(tutorial).to_be_visible(timeout=15000)
    tutorial.click()

    dialog = page.get_by_role("dialog", name="Choose data")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_text("Step 1 of 5")).to_be_visible()

    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(tutorial).to_be_focused()

    tutorial.click()
    page.get_by_role("button", name="Next").click()
    expect(page.get_by_role("dialog", name="Build an OMOP cohort")).to_be_visible()
    page.reload()
    page.get_by_role("button", name="Tutorial", exact=True).click()
    expect(page.get_by_role("dialog", name="Build an OMOP cohort")).to_be_visible()
    page.get_by_role("button", name="Skip tutorial").click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    page.get_by_role("button", name="Tutorial", exact=True).click()
    expect(page.get_by_role("dialog", name="Choose data")).to_be_visible()
