import pytest
from playwright.sync_api import expect

from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e


def test_query_failure_has_retry_and_keeps_last_successful_charts(page, app_url):
    pending = []
    query_requests = []
    columns = [{"name": "tissue", "dtype": "text", "filter_kind": "categorical",
                "values": ["liver", "lung"]}]
    result = {
        "total": 2, "filtered": 2, "scope": "database", "sampled": False,
        "charts": [{"kind": "bar", "data": [
            {"category": "liver", "all": 1, "selected": 1},
        ]}],
        "rows": {"page": 0, "page_size": 50, "columns": ["tissue"],
                 "data": [["liver"], ["lung"]]},
    }

    def fulfill(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", json=body)

    page.route("**/api/config", lambda route: fulfill(route, {
        "chart_palette": "verily", "llm": {"provider": "anthropic", "providers": {}}
    }))
    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True, "sources": [], "catalogs_pending": False,
    }))
    page.route("**/api/workflows**", lambda route: fulfill(route, {
        "available": False, "jobs": [], "running_count": 0,
    }))
    page.route("**/api/views/all", lambda route: fulfill(route, {
        "views": [], "unavailable": [],
    }))
    page.route("**/api/datasets/upload", lambda route: fulfill(route, {
        "dataset_id": "query-error-dataset", "source": "query-error.csv",
        "rows": 2, "query_scope": "database", "columns": columns,
    }))

    def query(route):
        query_requests.append(route.request.post_data_json)
        if len(query_requests) in (1, 3):
            pending.append(route)
        else:
            fulfill(route, result)

    page.route("**/api/datasets/query-error-dataset/query", query)

    page.goto(app_url)
    page.locator('input[type="file"]').set_input_files({
        "name": "query-error.csv", "mimeType": "text/csv",
        "buffer": b"tissue\nliver\nlung\n",
    })
    expect(page.get_by_text("Loading data and charts…", exact=True)).to_be_visible()
    expect(page.locator(".chart-grid")).to_have_count(0)
    pending[0].fulfill(status=504, content_type="application/json",
                       json={"detail": "Database query timed out."})
    expect(page.get_by_role("alert")).to_contain_text("Query failed: 504: Database query timed out.")
    expect(page.get_by_role("button", name="Retry query", exact=True)).to_be_visible()
    expect(page.locator(".chart-grid")).to_have_count(0)

    page.get_by_role("button", name="Retry query", exact=True).click()
    expect(page.locator(".chart-grid .chart-card")).to_be_visible()
    expect(page.get_by_role("cell", name="liver", exact=True)).to_be_visible()
    expect(page.get_by_role("alert")).to_have_count(0)

    page.get_by_role("button", name="Refresh data", exact=True).click()
    expect(page.get_by_text("Refreshing…", exact=True)).to_be_visible()
    pending[1].fulfill(status=504, content_type="application/json",
                       json={"detail": "Database query timed out again."})
    expect(page.get_by_role("alert")).to_contain_text("504: Database query timed out again.")
    expect(page.get_by_role("alert")).to_contain_text("Showing the last successful result.")
    expect(page.locator(".chart-grid .chart-card")).to_be_visible()
    expect(page.get_by_role("cell", name="liver", exact=True)).to_be_visible()
    assert len(query_requests) == 3
