import pytest
from playwright.sync_api import expect
from tests.test_e2e import app_url
from tests.test_table_info_progress_frontend import _mock_app, COLUMNS

pytestmark = pytest.mark.e2e


def _routes(page, opens):
    reply = _mock_app(page)

    def open_job(route):
        body = route.request.post_data_json
        opens.append(body)
        ref = body.get("source_ref") or {"kind": "aurora", "resource_id": "omop", "schema": "cms", "table": "cost"}
        reply(route, {"job_id": f"j{len(opens)}", "kind": "open", "status": "complete", "result": {
            "dataset_id": f"ds{len(opens)}", "source": "omop / cms.cost", "rows": 2, "columns": COLUMNS,
            "query_scope": "database", "source_ref": ref}})
    page.route('**/api/data-jobs/open', open_job)
    page.route('**/api/datasets/*/query', lambda r: reply(r, {
        'total': 2, 'filtered': 2, 'scope': 'database', 'sampled': False, 'entity': None, 'cache': None,
        'charts': [], 'rows': {'page': 0, 'page_size': 50, 'columns': ['person_id', 'cost'], 'data': [[1, 2]]}}))


def test_open_tabs_can_be_restored_after_reload(page, app_url):
    opens = []
    _routes(page, opens)
    page.goto(app_url)
    page.get_by_label('Source type', exact=True).select_option('aurora')
    page.get_by_label('Datasource', exact=True).select_option('aurora:omop')
    page.get_by_label('Schema', exact=True).select_option('cms')
    page.get_by_label('Table', exact=True).select_option('cms.cost')
    page.get_by_role('button', name='Load table', exact=True).click()
    expect(page.locator('.dataset-toolbar')).to_be_visible(timeout=10000)
    page.wait_for_timeout(1200)                       # autosave debounce

    page.reload()
    banner = page.locator('.session-restore')
    expect(banner).to_contain_text('Your last session had 1 tab', timeout=10000)
    page.get_by_role('button', name='Restore last session').click()
    expect(page.locator('.tab.active')).to_contain_text('cost', timeout=10000)
    assert opens[-1]['source_ref']['table'] == 'cost'
    expect(banner).to_have_count(0)


def test_dismissed_session_is_not_offered_again(page, app_url):
    opens = []
    _routes(page, opens)
    page.goto(app_url)
    page.evaluate("""() => localStorage.setItem('studio-session-v1:' + location.pathname, JSON.stringify({
        savedAt: new Date().toISOString(), active: 0, skipped: 1,
        datasets: [{source: {kind: 'aurora', resource_id: 'omop', schema: 'cms', table: 'cost'},
                    title: 'cms.cost', filters: [], charts: [], cohorts: []}]}))""")
    page.reload()
    banner = page.locator('.session-restore')
    expect(banner).to_contain_text("1 uploaded file can't be reopened", timeout=10000)
    page.get_by_role('button', name='Dismiss', exact=True).click()
    expect(banner).to_have_count(0)
    page.reload()
    page.wait_for_timeout(800)
    expect(banner).to_have_count(0)


def test_restore_respects_two_job_limit_and_keeps_partial_results(page, app_url):
    reply = _mock_app(page)
    state = {"active": 0, "peak": 0, "n": 0, "jobs": {}}

    def open_job(route):
        ref = route.request.post_data_json["source_ref"]
        if state["active"] >= 2:
            reply(route, {"detail": "Two data jobs are already active for this session."}, status=429)
            return
        state["active"] += 1
        state["peak"] = max(state["peak"], state["active"])
        state["n"] += 1
        job_id = f"r{state['n']}"
        state["jobs"][job_id] = ref
        reply(route, {"job_id": job_id, "kind": "open", "status": "running"})

    def poll(route):
        job_id = route.request.url.rsplit("/", 1)[-1]
        ref = state["jobs"].get(job_id)
        if ref is None:
            route.fallback()
            return
        state["active"] -= 1
        del state["jobs"][job_id]
        if ref["table"] == "broken":
            reply(route, {"job_id": job_id, "kind": "open", "status": "failed",
                          "error": "relation does not exist", "status_code": 400})
            return
        reply(route, {"job_id": job_id, "kind": "open", "status": "complete", "result": {
            "dataset_id": f"ds-{ref['table']}", "source": f"omop / cms.{ref['table']}", "rows": 2,
            "columns": COLUMNS, "query_scope": "database", "source_ref": ref}})
    page.route('**/api/data-jobs/open', open_job)
    page.route('**/api/data-jobs/r*', poll)
    page.route('**/api/datasets/*/query', lambda r: reply(r, {
        'total': 2, 'filtered': 2, 'scope': 'database', 'sampled': False, 'entity': None, 'cache': None,
        'charts': [], 'rows': {'page': 0, 'page_size': 50, 'columns': ['person_id', 'cost'], 'data': [[1, 2]]}}))
    page.goto(app_url)
    page.evaluate("""() => localStorage.setItem('studio-session-v1:' + location.pathname, JSON.stringify({
        savedAt: new Date().toISOString(), active: 2, skipped: 0,
        datasets: ['person', 'cost', 'drug', 'broken'].map(t => ({
          source: {kind: 'aurora', resource_id: 'omop', schema: 'cms', table: t},
          title: 'cms.' + t, filters: [], charts: [], cohorts: []}))}))""")
    page.reload()
    page.get_by_role('button', name='Restore last session').click()
    expect(page.locator('.tab')).to_have_count(3, timeout=10000)
    expect(page.locator('.tab.active')).to_contain_text('drug')
    expect(page.get_by_text("1 of 4 tab(s) could not be reopened", exact=False)).to_be_visible()
    assert state["peak"] <= 2
