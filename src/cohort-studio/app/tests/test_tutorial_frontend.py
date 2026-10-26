import pytest
from playwright.sync_api import Page, expect

from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e


def test_tutorial_highlights_real_controls_and_waits_for_actions(page: Page, app_url: str):
    def fulfill(route, body):
        route.fulfill(status=200, content_type="application/json", json=body)

    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True, "catalogs_pending": False,
        "sources": [{"kind": "aurora", "id": "db-main", "label": "Clinical database"}],
    }))
    page.route("**/api/workflows**", lambda route: fulfill(route, {
        "available": False, "jobs": [], "running_count": 0,
    }))
    page.route("**/api/config", lambda route: fulfill(route, {"chart_palette": "verily"}))
    page.route("**/api/tables?**", lambda route: fulfill(route, [{
        "name": "public.person", "table": "person", "schema": "public", "detail": "10 rows",
    }]))
    page.route("**/api/views/all", lambda route: fulfill(route, {
        "views": [], "unavailable": [],
    }))

    def open_dataset(route):
        body = route.request.post_data_json
        source_ref = body["source_ref"]
        route.fulfill(status=200, content_type="application/json", json={"job_id":"tutorial-job", "kind":"open", "status":"complete", "result": {
            "dataset_id": "tutorial-person", "source": "db-main / person", "rows": 10,
            "columns": [{"name": "person_id", "filter_kind": "none"}],
            "source_ref": source_ref, "query_scope": "database",
        }})

    page.route("**/api/data-jobs/open", open_dataset)
    page.route("**/api/datasets/tutorial-person/query", lambda route: fulfill(route, {
        "total": 10, "filtered": 10, "scope": "database", "charts": [],
        "rows": {"page": 0, "page_size": 50, "columns": ["person_id"], "data": [[1]]},
    }))
    page.route("**/api/omop/db-main?**", lambda route: fulfill(route, {
        "cdm": False, "cdm_schema": None, "vocab_schema": None,
        "version": None, "tables": [],
    }))

    page.goto(app_url)
    trigger = page.get_by_role("button", name="Tutorial", exact=True)
    expect(trigger).to_be_visible(timeout=15000)
    page.get_by_role("button", name="Load data", exact=True).click()
    expect(page.get_by_label("Source type", exact=True)).to_be_focused()
    expect(page.get_by_label("Source type", exact=True)).to_contain_text("▤ Aurora")
    page.screenshot(path="/private/tmp/tutorial-empty-state.png")
    trigger.click()
    dialog = page.get_by_role("dialog", name="Choose a source")
    expect(dialog).to_be_visible()
    expect(page.locator(".tutorial-spotlight")).to_have_attribute(
        "data-target", "[aria-label='Source type']")
    expect(dialog.get_by_role("button", name="Next")).to_be_disabled()

    page.get_by_label("Source type").select_option("aurora")
    expect(page.locator(".tutorial-spotlight")).to_have_attribute(
        "data-target", "[aria-label='Datasource']")
    page.get_by_label("Datasource").select_option("aurora:db-main")
    expect(dialog.get_by_role("button", name="Next")).to_be_enabled()
    dialog.get_by_role("button", name="Next").click()

    dialog = page.get_by_role("dialog", name="Open a table")
    expect(dialog.get_by_role("button", name="Next")).to_be_disabled()
    page.get_by_label("Table", exact=True).select_option("public.person")
    page.get_by_role("button", name="Load table").click()
    expect(page.locator(".tab.active")).to_contain_text("person", timeout=10000)
    expect(dialog.get_by_role("button", name="Next")).to_be_enabled()
    dialog.get_by_role("button", name="Next").click()

    dialog = page.get_by_role("dialog", name="Build an OMOP cohort")
    expect(page.locator(".tutorial-spotlight")).to_have_attribute(
        "data-target", "[data-tutorial-target='omop-toggle']")
    page.get_by_role("button", name="OMOP", exact=True).click()
    expect(page.locator(".tutorial-spotlight")).to_have_attribute(
        "data-target", "[aria-label='OMOP cohort builder']")
    expect(dialog.get_by_role("button", name="Next")).to_be_disabled()
    page.keyboard.press("Alt+ArrowRight")
    expect(page.get_by_role("dialog", name="Build an OMOP cohort")).to_be_visible()
    page.keyboard.press("Alt+ArrowLeft")
    expect(page.get_by_role("dialog", name="Open a table")).to_be_visible()
    page.keyboard.press("Alt+ArrowRight")
    expect(page.get_by_role("dialog", name="Build an OMOP cohort")).to_be_visible()

    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(page.locator(".tutorial-spotlight")).to_have_count(0)
    expect(trigger).to_be_focused()


def test_tutorial_current_agent_and_workflow_navigation(page: Page, app_url: str):
    page.route('**/api/datasources', lambda route: route.fulfill(json={
        'ready': True, 'sources': [], 'catalogs_pending': False,
    }))
    page.route('**/api/config', lambda route: route.fulfill(json={'chart_palette': 'verily'}))
    page.route('**/api/workflows**', lambda route: route.fulfill(json={
        'available': False, 'jobs': [], 'running_count': 0,
    }))
    page.route('**/api/agent/chat/sessions**', lambda route: route.fulfill(json={'sessions': []}))
    page.route('**/api/agent/chat/history**', lambda route: route.fulfill(json={'messages': []}))
    page.add_init_script("localStorage.setItem('cohort-studio.tutorial.v2', JSON.stringify({version:2,step:6,dismissed:false}))")
    page.goto(app_url)
    page.get_by_role('button', name='Tutorial', exact=True).click()
    expect(page.get_by_role('dialog', name='Choose a source')).to_be_visible()
    for title in ['Choose a source', 'Open a table', 'Build an OMOP cohort',
                  'Open related tables', 'Join on matching keys', 'Check assistant settings']:
        dialog = page.get_by_role('dialog', name=title, exact=True)
        dialog.get_by_role('button', name='Skip step', exact=True).click()
    dialog = page.get_by_role('dialog', name='Open an Agent conversation')
    expect(dialog).to_contain_text('New chat')
    page.locator('[data-tutorial-target="nav-agent"]').click()
    expect(page.locator('.tutorial-spotlight')).to_have_attribute(
        'data-target', "[aria-label='Message the Studio Agent']")
    dialog.get_by_role('button', name='Next', exact=True).click()
    dialog = page.get_by_role('dialog', name='Review workflow runs')
    expect(dialog).to_contain_text('cohort-genetics-demo')
    expect(dialog.get_by_role('button', name='Finish')).to_be_disabled()
    page.locator('[data-tutorial-target="nav-workflows"]').click()
    dialog.get_by_role('button', name='Finish').click()
    expect(page.get_by_role('dialog')).to_have_count(0)
