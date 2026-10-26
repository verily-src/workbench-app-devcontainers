from playwright.sync_api import expect
from tests.test_e2e import app_url


def test_ncbi_settings_save_remove_and_hide_key(page, app_url):
    state = {
        'chart_palette': 'verily', 'llm': {'provider': 'anthropic', 'providers': {}},
        'mcp': {'available': True, 'path': '/mcp'}, 'mcp_connections': [],
        'jev': {'api_key_set': False, 'api_key_source': None, 'model': 'jev-latest'},
        'literature': {'ncbi_api_key_set': False, 'ncbi_api_key_source': None},
    }
    bodies = []
    def settings(route):
        if route.request.method == 'PUT':
            body = route.request.post_data_json
            bodies.append(body)
            state['literature'] = {'ncbi_api_key_set': bool(body['ncbi_api_key']),
                                   'ncbi_api_key_source': 'local_encrypted' if body['ncbi_api_key'] else None}
        route.fulfill(json=state)
    page.route('**/api/config', settings)
    page.route('**/api/datasources', lambda route: route.fulfill(json={'ready': True, 'sources': []}))
    page.route('**/api/workflows**', lambda route: route.fulfill(json={'available': False, 'jobs': []}))
    page.route('**/api/views/all', lambda route: route.fulfill(json={'views': [], 'unavailable': []}))
    page.goto(app_url)
    page.locator('.topnav-link', has_text='Settings').click()
    key = page.locator('#ncbi-api-key')
    expect(key).to_have_attribute('type', 'password')
    key.fill('test_ncbi_key')
    page.get_by_role('button', name='Save NCBI key').click()
    expect(page.get_by_text('PubMed settings saved securely.', exact=True)).to_be_visible()
    expect(key).to_have_value('')
    assert bodies == [{'ncbi_api_key': 'test_ncbi_key'}]
    page.get_by_role('button', name='Remove saved key', exact=True).click()
    expect(page.get_by_text('Saved PubMed key removed.', exact=True)).to_be_visible()
    assert bodies[-1] == {'ncbi_api_key': ''}
    page.locator('#ncbi-api-key').scroll_into_view_if_needed()
    page.screenshot(path='/private/tmp/studio-literature-settings.png')
