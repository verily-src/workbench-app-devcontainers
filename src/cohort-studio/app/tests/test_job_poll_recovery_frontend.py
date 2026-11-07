import pytest
from playwright.sync_api import Page, expect

from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e

PERSON_REF = {"kind": "aurora", "resource_id": "fixture", "table": "person"}
OPENED = {"dataset_id": "live-person", "source": "Fixture / person", "rows": 1,
          "columns": [{"name": "person_id", "dtype": "int64", "filter_kind": "none"}],
          "source_ref": PERSON_REF, "query_scope": "database"}


def _fulfill(route, body, status=200):
    route.fulfill(status=status, content_type="application/json", json=body)


def _common_routes(page: Page):
    page.route("**/api/datasources", lambda route: _fulfill(route, {
        "ready": True, "sources": [{"kind": "aurora", "id": "fixture", "label": "Fixture"}],
        "catalogs_pending": False}))
    page.route("**/api/workflows**", lambda route: _fulfill(route, {
        "available": False, "jobs": [], "running_count": 0}))
    page.route("**/api/tables?**", lambda route: _fulfill(route, [
        {"name": "person", "schema": "public", "table": "person", "detail": "1 row"}]))
    page.route("**/api/views/all", lambda route: _fulfill(route, {"views": [], "unavailable": []}))
    page.route("**/api/datasets/*/query", lambda route: _fulfill(route, {
        "total": 1, "filtered": 1, "scope": "database", "sampled": False, "charts": [],
        "rows": {"page": 0, "page_size": 50, "columns": ["person_id"], "data": [[1]]}}))


def _load_person(page: Page, app_url: str):
    page.goto(app_url)
    from tests.ui_helpers import load_table
    load_table(page, "aurora:fixture", "person")


def test_expired_snapshot_job_stops_polling_and_reenables_save(page: Page, app_url: str):
    _common_routes(page)
    page.route("**/api/data-jobs/open", lambda route: _fulfill(route, {
        "job_id": "open-1", "kind": "open", "status": "complete", "result": OPENED}))
    page.route("**/api/views", lambda route: _fulfill(route, {
        "name": "people", "job_id": "lost-job", "status": "queued",
        "completed_sources": 0, "total_sources": 1}))
    polls = []

    def view_job(route):
        polls.append(route.request.url)
        _fulfill(route, {"detail": "Saved-view job expired or unknown."}, status=404)

    page.route("**/api/views/jobs/**", view_job)
    _load_person(page, app_url)
    expect(page.locator(".tab", has_text="person")).to_be_visible(timeout=10000)
    name_input = page.get_by_placeholder("name this view (1 tab)")
    name_input.fill("people")
    save = page.get_by_role("button", name="Save", exact=True)
    save.click()
    expect(page.locator(".sidebar").get_by_text(
        "This save job expired (the app restarted). Reload the view.", exact=True)
    ).to_be_visible(timeout=10000)
    name_input.fill("people again")
    expect(save).to_be_enabled()
    page.wait_for_timeout(3000)
    assert len(polls) == 1


def test_open_survives_one_gateway_error_while_polling(page: Page, app_url: str):
    _common_routes(page)
    page.route("**/api/data-jobs/open", lambda route: _fulfill(route, {
        "job_id": "job1", "kind": "open", "status": "running"}))
    polls = []

    def job(route):
        polls.append(route.request.url)
        if len(polls) == 1:
            _fulfill(route, {"detail": "Bad gateway"}, status=502)
        else:
            _fulfill(route, {"job_id": "job1", "kind": "open", "status": "complete",
                             "result": OPENED})

    page.route("**/api/data-jobs/job1", job)
    _load_person(page, app_url)
    expect(page.locator(".tab", has_text="person")).to_be_visible(timeout=15000)
    assert len(polls) == 2

    page.evaluate("sessionStorage.setItem('studio-data-jobs', JSON.stringify(['job1']))")
    polls.clear()
    page.reload()
    panel = page.get_by_role("region", name="Data operations")
    expect(panel.get_by_role("button", name="Open result").first).to_be_visible(timeout=10000)
    page.wait_for_timeout(500)
    settled = len(polls)
    assert settled >= 1
    page.wait_for_timeout(4500)
    assert len(polls) == settled
