import json
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import expect
from tests.test_e2e import app_url


def test_enter_sends_shift_enter_adds_line_and_success_animates(page, app_url):
    session = '00000000-0000-4000-8000-000000000011'
    held, requests = [], []
    page.route('**/api/datasources', lambda r: r.fulfill(json={'ready': True, 'sources': [], 'catalogs_pending': False}))
    page.route('**/api/views/all', lambda r: r.fulfill(json={'views': [], 'pending': [], 'unavailable': []}))
    page.route('**/api/agent/chat/history?*', lambda r: r.fulfill(json={'session_id': session, 'messages': [], 'has_more': False}))
    page.route('**/api/agent/chat/sessions', lambda r: r.fulfill(json={'sessions': []}))
    page.route('**/api/agent/workflows?*', lambda r: r.fulfill(json={'plans': []}))
    def stream(route):
        requests.append(route.request.post_data_json)
        held.append(route)
    page.route('**/api/agent/chat/stream', stream)
    page.goto(app_url)
    page.get_by_text('Agent', exact=True).first.click()
    box = page.get_by_role('textbox', name='Message the Studio Agent')
    box.fill('First line')
    box.press('Shift+Enter')
    box.press_sequentially('Second line')
    assert box.input_value() == 'First line\nSecond line'
    assert not requests
    box.press('Enter')
    expect(page.get_by_text('Working…')).to_be_visible()
    assert requests[0]['message'] == 'First line\nSecond line'
    avatar = page.locator('.studio-agent-avatar img')
    assert avatar.evaluate('(element) => element.getBoundingClientRect().width') >= 112
    expect(avatar).to_have_attribute('src', '/mascot/thinking.webp')
    reply = '**Sources**\n\n- **Aurora:** `cohort`\n- [PubMed](https://pubmed.ncbi.nlm.nih.gov/)\n\n<script>bad()</script> [bad](javascript:alert(1))'
    body = [{'type': 'result', 'result': {'reply': reply, 'session_id': session,
            'tool_calls': [], 'actions': [], 'workflow_plans': []}}, {'type': 'end'}]
    held[0].fulfill(status=200, content_type='application/x-ndjson', body=''.join(json.dumps(x)+'\n' for x in body))
    expect(avatar).to_have_attribute('src', '/mascot/greeting.webp')
    response = page.locator('.studio-agent-message.assistant .agent-text').last
    expect(response.locator('strong', has_text='Sources')).to_be_visible()
    expect(response.locator('ul li')).to_have_count(2)
    expect(response.locator('code', has_text='cohort')).to_be_visible()
    expect(response.get_by_role('link', name='PubMed')).to_have_attribute('href', 'https://pubmed.ncbi.nlm.nih.gov/')
    assert response.locator('script').count() == 0
    assert response.get_by_role('link', name='bad').count() == 0
    expect(avatar).to_have_attribute('src', '/mascot/idle.webp', timeout=5000)


def test_followup_is_queued_and_sent_after_current_turn(page, app_url):
    session = '00000000-0000-4000-8000-000000000011'
    requests, held = [], []
    def fulfill(route, value): route.fulfill(json=value)
    page.route('**/api/datasources', lambda route: fulfill(route, {'ready': True, 'sources': [], 'catalogs_pending': False}))
    page.route('**/api/views/all', lambda route: fulfill(route, {'views': [], 'pending': [], 'unavailable': []}))
    page.route('**/api/agent/chat/history?*', lambda route: fulfill(route, {'session_id': session, 'messages': [], 'has_more': False}))
    page.route('**/api/agent/chat/sessions', lambda route: fulfill(route, {'sessions': [{'session_id': session, 'title': 'Prior chat', 'updated_at': '2026-10-27T12:00:00Z'}]}))
    page.route('**/api/agent/workflows?*', lambda route: fulfill(route, {'plans': []}))
    def stream_response(route, reply):
        body = ''.join(json.dumps(event) + '\n' for event in [
            {'type': 'started', 'run_id': '00000000-0000-4000-8000-000000000456'},
            {'type': 'result', 'result': {'reply': reply, 'session_id': session, 'tool_calls': [], 'actions': [], 'workflow_plans': []}},
            {'type': 'end'}])
        route.fulfill(status=200, content_type='application/x-ndjson', body=body)
    def stream(route):
        requests.append(route.request.post_data_json)
        if len(requests) == 1: held.append(route)
        else: stream_response(route, 'Second answer')
    page.route('**/api/agent/chat/stream', stream)
    page.goto(app_url)
    page.get_by_text('Agent', exact=True).first.click()
    box = page.get_by_role('textbox', name='Message the Studio Agent')
    box.fill('First request'); page.get_by_role('button', name='Send', exact=True).click()
    expect(page.get_by_text('Working…')).to_be_visible()
    box.fill('Follow-up request'); page.get_by_role('button', name='Queue', exact=True).click()
    expect(page.get_by_text('Queued: Follow-up request')).to_be_visible()
    assert len(requests) == 1
    stream_response(held[0], 'First answer')
    expect(page.get_by_text('Second answer')).to_be_visible(timeout=15000)
    assert [item['message'] for item in requests] == ['First request', 'Follow-up request']
    assert requests[1]['session_id'] == session


def test_workflow_plans_follow_selected_conversation(page, app_url):
    old = '00000000-0000-4000-8000-000000000011'
    def fulfill(route, value): route.fulfill(json=value)
    page.route('**/api/datasources', lambda route: fulfill(route, {'ready': True, 'sources': [], 'catalogs_pending': False}))
    page.route('**/api/views/all', lambda route: fulfill(route, {'views': [], 'pending': [], 'unavailable': []}))
    page.route('**/api/agent/chat/history?*', lambda route: fulfill(route, {'session_id': old, 'messages': [], 'has_more': False}))
    page.route('**/api/agent/chat/sessions', lambda route: fulfill(route, {'sessions': [{'session_id': old, 'title': 'Old session', 'updated_at': '2026-10-27T12:00:00Z'}]}))
    plan={'id':'old-plan','workflow':'old-workflow','dataset_id':'x','rows':1,'required_columns':[], 'input_resource_id':'i','output_resource_id':'o','status':'failed','errors':[]}
    def plans(route):
        assert parse_qs(urlparse(route.request.url).query).get('session_id') == [old]
        fulfill(route, {'plans':[plan]})
    page.route('**/api/agent/workflows?*', plans)
    page.goto(app_url); page.get_by_text('Agent', exact=True).first.click()
    expect(page.get_by_text('Review workflow: old-workflow')).to_be_visible(timeout=15000)
    page.get_by_role('button', name='New chat', exact=True).click()
    expect(page.get_by_text('Review workflow: old-workflow')).to_have_count(0)
    page.get_by_role('button', name='Old session', exact=True).click()
    expect(page.get_by_text('Review workflow: old-workflow')).to_be_visible()


def test_queued_turn_waits_for_workflow_review(page, app_url):
    session = '00000000-0000-4000-8000-000000000011'
    held, requests = [], []
    def fulfill(route, value): route.fulfill(json=value)
    page.route('**/api/datasources', lambda route: fulfill(route, {'ready': True, 'sources': [], 'catalogs_pending': False}))
    page.route('**/api/views/all', lambda route: fulfill(route, {'views': [], 'pending': [], 'unavailable': []}))
    page.route('**/api/agent/chat/history?*', lambda route: fulfill(route, {'session_id': session, 'messages': [], 'has_more': False}))
    page.route('**/api/agent/chat/sessions', lambda route: fulfill(route, {'sessions': []}))
    page.route('**/api/agent/workflows?*', lambda route: fulfill(route, {'plans': []}))
    def stream(route):
        requests.append(route.request.post_data_json)
        if len(requests) == 1: held.append(route)
        else:
            body = [{'type': 'result', 'result': {'reply': 'Continued', 'session_id': session,
                     'tool_calls': [], 'actions': [], 'workflow_plans': []}}, {'type': 'end'}]
            route.fulfill(status=200, content_type='application/x-ndjson', body=''.join(json.dumps(x)+'\n' for x in body))
    page.route('**/api/agent/chat/stream', stream)
    page.goto(app_url); page.get_by_text('Agent', exact=True).first.click()
    box = page.get_by_role('textbox', name='Message the Studio Agent')
    box.fill('Prepare workflow'); page.get_by_role('button', name='Send', exact=True).click()
    expect(page.get_by_text('Working…')).to_be_visible()
    box.fill('Continue analysis'); page.get_by_role('button', name='Queue', exact=True).click()
    plan={'id':'ready-plan','workflow':'demo','dataset_id':'x','rows':1,'required_columns':[],
          'input_resource_id':'i','output_resource_id':'o','status':'ready','errors':[]}
    result={'reply':'Review the workflow', 'session_id':session, 'tool_calls':[], 'actions':[], 'workflow_plans':[plan]}
    held[0].fulfill(status=200, content_type='application/x-ndjson', body=''.join(json.dumps(x)+'\n' for x in [
        {'type':'result','result':result}, {'type':'end'}]))
    expect(page.get_by_text('Review the workflow')).to_be_visible()
    expect(page.get_by_role('button', name='Send queued messages')).to_be_visible()
    assert len(requests) == 1
    page.get_by_role('button', name='Send queued messages').click()
    expect(page.get_by_text('Continued', exact=True)).to_be_visible()
    assert len(requests) == 2
