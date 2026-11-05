"""Group summary "Open as table" and summary persistence in saved views (browser)."""
import json
import re

import pytest
from playwright.sync_api import expect

from tests.test_e2e import app_url, loaded_page

pytestmark = pytest.mark.e2e


def test_open_summary_as_table_with_real_backend(loaded_page):
    page = loaded_page
    page.get_by_role('button', name='+ Group summary').click()
    panel = page.get_by_role('region', name='Group summary')
    open_table = panel.get_by_role('button', name='Open as table')
    expect(open_table).to_be_disabled()
    panel.get_by_label('Group by').select_option('tissue')
    panel.get_by_role('button', name='Summarize').click()
    expect(panel.get_by_role('status')).to_contain_text('100 filtered rows · 4 groups', timeout=15000)
    open_table.click()
    tab = page.locator('.tab.active')
    expect(tab).to_contain_text('Group summary (tissue)', timeout=15000)
    expect(page.locator('.hero .count')).to_have_text('4', timeout=15000)
    table = page.locator('.data-table').first
    expect(table.get_by_role('columnheader', name='Rows')).to_be_visible()
    expect(table.locator('tbody tr')).to_have_count(4)
    expect(table.locator('tbody tr', has_text='liver')).to_contain_text('25')
    # The new tab is a regular dataset: its own summary panel works on the groups.
    page.get_by_role('button', name='+ Group summary').click()
    inner = page.get_by_role('region', name='Group summary')
    inner.get_by_label('Group by').select_option('Rows')
    inner.get_by_role('button', name='Summarize').click()
    expect(inner.get_by_role('status')).to_contain_text('4 filtered rows · 1 group', timeout=15000)


def test_summary_table_saves_and_reopens_with_the_view(page, app_url):
    base_source = {'kind': 'aurora', 'resource_id': 'db1', 'table': 'people'}
    summary_source = {'kind': 'group_summary', 'base': base_source, 'spec': {'group_by': ['tissue'], 'measure': 'value'},
                      'filters': [{'column': 'tissue', 'kind': 'categorical', 'values': ['liver', 'lung']}]}
    base_columns = [{'name': 'tissue', 'dtype': 'object', 'filter_kind': 'categorical', 'values': ['liver', 'lung', 'skin']},
                    {'name': 'value', 'dtype': 'float64', 'filter_kind': 'range', 'min': 1, 'max': 9}]
    summary_columns = [{'name': 'tissue', 'dtype': 'object', 'filter_kind': 'categorical', 'values': ['liver', 'lung']},
                       {'name': 'Rows', 'dtype': 'int64', 'filter_kind': 'range', 'min': 2, 'max': 3}]
    summaries, materialized, opened_refs, saves = [], [], [], []

    def ok(route, data):
        route.fulfill(status=200, content_type='application/json', json=data)

    def base_result():
        return {'dataset_id': 'base-ds', 'source': 'db1 / people', 'rows': 9, 'columns': base_columns,
                'source_ref': base_source, 'query_scope': 'database'}

    def summary_result():
        return {'dataset_id': 'sum-ds', 'source': 'db1 / people · Group summary (tissue)', 'rows': 2,
                'columns': summary_columns, 'source_ref': summary_source, 'query_scope': 'loaded'}

    page.route('**/api/datasources', lambda r: ok(r, {'ready': True, 'sources': [{'kind': 'aurora', 'id': 'db1', 'label': 'Database'}], 'catalogs_pending': False}))
    page.route('**/api/workflows**', lambda r: ok(r, {'available': False, 'jobs': [], 'running_count': 0}))
    page.route('**/api/views/all', lambda r: ok(r, {'views': [{'name': 'people', 'kind': 'aurora', 'resource_id': 'db1', 'store_label': 'Database', 'materialized_sources': 0}], 'unavailable': []}))
    page.route('**/api/views/one?**', lambda r: ok(r, {'version': 2, 'active': saves[-1]['active'] if saves else 0,
        'datasets': saves[-1]['datasets'] if saves else [{'source': base_source, 'title': 'people', 'filters': [], 'charts': []}]}))

    def open_job(route):
        ref = route.request.post_data_json['source_ref']
        opened_refs.append(ref)
        ok(route, {'job_id': f'open-{len(opened_refs)}', 'kind': 'open', 'status': 'complete',
                   'result': summary_result() if ref['kind'] == 'group_summary' else base_result()})
    page.route('**/api/data-jobs/open', open_job)
    page.route('**/api/datasets/base-ds/query', lambda r: ok(r, {'total': 9, 'filtered': 6, 'scope': 'database', 'charts': [],
        'rows': {'page': 0, 'page_size': 50, 'columns': ['tissue', 'value'], 'data': [['liver', 1]]}}))
    page.route('**/api/datasets/sum-ds/query', lambda r: ok(r, {'total': 2, 'filtered': 2, 'scope': 'loaded', 'charts': [],
        'rows': {'page': 0, 'page_size': 50, 'columns': ['tissue', 'Rows'], 'data': [['liver', 3], ['lung', 3]]}}))

    def summarize(route):
        summaries.append(route.request.post_data_json)
        ok(route, {'columns': ['tissue', 'Rows', 'Numeric values', 'Sum', 'Mean', 'Minimum', 'Maximum'],
                   'rows': [['liver', 3, 3, 6, 2, 1, 3], ['lung', 3, 3, 9, 3, 2, 4]], 'total_groups': 2, 'input_rows': 6,
                   'page': 0, 'page_size': 50, 'scope': 'database', 'sampled': False})
    page.route('**/api/datasets/base-ds/summary', summarize)

    def materialize(route):
        materialized.append(route.request.post_data_json)
        ok(route, {**summary_result(), 'summary': {'total_groups': 2, 'input_rows': 6, 'scope': 'database',
                                                   'sampled': False, 'staged': False}})
    page.route('**/api/datasets/base-ds/summary/materialize', materialize)

    def save(route):
        saves.append(route.request.post_data_json)
        ok(route, {'name': 'people'})
    page.route('**/api/views', save)

    page.goto(app_url)
    page.get_by_role('button', name='people', exact=True).click(timeout=15000)
    expect(page.locator('.tab.active')).to_contain_text('people', timeout=15000)
    page.locator('.filter-group', has_text='tissue').locator('summary').click()
    page.locator('.filter-group', has_text='tissue').get_by_label('liver').check()
    page.locator('.filter-group', has_text='tissue').get_by_label('lung').check()
    page.get_by_role('button', name='+ Group summary').click()
    panel = page.get_by_role('region', name='Group summary')
    panel.get_by_label('Group by').select_option('tissue')
    panel.get_by_label('Value column').select_option('value')
    panel.get_by_role('button', name='Summarize').click()
    expect(panel.get_by_role('status')).to_contain_text('6 filtered rows · 2 groups · Full database', timeout=15000)

    panel.get_by_role('button', name='Open as table').click()
    expect(page.locator('.tab.active')).to_contain_text('people · Group summary (tissue)', timeout=15000)
    assert materialized == [{'group_by': ['tissue'], 'measure': 'value',
                             'filters': [{'column': 'tissue', 'kind': 'categorical', 'values': ['liver', 'lung']}]}]
    table = page.locator('.data-table').first
    expect(table.locator('tbody tr')).to_have_count(2)
    expect(table.locator('tbody tr').first).to_contain_text('liver')

    # Session restore keeps the panel recipe and the reproducible summary tab.
    page.wait_for_function("() => Object.keys(localStorage).some(k => k.startsWith('studio-session-v1:') && localStorage[k].includes('group_summary'))")
    session = json.loads(page.evaluate("() => localStorage[Object.keys(localStorage).find(k => k.startsWith('studio-session-v1:'))]"))
    assert session['datasets'][0]['group_summary'] == {'group_by': ['tissue'], 'measure': 'value'}
    assert session['datasets'][1]['source'] == summary_source

    page.get_by_label('Saved view name').fill('people')
    page.locator('.view-save').get_by_role('button', name='Save', exact=True).click()
    expect(page.get_by_text('Saved 2 tab(s) to Database.')).to_be_visible()
    assert saves[0]['datasets'][0]['group_summary'] == {'group_by': ['tissue'], 'measure': 'value'}
    assert saves[0]['datasets'][1]['source'] == summary_source

    # Reopen the saved view: both tabs come back and the base tab reruns its summary.
    page.reload()
    page.get_by_role('button', name='people', exact=True).click(timeout=15000)
    tabs = page.locator('.tab')
    expect(tabs).to_have_count(2, timeout=15000)
    expect(tabs.nth(1)).to_contain_text('Group summary (tissue)')
    assert opened_refs[-2:] == [base_source, summary_source] or opened_refs[-2:] == [summary_source, base_source]
    tabs.nth(0).click()
    panel = page.get_by_role('region', name='Group summary')
    expect(panel.get_by_role('status')).to_contain_text('6 filtered rows · 2 groups', timeout=15000)
    assert summaries[-1]['group_by'] == ['tissue'] and summaries[-1]['measure'] == 'value'
    assert summaries[-1]['filters'] == [{'column': 'tissue', 'kind': 'categorical', 'values': ['liver', 'lung']}]
    expect(panel.get_by_label('Value column')).to_have_value('value')

    # Close drops the recipe, so the next save does not reopen the panel.
    panel.get_by_role('button', name='Close').click()
    expect(page.get_by_role('region', name='Group summary')).to_have_count(0)
    page.get_by_label('Saved view name').fill('people')
    page.locator('.view-save').get_by_role('button', name='Save', exact=True).click()
    expect(page.get_by_text(re.compile('Saved 2 tab'))).to_be_visible()
    assert saves[-1]['datasets'][0]['group_summary'] is None
