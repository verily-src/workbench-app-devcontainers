import time

import pytest
from playwright.sync_api import expect
from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e


def test_table_listing_status_sits_by_the_picker_and_latest_source_wins(page, app_url):
    def reply(route, value):
        route.fulfill(status=200, json=value)
    page.route('**/api/datasources', lambda r: reply(r, {'ready': True, 'sources': [
        {'kind': 'aurora', 'id': 'slowdb', 'label': 'Slow DB'},
        {'kind': 'aurora', 'id': 'fastdb', 'label': 'Fast DB'}]}))
    page.route('**/api/config', lambda r: reply(r, {'chart_palette': 'verily'}))
    page.route('**/api/workflows**', lambda r: reply(r, {'available': False, 'jobs': [], 'running_count': 0}))
    page.route('**/api/views/all', lambda r: reply(r, {'views': [], 'unavailable': [], 'pending': []}))
    page.route('**/api/omop/**', lambda r: reply(r, {'cdm': False, 'tables': []}))

    def tables(route):
        if 'slowdb' in route.request.url:
            time.sleep(2.5)
            reply(route, [{'name': 'public.slow_table', 'schema': 'public', 'table': 'slow_table', 'detail': 'table'}])
        else:
            time.sleep(1.0)
            reply(route, [{'name': 'public.fast_table', 'schema': 'public', 'table': 'fast_table', 'detail': 'table'}])
    page.route('**/api/tables?**', tables)
    page.goto(app_url)
    page.get_by_label('Source type', exact=True).select_option('aurora')
    page.get_by_label('Datasource', exact=True).select_option('aurora:slowdb')
    status = page.locator('.source-picker .picker-status')
    expect(status).to_contain_text('Listing tables in slowdb')
    expect(page.get_by_label('Table', exact=True).locator('option').first).to_have_text('Listing tables…')
    expect(page.locator('.topbar .activity')).to_have_count(0)
    page.screenshot(path='/private/tmp/cohort-listing-status.png')

    page.get_by_label('Datasource', exact=True).select_option('aurora:fastdb')
    expect(status).to_contain_text('Listing tables in fastdb')
    expect(status).to_have_count(0, timeout=6000)
    page.wait_for_timeout(2500)          # the slow response arrives after the fast one
    options = page.get_by_label('Table', exact=True).locator('option').all_inner_texts()
    assert any('fast_table' in o for o in options) and not any('slow_table' in o for o in options), options
