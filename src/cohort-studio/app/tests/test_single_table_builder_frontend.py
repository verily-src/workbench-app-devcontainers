import pytest
from playwright.sync_api import expect

from tests.test_e2e import app_url  # noqa: F401
from tests.ui_helpers import open_data_builder

pytestmark = pytest.mark.e2e


def test_one_table_can_open_as_a_new_explore_view(page, app_url):
    page.goto(app_url)
    page.locator('input[type="file"]').set_input_files({
        "name": "people.csv", "mimeType": "text/csv",
        "buffer": b"id,status\n1,case\n2,control\n"})
    expect(page.locator(".tab.active")).to_contain_text("people.csv", timeout=15000)
    canvas = open_data_builder(page, start_tab="people.csv")
    button = canvas.get_by_role("button", name="Save & open in Explore")
    expect(button).to_be_enabled(timeout=15000)
    button.click()
    expect(page.locator(".join-canvas-host")).to_be_hidden(timeout=30000)
    expect(page.locator(".tab")).to_have_count(2)
    expect(page.locator(".hero .count")).to_have_text("2", timeout=30000)
