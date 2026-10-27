from playwright.sync_api import expect
from tests.test_e2e import app_url, loaded_page


def test_initial_page_defers_charts_pdf_and_agent(page, app_url):
    requested = []
    page.on('request', lambda req: requested.append(req.url))
    page.route('**/api/datasources', lambda route: route.fulfill(json={'ready': True, 'sources': [], 'catalogs_pending': False}))
    page.route('**/api/views/all', lambda route: route.fulfill(json={'views': [], 'pending': [], 'unavailable': []}))
    page.route('**/api/agent/chat/sessions', lambda route: route.fulfill(json={'sessions': []}))
    page.route('**/api/agent/chat/history?*', lambda route: route.fulfill(json={'session_id': None, 'messages': []}))
    page.goto(app_url)
    expect(page.get_by_text('No data loaded')).to_be_visible()
    assert not any('/ChartCard-' in url or '/pdf-' in url or '/StudioAgent-' in url for url in requested)
    page.get_by_text('Agent', exact=True).first.click()
    expect(page.get_by_role('heading', name='Studio Agent')).to_be_visible()
    assert any('/StudioAgent-' in url for url in requested)
    assert not any('/pdf-' in url for url in requested)


def test_preloads_secondary_screens_after_initial_render(page, app_url):
    requested = []
    page.on('request', lambda req: requested.append(req.url))
    page.route('**/api/datasources', lambda r: r.fulfill(json={'ready': True, 'sources': [], 'catalogs_pending': False}))
    page.route('**/api/views/all', lambda r: r.fulfill(json={'views': [], 'pending': [], 'unavailable': []}))
    page.goto(app_url)
    expect(page.get_by_text('No data loaded')).to_be_visible()
    assert not any('/StudioAgent-' in url for url in requested)
    page.wait_for_function("performance.getEntriesByType('resource').some(e => /StudioAgent-.*\\.js/.test(e.name))", timeout=15000)
    assert any('/WorkflowsView-' in url for url in requested)


def test_workflow_navigation_reuses_startup_request(page, app_url):
    held, requests = [], []
    page.route('**/api/datasources', lambda r: r.fulfill(json={'ready': True, 'sources': [], 'catalogs_pending': False}))
    page.route('**/api/views/all', lambda r: r.fulfill(json={'views': [], 'pending': [], 'unavailable': []}))
    def workflows(route):
        requests.append(route.request.url)
        held.append(route)
    page.route('**/api/workflows', workflows)
    page.goto(app_url)
    expect(page.get_by_text('No data loaded')).to_be_visible()
    page.get_by_text('Workflows', exact=True).first.click()
    expect(page.get_by_text('Loading workflow jobs…')).to_be_visible()
    assert len(requests) == 1
    held[0].fulfill(json={'available': True, 'jobs': [{'run_id': '1', 'name': 'Test run', 'status': 'COMPLETED', 'engine_type': None, 'created_by': None, 'created_date': None, 'output_bucket_name': None, 'output_bucket_resource': None, 'output_bucket_path': None}], 'running_count': 0})
    expect(page.get_by_text('Test run')).to_be_visible()


def test_custom_categorical_filter_accepts_values_not_in_picker(loaded_page):
    group = loaded_page.locator('.filter-group', has_text='tissue')
    group.locator('summary').click()
    group.get_by_role('textbox', name='Custom filter value').fill('unlisted tissue')
    group.get_by_role('button', name='Add', exact=True).click()
    expect(group.get_by_label('unlisted tissue')).to_be_checked()
    expect(loaded_page.locator('.hero .count')).to_have_text('0', timeout=10000)
    group.get_by_label('unlisted tissue').click()
    expect(loaded_page.locator('.hero .count')).to_have_text('100', timeout=10000)


def test_aggregation_filter_keeps_rows_from_qualifying_groups(loaded_page):
    page = loaded_page
    page.get_by_role('button', name='+ Aggregation filter').click()
    panel = page.get_by_role('region', name='Aggregation filter')
    panel.get_by_label('Group by').select_option('tissue')
    panel.get_by_label('At least', exact=True).fill('26')
    panel.get_by_role('button', name='Apply filter').click()
    expect(panel).to_have_count(0, timeout=15000)
    expect(page.locator('.hero .count')).to_have_text('0', timeout=15000)
    expect(page.locator('.chip', has_text='Rows per group')).to_be_visible()
    page.locator('.chip', has_text='Rows per group').click()
    expect(page.locator('.hero .count')).to_have_text('100', timeout=15000)
