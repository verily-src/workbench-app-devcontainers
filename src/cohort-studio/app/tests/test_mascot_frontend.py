from playwright.sync_api import expect
from tests.test_e2e import app_url


def test_agent_mascot_renders_and_respects_reduced_motion(page, app_url):
    page.route('**/api/datasources', lambda route: route.fulfill(json={'ready': True, 'sources': [], 'catalogs_pending': False}))
    page.route('**/api/views/all', lambda route: route.fulfill(json={'views': [], 'pending': [], 'unavailable': []}))
    page.route('**/api/agent/chat/sessions', lambda route: route.fulfill(json={'sessions': []}))
    page.route('**/api/agent/workflows', lambda route: route.fulfill(json={'plans': []}))
    page.route('**/api/agent/chat/history?*', lambda route: route.fulfill(json={'session_id': None, 'messages': []}))
    page.goto(app_url)
    page.get_by_text('Agent', exact=True).first.click()
    avatar = page.locator('.studio-agent-avatar img')
    expect(avatar).to_be_visible(timeout=15000)
    page.wait_for_function("document.querySelector('.studio-agent-avatar img')?.naturalWidth > 0")
    assert avatar.evaluate('(img) => img.currentSrc').endswith('/mascot/idle.webp')
    page.screenshot(path='/private/tmp/cohort-mascot-ui.png')
    page.emulate_media(reduced_motion='reduce')
    page.wait_for_function("document.querySelector('.studio-agent-avatar img')?.currentSrc.endsWith('/mascot/still.webp')")
    assert avatar.evaluate('(img) => img.naturalWidth') > 0
