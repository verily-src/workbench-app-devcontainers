from playwright.sync_api import expect

from tests.test_e2e import app_url  # noqa: F401


def test_wide_rows_scroll_without_overlapping_tools(page, app_url):
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(app_url)
    names = [f"long_field_{i:02d}" for i in range(30)]
    content = ",".join(names) + "\n" + ",".join(str(i) for i in range(30)) + "\n"
    page.locator('input[type="file"]').set_input_files({
        "name": "wide.csv", "mimeType": "text/csv", "buffer": content.encode()})
    rows = page.get_by_role("region", name="Rows", exact=True)
    expect(rows.get_by_role("button", name="long_field_00")).to_be_visible(timeout=15000)
    tools = page.get_by_role("complementary", name="Dashboard tools")
    expect(tools).to_be_visible()
    assert rows.evaluate("el => el.scrollWidth > el.clientWidth")
    rects = page.evaluate("""() => {
      const rows = document.querySelector('.rows-table-scroll').getBoundingClientRect();
      const tools = document.querySelector('.chart-builder').getBoundingClientRect();
      return { rowRight: rows.right, toolsLeft: tools.left };
    }""")
    assert rects["rowRight"] <= rects["toolsLeft"]
    rows.evaluate("el => el.scrollLeft = el.scrollWidth")
    last = rows.get_by_role("button", name="long_field_29")
    expect(last).to_be_in_viewport()
    assert rows.evaluate("el => el.scrollLeft > 0")
