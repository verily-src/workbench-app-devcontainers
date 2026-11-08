from playwright.sync_api import expect

from tests.test_e2e import app_url  # noqa: F401
from tests.test_dashboard_filters_frontend import _tab, _upload, LABS, PEOPLE


def test_compare_discards_results_when_tab_or_scope_changes(page, app_url):
    page.goto(app_url)
    _upload(page, "labs.csv", LABS, 8)
    _upload(page, "people.csv", PEOPLE, 10)
    page.get_by_role("button", name="Compare groups").click()
    panel = page.locator(".compare-panel")
    panel.get_by_role("button", name="Compare", exact=True).click()
    expect(panel.locator("table")).to_be_visible(timeout=15000)
    _tab(page, "labs.csv")
    expect(panel.locator("table")).to_have_count(0)

    held = []
    page.route("**/api/datasets/*/compare", lambda route: held.append(route))
    panel.get_by_role("button", name="Compare", exact=True).click()
    page.wait_for_timeout(300)
    assert held
    _tab(page, "people.csv")
    held[0].fulfill(json={"a_n": 8, "b_n": 0, "n_overlap": 0, "results": []})
    expect(panel.locator("table")).to_have_count(0)
    expect(panel.get_by_role("button", name="Compare", exact=True)).to_be_enabled()
    page.unroute("**/api/datasets/*/compare")
    panel.get_by_role("button", name="Compare", exact=True).click()
    expect(panel.locator("table")).to_be_visible(timeout=15000)
    group = page.locator(".filter-group", has_text="sex")
    group.locator("summary").click()
    group.get_by_label("F", exact=True).check()
    expect(panel.locator("table")).to_have_count(0)
