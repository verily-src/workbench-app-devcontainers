import json

from playwright.sync_api import expect

from tests.test_e2e import app_url  # noqa: F401


def test_report_issue_downloads_diagnostics_and_prepares_draft(page, app_url):
    page.route("**/api/support/diagnostics", lambda route: route.fulfill(json={
        "generated_at": "2026-11-08T12:00:00+00:00", "version": "abcdef1",
        "recipient": "help@example.com", "events": [{"event": "http.finished", "status": 500}],
    }))
    page.goto(app_url)
    page.get_by_role("button", name="Report issue").click()
    dialog = page.get_by_role("dialog", name="Report issue")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_text("attach the file", exact=False)).to_be_visible()
    dialog.get_by_label("What happened?").fill("The query failed.")
    with page.expect_download() as download:
        dialog.get_by_role("button", name="Download diagnostics").click()
    artifact = download.value
    assert artifact.suggested_filename == "cohort-browser-diagnostics.json"
    report = json.loads(artifact.path().read_text())
    assert report["events"] == [{"event": "http.finished", "status": 500}]
    assert "recipient" not in report
    expect(dialog.get_by_label("Email to")).to_have_value("help@example.com")
    draft = dialog.get_by_role("link", name="Open email draft")
    assert "mailto:help%40example.com" in draft.get_attribute("href")
    assert "The%20query%20failed" in draft.get_attribute("href")
    expect(dialog.get_by_role("status")).to_contain_text("Attach it")
