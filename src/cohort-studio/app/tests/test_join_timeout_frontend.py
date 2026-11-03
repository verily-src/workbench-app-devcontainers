from playwright.sync_api import expect
from tests.test_e2e import app_url, loaded_page


def test_cancel_join_preview_sends_cancellation(loaded_page):
    page = loaded_page
    path = __import__('pathlib').Path(__file__).parent / 'fixtures' / 'phenotypes.csv'
    page.locator('input[type="file"]').set_input_files(path)
    expect(page.locator('.tab', has_text='phenotypes.csv')).to_be_visible(timeout=15000)
    page.locator('.tab-join').click()
    panel = page.locator('.join-panel')
    panel.get_by_label('Left key step 1 condition 1').select_option('sample_id')
    panel.get_by_label('Right key step 1 condition 1').select_option('sample_id')
    calls = []
    page.route('**/api/data-jobs/join_preview', lambda r: r.fulfill(status=202, json={'job_id': 'preview-1', 'kind': 'join_preview', 'status': 'queued'}))
    def cancel(route):
        calls.append('cancel')
        route.fulfill(status=200, json={'job_id': 'preview-1', 'kind': 'join_preview', 'status': 'cancelling'})
    page.route('**/api/data-jobs/preview-1/cancel', cancel)
    page.route('**/api/data-jobs/preview-1', lambda r: r.fulfill(status=200, json={'job_id': 'preview-1', 'kind': 'join_preview', 'status': 'cancelled' if calls else 'running'}))
    panel.get_by_role('button', name='Preview').click()
    panel.get_by_role('button', name='Cancel preview').click()
    expect(panel).to_contain_text('Preview cancelled', timeout=10000)
    assert calls == ['cancel']
