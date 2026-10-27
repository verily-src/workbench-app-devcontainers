from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Page, expect

from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e


def test_unified_saved_views_restore_recipe_and_delete_from_its_store(
        page: Page, app_url: str):
    join_ref = {
        "kind": "join",
        "base": {"kind": "aurora", "resource_id": "db-main", "table": "person"},
        "steps": [{
            "source": {"kind": "s3", "resource_id": "s3:lake",
                       "table": "variants/part-1.parquet"},
            "how": "left",
            "conditions": [{"left": "person_id", "op": "=", "right": "person_id"}],
            "columns": None,
            "alias": "variants",
        }],
    }
    listings = [
        {"name": "shared cohort", "kind": "aurora", "resource_id": "db-main",
         "store_label": "Clinical database", "materialized_sources": 0,
         "refreshed_at": None},
        {"name": "shared cohort", "kind": "s3", "resource_id": "s3:lake",
         "store_label": "Genetics lake", "materialized_sources": 0,
         "refreshed_at": None},
    ]
    opened_refs = []
    deleted = []
    saves = []

    def fulfill(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", json=body)

    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True,
        "sources": [
            {"kind": "aurora", "id": "db-main", "label": "Clinical database"},
            {"kind": "s3", "id": "s3:lake", "label": "Genetics lake"},
        ],
        "catalogs_pending": False,
    }))
    page.route("**/api/workflows**", lambda route: fulfill(route, {
        "available": False, "jobs": [], "running_count": 0,
    }))
    page.route("**/api/views/all", lambda route: fulfill(route, {
        "views": listings, "unavailable": [],
    }))

    def save_view(route):
        body = route.request.post_data_json
        saves.append(body)
        listings.append({
            "name": body["name"], "kind": body["kind"],
            "resource_id": body["resource_id"],
            "store_label": "Clinical database", "materialized_sources": 0,
            "refreshed_at": None,
        })
        fulfill(route, {"name": body["name"]})

    page.route("**/api/views", save_view)

    def get_view(route):
        params = parse_qs(urlparse(route.request.url).query)
        assert params["kind"] == ["s3"]
        assert params["resource_id"] == ["s3:lake"]
        assert params["name"] == ["shared cohort"]
        fulfill(route, {"version": 2, "active": 0, "datasets": [{
            "source": join_ref, "title": "Joined phenotype",
            "filters": [], "charts": [], "cohorts": [],
        }]})

    page.route("**/api/views/one?**", get_view)

    def open_source(route):
        body = route.request.post_data_json
        opened_refs.append(body["source_ref"])
        fulfill(route, {"job_id": "test-open", "status": "complete", "result": {
            "dataset_id": "joined-from-view", "source": "person + variants",
            "rows": 2, "columns": [], "source_ref": body["source_ref"],
            "query_scope": "loaded",
        }})

    page.route("**/api/data-jobs/open", open_source)
    page.route("**/api/datasets/joined-from-view/query", lambda route: fulfill(route, {
        "total": 2, "filtered": 2, "scope": "loaded", "charts": [],
        "rows": {"page": 0, "page_size": 50, "columns": [], "data": []},
    }))

    def delete_view(route):
        params = parse_qs(urlparse(route.request.url).query)
        deleted.append(params)
        listings[:] = [item for item in listings
                       if not (item["kind"] == params["kind"][0]
                               and item["resource_id"] == params["resource_id"][0]
                               and item["name"] == params["name"][0])]
        fulfill(route, {"ok": True})

    page.route("**/api/views?*", delete_view)
    page.goto(app_url)

    listing = page.locator(".view-list")
    expect(listing.get_by_text("Clinical database")).to_be_visible(timeout=15000)
    expect(listing.get_by_text("Genetics lake")).to_be_visible()
    lake_row = page.locator(".view-row").filter(has_text="Genetics lake")
    lake_row.get_by_role("button", name="shared cohort", exact=True).click()

    expect(page.locator(".tab.active")).to_contain_text("Joined phenotype")
    assert opened_refs == [join_ref]
    page.evaluate("""() => Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: async (text) => { window.__savedViewLink = text; } },
    })""")
    lake_row.get_by_role(
        "button", name="Copy link for shared cohort from Genetics lake").click()
    link = page.evaluate("window.__savedViewLink")
    assert link.endswith("#view=s3:s3%3Alake:shared%20cohort")
    page.goto(link)
    page.reload()
    expect(page.locator(".tab.active")).to_contain_text("Joined phenotype")
    assert opened_refs == [join_ref, join_ref]

    page.get_by_label("Saved view name").fill("Aurora copy")
    page.locator(".view-save").get_by_role(
        "button", name="Save", exact=True).click()
    expect(page.get_by_text(
        "Saved 1 tab(s) to Clinical database.")).to_be_visible()
    assert saves[0]["kind"] == "aurora"
    assert saves[0]["resource_id"] == "db-main"

    lake_row.get_by_role("button", name="Delete shared cohort from Genetics lake").click()
    expect(listing.locator(".view-row")).to_have_count(2)
    expect(listing.get_by_text("Genetics lake")).to_have_count(0)
    expect(listing.get_by_role(
        "button", name="shared cohort", exact=True)).to_have_count(1)
    assert deleted == [{
        "kind": ["s3"], "resource_id": ["s3:lake"], "name": ["shared cohort"],
    }]


def test_saved_views_retry_after_store_recovers(page: Page, app_url: str):
    page.clock.install()
    calls = []
    recovered = []
    def fulfill(route, body):
        route.fulfill(status=200, content_type='application/json', json=body)
    page.route('**/api/datasources', lambda route: fulfill(route, {
        'ready': True, 'sources': [{'kind': 'aurora', 'id': 'db-main', 'label': 'Clinical database'}],
        'catalogs_pending': False}))
    def listing(route):
        calls.append(1)
        if not recovered:
            return fulfill(route, {'views': [], 'pending': [], 'unavailable': [
                {'kind': 'aurora', 'resource_id': 'db-main', 'label': 'Clinical database',
                 'error': 'Temporarily unavailable'}]})
        return fulfill(route, {'views': [{'name': 'Recovered view', 'kind': 'aurora',
            'resource_id': 'db-main', 'store_label': 'Clinical database',
            'materialized_sources': 0}], 'pending': [], 'unavailable': []})
    page.route('**/api/views/all', listing)
    page.goto(app_url)
    expect(page.get_by_text('1 saved-view stores unavailable')).to_be_visible(timeout=15000)
    recovered.append(True)
    page.clock.fast_forward(21000)
    expect(page.get_by_role('button', name='Recovered view', exact=True)).to_be_visible(timeout=15000)
    assert len(calls) >= 2
