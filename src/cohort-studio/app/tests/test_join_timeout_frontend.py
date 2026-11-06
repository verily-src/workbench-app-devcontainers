from playwright.sync_api import expect
from tests.test_e2e import app_url, loaded_page
from tests.ui_helpers import add_to_canvas, open_data_builder, set_join_keys


def test_cancel_join_preview_sends_cancellation(loaded_page):
    page = loaded_page
    path = __import__('pathlib').Path(__file__).parent / 'fixtures' / 'phenotypes.csv'
    page.locator('input[type="file"]').set_input_files(path)
    expect(page.locator('.tab', has_text='phenotypes.csv')).to_be_visible(timeout=15000)
    canvas = open_data_builder(page, 'phenotypes.csv')
    expect(canvas.locator('.jc-node')).to_have_count(1, timeout=10000)
    add_to_canvas(canvas, 'samples.csv', tab=True)
    expect(canvas.locator('.jc-node')).to_have_count(2, timeout=10000)
    set_join_keys(canvas, 'sample_id', 'sample_id')
    panel = canvas
    calls = []
    page.route('**/api/data-jobs/join_preview', lambda r: r.fulfill(status=202, json={'job_id': 'preview-1', 'kind': 'join_preview', 'status': 'queued'}))
    def cancel(route):
        calls.append('cancel')
        route.fulfill(status=200, json={'job_id': 'preview-1', 'kind': 'join_preview', 'status': 'cancelling'})
    page.route('**/api/data-jobs/preview-1/cancel', cancel)
    page.route('**/api/data-jobs/preview-1', lambda r: r.fulfill(status=200, json={'job_id': 'preview-1', 'kind': 'join_preview', 'status': 'cancelled' if calls else 'running'}))
    panel.get_by_role('button', name='Preview', exact=True).first.click()
    panel.get_by_role('button', name='Cancel preview').click()
    expect(panel).to_contain_text('Preview cancelled', timeout=10000)
    assert calls == ['cancel']
