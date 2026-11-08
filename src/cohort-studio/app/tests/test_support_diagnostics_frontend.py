from playwright.sync_api import expect

from tests.test_e2e import app_url, loaded_page  # noqa: F401


def test_report_issue_sends_with_diagnostics(page, app_url):
    submitted = []
    def send(route):
        submitted.append(route.request.post_data_json)
        route.fulfill(json={"sent": True})
    page.route("**/api/support/report", send)
    page.goto(app_url)
    page.get_by_role("button", name="Report issue").click()
    dialog = page.get_by_role("dialog", name="Report issue")
    expect(dialog).to_be_visible()
    assert dialog.evaluate("el => el.parentElement.parentElement === document.body")
    expect(dialog.get_by_role("button", name="Send")).to_be_disabled()
    expect(dialog.get_by_text("attached automatically", exact=False)).to_be_visible()
    assert "olekskazakov" not in dialog.inner_text()
    dialog.get_by_label("What happened?").fill("The query failed.")
    dialog.get_by_role("button", name="Send").click()
    expect(dialog.get_by_role("status")).to_have_text("Report sent.")
    assert submitted == [{"details": "The query failed."}]


def test_report_failure_is_visible(page, app_url):
    page.route("**/api/support/report", lambda route: route.fulfill(status=503, json={"detail": "Issue reporting is not configured."}))
    page.goto(app_url)
    page.get_by_role("button", name="Report issue").click()
    dialog = page.get_by_role("dialog", name="Report issue")
    dialog.get_by_label("What happened?").fill("A problem")
    dialog.get_by_role("button", name="Send").click()
    expect(dialog.get_by_role("alert")).to_have_text("Issue reporting is not configured.")
    expect(dialog.get_by_label("What happened?")).to_have_value("A problem")


def test_report_dialog_is_above_charts(loaded_page):
    page = loaded_page
    expect(page.locator(".chart-card").first).to_be_visible()
    page.get_by_role("button", name="Report issue").click()
    dialog = page.get_by_role("dialog", name="Report issue")
    expect(dialog).to_be_visible()
    assert dialog.evaluate("el => { const r = el.getBoundingClientRect(); return el.contains(document.elementFromPoint(r.left + r.width / 2, r.top + 20)); }")
    dialog.get_by_label("What happened?").fill("Chart issue")
