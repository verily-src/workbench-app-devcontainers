import pytest
from playwright.sync_api import expect
from tests.test_e2e import app_url
from tests.test_table_info_progress_frontend import _mock_app, COLUMNS

pytestmark = pytest.mark.e2e


def test_one_dataset_settings_entry_with_columns_and_grain_tabs(page, app_url):
    reply = _mock_app(page)
    page.route('**/api/data-jobs/open', lambda r: reply(r, {'job_id': 'j', 'kind': 'open', 'status': 'complete',
        'result': {'dataset_id': 'ds1', 'source': 'omop / cms.cost', 'rows': 2, 'columns': COLUMNS, 'query_scope': 'database'}}))
    page.route('**/api/datasets/ds1/query', lambda r: reply(r, {'total': 2, 'filtered': 2, 'scope': 'database', 'sampled': False,
        'entity': None, 'cache': None, 'charts': [], 'rows': {'page': 0, 'page_size': 50, 'columns': ['person_id', 'cost'], 'data': [[1, 2]]}}))
    page.goto(app_url)
    page.get_by_label('Source type', exact=True).select_option('aurora')
    page.get_by_label('Datasource', exact=True).select_option('aurora:omop')
    page.get_by_label('Schema', exact=True).select_option('cms')
    page.get_by_label('Table', exact=True).select_option('cms.cost')
    page.get_by_role('button', name='Load table', exact=True).click()
    expect(page.locator('.dataset-toolbar')).to_be_visible(timeout=10000)
    page.wait_for_timeout(1500)
    toolbar = page.locator('.dataset-toolbar')
    expect(toolbar.get_by_role("button", name="Dataset settings")).to_have_count(1)
    expect(toolbar.get_by_role("button", name="Row grain", exact=True)).to_have_count(0)
    expect(toolbar.get_by_role("button", name="Column settings", exact=True)).to_have_count(0)
    # Re-query (Refresh) must not multiply the entry.
    page.get_by_role("button", name="Refresh data", exact=True).click()
    page.wait_for_timeout(800)
    expect(toolbar.get_by_role("button", name="Dataset settings")).to_have_count(1)
    toolbar.get_by_role("button", name="Dataset settings").click()
    drawer = page.get_by_role("dialog", name="Dataset settings")
    expect(drawer).to_contain_text("cms.cost")
    expect(drawer.get_by_role("tab", name="Columns")).to_have_attribute("aria-selected", "true")
    expect(drawer.locator(".column-setting-row")).to_have_count(2)
    drawer.get_by_role("tab", name="Row grain").click()
    expect(drawer.get_by_role("region", name="Row grain")).to_be_visible()
    page.wait_for_timeout(300)   # let the 0.12 s tab border transition finish
    page.screenshot(path="/private/tmp/cohort-dataset-settings.png")
    page.keyboard.press("Escape")
    expect(drawer).to_have_count(0)
