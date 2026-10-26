import pytest
from playwright.sync_api import Page, expect

from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e


def test_saved_view_materialization_status_refresh_and_failure(page: Page, app_url: str):
    saved = False
    materialized_sources = 0
    refreshed_at = None
    jobs = {
        "save-job": ["queued", "running", "complete"],
        "refresh-job": ["queued", "running", "complete"],
        "failed-job": ["queued", "failed"],
    }
    job_calls = {key: 0 for key in jobs}
    save_posts = []
    refresh_posts = []
    loaded_refs = []
    sources_ref = {"kind": "aurora", "resource_id": "fixture", "table": "person"}
    snapshot_id = "a" * 32

    def fulfill(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", json=body)

    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True,
        "sources": [{"kind": "aurora", "id": "fixture", "label": "Fixture"}],
        "catalogs_pending": False,
    }))
    page.route("**/api/workflows**", lambda route: fulfill(route, {
        "available": False, "jobs": [], "running_count": 0,
    }))
    page.route("**/api/tables?**", lambda route: fulfill(route, [
        {"name": "person", "schema": "public", "table": "person", "detail": "1 row"},
    ]))

    def list_views(route):
        rows = ([{"name": "people joins", "materialized_sources": materialized_sources,
                 "refreshed_at": refreshed_at, "refresh_mode": "blocking"}] if saved else [])
        fulfill(route, {"views": [{**row, "kind": "aurora", "resource_id": "fixture", "store_label": "Fixture"} for row in rows], "unavailable": []})

    page.route("**/api/views/all", list_views)

    def open_dataset(route):
        body = route.request.post_data_json
        if body.get("source_ref", {}).get("kind") == "materialized":
            loaded_refs.append(body["source_ref"])
            fulfill(route, {"dataset_id": f"snapshot-{len(loaded_refs)}",
                            "source": "Fixture / people snapshot", "rows": 1,
                            "columns": [{"name": "person_id", "dtype": "int64",
                                         "filter_kind": "none"}],
                            "source_ref": body["source_ref"],
                            "query_scope": "database"})
        else:
            fulfill(route, {"dataset_id": "live-person", "source": "Fixture / person",
                            "rows": 1, "columns": [{"name": "person_id", "dtype": "int64",
                                                     "filter_kind": "none"}],
                            "source_ref": sources_ref, "query_scope": "database"})

    page.route("**/api/datasets/open", open_dataset)
    page.route("**/api/datasets/*/query", lambda route: fulfill(route, {
        "total": 1, "filtered": 1, "scope": "database", "sampled": False,
        "charts": [], "rows": {"page": 0, "page_size": 50,
                                  "columns": ["person_id"], "data": [[1]]},
    }))

    def save_view(route):
        nonlocal saved
        save_posts.append(route.request.post_data_json)
        saved = True
        fulfill(route, {"name": "people joins", "job_id": "save-job", "status": "queued"})

    page.route("**/api/views", save_view)

    def refresh_view(route):
        refresh_posts.append(route.request.post_data_json)
        job_id = ["refresh-job", "failed-job"][len(refresh_posts) - 1]
        fulfill(route, {"name": "people joins", "job_id": job_id, "status": "queued",
                        "completed_sources": 0, "total_sources": 1})

    page.route("**/api/views/refresh", refresh_view)

    def view_job(route):
        nonlocal materialized_sources, refreshed_at
        job_id = route.request.url.rsplit("/", 1)[-1]
        states = jobs[job_id]
        index = min(job_calls[job_id], len(states) - 1)
        job_calls[job_id] += 1
        status = states[index]
        if status == "complete":
            materialized_sources = 1
            refreshed_at = f"2026-10-23T12:0{len(refresh_posts)}:00Z"
        if job_id == "failed-job" and status == "failed":
            fulfill(route, {"job_id": job_id, "status": status, "name": "people joins",
                            "completed_sources": 0, "total_sources": 1,
                            "error": "Aurora is unavailable"})
        else:
            fulfill(route, {"job_id": job_id, "status": status, "name": "people joins",
                            "completed_sources": int(status == "complete"),
                            "total_sources": 1})

    page.route("**/api/views/jobs/**", view_job)

    page.route("**/api/views/one?**", lambda route: fulfill(route, {
        "version": 2, "active": 0,
        "datasets": [{"source": {"kind": "materialized", "resource_id": "fixture",
                                    "materialized_id": snapshot_id},
                      "title": "People snapshot", "filters": [], "charts": [],
                      "cohorts": [], "entity_column": "person_id"}],
    }))

    page.goto(app_url)
    page.get_by_label("Source type", exact=True).select_option("aurora")
    source_picker = page.get_by_label("Datasource", exact=True)
    expect(source_picker.locator("option", has_text="Fixture")).to_be_attached(timeout=10000)
    source_picker.select_option("aurora:fixture")
    expect(page.get_by_label("Table", exact=True)).to_be_enabled(timeout=10000)
    page.get_by_label("Table", exact=True).select_option("person")
    page.get_by_role("button", name="Load table").click()
    expect(page.locator(".tab", has_text="person")).to_be_visible(timeout=10000)
    name_input = page.get_by_placeholder("name this view (1 tab)")
    name_input.fill("people joins")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.locator(".sidebar").get_by_text(
        "Building snapshot for people joins…", exact=True)).to_be_visible(timeout=10000)
    expect(page.get_by_role("button", name="Save", exact=True)).to_be_disabled()
    expect(page.locator(".sidebar").get_by_text(
        "Snapshot ready for people joins.", exact=True)).to_be_visible(timeout=10000)
    expect(page.locator(".view-row")).to_contain_text("Snapshot · 1 source")
    expect(page.locator(".view-row")).to_contain_text("Refresh can pause queries")
    assert len(save_posts) == 1
    assert loaded_refs == [{"kind": "materialized", "resource_id": "fixture",
                            "materialized_id": snapshot_id}]

    refresh_button = page.get_by_role("button", name="Refresh saved data for people joins from Fixture")
    refresh_button.click()
    expect(refresh_button).to_be_disabled()
    expect(page.locator(".view-row")).to_contain_text("Refreshing — queries may wait")
    expect(page.locator(".sidebar").get_by_text(
        "Snapshot ready for people joins.", exact=True)).to_be_visible(timeout=10000)
    assert len(refresh_posts) == 1
    assert len(loaded_refs) == 2

    refresh_button = page.get_by_role("button", name="Refresh saved data for people joins from Fixture")
    refresh_button.click()
    expect(page.locator(".sidebar").get_by_text(
        "Snapshot failed: Aurora is unavailable", exact=True)).to_be_visible(timeout=10000)
    expect(page.locator(".view-row")).to_contain_text("Snapshot · 1 source")
    assert len(refresh_posts) == 2
    assert len(loaded_refs) == 2
