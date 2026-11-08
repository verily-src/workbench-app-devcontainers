"""Data loads in Data Builder; Explore's side panel shows the tab's source card
and foldable Parameters / Filters / Saved views sections."""
import pytest
from playwright.sync_api import expect

from tests.test_e2e import app_url
from tests.ui_helpers import load_table, pick_table

pytestmark = pytest.mark.e2e

SHOTS = "/private/tmp"
COLUMNS = [
    {"name": "person_id", "dtype": "int64", "filter_kind": "none"},
    {"name": "cost", "dtype": "float64", "logical_type": "number",
     "filter_kind": "range", "min": 0, "max": 10},
    {"name": "state", "dtype": "object", "filter_kind": "categorical", "values": ["CA", "NY"]},
]
TABLES = [
    {"name": "cms.cost", "schema": "cms", "table": "cost", "detail": "table",
     "rows": 32355293, "rows_estimated": True, "bytes": 6_550_000_000,
     "columns": 22, "analyzed": "2026-11-04T03:50:00+00:00"},
    {"name": "cms.person", "schema": "cms", "table": "person", "detail": "table",
     "rows": 100000, "rows_estimated": True, "bytes": 24_000_000, "columns": 18},
    {"name": "public.notes", "schema": "public", "table": "notes", "detail": "view", "columns": 4},
]
EXTRACT = {"table": "cost_extract", "title": "cost", "rows": 3, "created_at": "2026-11-07T10:00:00Z",
           "refreshed_at": "2026-11-07T10:00:00Z", "refreshable": True,
           "recipe": {"kind": "aurora", "resource_id": "omop", "schema": "cms", "table": "cost"}}


def _mock(page):
    calls = {"open": [], "extract": [], "query": []}

    def reply(route, value, status=200):
        route.fulfill(status=status, json=value)

    page.route("**/api/datasources", lambda r: reply(r, {"ready": True, "catalogs_pending": False, "sources": [
        {"kind": "aurora", "id": "omop", "label": "OMOP"},
        {"kind": "s3", "id": "lake", "label": "Lake"},
        {"kind": "bq", "id": "bq:pub", "label": "Public BigQuery"}]}))
    page.route("**/api/config", lambda r: reply(r, {"chart_palette": "verily"}))
    page.route("**/api/workflows**", lambda r: reply(r, {"available": False, "jobs": [], "running_count": 0}))
    page.route("**/api/views/all", lambda r: reply(r, {"views": [], "unavailable": [], "pending": []}))
    page.route("**/api/omop/**", lambda r: reply(r, {"cdm": False, "tables": []}))
    page.route("**/api/tables?**", lambda r: reply(r, TABLES if "omop" in r.request.url
                                                    else [{"name": "raw/a.csv", "detail": "file", "bytes": 10}]))

    def open_job(route):
        body = route.request.post_data_json
        calls["open"].append(body.get("source_ref", body))
        n = len(calls["open"])
        ref = body.get("source_ref") or {}
        reply(route, {"job_id": f"open{n}", "kind": "open", "status": "complete", "result": {
            "dataset_id": f"ds{n}", "source": f"omop / {ref.get('schema')}.{ref.get('table')}",
            "rows": 3, "columns": COLUMNS,
            "query_scope": "database", "source_ref": body.get("source_ref")}})

    def extract_job(route):
        calls["extract"].append(route.request.post_data_json)
        reply(route, {"job_id": "ex1", "kind": "extract", "status": "complete", "result": {
            "dataset_id": "dsx", "source": "omop / cost_extract", "rows": 3, "columns": COLUMNS,
            "query_scope": "database", "extract": EXTRACT,
            "source_ref": {"kind": "aurora", "resource_id": "omop", "table": "cost_extract"}}})

    def query(route):
        calls["query"].append(route.request.url)
        reply(route, {"total": 32355293, "filtered": 32355293, "scope": "database", "sampled": False,
                      "entity": None, "cache": None, "charts": [],
                      "rows": {"page": 0, "page_size": 50, "columns": ["person_id"], "data": [[1]]}})

    page.route("**/api/data-jobs/open", open_job)
    page.route("**/api/data-jobs/extract", extract_job)
    page.route("**/api/datasets/*/query", query)
    page.route("**/api/datasets/*", lambda r: reply(r, {}) if r.request.method == "DELETE" else r.fallback())
    return calls


def test_load_data_opens_data_builder_and_a_table_opens_live_in_explore(page, app_url):
    calls = _mock(page)
    page.set_viewport_size({"width": 1280, "height": 720})
    page.goto(app_url)
    expect(page.get_by_text("No data loaded").first).to_be_visible(timeout=15000)
    # The side panel no longer holds the datasource selects.
    expect(page.get_by_label("Source type")).to_have_count(0)
    side = page.get_by_role("complementary", name="Side panel")
    expect(side.get_by_role("button", name="Data source")).to_have_attribute("aria-expanded", "true")

    # Click 1: Load data → Data Builder; the first datasource is already chosen.
    page.get_by_role("button", name="Load data", exact=True).click()
    canvas = page.locator(".jc")
    expect(canvas).to_be_visible()
    expect(canvas.locator('[data-source-key="aurora:omop"]')).to_have_attribute("aria-pressed", "true")
    expect(canvas.get_by_role("group", name="Schema cms")).to_be_visible()

    # Click 2: the table shows its statistics and the Open actions.
    canvas.locator('li[data-table="cms.cost"] .jc-table-pick').click()
    card = canvas.get_by_role("region", name="Selected table")
    details = card.get_by_label("Table details")
    expect(details).to_contain_text("Rows~32.4M")
    expect(details).to_contain_text("Size6.1 GB")
    expect(details).to_contain_text("Columns22")
    expect(details).to_contain_text("Stats as of")
    expect(card.get_by_role("radio", name="Live")).to_be_checked()
    page.screenshot(path=f"{SHOTS}/cohort-data-builder-open-table.png")

    # Click 3: Open in Explore (Live).
    card.get_by_role("button", name="Open in Explore").click()
    expect(page.locator(".tab.active")).to_contain_text("cost", timeout=10000)
    assert calls["open"][-1] == {"kind": "aurora", "resource_id": "omop", "table": "cost", "schema": "cms"}

    source = side.get_by_role("group", name="Data source of this tab")
    expect(source).to_contain_text("omop / cms.cost")
    expect(source).to_contain_text("Aurora")
    expect(source).to_contain_text("Live")
    expect(source).to_contain_text("32,355,293")
    expect(side.locator(".section-label", has_text="Filters")).to_be_visible()
    page.screenshot(path=f"{SHOTS}/cohort-explore-side-panel.png")
    page.evaluate("document.documentElement.dataset.theme = 'dark'; document.documentElement.dataset.palette = 'partner'")
    page.screenshot(path=f"{SHOTS}/cohort-explore-side-panel-dark-partner.png")
    page.evaluate("document.documentElement.dataset.theme = 'light'; delete document.documentElement.dataset.palette")

    # Refresh source queries the live table again.
    before = len(calls["query"])
    source.get_by_role("button", name="Refresh source").click()
    for _ in range(50):
        if len(calls["query"]) > before:
            break
        page.wait_for_timeout(100)
    assert len(calls["query"]) > before
    assert len(calls["open"]) == 1

    # Change… goes back to Data Builder with this table picked.
    source.get_by_role("button", name="Change data source").click()
    expect(canvas).to_be_visible()
    expect(canvas.locator('li[data-table="cms.cost"] .jc-table-pick')).to_have_attribute("aria-pressed", "true")
    person = canvas.locator('li[data-table="cms.person"] .jc-table-pick')
    person.click()
    expect(canvas.get_by_role("region", name="Selected table")).to_contain_text("person")
    # Double-click opens a table Live in one step.
    person.dblclick()
    expect(page.locator(".tab")).to_have_count(2, timeout=10000)
    assert calls["open"][-1]["table"] == "person"


def test_a_table_opens_as_an_extract_from_data_builder(page, app_url):
    calls = _mock(page)
    page.goto(app_url)
    card = pick_table(page, "aurora:omop", "cms.cost")
    card.get_by_role("radio", name="Extract").check()
    expect(card.get_by_label("Extract table")).to_have_value("cost_extract")
    page.set_viewport_size({"width": 1280, "height": 720})
    page.screenshot(path=f"{SHOTS}/cohort-data-builder-open-extract.png")
    card.get_by_role("button", name="Open in Explore").click()
    expect(page.locator(".tab.active")).to_contain_text("cost", timeout=10000)
    assert calls["extract"][-1]["resource_id"] == "omop"
    assert calls["extract"][-1]["table"] == "cost_extract"
    assert calls["extract"][-1]["dataset_id"] == "ds1"
    source = page.get_by_role("group", name="Data source of this tab")
    expect(source.locator(".source-chip.mode")).to_have_text("Extract")
    expect(source).to_contain_text("Refreshed")
    source.get_by_role("button", name="Edit…").click()
    expect(page.locator(".jc .jc-node")).to_have_count(1, timeout=10000)


def test_bigquery_tables_open_live_only(page, app_url):
    """A BigQuery table opens as a capped sample, so Extract (every row) is off."""
    _mock(page)
    page.goto(app_url)
    card = pick_table(page, "bq:bq:pub", "raw/a.csv")
    expect(card.get_by_role("radio", name="Extract")).to_be_disabled()
    expect(card.get_by_role("radio", name="Live")).to_be_checked()


def test_upload_lives_in_data_builder_and_the_card_says_upload(page, app_url):
    _mock(page)
    page.goto(app_url)
    canvas = page.locator(".jc")
    page.get_by_role("button", name="Load data", exact=True).click()
    expect(canvas.get_by_role("button", name="+ Add data source")).to_be_visible()
    with page.expect_file_chooser() as chooser:
        canvas.get_by_role("button", name="Upload CSV, TSV or Parquet").click()
    chooser.value.set_files(files=[{"name": "tiny.csv", "mimeType": "text/csv",
                                    "buffer": b"person_id,group\n1,a\n2,b\n"}])
    expect(page.locator(".tab.active")).to_contain_text("tiny.csv", timeout=15000)
    source = page.get_by_role("group", name="Data source of this tab")
    expect(source.locator(".source-chip.mode")).to_have_text("Upload")
    expect(source.get_by_role("button", name="Refresh source")).to_have_count(0)


def test_side_panel_sections_fold_and_stay_folded_after_reload(page, app_url):
    _mock(page)
    page.goto(app_url)
    load_table(page, "aurora:omop", "cms.cost")
    side = page.get_by_role("complementary", name="Side panel")
    filters = side.get_by_role("button", name="Filters")
    expect(filters).to_have_attribute("aria-expanded", "true")
    body = page.locator("#fold-filters")
    expect(body).to_be_visible()
    filters.click()
    expect(filters).to_have_attribute("aria-expanded", "false")
    expect(body).to_be_hidden()
    side.get_by_role("button", name="Saved views").click()
    expect(page.locator("#fold-saved-views")).to_be_hidden()
    # The data source card stays open.
    expect(side.get_by_role("group", name="Data source of this tab")).to_be_visible()

    page.reload()
    expect(page.get_by_text("No data loaded").first).to_be_visible(timeout=15000)
    side = page.get_by_role("complementary", name="Side panel")
    expect(side.get_by_role("button", name="Filters")).to_have_attribute("aria-expanded", "false")
    expect(page.locator("#fold-filters")).to_be_hidden()
    expect(page.locator("#fold-saved-views")).to_be_hidden()
    side.get_by_role("button", name="Filters").click()
    expect(page.locator("#fold-filters")).to_be_visible()
    assert page.evaluate("localStorage.getItem('cohort-studio.fold.filters')") == "1"
