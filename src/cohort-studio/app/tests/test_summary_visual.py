from playwright.sync_api import expect
from tests.test_e2e import app_url, loaded_page


def test_summary_layout_light_and_dark(loaded_page, tmp_path):
    page = loaded_page
    page.get_by_role('button', name='+ Group summary').click()
    panel = page.get_by_role('region', name='Group summary')
    panel.get_by_label('Group by').select_option('tissue')
    panel.get_by_role('button', name='Summarize').click()
    expect(panel.get_by_role('status')).to_contain_text('100 filtered rows', timeout=15000)
    page.screenshot(path=str(tmp_path / 'light.png'))
    page.evaluate("document.documentElement.setAttribute('data-theme', 'dark')")
    page.wait_for_timeout(500)
    button = panel.get_by_role('button', name='Add group')
    assert button.evaluate("element => getComputedStyle(element).backgroundColor") == 'rgb(32, 38, 45)'
    page.screenshot(path=str(tmp_path / 'dark.png'))
