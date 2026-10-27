from playwright.sync_api import expect
from tests.test_e2e import app_url, loaded_page


def test_chart_controls_and_picker_remain_usable_in_both_themes(loaded_page):
    page = loaded_page
    card = page.locator('.chart-grid .chart-card').first
    expect(card).to_be_visible()
    expect(card.get_by_role('button', name='Rename chart')).to_be_visible()
    assert page.get_by_label('Source type').is_visible()
    for theme in ('light', 'dark'):
        page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
        page.set_viewport_size({'width': 1440, 'height': 900})
        page.screenshot(path=f'/private/tmp/cohort-dashboard-{theme}.png')
        card.get_by_role('button', name='Rename chart').click()
        editor = card.get_by_role('textbox', name='Chart title')
        editor.fill('Very long chart title that remains readable and can wrap in the card header')
        editor.press('Enter')
        expect(card.locator('.title')).to_contain_text('Very long chart title')
        assert card.evaluate('(el) => el.scrollWidth <= el.clientWidth + 1')
    page.set_viewport_size({'width': 390, 'height': 844})
    page.screenshot(path='/private/tmp/cohort-dashboard-mobile.png')
    assert card.evaluate('(el) => el.scrollWidth <= el.clientWidth + 1')
    expect(card.get_by_role('button', name='Rename chart')).to_be_visible()
