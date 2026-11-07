import pytest
from playwright.sync_api import expect
from tests.test_e2e import app_url
from tests.ui_helpers import open_data_builder, pick_table

pytestmark = pytest.mark.e2e

COLUMNS = [
    {"name": "person_id", "dtype": "int64", "filter_kind": "none"},
    {"name": "cost", "dtype": "float64", "logical_type": "number",
     "filter_kind": "range", "min": 0, "max": 10},
]
TABLES = [
    {"name": "cms.cost", "schema": "cms", "table": "cost", "detail": "table",
     "rows": 32355293, "rows_estimated": True, "bytes": 6_550_000_000,
     "columns": 22, "analyzed": "2026-11-04T03:50:00+00:00"},
    {"name": "cms.person", "schema": "cms", "table": "person", "detail": "table",
     "rows": 100000, "rows_estimated": True, "bytes": 24_000_000, "columns": 18},
    {"name": "cms.v_people", "schema": "cms", "table": "v_people", "detail": "view",
     "columns": 4},
]


def _mock_app(page):
    def reply(route, value, status=200):
        route.fulfill(status=status, json=value)

    page.route('**/api/datasources', lambda r: reply(r, {
        'ready': True, 'sources': [{'kind': 'aurora', 'id': 'omop', 'label': 'OMOP'}]}))
    page.route('**/api/config', lambda r: reply(r, {'chart_palette': 'verily'}))
    page.route('**/api/workflows**', lambda r: reply(r, {'available': False, 'jobs': [], 'running_count': 0}))
    page.route('**/api/views/all', lambda r: reply(r, {'views': [], 'unavailable': [], 'pending': []}))
    page.route('**/api/tables?**', lambda r: reply(r, TABLES))
    page.route('**/api/omop/**', lambda r: reply(r, {'cdm': False, 'tables': []}))
    return reply


def test_table_details_running_card_and_completion_summary(page, app_url):
    reply = _mock_app(page)
    state = {'job_id': 'job1', 'kind': 'open', 'status': 'running',
             'label': 'cms.cost from omop', 'phase': 'Reading cms.cost from omop',
             'detail': {'resource': 'omop', 'table': 'cms.cost', 'cap': 100000},
             'started': 1, 'elapsed': 3.0}
    page.route('**/api/data-jobs/open', lambda r: reply(r, state))
    page.route('**/api/data-jobs/job1', lambda r: reply(r, state))
    page.route('**/api/datasets/ds1/query', lambda r: reply(r, {
        'total': 32355293, 'filtered': 32355293, 'scope': 'database', 'sampled': False,
        'entity': None, 'cache': None, 'charts': [],
        'rows': {'page': 0, 'page_size': 50, 'columns': ['person_id', 'cost'], 'data': [[1, 2.5]]}}))

    page.goto(app_url)
    canvas = open_data_builder(page)
    rows = canvas.get_by_role('group', name='Schema cms').locator('.jc-table-pick')
    expect(rows.nth(0)).to_have_attribute('title', 'cms.cost · table · ~32.4M rows · 6.1 GB · 22 cols')
    expect(rows.nth(2)).to_have_attribute('title', 'cms.v_people · view · 4 cols')

    card = pick_table(page, 'aurora:omop', 'cms.cost')
    details = card.get_by_label('Table details')
    expect(details).to_contain_text('Rows~32.4M')
    expect(details).to_contain_text('Size6.1 GB')
    expect(details).to_contain_text('Columns22')
    expect(details).to_contain_text('Stats as of')

    card.get_by_role('button', name='Open in Explore', exact=True).click()
    panel = page.get_by_role('region', name='Data operations')
    expect(panel).to_contain_text('Loading cms.cost from omop')
    expect(panel).to_contain_text('Reading cms.cost from omop')
    expect(panel).to_contain_text('Source: ~32.4M rows · 6.1 GB · 22 cols')
    expect(panel.get_by_label('Elapsed time')).to_have_text('3s')
    expect(panel.get_by_label('Elapsed time')).not_to_have_text('3s', timeout=4000)
    # The top bar no longer repeats "Loading …" while the card is visible.
    expect(page.locator('.topbar .activity')).to_have_count(0)

    state['phase'] = 'Profiling columns'
    state['detail'] = {**state['detail'], 'rows': 100000, 'columns': 2}
    expect(panel).to_contain_text('Profiling columns · 100K rows × 2 columns')
    page.screenshot(path='/private/tmp/cohort-table-load-progress.png')

    state.update({'status': 'complete', 'elapsed': 12.4, 'result': {
        'dataset_id': 'ds1', 'source': 'omop / cms.cost', 'rows': 100000,
        'columns': COLUMNS, 'query_scope': 'database'}})
    expect(panel).to_contain_text('Loaded cms.cost from omop')
    expect(panel).to_contain_text('100,000 rows in memory × 2 columns')
    expect(panel).to_contain_text('in 12s')
    expect(panel).to_contain_text('Filters and charts query the full table in the database')
    page.screenshot(path='/private/tmp/cohort-table-load-done.png')
    panel.get_by_role('button', name='Hide', exact=True).click()
    expect(panel).not_to_be_visible()


def test_join_job_card_shows_sources_engine_and_result(page, app_url):
    """Join progress travels through the same studio-data-job event api.join dispatches."""
    _mock_app(page)
    page.goto(app_url)
    expect(page.get_by_text('No data loaded')).to_be_visible(timeout=15000)
    running = {'job_id': 'join1', 'kind': 'join', 'status': 'running',
               'label': 'omop / cms.person + omop / genetics_demo.samples (inner on person_id)',
               'phase': 'Joining 2 tables inside the database (PostgreSQL)',
               'detail': {'engine': 'aurora', 'sources': 2}, 'started': 1, 'elapsed': 2.0}
    dispatch = ("job => window.dispatchEvent(new CustomEvent('studio-data-job', "
                "{detail: {id: job.job_id, job}}))")
    page.evaluate(dispatch, running)
    panel = page.get_by_role('region', name='Data operations')
    expect(panel).to_contain_text('Joining omop / cms.person + omop / genetics_demo.samples (inner on person_id)')
    expect(panel).to_contain_text('Joining 2 tables inside the database (PostgreSQL) · runs in the database')
    expect(panel.get_by_role('button', name='Cancel', exact=True)).to_be_enabled()
    page.evaluate(dispatch, {**running, 'phase': 'Building the joined tab',
                             'detail': {'engine': 'aurora', 'rows': 5000, 'columns': 9}})
    expect(panel).to_contain_text('Building the joined tab · 5,000 rows × 9 columns · runs in the database')
    page.screenshot(path='/private/tmp/cohort-join-progress.png')
    page.evaluate(dispatch, {**running, 'status': 'complete', 'elapsed': 6.2,
                             'result': {'dataset_id': 'j1', 'source': 'x', 'rows': 5000,
                                        'columns': [{'name': 'person_id'}] * 9,
                                        'query_scope': 'loaded'}})
    expect(panel).to_contain_text('Joined omop / cms.person')
    expect(panel).to_contain_text('5,000 rows × 9 columns')
    expect(panel).to_contain_text('in 6s')
