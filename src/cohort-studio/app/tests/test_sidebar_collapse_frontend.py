"""The Data sources panel folds to a narrow rail, stays folded across reloads, and reopens."""
from playwright.sync_api import expect

from tests.test_e2e import app_url  # noqa: F401  (fixture)


def test_sidebar_collapses_persists_and_expands(page, app_url):
    def fulfill(route, value):
        route.fulfill(status=200, content_type="application/json", json=value)

    page.route("**/api/datasources", lambda r: fulfill(r, {
        "ready": True, "sources": [{"kind": "aurora", "id": "omop", "label": "omop · Aurora"}],
        "catalogs_pending": False}))
    page.route("**/api/tables?**", lambda r: fulfill(r, []))
    page.route("**/api/workflows**", lambda r: fulfill(r, {"available": False, "jobs": [], "running_count": 0}))
    page.route("**/api/views/all", lambda r: fulfill(r, {"views": [], "unavailable": []}))
    page.goto(app_url)
    source_type = page.get_by_label("Source type")
    expect(source_type).to_be_visible()
    page.get_by_role("button", name="Collapse data sources").click()
    expect(source_type).to_be_hidden()
    expand = page.get_by_role("button", name="Expand data sources")
    expect(expand).to_be_visible()
    # The main area takes the freed width.
    main_left = page.locator(".main").bounding_box()["x"]
    assert main_left < 100

    page.reload()
    expect(page.get_by_role("button", name="Expand data sources")).to_be_visible()
    expect(page.get_by_label("Source type")).to_be_hidden()
    page.get_by_role("button", name="Expand data sources").click()
    expect(page.get_by_label("Source type")).to_be_visible()

    # "Load data" in the empty state reopens a folded panel and focuses the picker.
    page.get_by_role("button", name="Collapse data sources").click()
    page.get_by_role("button", name="Load data").click()
    expect(page.get_by_label("Source type")).to_be_focused()


def test_tutorial_opens_a_folded_data_sources_panel(page, app_url):
    def fulfill(route, value):
        route.fulfill(status=200, content_type="application/json", json=value)

    page.route("**/api/datasources", lambda r: fulfill(r, {
        "ready": True, "sources": [{"kind": "aurora", "id": "omop", "label": "omop · Aurora"}],
        "catalogs_pending": False}))
    page.route("**/api/tables?**", lambda r: fulfill(r, []))
    page.route("**/api/workflows**", lambda r: fulfill(r, {"available": False, "jobs": [], "running_count": 0}))
    page.route("**/api/views/all", lambda r: fulfill(r, {"views": [], "unavailable": []}))
    page.add_init_script("localStorage.setItem('cohort-studio.sidebar-collapsed', '1')")
    page.goto(app_url)
    expect(page.get_by_role("button", name="Expand data sources")).to_be_visible()
    page.get_by_role("button", name="Tutorial").click()
    # The first step points at the source picker, so the panel opens for it.
    expect(page.get_by_label("Source type")).to_be_visible()
    expect(page.locator(".tutorial-spotlight")).to_have_attribute("data-target", "[aria-label='Source type']")
    expect(page.locator(".tutorial-unavailable")).to_have_count(0)
