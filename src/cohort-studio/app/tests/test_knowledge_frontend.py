import pytest
from playwright.sync_api import expect
from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e


def test_upload_search_and_remove_document(page, app_url):
    page.goto(app_url)
    page.locator(".topnav").get_by_text("Settings", exact=True).click()
    section = page.get_by_role("region", name="Knowledge base")
    for width in (1280, 760):
        page.set_viewport_size({"width": width, "height": 900})
        title_box = section.get_by_label("Document title").bounding_box()
        text_box = section.get_by_label("Document text").bounding_box()
        assert text_box["y"] > title_box["y"] + title_box["height"]
        assert section.evaluate("el => el.scrollWidth <= el.clientWidth")
    page.set_viewport_size({"width": 1280, "height": 900})
    section.get_by_label("Upload text file").set_input_files({
        "name": "test-genetics-dictionary.txt", "mimeType": "text/plain",
        "buffer": b"kb_unique_sample_key links a specimen to the clinical record."})
    expect(section.get_by_label("Document title")).to_have_value("test-genetics-dictionary.txt")
    section.get_by_role("button", name="Add document", exact=True).click()
    remove = section.get_by_role("button", name="Remove test-genetics-dictionary.txt")
    expect(remove).to_be_visible()
    page.reload()
    page.locator(".topnav").get_by_text("Settings", exact=True).click()
    section.get_by_label("Search knowledge").fill("kb_unique_sample_key")
    section.get_by_role("button", name="Search documents").click()
    expect(section.locator("article")).to_contain_text("KB:")
    expect(section.locator("article")).to_contain_text("links a specimen")
    remove.click()
    expect(remove).to_have_count(0)
