import pytest
from playwright.sync_api import Page, expect

from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e


def test_theme_preference_persists_and_updates_chart_contrast(
        page: Page, app_url: str):
    page.goto(app_url)
    page.locator(".topnav-link", has_text="Settings").click()
    theme = page.get_by_label("Theme")
    theme.select_option("dark")
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    assert page.locator("body").evaluate(
        "element => getComputedStyle(element).backgroundColor") == "rgb(23, 27, 32)"
    assert page.locator("html").evaluate(
        "element => getComputedStyle(element).getPropertyValue('--chart-ink').trim()") == "#d1d7dd"

    page.reload()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    page.locator(".topnav-link", has_text="Settings").click()
    expect(page.get_by_label("Theme")).to_have_value("dark")

    page.get_by_label("Theme").select_option("light")
    expect(page.locator("body")).to_have_css("background-color", "rgb(250, 250, 250)")
    page.get_by_label("Theme").select_option("system")
    expect(page.locator("html")).to_have_attribute("data-theme", "system")
