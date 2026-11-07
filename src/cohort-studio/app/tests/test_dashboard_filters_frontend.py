"""Dashboard filters (apply to every tab with the column) and linked chart selection."""
import pytest
from playwright.sync_api import Page, expect

from tests.test_e2e import FIXTURE_CSV, app_url  # noqa: F401
from tests.test_table_info_progress_frontend import _mock_app

pytestmark = pytest.mark.e2e

PEOPLE = "id,sex,age\n" + "".join(f"p{i},{'F' if i < 6 else 'M'},{20 + i}\n" for i in range(10))
LABS = "id,sex,value\n" + "".join(f"l{i},{'F' if i < 3 else 'M'},{i}\n" for i in range(8))
SITES = "site,sex\n" + "".join(f"s{i},{i + 0.5}\n" for i in range(12))


def _upload(page, name, text, rows):
    page.locator('input[type="file"]').set_input_files(
        {"name": name, "mimeType": "text/csv", "buffer": text.encode()})
    expect(page.locator(".tab.active", has_text=name)).to_be_visible(timeout=15000)
    expect(page.locator(".hero .count")).to_have_text(str(rows), timeout=15000)


def _tab(page, name):
    page.locator(".tab", has_text=name).locator("span").first.click()
    expect(page.locator(".tab.active", has_text=name)).to_be_visible()


def test_filter_applies_to_every_tab_with_the_column(page: Page, app_url: str):
    page.goto(app_url)
    expect(page.get_by_text("No data loaded")).to_be_visible(timeout=15000)
    _upload(page, "sites.csv", SITES, 12)
    _upload(page, "labs.csv", LABS, 8)
    _upload(page, "people.csv", PEOPLE, 10)
    strip = page.get_by_role("region", name="Dashboard filters")
    expect(strip).to_have_count(0)            # no strip until there is a dashboard filter

    group = page.locator(".filter-group", has_text="sex")
    group.locator("summary").click()
    group.get_by_label("F", exact=True).check()
    expect(page.locator(".hero .count")).to_have_text("6", timeout=10000)
    group.get_by_role("button", name="Apply to all tabs", exact=True).click()
    expect(strip).to_contain_text("sex: F")
    # The filter moved to dashboard level: no tab chip, same rows.
    expect(page.locator(".chips .chip", has_text="sex: F")).to_have_count(0)
    expect(page.locator(".hero .count")).to_have_text("6")

    _tab(page, "labs.csv")
    expect(page.locator(".hero .count")).to_have_text("3", timeout=10000)
    expect(page.locator(".hero .detail")).to_contain_text("of 8 rows")

    _tab(page, "sites.csv")                   # sex is a number column here: the filter doesn't apply
    chip = strip.locator(".dashboard-chip")
    expect(chip).to_contain_text("not in this tab")
    expect(chip).to_have_attribute("title", "sex isn't a categorical field in this tab.")
    page.wait_for_timeout(600)
    expect(page.locator(".hero .count")).to_have_text("12")

    # Edit on this tab: the filter becomes the tab's own again (and leaves the other tabs).
    _tab(page, "labs.csv")
    strip.get_by_role("button", name="Dashboard filter sex: F", exact=True).click()
    strip.get_by_role("button", name="Edit on this tab", exact=True).click()
    expect(strip).to_have_count(0)
    expect(page.locator(".chips .chip", has_text="sex: F")).to_be_visible()
    expect(page.locator(".hero .count")).to_have_text("3", timeout=10000)
    _tab(page, "people.csv")
    expect(page.locator(".hero .count")).to_have_text("10", timeout=10000)

    # Re-apply from labs, then remove it from every tab with ✕.
    _tab(page, "labs.csv")
    page.locator(".filter-group", has_text="sex").get_by_role(
        "button", name="Apply to all tabs", exact=True).click()
    _tab(page, "people.csv")
    expect(page.locator(".hero .count")).to_have_text("6", timeout=10000)
    # Compare groups stays inside the dashboard filters: "rest" is not every other row.
    compares = []
    page.on("request", lambda r: "/compare" in r.url and compares.append(r.post_data_json))
    page.get_by_role("button", name="Compare groups", exact=True).click()
    panel = page.locator(".compare-panel")
    panel.get_by_role("button", name="Compare", exact=True).click()
    expect(panel.locator(".data-table")).to_be_visible(timeout=10000)
    assert compares[-1]["scope"] == [{"column": "sex", "kind": "categorical", "values": ["F"]}]
    page.get_by_role("button", name="Hide compare", exact=True).click()

    strip.get_by_role("button", name="Remove dashboard filter sex: F", exact=True).click()
    expect(strip).to_have_count(0)
    expect(page.locator(".hero .count")).to_have_text("10", timeout=10000)

    # Closing every tab drops the dashboard filters; the next table starts without them.
    sex = page.locator(".filter-group", has_text="sex")
    if not sex.get_by_label("F", exact=True).is_visible():
        sex.locator("summary").click()
    sex.get_by_label("F", exact=True).check()
    sex.get_by_role(
        "button", name="Apply to all tabs", exact=True).click()
    expect(strip).to_be_visible()
    while page.locator(".tab").count():
        page.locator(".tab").first.get_by_role("button", name="✕", exact=True).click()
    _upload(page, "labs.csv", LABS, 8)
    expect(strip).to_have_count(0)


def _routes(page, queries, saves, view_state=None):
    reply = _mock_app(page)
    columns = {
        "person": [{"name": "person_id", "dtype": "int64", "filter_kind": "none"},
                   {"name": "sex", "dtype": "object", "filter_kind": "categorical", "values": ["F", "M"]}],
        "visit": [{"name": "visit_id", "dtype": "int64", "filter_kind": "none"}],
    }

    def open_job(route):
        ref = route.request.post_data_json["source_ref"]
        table = ref["table"]
        reply(route, {"job_id": f"j-{table}", "kind": "open", "status": "complete", "result": {
            "dataset_id": f"ds-{table}", "source": f"omop / cms.{table}", "rows": 4,
            "columns": columns[table], "query_scope": "database", "source_ref": ref}})

    def query(route):
        queries.append((route.request.url.split("/")[-2], route.request.post_data_json["filters"]))
        reply(route, {"total": 4, "filtered": 4, "scope": "database", "sampled": False, "entity": None,
                      "cache": None, "charts": [],
                      "rows": {"page": 0, "page_size": 50, "columns": [], "data": []}})

    def save(route):
        saves.append(route.request.post_data_json)
        reply(route, {"name": saves[-1]["name"]})

    page.route("**/api/data-jobs/open", open_job)
    page.route("**/api/datasets/*/query", query)
    page.route("**/api/views", save)
    page.route("**/api/views/all", lambda r: reply(r, {"views": [
        {"name": "two tabs", "kind": "aurora", "resource_id": "omop", "store_label": "OMOP",
         "materialized_sources": 0, "refreshed_at": None}], "unavailable": [], "pending": []}))
    page.route("**/api/views/one?**", lambda r: reply(r, view_state))


SEX_F = {"column": "sex", "kind": "categorical", "values": ["F"]}


def test_dashboard_filters_save_with_views_and_restore_with_the_session(page: Page, app_url: str):
    queries, saves = [], []
    tab = lambda table: {"source": {"kind": "aurora", "resource_id": "omop", "schema": "cms", "table": table},
                         "title": table, "filters": [], "charts": [], "cohorts": []}
    _routes(page, queries, saves, {"version": 2, "active": 0, "datasets": [tab("person"), tab("visit")],
                                   "dashboard_filters": [SEX_F]})
    page.goto(app_url)
    page.locator(".view-row").get_by_role("button", name="two tabs", exact=True).click()
    expect(page.locator(".tab.active")).to_contain_text("person", timeout=10000)
    strip = page.get_by_role("region", name="Dashboard filters")
    expect(strip).to_contain_text("sex: F")
    page.wait_for_timeout(600)
    assert ("ds-person", [SEX_F]) in queries
    _tab(page, "visit")
    page.wait_for_timeout(600)
    assert queries[-1] == ("ds-visit", [])        # visit has no sex column
    expect(strip.locator(".dashboard-chip")).to_contain_text("not in this tab")

    page.get_by_label("Saved view name").fill("copy")
    page.locator(".view-save").get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_text("Saved 2 tab(s)", exact=False)).to_be_visible(timeout=10000)
    assert saves[-1]["dashboard_filters"] == [SEX_F]

    page.wait_for_timeout(1200)                   # session autosave debounce
    page.reload()
    page.get_by_role("button", name="Restore last session", exact=True).click()
    expect(page.locator(".tab.active")).to_contain_text("visit", timeout=10000)
    expect(page.get_by_role("region", name="Dashboard filters")).to_contain_text("sex: F")
    _tab(page, "person")
    page.wait_for_timeout(600)
    assert queries[-1] == ("ds-person", [SEX_F])


def _bar_point(page, card, category):
    return card.locator(".chart-plot").evaluate("""(el, cat) => {
      const chart = window.__studioEcharts.getInstanceByDom(el);
      const option = chart.getOption();
      const cats = option.yAxis[0].data;
      const i = cats.indexOf(cat);
      const raw = option.series[0].data[i];
      const value = raw !== null && typeof raw === 'object' ? raw.value : raw;
      const [x, y] = chart.convertToPixel({seriesIndex: 0}, [value / 2, cat]);
      const rect = el.getBoundingClientRect();
      return [rect.left + x, rect.top + y];   // ECharts reads client offsets without the UI zoom
    }""", category)


def _opacities(card):
    return card.locator(".chart-plot").evaluate("""el => {
      const option = window.__studioEcharts.getInstanceByDom(el).getOption();
      const cats = option.yAxis[0].data;
      return Object.fromEntries(cats.map((c, i) => {
        const d = option.series[0].data[i];
        return [c, d && typeof d === 'object' && d.itemStyle && d.itemStyle.opacity !== undefined ? d.itemStyle.opacity : 1];
      }));
    }""")


def test_chart_click_selects_and_links_the_other_charts(page: Page, app_url: str):
    page.goto(app_url)
    expect(page.get_by_text("No data loaded")).to_be_visible(timeout=15000)
    page.locator('input[type="file"]').set_input_files(FIXTURE_CSV)
    count = page.locator(".hero .count")
    expect(count).to_have_text("100", timeout=15000)
    card = page.locator(".chart-card", has_text="tissue").first
    card.scroll_into_view_if_needed()
    page.wait_for_timeout(800)

    def click(category, modifier=None):
        x, y = _bar_point(page, card, category)
        if modifier:
            page.keyboard.down(modifier)
        page.mouse.click(x, y)
        if modifier:
            page.keyboard.up(modifier)

    click("liver")
    expect(count).to_have_text("25", timeout=10000)
    expect(card.locator(".chart-selection")).to_have_text("liver✕")
    page.wait_for_timeout(600)
    shade = _opacities(card)
    assert shade["liver"] == 1 and all(v == 0.3 for c, v in shade.items() if c != "liver"), shade

    click("lung")                                   # a plain click selects only that one
    expect(page.locator(".chips .chip", has_text="tissue: lung")).to_be_visible(timeout=10000)
    expect(page.locator(".chips .chip", has_text="tissue: liver")).to_have_count(0)

    click("liver", "Shift")                         # Shift adds
    expect(card.locator(".chart-selection")).to_contain_text("2 selected", timeout=10000)
    expect(count).to_have_text("50", timeout=10000)
    # Every chart on the tab follows the selection (age histogram's selected bars).
    page.wait_for_timeout(600)
    age = page.locator(".chart-card", has_text="age").first
    selected = age.locator(".chart-plot").evaluate("""el => window.__studioEcharts.getInstanceByDom(el)
        .getOption().series[1].data.reduce((a, b) => a + (typeof b === 'object' && b ? b.value : b), 0)""")
    assert selected == 50

    click("lung", "Shift")                          # Shift removes
    expect(card.locator(".chart-selection")).to_have_text("liver✕", timeout=10000)
    click("liver")                                  # clicking the only selected value clears it
    expect(count).to_have_text("100", timeout=10000)
    expect(card.locator(".chart-selection")).to_have_count(0)

    click("lung")
    expect(count).to_have_text("25", timeout=10000)
    page.keyboard.press("Escape")
    expect(count).to_have_text("100", timeout=10000)

    click("lung")
    expect(count).to_have_text("25", timeout=10000)
    card.get_by_role("button", name="Clear selection", exact=True).click()
    expect(count).to_have_text("100", timeout=10000)
