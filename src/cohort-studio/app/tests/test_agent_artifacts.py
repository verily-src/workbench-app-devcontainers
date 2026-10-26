import json

import pytest

import agent_artifacts
import agent_mode_api
import datasets
from tests.test_studio_agent_api import workspace
from tests.test_agent_store import agent_store


def test_saved_dashboard_reopens_after_restart_with_filters(workspace):
    ops = agent_mode_api.Operations('owner-artifact')
    ref = {'kind': 'aurora', 'resource_id': 'omopdb', 'schema': 'cdm', 'table': 'person'}
    ops.inspect_table(json.dumps(ref))
    result = ops.build_dashboard(json.dumps(ref), 'Saved women',
        charts_json='[{"kind":"bar","x":"gender_concept_id"}]',
        filters_json='[{"column":"gender_concept_id","kind":"categorical","values":["8532"]}]')
    did = result['dataset_id']
    datasets.close_dataset(did)
    agent_mode_api._dashboards.clear()
    resumed = agent_mode_api.Operations('owner-artifact')
    assert resumed.list_sources()['saved_dashboards'][0]['dataset_id'] == did
    opened = resumed.open_dashboard(did)
    assert opened['dataset_id'] != did
    assert opened['filtered'] == result['filtered']
    assert resumed.actions[0]['title'] == 'Saved women'
    assert resumed.actions[0]['charts'][0]['x'] == 'gender_concept_id'
    assert resumed.actions[0]['filters'][0]['values'] == ['8532']
    with pytest.raises(ValueError, match='your Agent session'):
        agent_mode_api.Operations('other-owner').open_dashboard(did)
    assert agent_artifacts.list_saved('other-owner') == []
    resumed.available.clear()
    with pytest.raises(ValueError, match='workspace'):
        resumed.open_dashboard(did)


def test_changed_schema_rejected_and_opened_dataset_closed(workspace, monkeypatch):
    ops = agent_mode_api.Operations('owner-schema')
    ref = {'kind': 'aurora', 'resource_id': 'omopdb', 'schema': 'cdm', 'table': 'person'}
    ops.inspect_table(json.dumps(ref))
    result = ops.build_dashboard(json.dumps(ref), 'People')
    saved = agent_artifacts.get(ops.owner, result['dataset_id'])
    saved['columns'][0]['name'] = 'removed_column'
    agent_artifacts.save(ops.owner, saved)
    closed = []
    original = datasets.close_dataset
    def close(did):
        closed.append(did)
        original(did)
    monkeypatch.setattr(datasets, 'close_dataset', close)
    with pytest.raises(ValueError, match='schema changed'):
        ops.open_dashboard(result['dataset_id'])
    assert len(closed) == 1
    with pytest.raises(datasets.DatasetNotFound):
        datasets.get(closed[0])


def test_workflow_dashboard_rechecks_results(workspace, monkeypatch):
    ops = agent_mode_api.Operations('owner-result')
    agent_artifacts.save(ops.owner, {'dataset_id': 'abcdef123456', 'title': 'Carrier summary',
        'source_ref': {'kind': 's3', 'resource_id': 'outputs', 'table': 'results.csv'},
        'plan_id': 'saved-plan'})
    calls = []
    def verify(owner, plan_id):
        calls.append((owner, plan_id))
        raise ValueError('Output checksum changed')
    monkeypatch.setattr(agent_mode_api, '_open_workflow_result', verify)
    with pytest.raises(ValueError, match='checksum changed'):
        ops.open_dashboard('abcdef123456')
    assert calls == [(ops.owner, 'saved-plan')]
    assert ops.actions == []
