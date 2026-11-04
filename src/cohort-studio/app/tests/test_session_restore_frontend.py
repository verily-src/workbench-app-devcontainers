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
