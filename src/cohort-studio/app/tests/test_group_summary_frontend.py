from playwright.sync_api import expect
from tests.test_e2e import app_url, loaded_page


def test_summary_table_and_pagination(loaded_page):
    page = loaded_page
    page.get_by_role('button', name='+ Group summary').click()
    panel = page.get_by_role('region', name='Group summary')
    panel.get_by_label('Group by').select_option('sample_id')
    panel.get_by_role('button', name='Summarize').click()
    expect(panel.get_by_role('status')).to_contain_text('100 filtered rows · 100 groups', timeout=15000)
    expect(panel.locator('tbody tr')).to_have_count(50)
    panel.get_by_role('button', name='Next').click()
    expect(panel.get_by_text('Page 2 of 2')).to_be_visible(timeout=15000)
    expect(panel.locator('tbody tr')).to_have_count(50)
    panel.get_by_label('Group by').select_option('tissue')
    panel.get_by_label('Value column').select_option('rin_score')
    panel.get_by_role('button', name='Summarize').click()
    expect(panel.get_by_role('columnheader', name='Mean')).to_be_visible(timeout=15000)
    expect(panel.get_by_role('status')).to_contain_text('100 filtered rows')


def test_summary_follows_active_filters(loaded_page):
    page = loaded_page
    group = page.locator('.filter-group', has_text='tissue')
    group.locator('summary').click()
    group.get_by_label('liver').check()
    expect(page.locator('.hero .count')).to_have_text('25', timeout=15000)
    page.get_by_role('button', name='+ Group summary').click()
    panel = page.get_by_role('region', name='Group summary')
    panel.get_by_label('Group by').select_option('tissue')
    panel.get_by_role('button', name='Summarize').click()
    expect(panel.get_by_role('status')).to_contain_text('25 filtered rows · 1 group', timeout=15000)
    expect(panel.locator('tbody tr')).to_have_count(1)
    expect(panel.locator('tbody tr').first).to_contain_text('liver')
    expect(panel.locator('tbody tr').first).to_contain_text('25')
