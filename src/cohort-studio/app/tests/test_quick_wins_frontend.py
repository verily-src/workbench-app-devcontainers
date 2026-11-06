"""Quick wins: apply a saved cohort, search filter values, move and duplicate charts."""
import pytest
from playwright.sync_api import expect

from tests.test_frontend_e2e import loaded_page, app_url  # noqa: F401

pytestmark = pytest.mark.e2e


def _titles(page):
    return [t.strip() for t in page.locator(".chart-card .head .title").all_inner_texts()]


def test_charts_move_and_duplicate(loaded_page):
    page = loaded_page
    expect(page.locator(".chart-card")).to_have_count(3, timeout=10000)
    first, second = _titles(page)[:2]
    card = page.locator(".chart-card").first
    card.get_by_role("button", name="Chart actions").click()
    card.get_by_role("button", name="Duplicate").click()
    expect(page.locator(".chart-card")).to_have_count(4)
    assert _titles(page)[:3] == [first, f"{first} (copy)", second]
    # The copy shows the same data right away (results move with their charts).
    data = page.evaluate("""() => [...document.querySelectorAll('.chart-card .chart-plot')].slice(0, 2)
        .map((el) => JSON.stringify(window.__studioEcharts.getInstanceByDom(el).getOption().series.map((s) => s.data)))""")
    assert data[0] == data[1]
    # Moving the copy later swaps it with its neighbour; the first chart can't move earlier.
    copy = page.locator(".chart-card").nth(1)
    copy.get_by_role("button", name="Chart actions").click()
    copy.get_by_role("button", name="Move later").click()
    expect(page.locator(".chart-card .head .title").nth(2)).to_have_text(f"{first} (copy)")
    card.get_by_role("button", name="Chart actions").click()
    expect(card.get_by_role("button", name="Move earlier")).to_be_disabled()


def test_saved_cohort_applies_its_filters(loaded_page):
    page = loaded_page
    page.locator(".filter-group summary", has_text="tissue").click()
    page.locator(".filter-group", has_text="tissue").get_by_label("liver").check()
    expect(page.locator(".chips .chip").first).to_contain_text("tissue: liver", timeout=10000)
    page.locator(".cohort-name").fill("Liver")
    page.get_by_role("button", name="Save cohort").click()
    expect(page.locator(".cohort-chip.active")).to_contain_text("Liver")
    page.locator(".chips .chip.clear").click()
    expect(page.locator(".chips")).to_have_count(0)
    expect(page.locator(".cohort-chip.active")).to_have_count(0)
    page.get_by_role("button", name="Apply cohort Liver").click()
    expect(page.locator(".chips .chip").first).to_contain_text("tissue: liver", timeout=10000)
    expect(page.locator(".cohort-chip.active")).to_contain_text("Liver")


def test_filter_values_can_be_searched(page, app_url):
    values = [f"site_{i:02d}" for i in range(12)]

    def fulfill(route, body):
        route.fulfill(status=200, content_type="application/json", json=body)

    page.route("**/api/datasources", lambda r: fulfill(r, {
        "ready": True, "sources": [{"kind": "aurora", "id": "db", "label": "DB"}], "catalogs_pending": False}))
    page.route("**/api/workflows**", lambda r: fulfill(r, {"available": False, "jobs": [], "running_count": 0}))
    page.route("**/api/views/all", lambda r: fulfill(r, {"views": [], "unavailable": []}))
    page.route("**/api/tables?**", lambda r: fulfill(r, [
        {"name": "public.visits", "schema": "public", "table": "visits", "detail": "table"}]))
    page.route("**/api/data-jobs/open", lambda r: fulfill(r, {"job_id": "o", "kind": "open", "status": "complete",
        "result": {"dataset_id": "visits", "source": "visits", "rows": 12, "query_scope": "database",
                   "source_ref": r.request.post_data_json["source_ref"],
                   "columns": [{"name": "site", "dtype": "object", "filter_kind": "categorical",
                                "values": values}]}}))
    page.route("**/api/datasets/*/query", lambda r: fulfill(r, {
        "total": 12, "filtered": 12, "scope": "database", "sampled": False, "charts": [],
        "rows": {"page": 0, "page_size": 50, "columns": ["site"], "data": [[v] for v in values]}}))
    page.goto(app_url)
    page.get_by_label("Source type", exact=True).select_option("aurora")
    page.get_by_label("Datasource", exact=True).select_option("aurora:db")
    page.get_by_label("Schema", exact=True).select_option("public")
    page.get_by_label("Table", exact=True).select_option("public.visits")
    page.get_by_role("button", name="Load table").click()
    group = page.locator(".filter-group", has_text="site")
    group.locator("summary").click()
    group.get_by_label("site_03").check()
    search = group.get_by_label("Search site values")
    search.fill("1")
    # Matches plus the selected value stay listed.
    expect(group.locator(".filter-values label")).to_have_text(["site_01", "site_03", "site_10", "site_11"])
    search.fill("zz")
    expect(group).to_contain_text('No other values match "zz".')
    expect(group.get_by_label("site_03")).to_be_checked()
