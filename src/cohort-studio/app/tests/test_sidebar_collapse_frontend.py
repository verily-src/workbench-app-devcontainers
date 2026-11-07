"""The Explore side panel folds to a narrow rail, stays folded across reloads, and reopens."""
from playwright.sync_api import expect

from tests.test_e2e import app_url  # noqa: F401  (fixture)


def _mock(page):
    def fulfill(route, value):
        route.fulfill(status=200, content_type="application/json", json=value)

    page.route("**/api/datasources", lambda r: fulfill(r, {
        "ready": True, "sources": [{"kind": "aurora", "id": "omop", "label": "omop · Aurora"}],
        "catalogs_pending": False}))
    page.route("**/api/tables?**", lambda r: fulfill(r, []))
    page.route("**/api/workflows**", lambda r: fulfill(r, {"available": False, "jobs": [], "running_count": 0}))
    page.route("**/api/views/all", lambda r: fulfill(r, {"views": [], "unavailable": []}))


def test_sidebar_collapses_persists_and_expands(page, app_url):
    _mock(page)
    page.goto(app_url)
    filters = page.get_by_role("button", name="Filters")
    expect(filters).to_be_visible()
    page.get_by_role("button", name="Collapse side panel").click()
    expect(filters).to_be_hidden()
    expand = page.get_by_role("button", name="Expand side panel")
    expect(expand).to_be_visible()
    # The main area takes the freed width.
    main_left = page.locator(".main").bounding_box()["x"]
    assert main_left < 100

    page.reload()
    expect(page.get_by_role("button", name="Expand side panel")).to_be_visible()
    expect(page.get_by_role("button", name="Filters")).to_be_hidden()
    page.get_by_role("button", name="Expand side panel").click()
    expect(page.get_by_role("button", name="Filters")).to_be_visible()

    # "Load data" in the empty state opens Data Builder, where data loads.
    page.get_by_role("button", name="Collapse side panel").click()
    page.get_by_role("button", name="Load data").click()
    expect(page.locator(".jc")).to_be_visible()
    expect(page.locator('[data-source-key="aurora:omop"]')).to_have_attribute("aria-pressed", "true")


def test_tutorial_opens_a_folded_side_panel(page, app_url):
    _mock(page)
    page.add_init_script("localStorage.setItem('cohort-studio.sidebar-collapsed', '1')")
    page.goto(app_url)
    expect(page.get_by_role("button", name="Expand side panel")).to_be_visible()
    page.get_by_role("button", name="Tutorial").click()
    expect(page.get_by_role("button", name="Collapse side panel")).to_be_visible()
    # The first step points at Data Builder, where data loads.
    expect(page.locator(".tutorial-spotlight")).to_have_attribute("data-target", "[data-tutorial-target='nav-join']")
    expect(page.locator(".tutorial-unavailable")).to_have_count(0)
    # Skipping to "Open a table" from Explore still points at Data Builder (not "unavailable").
    page.get_by_role("dialog", name="Choose a source").get_by_role("button", name="Skip step").click()
    expect(page.get_by_role("dialog", name="Open a table")).to_be_visible()
    expect(page.locator(".tutorial-spotlight")).to_have_attribute("data-target", "[data-tutorial-target='nav-join']")
    expect(page.locator(".tutorial-unavailable")).to_have_count(0)
