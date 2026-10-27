from playwright.sync_api import expect
from tests.test_e2e import app_url


def test_mascot_animations_have_smooth_frames():
    from pathlib import Path
    from PIL import Image
    import main
    assets = Path(main.__file__).parent.parent / 'web' / 'public' / 'mascot'
    for name in ('idle', 'thinking', 'greeting', 'dance'):
        with Image.open(assets / f'{name}.webp') as image:
            assert image.n_frames == 24
            image.seek(0)
            image.load()
            assert 35 <= image.info['duration'] <= 45


def test_agent_mascot_renders_and_respects_reduced_motion(page, app_url):
    page.clock.install()
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
    page.clock.fast_forward(10001)
    expect(avatar).to_have_attribute('src', '/mascot/dance.webp')
    page.clock.fast_forward(20001)
    expect(page.locator('.mascot-drive')).to_be_visible()
    expect(page.locator('.mascot-chaser')).to_be_visible()
    expect(page.locator('.mascot-truck')).to_be_visible()
    page.wait_for_function("document.querySelector('.mascot-truck')?.naturalWidth > 0")
    page.wait_for_function("document.querySelector('.mascot-chaser')?.naturalWidth > 0")
    page.screenshot(path='/private/tmp/cohort-mascot-flight.png')
    page.keyboard.press('Shift')
    expect(page.locator('.mascot-drive')).to_have_count(0)
    expect(avatar).to_have_attribute('src', '/mascot/idle.webp')
    page.screenshot(path='/private/tmp/cohort-mascot-ui.png')
    page.emulate_media(reduced_motion='reduce')
    page.wait_for_function("document.querySelector('.studio-agent-avatar img')?.currentSrc.endsWith('/mascot/still.webp')")
    assert avatar.evaluate('(img) => img.naturalWidth') > 0
    page.clock.fast_forward(30001)
    expect(page.locator('.mascot-drive')).to_be_hidden()
