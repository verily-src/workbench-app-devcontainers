"""Match any group: alternative criteria sent as one {kind: "any"} filter."""
import pytest
from playwright.sync_api import expect

from tests.test_e2e import app_url  # noqa: F401
from tests.ui_helpers import load_table, menu

pytestmark = pytest.mark.e2e


def test_or_groups_build_one_any_filter(page, app_url):
    queries = []

    def fulfill(route, body):
        route.fulfill(status=200, content_type="application/json", json=body)

    def query(route):
        queries.append(route.request.post_data_json.get("filters", []))
        fulfill(route, {"total": 5, "filtered": 2, "scope": "database", "sampled": False, "charts": [],
                        "rows": {"page": 0, "page_size": 50, "columns": ["dx"], "data": [["A"]]}})

    page.route("**/api/datasources", lambda r: fulfill(r, {
        "ready": True, "sources": [{"kind": "aurora", "id": "db", "label": "DB"}], "catalogs_pending": False}))
    page.route("**/api/workflows**", lambda r: fulfill(r, {"available": False, "jobs": [], "running_count": 0}))
    page.route("**/api/views/all", lambda r: fulfill(r, {"views": [], "unavailable": []}))
    page.route("**/api/tables?**", lambda r: fulfill(r, [
        {"name": "public.people", "schema": "public", "table": "people", "detail": "table"}]))
    page.route("**/api/data-jobs/open", lambda r: fulfill(r, {"job_id": "o", "kind": "open", "status": "complete",
        "result": {"dataset_id": "people", "source": "people", "rows": 5, "query_scope": "database",
                   "source_ref": r.request.post_data_json["source_ref"],
                   "columns": [{"name": "dx", "dtype": "object", "filter_kind": "categorical", "values": ["A", "B", "C"]},
                               {"name": "age", "dtype": "int64", "filter_kind": "range", "min": 20, "max": 90}]}}))
    page.route("**/api/datasets/*/query", query)
    page.goto(app_url)
    load_table(page, "aurora:db", "public.people")

    menu(page, "Add to this view").get_by_role("button", name="+ Match any group (OR)").click()
    panel = page.get_by_role("region", name="Match any group")
    g1 = panel.get_by_role("group", name="Group 1")
    g1.locator(".filter-group summary", has_text="dx").click()
    g1.get_by_role("checkbox", name="A", exact=True).check()
    panel.get_by_role("button", name="+ Add OR group").click()
    g2 = panel.get_by_role("group", name="Group 2")
    g2.locator(".filter-group summary", has_text="dx").click()
    g2.get_by_role("checkbox", name="B", exact=True).check()
    expect(page.locator(".chips .chip").first).to_have_text("any of 2 groups ✕")
    expected = [{"column": "", "kind": "any", "groups": [
        [{"column": "dx", "kind": "categorical", "values": ["A"]}],
        [{"column": "dx", "kind": "categorical", "values": ["B"]}]]}]
    for _ in range(50):
        if queries and queries[-1] == expected:
            break
        page.wait_for_timeout(100)
    assert queries[-1] == expected
    # Removing group 1 leaves a single group; removing the chip clears it all.
    panel.get_by_role("button", name="Remove group 1").click()
    expect(page.locator(".chips .chip").first).to_have_text("any of 1 group ✕")
    page.locator(".chips .chip").first.click()
    expect(page.locator(".chips")).to_have_count(0)
