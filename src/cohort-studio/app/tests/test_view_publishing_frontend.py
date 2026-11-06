import copy
import json
import re
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Page, expect

from tests.test_e2e import app_url  # noqa: F401

pytestmark = pytest.mark.e2e

NAME = "Liver report"


def _state(title):
    return {"version": 2, "active": 0, "datasets": [{
        "source": {"kind": "aurora", "resource_id": "db-main", "table": "person"},
        "title": title, "filters": [], "charts": [], "cohorts": [], "parameters": []}]}


def test_publish_viewer_link_republish_and_rollback(page: Page, app_url: str):
    store = {"draft": _state("Report v1"), "revisions": []}
    calls = []

    def fulfill(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", json=body)

    def listing():
        revisions = store["revisions"]
        latest = revisions[-1] if revisions else None
        return {"views": [{
            "name": NAME, "kind": "aurora", "resource_id": "db-main",
            "store_label": "Clinical database", "materialized_sources": 0, "refreshed_at": None,
            "published_revision": latest["revision"] if latest else None,
            "published_at": latest["published_at"] if latest else None,
            "draft_changed": (latest["state"] != store["draft"]) if latest else None,
        }], "unavailable": [], "pending": []}

    def meta(rev):
        return {key: rev[key] for key in
                ("name", "revision", "published_at", "published_by", "note")}

    def views_api(route):
        request = route.request
        url = urlparse(request.url)
        params = {key: values[0] for key, values in parse_qs(url.query).items()}
        path = url.path
        calls.append((request.method, path, params))
        if path.endswith("/api/views/all"):
            return fulfill(route, listing())
        if path.endswith("/api/views/one"):
            return fulfill(route, store["draft"])
        if path.endswith("/api/views") and request.method == "POST":
            body = request.post_data_json
            store["draft"] = {"version": 2, "active": body["active"], "datasets": [{
                key: dataset.get(key) for key in
                ("source", "title", "filters", "charts", "cohorts", "parameters")}
                for dataset in body["datasets"]]}
            return fulfill(route, {"name": body["name"]})
        if path.endswith("/api/views/publish"):
            body = request.post_data_json
            rev = {"name": NAME, "revision": len(store["revisions"]) + 1,
                   "published_at": f"2026-11-0{len(store['revisions']) + 1}T10:00:00+00:00",
                   "published_by": "analyst@example.org", "note": body.get("note"),
                   "state": copy.deepcopy(store["draft"])}
            store["revisions"].append(rev)
            return fulfill(route, meta(rev))
        if path.endswith("/api/views/revisions"):
            return fulfill(route, {"revisions": [meta(rev) for rev in reversed(store["revisions"])]})
        if path.endswith("/api/views/revision"):
            number = int(params.get("revision") or len(store["revisions"]))
            rev = store["revisions"][number - 1]
            return fulfill(route, {**rev["state"], "published": meta(rev)})
        if path.endswith("/api/views/rollback"):
            number = request.post_data_json["revision"]
            store["draft"] = copy.deepcopy(store["revisions"][number - 1]["state"])
            return fulfill(route, {"name": NAME, "revision": number})
        return fulfill(route, {"detail": "unexpected"}, 500)

    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True, "catalogs_pending": False,
        "sources": [{"kind": "aurora", "id": "db-main", "label": "Clinical database"}]}))
    page.route("**/api/workflows**", lambda route: fulfill(route, {
        "available": False, "jobs": [], "running_count": 0}))
    page.route(re.compile(r".*/api/views(/[a-z]+)?(\?.*)?$"), views_api)
    page.route("**/api/data-jobs/open", lambda route: fulfill(route, {
        "job_id": "open", "status": "complete", "result": {
            "dataset_id": "report-ds", "source": "person", "rows": 2, "columns": [],
            "source_ref": route.request.post_data_json["source_ref"], "query_scope": "loaded"}}))
    page.route("**/api/datasets/report-ds/query", lambda route: fulfill(route, {
        "total": 2, "filtered": 2, "scope": "loaded", "charts": [],
        "rows": {"page": 0, "page_size": 50, "columns": [], "data": []}}))
    page.on("dialog", lambda dialog: dialog.accept())
    page.goto(app_url)
    page.evaluate("""() => Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: async (text) => { window.__copied = text; } },
    })""")

    row = page.locator(".view-row").filter(has_text=NAME)
    expect(row.get_by_text("Draft · not published")).to_be_visible(timeout=15000)

    def open_versions():
        toggle = row.get_by_role("button", name=f"Versions of {NAME} from Clinical database")
        if toggle.get_attribute("aria-expanded") != "true":
            toggle.click()

    open_versions()
    versions = page.get_by_role("group", name=f"Versions of {NAME}")
    expect(versions.get_by_text("No published revisions.")).to_be_visible()
    versions.get_by_label(f"Publish note for {NAME}").fill("Approved by review board")
    versions.get_by_role("button", name="Publish", exact=True).click()
    expect(row.get_by_text("Published rev 1", exact=True)).to_be_visible()
    expect(versions.get_by_text("Approved by review board")).to_be_visible()

    versions.get_by_role("button", name=f"Copy published link for {NAME}").click()
    link = page.evaluate("window.__copied")
    assert link.endswith("#view=aurora:db-main:Liver%20report&published")

    page.goto(link)
    page.reload()
    banner = page.get_by_role("status", name="Published view")
    expect(banner).to_contain_text("Published · rev 1")
    expect(banner).to_contain_text("Approved by review board")
    expect(page.locator(".tab.active")).to_contain_text("Report v1")
    assert any(path.endswith("/api/views/revision") and "revision" not in params
               for _, path, params in calls)
    expect(page.get_by_label("Saved view name")).to_have_count(0)
    expect(page.locator(".topnav-link").filter(has_text="Data Builder")).to_have_count(0)
    expect(page.locator(".tab-join")).to_have_count(0)
    expect(page.get_by_role("button", name=f"Delete {NAME} from Clinical database")).to_have_count(0)
    expect(page.get_by_text("Filters", exact=True)).to_be_visible()
    open_versions()
    expect(versions.get_by_role("button", name=re.compile("^Publish"))).to_have_count(0)
    expect(versions.get_by_role("button", name=re.compile("^Roll back"))).to_have_count(0)
    expect(versions.get_by_role("button", name=f"Open rev 1 of {NAME}")).to_be_visible()

    banner.get_by_role("button", name="Open draft").click()
    expect(banner).to_have_count(0)
    assert page.evaluate("location.hash") == "#view=aurora:db-main:Liver%20report"
    expect(page.get_by_label("Saved view name")).to_be_visible()
    expect(page.locator(".topnav-link").filter(has_text="Data Builder")).to_have_count(1)

    page.get_by_role("button", name="Rename Report v1").click()
    page.get_by_label("Name for Report v1").fill("Report v2")
    page.get_by_role("button", name="Save tab name").click()
    page.get_by_label("Saved view name").fill(NAME)
    page.locator(".view-save").get_by_role("button", name="Save", exact=True).click()
    expect(row.get_by_text("Published rev 1 · draft has changes")).to_be_visible()
    assert store["revisions"][0]["state"]["datasets"][0]["title"] == "Report v1"

    open_versions()
    versions.get_by_role("button", name="Publish rev 2").click()
    expect(row.get_by_text("Published rev 2", exact=True)).to_be_visible()
    expect(versions.locator(".view-revisions li")).to_have_count(2)

    versions.get_by_role("button", name=f"Roll back draft of {NAME} to rev 1").click()
    expect(page.get_by_text(f"Draft of {NAME} rolled back to rev 1.")).to_be_visible()
    expect(page.locator(".tab.active")).to_contain_text("Report v1")
    expect(row.get_by_text("Published rev 2 · draft has changes")).to_be_visible()
    assert json.dumps(store["draft"]) == json.dumps(store["revisions"][0]["state"])

    versions.get_by_role("button", name=f"Open rev 2 of {NAME}").click()
    expect(banner).to_contain_text("Published · rev 2")
    expect(page.locator(".tab.active")).to_contain_text("Report v2")
    expect(page.get_by_label("Saved view name")).to_have_count(0)
