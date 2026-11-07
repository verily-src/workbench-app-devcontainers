import duckdb
from playwright.sync_api import expect

from tests.test_e2e import app_url
from tests.ui_helpers import pick_table


def test_s3_parquet_folder_lists_and_opens_as_one_dataset(page, app_url):
    def fulfill(route, value, status=200):
        route.fulfill(status=status, content_type='application/json', json=value)

    page.route('**/api/datasources', lambda r: fulfill(r, {
        'ready': True, 'sources': [{'kind': 's3', 'id': 'lake', 'label': 'lake · S3'}],
        'catalogs_pending': False}))
    page.route('**/api/tables?**', lambda r: fulfill(r, [
        {'name': 'events/', 'detail': 'Parquet folder · 2 parts', 'parts': 2,
         'bytes': 2048, 'modified': '2026-10-22 01:37:06'},
        {'name': 'events/year=2024/p.parquet', 'detail': 'file', 'bytes': 1024},
        {'name': 'events/year=2025/p.parquet', 'detail': 'file', 'bytes': 1024},
    ]))
    page.route('**/api/workflows**', lambda r: fulfill(r, {'available': False, 'jobs': [], 'running_count': 0}))
    page.route('**/api/views/all', lambda r: fulfill(r, {'views': [], 'unavailable': []}))
    opened_refs = []

    def open_job(route):
        body = route.request.post_data_json
        ref = body.get('source_ref', body)
        opened_refs.append(ref)
        fulfill(route, {'job_id': 'open-1', 'status': 'complete', 'result': {
            'dataset_id': 'folder-1', 'source': 'lake / events/', 'rows': 2,
            'columns': [{'name': 'year', 'dtype': 'int64', 'filter_kind': 'none'}],
            'source_ref': ref, 'query_scope': 'loaded'}})

    page.route('**/api/data-jobs/open', open_job)
    page.route('**/api/datasets/folder-1/query', lambda r: fulfill(r, {
        'total': 2, 'filtered': 2, 'charts': [], 'scope': 'loaded', 'sampled': False,
        'rows': {'page': 0, 'page_size': 50, 'columns': ['year'], 'data': [[2024], [2025]]}}))
    page.goto(app_url)
    card = pick_table(page, 's3:lake', 'events/')
    details = card.get_by_label('Table details')
    expect(details).to_contain_text('Parquet folder · 2 parts')
    expect(details.locator('[title="Total size of the Parquet parts in S3"]')).to_have_count(1)
    card.get_by_role('button', name='Open in Explore').click()
    expect(page.locator('.hero-source', has_text='lake / events/')).to_be_visible(timeout=10000)
    assert opened_refs[0]['table'] == 'events/'
    assert opened_refs[0]['kind'] == 's3'


def test_local_parquet_upload_opens_a_tab(page, app_url, tmp_path):
    path = tmp_path / 'local_cohort.parquet'
    con = duckdb.connect()
    con.execute(f"COPY (SELECT * FROM (VALUES (101, 'a'), (202, 'b')) t(person_id, arm)) "
                f"TO '{path}' (FORMAT PARQUET)")
    con.close()
    page.goto(app_url)
    upload = page.get_by_label('Upload CSV, TSV or Parquet')
    assert '.parquet' in upload.get_attribute('accept')
    upload.set_input_files(str(path))
    expect(page.locator('.tab.active', has_text='local_cohort.parquet')).to_be_visible(timeout=10000)
    expect(page.get_by_role('cell', name='202', exact=True)).to_be_visible(timeout=10000)
