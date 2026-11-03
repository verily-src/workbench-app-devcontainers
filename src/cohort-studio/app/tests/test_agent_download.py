import hashlib
import time

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import agent_mode_api
import agent_sessions
import datasets
import execution
import main


@pytest.fixture
def owned_dashboard(monkeypatch):
    monkeypatch.setattr(main, 'datasources', lambda: {'sources': []})
    monkeypatch.setattr(main, '_lineage_engine', lambda: None)
    monkeypatch.setattr(main.lineage, 'record', lambda *args, **kwargs: None)
    client = TestClient(main.app)
    client.get('/api/health')
    owner = hashlib.sha256(client.cookies[agent_sessions._COOKIE].encode()).hexdigest()
    opened = datasets.open_dataset(pd.DataFrame({'id': [1, 2], 'name': ['a', 'b']}), 'test')
    did = opened['dataset_id']
    agent_mode_api._dashboards[did] = {
        'owner': owner, 'title': 'Test cohort', 'source_ref': {},
        'filters': [{'column': 'id', 'kind': 'range', 'min': 2, 'max': 2}],
        'created': time.monotonic(),
    }
    yield client, owner, did
    datasets.close_dataset(did)
    agent_mode_api._dashboards.pop(did, None)


def test_agent_download_requires_owner_and_applies_saved_filters(owned_dashboard):
    import gzip
    client, owner, did = owned_dashboard
    ops = agent_mode_api.Operations(owner)
    proposal = ops.prepare_download(did, 'tsv.gz')
    assert proposal['status'] == 'ready_to_download'
    assert ops.downloads == [{'dataset_id': did, 'title': 'Test cohort', 'format': 'tsv.gz'}]
    response = client.post(f'/api/agent/dashboards/{did}/download', json={'format': 'tsv.gz'})
    assert response.status_code == 200, response.text
    assert gzip.decompress(response.content).decode().splitlines() == ['id\tname', '2\tb']
    outsider = TestClient(main.app)
    denied = outsider.post(f'/api/agent/dashboards/{did}/download', json={'format': 'tsv.gz'})
    assert denied.status_code == 404
    with pytest.raises(ValueError):
        agent_mode_api.Operations('outsider').prepare_download(did, 'tsv')
    assert client.post(f'/api/agent/dashboards/{did}/download', json={'format': 'vcf'}).status_code == 400


def test_agent_live_download_starts_under_request_owner(owned_dashboard, monkeypatch):
    client, owner, did = owned_dashboard
    datasets.get(did)['live_source'] = {'resource_id': 'fixture', 'sql': 'SELECT 1', 'columns': {'id': 'id'}}
    observed = {}
    def start(dataset_id, req):
        observed.update(owner=execution.owner_id.get(), filters=[f.model_dump() for f in req.filters], format=req.format)
        return {'id': 'job-1', 'status': 'queued'}
    monkeypatch.setattr(main, 'start_export', start)
    response = client.post(f'/api/agent/dashboards/{did}/download', json={'format': 'tsv'})
    assert response.status_code == 200, response.text
    assert response.json()['job']['id'] == 'job-1'
    assert observed['owner'] == owner
    assert observed['filters'][0]['min'] == 2
    assert observed['format'] == 'tsv'


def test_agent_stream_provides_download_card_without_starting_export(owned_dashboard, monkeypatch):
    from contextlib import nullcontext
    import json
    import studio_agent
    client, owner, did = owned_dashboard
    monkeypatch.setattr(agent_sessions, 'bind', lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(agent_sessions, 'finish', lambda *args: None)
    def chat(message, callbacks, on_step=None):
        proposal = callbacks['prepare_download'](did, 'tsv')
        assert proposal['status'] == 'ready_to_download'
        return {'reply': 'Use the download button.', 'tool_calls': ['prepare_download']}
    monkeypatch.setattr(studio_agent, 'chat', chat)
    response = client.post('/api/agent/chat/stream', json={'message': 'Export TSV'})
    assert response.status_code == 200, response.text
    events = [json.loads(line) for line in response.text.splitlines()]
    result = next(event['result'] for event in events if event['type'] == 'result')
    assert result['downloads'] == [{'dataset_id': did, 'title': 'Test cohort', 'format': 'tsv'}]
