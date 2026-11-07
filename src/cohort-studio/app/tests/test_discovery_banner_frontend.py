from datetime import datetime, timedelta, timezone

from playwright.sync_api import expect
from tests.test_e2e import app_url
from tests.ui_helpers import open_data_builder

SOURCES = [{"kind": "aurora", "id": "omop", "label": "omop · Aurora"}]
NO_WORKSPACE = ("The Workbench CLI has no workspace set on the app VM; "
                "run `wb workspace set --id=ws-123`.")


def _ago(minutes):
    at = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    return at.isoformat().replace("+00:00", "Z")


def _mock(page, discovery_states, refresh_calls):
    """Serve /api/datasources from `discovery_states` (last one repeats)."""
    served = []

    def datasources(route):
        state = discovery_states[min(len(served), len(discovery_states) - 1)]
        served.append(state)
        body = {"ready": True, "sources": SOURCES, "catalogs_pending": False}
        if state is not None:
            body["discovery"] = state
        route.fulfill(json=body)

    def refresh(route):
        refresh_calls.append(route.request.method)
        route.fulfill(json={"started": True, "discovery": {
            "status": "refreshing", "from_cache": True, "updated_at": _ago(42),
            "error": NO_WORKSPACE, "error_code": "no_workspace"}})

    page.route("**/api/datasources", datasources)
    page.route("**/api/datasources/refresh", refresh)
    page.route("**/api/views/all", lambda r: r.fulfill(
        json={"views": [], "pending": [], "unavailable": []}))
    return served


def test_stale_discovery_shows_banner_and_retry_posts_refresh(page, app_url):
    refresh_calls = []
    stale = {"status": "stale", "from_cache": True, "updated_at": _ago(42),
             "error": NO_WORKSPACE, "error_code": "no_workspace"}
    served = _mock(page, [stale], refresh_calls)
    page.goto(app_url)
    open_data_builder(page)   # datasource status sits in Connections

    banner = page.get_by_role("status").filter(has_text="Showing datasources from")
    expect(banner).to_be_visible(timeout=15000)
    expect(banner).to_contain_text("42 minutes ago")
    expect(banner).to_contain_text("wb workspace set --id=ws-123")
    # The cached list stays usable underneath the banner.
    expect(page.get_by_text("1 available")).to_be_visible()

    before = len(served)
    banner.get_by_role("button", name="Retry").click()
    for _ in range(20):
        if refresh_calls and len(served) > before:
            break
        page.wait_for_timeout(100)
    assert refresh_calls == ["POST"]
    # Retrying re-polls the list straight away (well inside the 3 s interval).
    assert len(served) > before


def test_failed_partial_kind_message_and_refreshing_status(page, app_url):
    refresh_calls = []
    partial = {"status": "stale", "from_cache": False, "updated_at": _ago(3),
               "failed_kinds": ["bq"], "error_code": "partial",
               "error": "BigQuery resources could not be listed (the CLI listing failed); "
                        "showing the other sources."}
    refreshing = {"status": "refreshing", "from_cache": True, "updated_at": _ago(3)}
    _mock(page, [refreshing, refreshing, partial], refresh_calls)
    page.goto(app_url)
    open_data_builder(page)   # datasource status sits in Connections
    expect(page.get_by_role("status").filter(has_text="Refreshing datasources…")
           ).to_be_visible(timeout=15000)
    banner = page.get_by_role("status").filter(has_text="BigQuery resources could not be listed")
    expect(banner).to_be_visible(timeout=15000)
    expect(banner).to_contain_text("3 minutes ago")


def test_failed_without_cache_shows_failure_banner(page, app_url):
    failed = {"status": "failed", "from_cache": False, "updated_at": None,
              "error": "The Workbench CLI login on the app VM has expired; "
                       "run `wb auth login` there, then retry.", "error_code": "auth"}
    page.route("**/api/datasources", lambda r: r.fulfill(json={
        "ready": True, "sources": [], "catalogs_pending": False, "discovery": failed}))
    page.route("**/api/views/all", lambda r: r.fulfill(
        json={"views": [], "pending": [], "unavailable": []}))
    page.goto(app_url)
    open_data_builder(page)   # datasource status sits in Connections
    banner = page.locator(".discovery-banner")
    expect(banner).to_contain_text("Workspace datasources could not be listed", timeout=15000)
    expect(banner).to_contain_text("wb auth login")
    expect(banner.get_by_role("button", name="Retry")).to_be_visible()


def test_fresh_or_absent_discovery_shows_no_banner(page, app_url):
    refresh_calls = []
    fresh = {"status": "fresh", "from_cache": False, "updated_at": _ago(0)}
    served = _mock(page, [fresh], refresh_calls)
    page.goto(app_url)
    open_data_builder(page)   # datasource status sits in Connections
    expect(page.get_by_text("1 available")).to_be_visible(timeout=15000)
    page.wait_for_timeout(500)
    expect(page.locator(".discovery-banner")).to_have_count(0)
    expect(page.locator(".discovery-status")).to_have_count(0)
    # Settled: polling stops after the first answer.
    page.wait_for_timeout(3500)
    assert len(served) == 1
    assert refresh_calls == []


def test_older_server_without_discovery_field_shows_no_banner(page, app_url):
    _mock(page, [None], [])
    page.goto(app_url)
    open_data_builder(page)   # datasource status sits in Connections
    expect(page.get_by_text("1 available")).to_be_visible(timeout=15000)
    expect(page.locator(".discovery-banner")).to_have_count(0)
