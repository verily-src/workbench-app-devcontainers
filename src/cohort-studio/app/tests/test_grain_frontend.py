import re
import pytest
from playwright.sync_api import Page, expect
from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e


def test_row_grain_and_session_performance_through_real_api(page: Page, app_url: str):
    page.route('**/api/datasources', lambda route: route.fulfill(json={'ready':True,'sources':[]}))
    page.route('**/api/views/all', lambda route: route.fulfill(json={'views':[],'unavailable':[]}))
    page.route('**/api/workflows**', lambda route: route.fulfill(json={'available':False,'jobs':[],'running_count':0}))
    page.goto(app_url)
    page.locator('input[type="file"]').first.set_input_files({'name':'grain.csv','mimeType':'text/csv','buffer':b'person_id,visit_id\n1,1\n1,2\n2,1\n'})
    expect(page.locator('.hero')).to_contain_text('3', timeout=15000)
    page.get_by_role('button',name='Row grain',exact=True).click()
    panel = page.get_by_role('region', name='Row grain')
    panel.get_by_label('One row represents').select_option('event')
    panel.get_by_label('person_id',exact=True).check()
    panel.get_by_label('visit_id',exact=True).check()
    panel.get_by_role('button',name='Save and check key').click()
    expect(panel).to_contain_text('Key is unique and complete',timeout=15000)
    expect(panel).to_contain_text('3 distinct keys')
    expect(panel).to_contain_text('Loaded data')
    page.screenshot(path='/private/tmp/studio-grain-panel.png')
    page.set_viewport_size({'width':390, 'height':844})
    bounds = panel.bounding_box()
    assert bounds and bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= 390
    page.screenshot(path='/private/tmp/studio-grain-mobile.png')
    page.set_viewport_size({'width':1280, 'height':720})
    panel.get_by_label('visit_id',exact=True).uncheck()
    panel.get_by_role('button',name='Save and check key').click()
    expect(panel).to_contain_text('Key has duplicates or missing values',timeout=15000)
    expect(panel).to_contain_text('1 duplicate rows')
    page.get_by_role('button',name='Row grain',exact=True).click()
    page.locator('.topnav').get_by_text('Settings',exact=True).click()
    perf = page.get_by_role('region',name='Performance',exact=True)
    perf.get_by_role('button',name='Refresh performance').click()
    expect(perf).to_contain_text('grain.check',timeout=15000)
    expect(perf).to_contain_text('p95 (ms)')
    perf.scroll_into_view_if_needed()
    page.screenshot(path='/private/tmp/studio-performance-panel.png')
