import os
import re
import pytest
from email import policy
from email.parser import BytesParser
from pathlib import Path
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

@pytest.fixture
def url():
    value = os.environ.get("STUDIO_LOCAL_URL", "").rstrip("/")
    if not value:
        pytest.skip("Set STUDIO_LOCAL_URL to the running local container app.")
    return value

def test_single_table_and_report(page, url):
    page.goto(url)
    page.get_by_role("button", name="Data Builder").click()
    canvas = page.locator(".jc")
    canvas.get_by_role("button", name=re.compile("^local-postgres|^Local")).first.click()
    canvas.get_by_role("button", name="Add cdm.person to canvas").click()
    expect(canvas.locator(".jc-node")).to_have_count(1, timeout=15000)
    button = canvas.get_by_role("button", name="Save & open in Explore")
    expect(button).to_be_enabled(timeout=15000)
    button.click()
    expect(page.locator(".tab.active")).to_contain_text("person", timeout=30000)
    expect(page.locator(".hero .count")).to_have_text("100", timeout=30000)
    tools = page.get_by_role("complementary", name="Dashboard tools")
    for name in ("Dataset statistics", "Analysis actions", "Chart builder"):
        expect(tools.get_by_role("region", name=name)).to_be_visible()
    source = page.get_by_role("group", name="Data source of this tab")
    expect(source.get_by_role("button", name="Edit…")).to_be_visible()
    page.get_by_role("button", name="Report issue").click()
    dialog = page.get_by_role("dialog", name="Report issue")
    expect(dialog.get_by_role("button", name="Send")).to_be_visible()
    assert dialog.evaluate("el => { const r = el.getBoundingClientRect(); return el.contains(document.elementFromPoint(r.left + r.width / 2, r.top + 20)); }")

def test_wide_table_scroll(page, url):
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(url)
    names = [f"long_field_{i:02d}" for i in range(30)]
    content = ",".join(names) + "\n" + ",".join(str(i) for i in range(30)) + "\n"
    page.locator('input[type="file"]').set_input_files({"name": "wide.csv", "mimeType": "text/csv", "buffer": content.encode()})
    rows = page.get_by_role("region", name="Rows", exact=True)
    expect(rows.get_by_role("button", name="long_field_00")).to_be_visible(timeout=15000)
    assert rows.evaluate("el => el.scrollWidth > el.clientWidth")
    assert page.evaluate("document.querySelector('.rows-table-scroll').getBoundingClientRect().right <= document.querySelector('.chart-builder').getBoundingClientRect().left")
    rows.evaluate("el => el.scrollLeft = el.scrollWidth")
    expect(rows.get_by_role("button", name="long_field_29")).to_be_in_viewport()


def test_report_reaches_mail_server_with_attachment(page, url):
    path = os.environ.get("STUDIO_TEST_MAIL_CAPTURE")
    if not path:
        pytest.skip("Set STUDIO_TEST_MAIL_CAPTURE to the local SMTP receiver file.")
    page.goto(url)
    page.get_by_role("button", name="Report issue").click()
    dialog = page.get_by_role("dialog", name="Report issue")
    dialog.get_by_label("What happened?").fill("Container test issue")
    dialog.get_by_role("button", name="Send").click()
    expect(dialog.get_by_role("status")).to_have_text("Report sent.", timeout=15000)
    message = BytesParser(policy=policy.default).parsebytes(Path(path).read_bytes())
    assert message["To"] == "help@example.com"
    assert "Container test issue" in message.get_body(preferencelist=("plain",)).get_content()
    assert [item.get_filename() for item in message.iter_attachments()] == ["cohort-browser-diagnostics.json"]
