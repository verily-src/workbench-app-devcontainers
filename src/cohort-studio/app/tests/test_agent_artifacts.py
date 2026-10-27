import json

import pytest
import duckdb
import pandas as pd
from sqlalchemy import text

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


def test_restore_uses_postgres_types_not_preview_dtypes(workspace, engine):
    ops = agent_mode_api.Operations('owner-storage-types')
    ref = {'kind': 'aurora', 'resource_id': 'omopdb', 'schema': 'cdm', 'table': 'person'}
    with engine.begin() as conn:
        conn.execute(text('UPDATE cdm.person SET location_id = 42'))
    ops.inspect_table(json.dumps(ref))
    built = ops.build_dashboard(json.dumps(ref), 'People', charts_json='[{"kind":"bar","x":"gender_concept_id"}]')
    saved = agent_artifacts.get(ops.owner, built['dataset_id'])
    assert saved['signature_kind'] == 'postgres-oid-v1'
    with engine.begin() as conn:
        conn.execute(text('UPDATE cdm.person SET location_id = NULL WHERE person_id = '
                          '(SELECT MIN(person_id) FROM cdm.person)'))
    try:
        reopened = ops.open_dashboard(built['dataset_id'])
        assert reopened['total'] == built['total']
        opened = ops.actions[-1]['dataset']
        preview_type = next(c['dtype'] for c in opened['columns'] if c['name'] == 'location_id')
        assert preview_type.startswith('float')
        with engine.begin() as conn:
            conn.execute(text('ALTER TABLE cdm.person ALTER COLUMN location_id TYPE bigint'))
        with pytest.raises(ValueError, match='schema changed'):
            ops.open_dashboard(built['dataset_id'])
    finally:
        with engine.begin() as conn:
            conn.execute(text('ALTER TABLE cdm.person ALTER COLUMN location_id TYPE integer'))
            conn.execute(text('UPDATE cdm.person SET location_id = NULL'))


def test_legacy_recipe_recovers_with_changed_preview_type(workspace, monkeypatch):
    ops = agent_mode_api.Operations('owner-legacy')
    ref = {'kind': 'aurora', 'resource_id': 'omopdb', 'schema': 'cdm', 'table': 'person'}
    ops.inspect_table(json.dumps(ref))
    built = ops.build_dashboard(json.dumps(ref), 'People')
    saved = agent_artifacts.get(ops.owner, built['dataset_id'])
    saved['signature_kind'] = None
    saved['columns'] = [{'name': col['name'], 'dtype': 'legacy-preview'} for col in saved['columns']]
    agent_artifacts.save(ops.owner, saved)
    assert ops.open_dashboard(built['dataset_id'])['total'] == built['total']


def test_disk_source_signature_uses_duckdb_storage_types(tmp_path):
    path = str(tmp_path / 'source.duckdb')
    con = duckdb.connect(path)
    con.execute('CREATE TABLE data (person_id BIGINT, score DECIMAL(8,2))')
    con.execute('INSERT INTO data VALUES (1, 2.50)')
    con.close()
    opened = datasets.open_dataset(pd.DataFrame({'person_id': [1], 'score': [2.5]}),
        'local file', disk_source={'path': path, 'table': 'data'})
    try:
        kind, columns = agent_mode_api._storage_signature(opened['dataset_id'])
        assert kind == 'duckdb-type-v1'
        assert columns == [{'name': 'person_id', 'storage_type': 'BIGINT'},
                           {'name': 'score', 'storage_type': 'DECIMAL(8,2)'}]
    finally:
        datasets.close_dataset(opened['dataset_id'])
