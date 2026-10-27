from playwright.sync_api import expect
from tests.test_e2e import app_url, loaded_page


def test_expression_field_calculates_and_displays_rows(loaded_page):
    page = loaded_page
    page.get_by_role('button', name='+ Calculated field').click()
    panel = page.locator('.derive-panel')
    panel.get_by_label('Operation').select_option('expression')
    panel.get_by_label('New column name').fill('double RIN')
    panel.get_by_label('Calculation expression').fill('coalesce(rin_score, 0) * 2')
    panel.get_by_role('button', name='Add column').click()
    expect(panel.get_by_text('Added "double RIN".')).to_be_visible(timeout=15000)
    expect(page.get_by_role('columnheader', name='double RIN')).to_be_visible(timeout=15000)
    expect(page.locator('.data-table tbody tr').first).to_contain_text('13.2')


def test_multiple_groups_and_at_most_filter(loaded_page):
    page = loaded_page
    page.get_by_role('button', name='+ Aggregation filter').click()
    panel = page.get_by_role('region', name='Aggregation filter')
    panel.get_by_label('Group by').select_option('tissue')
    panel.get_by_role('button', name='Add group').click()
    panel.get_by_label('Group 2').select_option('sample_id')
    panel.get_by_label('Comparison').select_option('at_most')
    panel.get_by_label('At most', exact=True).fill('1')
    panel.get_by_role('button', name='Apply filter').click()
    expect(panel).to_have_count(0, timeout=15000)
    expect(page.locator('.chip', has_text='Rows per group: ≤ 1')).to_be_visible(timeout=15000)
    expect(page.locator('.hero .count')).to_have_text('100', timeout=15000)
