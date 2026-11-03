import json

from playwright.sync_api import expect
from tests.test_e2e import app_url


def test_agent_download_card_retries_status_without_resubmission(page, app_url):
    def fulfill(route, body):
        route.fulfill(status=200, content_type='application/json', json=body)
    page.route('**/api/config', lambda r: fulfill(r, {'chart_palette': 'verily', 'llm': {'provider': 'anthropic', 'providers': {}}}))
    page.route('**/api/datasources', lambda r: fulfill(r, {'ready': True, 'sources': [], 'catalogs_pending': False}))
    page.route('**/api/views/all', lambda r: fulfill(r, {'views': [], 'unavailable': []}))
    page.route('**/api/workflows**', lambda r: fulfill(r, {'available': True, 'jobs': [], 'running_count': 0}))
    page.route('**/api/agent/chat/sessions', lambda r: fulfill(r, {'sessions': []}))
    page.route('**/api/agent/chat/history**', lambda r: fulfill(r, {'session_id': None, 'messages': [], 'has_more': False, 'next_before_message_id': None}))
    page.route('**/api/agent/workflows**', lambda r: fulfill(r, {'plans': []}))
    result = {'reply': 'Use the download button.', 'session_id': '00000000-0000-4000-8000-000000000123',
              'tool_calls': ['prepare_download'], 'actions': [], 'workflow_plans': [],
              'downloads': [{'dataset_id': 'data-1', 'title': 'Cohort', 'format': 'tsv.gz'}]}
    stream = ''.join(json.dumps(event) + '\n' for event in [{'type': 'result', 'result': result}, {'type': 'end'}])
    page.route('**/api/agent/chat/stream', lambda r: r.fulfill(status=200, content_type='application/x-ndjson', body=stream))
    posts, polls = [], []
    def start(route):
        posts.append(route.request.post_data_json)
        fulfill(route, {'job': {'id': 'job-1', 'status': 'queued'}})
    def status(route):
        polls.append(1)
        if len(polls) == 1:
            route.fulfill(status=503, content_type='application/json', json={'detail': 'Status unavailable'})
        else:
            fulfill(route, {'id': 'job-1', 'status': 'complete', 'rows': 2})
    page.route('**/api/agent/dashboards/data-1/download', start)
    page.route('**/api/exports/job-1', status)
    page.route('**/api/exports/job-1/download', lambda r: r.fulfill(status=200, content_type='application/gzip', headers={'Content-Disposition': 'attachment; filename=cohort.tsv.gz'}, body=b'fixture-compressed-data'))
    page.goto(app_url)
    page.locator('.topnav-link', has_text='Agent').click()
    textbox = page.get_by_placeholder('What would you like to analyze?')
    textbox.fill('Download my cohort as TSV.gz')
    textbox.press('Enter')
    page.get_by_role('button', name='Download TSV.GZ').click()
    expect(page.get_by_text('Status unavailable')).to_be_visible(timeout=10000)
    page.get_by_role('button', name='Retry status').click()
    link = page.get_by_role('link', name='Download TSV.GZ')
    expect(link).to_have_attribute('href', '/api/exports/job-1/download', timeout=10000)
    with page.expect_download() as download_info:
        link.click()
    download = download_info.value
    assert download.suggested_filename == 'cohort.tsv.gz'
    assert download.path().read_bytes() == b'fixture-compressed-data'
    assert posts == [{'format': 'tsv.gz'}]
