from playwright.sync_api import expect
from tests.test_e2e import app_url, loaded_page


def test_row_sort_and_hide_sidebar(loaded_page):
    page=loaded_page
    header=page.get_by_role('columnheader',name='age')
    header.get_by_role('button',name='age').click()
    expect(header).to_have_attribute('aria-sort','ascending')
    expect(page.locator('.data-table tbody tr').first).to_contain_text('20', timeout=10000)
    header.get_by_role('button',name='age').click()
    expect(header).to_have_attribute('aria-sort','descending')
    expect(page.locator('.data-table tbody tr').first).to_contain_text('79', timeout=10000)
    page.get_by_text('Workflows',exact=True).first.click()
    expect(page.locator('.sidebar')).to_be_hidden()
    page.get_by_text('Explore',exact=True).first.click()
    expect(page.locator('.sidebar')).to_be_visible()


def test_workflow_sort_and_links(page,app_url):
    jobs=[{'run_id':'ceea2bdc-50fa-4922-a1a3-53e2a3e2b3fe','name':'Alpha','status':'FAILED','created_date':'2026-10-01'}, {'run_id':'e85e1aba-565f-4dcc-9f28-262d38e2b879','name':'Beta','status':'COMPLETED','created_date':'2026-10-02'}]
    page.route('**/api/workflows**',lambda r:r.fulfill(json={'available':True,'running_count':0,'jobs':jobs,'monitor_base':'https://workbench-dev.verily.com/workspaces/bugbash-nextflowonaws/workflows/monitor/'}))
    page.goto(app_url)
    page.get_by_text('Workflows',exact=True).first.click()
    table=page.locator('table.data-table')
    expect(table.locator('tbody tr').first).to_contain_text('Beta',timeout=15000)
    table.get_by_role('button',name='Status').click()
    expect(table.locator('tbody tr').first).to_contain_text('COMPLETED')
    table.get_by_role('button',name='Status').click()
    expect(table.locator('tbody tr').first).to_contain_text('FAILED')
    expect(table.get_by_role('link',name='FAILED: Open workflow Alpha in Workbench')).to_have_attribute('href','https://workbench-dev.verily.com/workspaces/bugbash-nextflowonaws/workflows/monitor/ceea2bdc-50fa-4922-a1a3-53e2a3e2b3fe')
