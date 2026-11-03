import gzip
import json

import duckdb
import pytest

import agent_mode_api
import duck
import main


@pytest.mark.parametrize('suffix', ['parquet', 'tsv.gz'])
def test_agent_discovers_inspects_and_opens_s3_file(tmp_path, monkeypatch, suffix):
    path = tmp_path / ('cohort.' + suffix)
    if suffix == 'parquet':
        con = duckdb.connect()
        con.execute(f"COPY (SELECT 1 AS id UNION ALL SELECT 2 AS id) TO '{path}' (FORMAT PARQUET)")
        con.close()
    else:
        with gzip.open(path, 'wt') as stream:
            stream.write('id\n1\n2\n')
    monkeypatch.setattr(main, 'datasources', lambda: {'sources': [{'kind': 's3', 'id': 'fixture'}]})
    monkeypatch.setattr(main, 'tables', lambda kind, rid: [{'name': path.name, 'table': path.name}])
    monkeypatch.setattr(main.disk_data, '_object_size', lambda *_: (path.stat().st_size, str(path), 'us-east-1', False))
    monkeypatch.setattr(duck, '_connect', lambda *args, **kwargs: duckdb.connect())
    monkeypatch.setattr(agent_mode_api.agent_artifacts, 'save', lambda *args, **kwargs: None)
    ops = agent_mode_api.Operations('format-test')
    listing = ops.list_tables('fixture', kind='s3')
    assert listing['tables'][0]['name'] == path.name
    assert '.' + suffix in listing['supported_suffixes']
    ref = {'kind': 's3', 'resource_id': 'fixture', 'table': path.name}
    inspected = ops.inspect_table(json.dumps(ref))
    assert inspected['metadata']['columns'][0]['name'] == 'id'
    result = ops.build_dashboard(json.dumps(ref), 'S3 data')
    try:
        assert result['total'] == 2
        assert ops.query_dashboard(result['dataset_id'])['total'] == 2
    finally:
        main.datasets.close_dataset(result['dataset_id'])
        agent_mode_api._dashboards.pop(result['dataset_id'], None)
