import pytest
from playwright.sync_api import expect
from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e

COLUMNS = [
    {"name": "person_id", "dtype": "int64", "filter_kind": "none"},
    {"name": "group", "dtype": "object", "filter_kind": "categorical",
     "values": ["A", "B", "C", "D"]},
]


def _mock(page, query_handler):
    def reply(route, value, status=200):
        route.fulfill(status=status, json=value)
    page.route("**/api/datasources", lambda r: reply(r, {
        "ready": True, "sources": [{"kind": "aurora", "id": "db", "label": "DB"}]}))
    page.route("**/api/config", lambda r: reply(r, {"chart_palette": "verily"}))
    page.route("**/api/workflows**", lambda r: reply(r, {"available": False, "jobs": [], "running_count": 0}))
    page.route("**/api/views/all", lambda r: reply(r, {"views": [], "unavailable": [], "pending": []}))
    page.route("**/api/tables?**", lambda r: reply(r, [
        {"name": "public.person", "schema": "public", "table": "person", "detail": "table"}]))
    page.route("**/api/omop/**", lambda r: reply(r, {"cdm": False, "tables": []}))
    page.route("**/api/data-jobs/open", lambda r: reply(r, {
        "job_id": "o1", "kind": "open", "status": "complete", "result": {
            "dataset_id": "ds1", "source": "db / person", "rows": 4, "columns": COLUMNS,
            "query_scope": "database"}}))
    page.route("**/api/datasets/ds1/query", query_handler)
    return reply


def _body(selected):
    return {"total": 4, "filtered": len(selected) or 4, "scope": "database", "sampled": False,
            "entity": None, "cache": None, "charts": [],
            "rows": {"page": 0, "page_size": 50, "columns": ["person_id", "group"], "data": [[1, "A"]]}}


def _load(page, app_url):
    page.goto(app_url)
    page.get_by_label("Source type", exact=True).select_option("aurora")
    page.get_by_label("Datasource", exact=True).select_option("aurora:db")
    page.get_by_label("Table", exact=True).select_option("public.person")
    page.get_by_role("button", name="Load table", exact=True).click()
    expect(page.locator(".dataset-toolbar")).to_be_visible(timeout=10000)


def test_rapid_filter_clicks_send_one_dashboard_query(page, app_url):
    bodies = []

    def query(route):
        body = route.request.post_data_json
        bodies.append(body)
        values = next((f.get("values", []) for f in body["filters"] if f["column"] == "group"), [])
        route.fulfill(status=200, json=_body(values))
    _mock(page, query)
    _load(page, app_url)
    page.wait_for_timeout(500)
    initial = len(bodies)
    page.locator("summary", has_text="group").click()
    for value in ("A", "B", "C", "D"):
        page.locator(".filter-values label", has_text=value).locator("input").click()
    page.wait_for_timeout(1200)
    later = bodies[initial:]
    assert len(later) == 1, [b["filters"] for b in later]
    assert later[0]["filters"][0]["values"] == ["A", "B", "C", "D"]


def test_busy_dashboard_query_is_retried_once(page, app_url):
    calls = {"n": 0}

    def query(route):
        calls["n"] += 1
        if calls["n"] == 1:
            route.fulfill(status=429, json={"detail": "Dashboard queries are busy. Try again."})
            return
        route.fulfill(status=200, json=_body([]))
    _mock(page, query)
    _load(page, app_url)
    expect(page.locator(".hero .count")).to_have_text("4", timeout=10000)
    expect(page.get_by_text("Query failed")).to_have_count(0)
    assert calls["n"] == 2
