import json

from playwright.sync_api import expect

from tests.test_e2e import app_url, loaded_page  # noqa: F401


def test_report_issue_downloads_diagnostics_and_prepares_draft(page, app_url):
    page.route("**/api/support/diagnostics", lambda route: route.fulfill(json={
        "generated_at": "2026-11-08T12:00:00+00:00", "version": "abcdef1",
        "recipient": "help@example.com", "events": [{"event": "http.finished", "status": 500}],
    }))
    page.goto(app_url)
    page.get_by_role("button", name="Report issue").click()
    dialog = page.get_by_role("dialog", name="Report issue")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_label("Email to")).to_have_value("olekskazakov@tvc.verily.health")
    assert dialog.evaluate("el => el.parentElement.parentElement === document.body")
    assert dialog.evaluate("el => { const r = el.getBoundingClientRect(); return el.contains(document.elementFromPoint(r.left + r.width / 2, r.top + 20)); }")
    expect(dialog.get_by_text("attach the file", exact=False)).to_be_visible()
    dialog.get_by_label("What happened?").fill("The query failed.")
    dialog.get_by_label("Include logs and queries").check()
    dialog.get_by_label("Queries", exact=True).fill("select 1")
    dialog.get_by_label("Log file (up to 5 MB)").set_input_files({"name": "app.log", "mimeType": "text/plain", "buffer": b"log entry"})
    with page.expect_download() as download:
        dialog.get_by_role("button", name="Download diagnostics").click()
    artifact = download.value
    assert artifact.suggested_filename == "cohort-browser-diagnostics.json"
    report = json.loads(artifact.path().read_text())
    assert report["events"] == [{"event": "http.finished", "status": 500}]
    assert report["queries"] == "select 1"
    assert report["log_file"] == {"name": "app.log", "contents": "log entry"}
    assert "recipient" not in report
    expect(dialog.get_by_label("Email to")).to_have_value("olekskazakov@tvc.verily.health")
    draft = dialog.get_by_role("link", name="Open email draft")
    assert "mailto:olekskazakov%40tvc.verily.health" in draft.get_attribute("href")
    assert "The%20query%20failed" in draft.get_attribute("href")
    expect(dialog.get_by_role("status")).to_contain_text("Attach it")


def test_report_dialog_is_above_charts(loaded_page):
    page = loaded_page
    expect(page.locator(".chart-card").first).to_be_visible()
    page.get_by_role("button", name="Report issue").click()
    dialog = page.get_by_role("dialog", name="Report issue")
    expect(dialog).to_be_visible()
    assert dialog.evaluate("el => { const r = el.getBoundingClientRect(); return el.contains(document.elementFromPoint(r.left + r.width / 2, r.top + 20)); }")
    dialog.get_by_label("What happened?").fill("Chart issue")
