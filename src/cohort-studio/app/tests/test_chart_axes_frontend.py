from playwright.sync_api import expect
from tests.test_e2e import app_url, loaded_page


def test_axis_controls_validate_and_update_without_query(loaded_page):
    page = loaded_page
    card = page.locator('.chart-grid .chart-card').first
    queries = []
    page.on('request', lambda request: queries.append(request.url) if '/query' in request.url else None)
    card.get_by_role('button', name='Edit axes').click()
    form = card.get_by_role('form', name='Chart axes')
    form.get_by_label('X axis label').fill('Number of samples')
    form.get_by_label('Y axis label').fill('Tissue type')
    form.get_by_label('X axis scale').select_option('log')
    form.get_by_label('X axis minimum').fill('0')
    form.get_by_role('button', name='Apply').click()
    expect(form.get_by_role('alert')).to_contain_text('must be positive')
    form.get_by_label('X axis minimum').fill('1')
    form.get_by_label('X axis maximum').fill('100')
    form.get_by_role('button', name='Apply').click()
    expect(form).to_have_count(0)
    expect(card.get_by_text('Log scale shows positive values only.')).to_be_visible()
    page.wait_for_timeout(500)
    assert not queries
    page.screenshot(path='/private/tmp/cohort-axis-chart.png')
    card.get_by_role('button', name='Edit axes').click()
    form = card.get_by_role('form', name='Chart axes')
    assert form.get_by_label('X axis label').input_value() == 'Number of samples'
    assert form.get_by_label('Y axis label').input_value() == 'Tissue type'
    assert form.get_by_label('X axis scale').input_value() == 'log'
    assert form.get_by_label('X axis minimum').input_value() == '1'
    assert form.get_by_label('X axis maximum').input_value() == '100'
    assert form.get_by_label('Y axis scale').count() == 0


def test_saved_view_preserves_chart_axes(page, app_url):
    saved = []
    source = {'kind': 'aurora', 'resource_id': 'db-main', 'schema': 'public', 'table': 'samples'}
    charts = [{'kind': 'bar', 'x': 'tissue', 'title': 'Tissues'}]
    page.route('**/api/datasources', lambda r: r.fulfill(json={'ready': True, 'sources': [{'kind': 'aurora', 'id': 'db-main', 'label': 'DB'}], 'catalogs_pending': False}))
    page.route('**/api/views/all', lambda r: r.fulfill(json={'views': [{'name': 'Example', 'kind': 'aurora', 'resource_id': 'db-main', 'store_label': 'DB'}], 'unavailable': []}))
    page.route('**/api/views/one?**', lambda r: r.fulfill(json={'version': 2, 'active': 0, 'datasets': saved[-1]['datasets'] if saved else [{'source': source, 'title': 'Samples', 'filters': [], 'charts': charts, 'cohorts': []}]}))
    page.route('**/api/data-jobs/open', lambda r: r.fulfill(json={'job_id': 'open', 'status': 'complete', 'result': {'dataset_id': 'axis-dataset', 'source': 'samples', 'rows': 2, 'source_ref': source, 'query_scope': 'loaded', 'columns': [{'name': 'tissue', 'filter_kind': 'categorical', 'values': ['A', 'B']}]}}))
    page.route('**/api/datasets/axis-dataset/query', lambda r: r.fulfill(json={'total': 2, 'filtered': 2, 'scope': 'loaded', 'charts': [{'kind': 'bar', 'x': 'tissue', 'data': [{'category': 'A', 'all': 1, 'selected': 1}, {'category': 'B', 'all': 1, 'selected': 1}]}], 'rows': {'page': 0, 'page_size': 50, 'columns': ['tissue'], 'data': [['A'], ['B']]}}))
    def save(route):
        saved.append(route.request.post_data_json)
        route.fulfill(json={'name': 'Saved'})
    page.route('**/api/views', save)
    page.goto(app_url)
    page.get_by_role('button', name='Example', exact=True).click()
    card = page.locator('.chart-grid .chart-card').first
    card.get_by_role('button', name='Edit axes').click()
    form = card.get_by_role('form', name='Chart axes')
    form.get_by_label('X axis label').fill('Participants')
    form.get_by_label('Y axis label').fill('Type')
    form.get_by_label('X axis maximum').fill('50')
    form.get_by_role('button', name='Apply').click()
    page.get_by_label('Saved view name').fill('Saved')
    page.locator('.view-save').get_by_role('button', name='Save', exact=True).click()
    expect(page.get_by_text('Saved 1 tab(s) to DB.')).to_be_visible()
    chart = saved[0]['datasets'][0]['charts'][0]
    assert chart['title'] == 'Tissues' and chart['x_axis']['label'] == 'Participants'
    assert chart['x_axis']['max'] == 50 and chart['y_axis']['label'] == 'Type'
    page.get_by_role('button', name='Example', exact=True).click()
    card = page.locator('.chart-grid .chart-card').first
    card.get_by_role('button', name='Edit axes').click()
    expect(card.get_by_label('X axis label')).to_have_value('Participants')
    expect(card.get_by_label('X axis maximum')).to_have_value('50')
