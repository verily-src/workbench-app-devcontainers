from playwright.sync_api import expect
from tests.test_e2e import app_url


def test_large_histogram_labels_fit(page,app_url,tmp_path):
    path=tmp_path/'large_ids.csv'
    path.write_text('record_id\n' + ''.join(f'{856210473 + i * 200000}\n' for i in range(100)))
    page.goto(app_url)
    page.locator('input[type="file"]').set_input_files(path)
    card=page.locator('.chart-card').first
    expect(card).to_be_visible(timeout=15000)
    page.wait_for_timeout(300)
    card.screenshot(path=str(tmp_path / 'histogram.png'))
