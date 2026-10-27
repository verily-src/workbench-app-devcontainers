import re
from pathlib import Path
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
    card.get_by_role('button', name='Edit axes').click()
    card.get_by_label('X axis label').fill('Samples')
    card.get_by_label('Y axis label').fill('Tissue')
    card.get_by_role('button', name='Apply').click()
    with page.expect_download(timeout=30000) as download:
        page.get_by_role('button', name='Export PDF').click()
    download.value.save_as('/private/tmp/cohort-improved.pdf')
    assert card.locator('canvas').count() > 0
    pdf = Path('/private/tmp/cohort-improved.pdf').read_bytes()
    contents = re.findall(rb'/Type\s*/Page\b(?:(?!endobj).)*?/Contents\s+(\d+)\s+0\s+R', pdf, re.S)
    images_per_page = []
    for number in contents:
        stream = re.search(rb'(?m)^' + number + rb'\s+0\s+obj\b(.*?)endobj', pdf, re.S)
        assert stream
        images_per_page.append(len(re.findall(rb'/I\d+\s+Do', stream.group(1))))
    assert sum(images_per_page) == page.locator('.chart-grid .chart-card').count()
    assert max(images_per_page) == 1
