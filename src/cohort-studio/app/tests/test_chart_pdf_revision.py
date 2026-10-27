from playwright.sync_api import expect
from tests.test_e2e import app_url, loaded_page


def test_chart_rename_and_dark_theme_pdf(loaded_page):
    page = loaded_page
    page.evaluate("document.documentElement.setAttribute('data-theme', 'dark')")
    card = page.locator('.chart-grid .chart-card').first
    card.get_by_role('button', name='Rename chart').click()
    title = card.get_by_role('textbox', name='Chart title')
    title.fill('Sample distribution'); title.press('Enter')
    expect(card.locator('.title')).to_have_text('Sample distribution')
    with page.expect_download(timeout=30000) as download:
        page.get_by_role('button', name='Export PDF').click()
    download.value.save_as('/private/tmp/cohort-improved.pdf')
    assert card.locator('canvas').count() > 0
