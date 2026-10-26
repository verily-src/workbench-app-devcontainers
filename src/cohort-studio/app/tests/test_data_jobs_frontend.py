import pytest
from playwright.sync_api import expect
from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e


def test_load_progress_cancel_and_reload_resume(page, app_url):
    def reply(route, value):
        route.fulfill(status=200, json=value)
    page.route('**/api/datasources', lambda r: reply(r, {'ready':True,'sources':[{'kind':'aurora','id':'db','label':'Database'}]}))
    page.route('**/api/config', lambda r: reply(r, {'chart_palette':'verily'}))
    page.route('**/api/workflows**', lambda r: reply(r, {'available':False,'jobs':[],'running_count':0}))
    page.route('**/api/views/all', lambda r: reply(r, {'views':[],'unavailable':[],'pending':[]}))
    page.route('**/api/tables?**', lambda r: reply(r, [{'name':'public.person','schema':'public','table':'person'}]))
    page.route('**/api/omop/**', lambda r: reply(r, {'cdm':False,'tables':[]}))
    state = {'job_id':'job1','kind':'open','status':'running'}
    page.route('**/api/data-jobs/open', lambda r: reply(r,state))
    page.route('**/api/data-jobs/job1', lambda r: reply(r,state))
    def cancel(route):
        state['status'] = 'cancelled'
        reply(route,state)
    page.route('**/api/data-jobs/job1/cancel', cancel)
    page.goto(app_url)
    page.get_by_label('Source type', exact=True).select_option('aurora')
    page.get_by_label('Datasource', exact=True).select_option('aurora:db')
    page.get_by_label('Table', exact=True).select_option('public.person')
    page.get_by_role('button', name='Load table', exact=True).click()
    panel = page.get_by_role('region', name='Data operations')
    expect(panel).to_contain_text('running')
    assert panel.bounding_box()['y'] >= page.locator('.topbar').bounding_box()['height']
    page.screenshot(path='/private/tmp/cohort-data-job-progress.png')
    panel.get_by_role('button', name='Cancel', exact=True).click()
    expect(panel).not_to_be_visible(timeout=5000)
    expect(page.get_by_role('button',name='Load table',exact=True)).to_be_enabled()
    page.evaluate("sessionStorage.setItem('studio-data-jobs', JSON.stringify(['job1']))")
    state['status'] = 'interrupted'
    page.reload()
    expect(panel).to_contain_text('interrupted')
    panel.get_by_role('button',name='Dismiss').click()
    expect(panel).not_to_be_visible()
