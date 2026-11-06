"""With AI features off (the default outside the test suite), the Agent tab,
Ask AI, chat, the assistant tutorial steps and the AI settings are hidden."""
import re

import pytest
from playwright.sync_api import expect

import config
from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e


def test_ai_features_default_off(monkeypatch):
    monkeypatch.delenv("STUDIO_AI_FEATURES", raising=False)
    assert config.ai_features_enabled() is False
    monkeypatch.setenv("STUDIO_AI_FEATURES", "on")
    assert config.ai_features_enabled() is True
    monkeypatch.delenv("STUDIO_LINEAGE_UI", raising=False)
    assert config.lineage_ui_enabled() is False
    monkeypatch.delenv("STUDIO_PLINK_UI", raising=False)
    assert config.plink_ui_enabled() is False


def _fulfill(route, body):
    route.fulfill(status=200, content_type="application/json", json=body)


def _setup(page, ai):
    def cfg(route):
        if route.request.method != "GET":
            route.continue_()
            return
        body = route.fetch().json()
        body["features"] = {"ai": ai, "lineage": ai, "plink": ai}
        _fulfill(route, body)
    page.route("**/api/config", cfg)
    page.route("**/api/datasources", lambda route: _fulfill(route, {
        "ready": True, "sources": [{"kind": "aurora", "id": "clinical", "label": "Clinical"}],
        "catalogs_pending": False}))
    page.route("**/api/workflows**", lambda route: _fulfill(route, {
        "available": False, "jobs": [], "running_count": 0}))
    page.route("**/api/views/all", lambda route: _fulfill(route, {"views": [], "unavailable": []}))
    page.route("**/api/tables?**", lambda route: _fulfill(route, [
        {"name": "public.person", "schema": "public", "table": "person", "detail": "table"}]))

    def open_dataset(route):
        source = route.request.post_data_json["source_ref"]
        _fulfill(route, {"job_id": "open-1", "kind": "open", "status": "complete",
                         "result": {"dataset_id": "db-person", "source": "person",
                                    "source_ref": source, "rows": 2, "query_scope": "database",
                                    "columns": [{"name": "person_id", "dtype": "int64",
                                                 "filter_kind": "none"}]}})
    page.route("**/api/data-jobs/open", open_dataset)
    page.route("**/api/datasets/*/query", lambda route: _fulfill(route, {
        "total": 2, "filtered": 2, "scope": "database", "sampled": False, "charts": [],
        "rows": {"page": 0, "page_size": 50, "columns": ["person_id"], "data": [[1], [2]]}}))


def _load_person(page, app_url):
    page.goto(app_url)
    page.get_by_label("Source type").select_option("aurora")
    page.get_by_label("Datasource").select_option("aurora:clinical")
    page.get_by_label("Schema").select_option("public")
    page.get_by_label("Table", exact=True).select_option("public.person")
    page.get_by_role("button", name="Load table").click()
    expect(page.locator(".tab.active")).to_contain_text("person")


def test_ai_features_hidden_when_off(page, app_url):
    _setup(page, ai=False)
    _load_person(page, app_url)
    nav = page.locator(".topnav")
    expect(nav).to_contain_text("Data Builder")
    expect(nav.locator(".topnav-link")).to_have_text(
        ["Explore Cohort", "Data Builder", "Workflows"])
    expect(page.locator(".ask-ai")).to_have_count(0)
    expect(page.get_by_placeholder(re.compile("Ask AI|Ask the assistant"))).to_have_count(0)
    # PLINK 2 export is hidden from the Export menu.
    page.get_by_role("button", name="Export options").click()
    expect(page.get_by_role("button", name="Export PDF")).to_be_visible()
    expect(page.get_by_role("button", name="Export PLINK 2")).to_have_count(0)
    page.keyboard.press("Escape")

    # Settings, Tutorial and ⌘K sit in the bottom-left corner, not in the tabs.
    tools = page.get_by_role("toolbar", name="App tools")
    settings = tools.get_by_role("button", name="Settings", exact=True)
    box = settings.bounding_box()
    assert box["x"] < 320 and box["y"] > page.viewport_size["height"] - 80, box
    expect(tools.get_by_role("button", name="Tutorial")).to_be_visible()
    expect(tools.get_by_role("button", name="Command palette")).to_be_visible()
    settings.click()
    # On Settings (no sidebar) the tools move to a slim left rail, still bottom-left.
    settings = page.get_by_role("toolbar", name="App tools").get_by_role("button", name="Settings")
    expect(settings).to_have_attribute("aria-pressed", "true")
    box = settings.bounding_box()
    assert box["x"] < 60 and box["y"] > page.viewport_size["height"] - 80, box
    expect(page.locator(".section-label", has_text="Appearance")).to_be_visible(timeout=10000)
    for label in ("AI model", "Jev join recommendations", "Agent", "MCP server (this app)",
                  "Other MCP connections"):
        expect(page.locator(".section-label").filter(
            has_text=re.compile(f"^{re.escape(label)}$"))).to_have_count(0)

    # The assistant and Agent steps are left out: 6 of the 8 steps remain.
    page.get_by_role("button", name="Tutorial").click()
    expect(page.locator(".tutorial-count")).to_have_text("Step 1 of 6")
    for _ in range(5):
        expect(page.locator("#tutorial-text")).not_to_contain_text("Agent")
        page.get_by_role("button", name="Skip step").or_(
            page.get_by_role("button", name="Next")).first.click()
    expect(page.locator(".tutorial-count")).to_have_text("Step 6 of 6")
    expect(page.locator("#tutorial-text")).to_contain_text("Open Workflows to see each run's status")


def test_ai_features_shown_when_on(page, app_url):
    _setup(page, ai=True)
    _load_person(page, app_url)
    expect(page.locator(".topnav .topnav-link").filter(has_text=re.compile(r"^Agent$"))).to_have_count(1)
    expect(page.locator(".ask-ai")).to_have_count(1)
    page.get_by_role("button", name="Export options").click()
    expect(page.get_by_role("button", name="Export PLINK 2")).to_be_visible()
    expect(page.locator(".topnav .topnav-link").filter(has_text=re.compile(r"^Lineage$"))).to_have_count(1)
