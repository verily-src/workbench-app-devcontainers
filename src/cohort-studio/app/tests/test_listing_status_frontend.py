import pytest
from playwright.sync_api import expect
from tests.test_e2e import app_url
from tests.ui_helpers import open_data_builder

pytestmark = pytest.mark.e2e


def test_table_listing_status_sits_in_connections_and_latest_source_wins(page, app_url):
    def reply(route, value):
        route.fulfill(status=200, json=value)
    page.route('**/api/datasources', lambda r: reply(r, {'ready': True, 'sources': [
        {'kind': 'aurora', 'id': 'slowdb', 'label': 'Slow DB'},
        {'kind': 'aurora', 'id': 'fastdb', 'label': 'Fast DB'}]}))
    page.route('**/api/config', lambda r: reply(r, {'chart_palette': 'verily'}))
    page.route('**/api/workflows**', lambda r: reply(r, {'available': False, 'jobs': [], 'running_count': 0}))
    page.route('**/api/views/all', lambda r: reply(r, {'views': [], 'unavailable': [], 'pending': []}))
    page.route('**/api/omop/**', lambda r: reply(r, {'cdm': False, 'tables': []}))

    held = {}
    page.route('**/api/tables?**', lambda route: held.setdefault(
        'slowdb' if 'slowdb' in route.request.url else 'fastdb', route))
    page.goto(app_url)
    canvas = open_data_builder(page)   # Connections starts on the first datasource (slowdb)
    status = canvas.get_by_role('complementary', name='Connections').locator('.picker-status')
    expect(status).to_contain_text('Listing tables in slowdb')
    expect(page.locator('.topbar .activity')).to_have_count(0)
    page.screenshot(path='/private/tmp/cohort-listing-status.png')

    canvas.locator('[data-source-key="aurora:fastdb"]').click()
    expect(status).to_contain_text('Listing tables in fastdb')
    # Answer the newer request first, then the stale one.
    for _ in range(50):
        if 'fastdb' in held and 'slowdb' in held:
            break
        page.wait_for_timeout(100)
    reply(held['fastdb'], [{'name': 'public.fast_table', 'schema': 'public', 'table': 'fast_table', 'detail': 'table'}])
    expect(status).to_have_count(0, timeout=5000)
    reply(held['slowdb'], [{'name': 'public.slow_table', 'schema': 'public', 'table': 'slow_table', 'detail': 'table'}])
    page.wait_for_timeout(500)
    expect(canvas.locator('li[data-table="public.fast_table"]')).to_have_count(1)
    expect(canvas.locator('li[data-table="public.slow_table"]')).to_have_count(0)
