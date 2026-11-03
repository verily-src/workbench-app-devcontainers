import gzip
import io
import json

from botocore.response import StreamingBody
from fastapi.testclient import TestClient
import pytest

import agent_mode_api
import datasets
import disk_data
import duck
import main
import vcf_reader

HEADER = ('##fileformat=VCFv4.2\n##reference=GRCh38\n'
          '#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\tS2\n')
ROW = '1\t42\trs42\tA\tG\t.\tPASS\t.\tGT\t0/1\t./.\n'


class S3:
    def __init__(self, content):
        self.content = content
        self.request = None
        self.stream = None
    def head_object(self, **kwargs):
        return {'ContentLength': len(self.content), 'ETag': '"etag"', 'VersionId': 'ver-1'}
    def get_object(self, **kwargs):
        self.request = kwargs
        self.stream = StreamingBody(io.BytesIO(self.content), len(self.content))
        return {'Body': self.stream, 'ContentLength': len(self.content)}


@pytest.fixture
def make_client(monkeypatch):
    monkeypatch.setattr(main, '_lineage_engine', lambda: None)
    monkeypatch.setattr(main.lineage, 'record', lambda *a, **k: None)
    return TestClient(main.app)


@pytest.mark.parametrize('extension', ['vcf', 'vcf.gz'])
def test_open_s3_vcf_and_query_preserves_missing_calls_and_provenance(make_client, monkeypatch, extension):
    content = (HEADER + ROW).encode()
    if extension.endswith('.gz'):
        content = gzip.compress(content)
    s3 = S3(content)
    monkeypatch.setattr(disk_data, '_s3_client', lambda *a: (s3, 'bucket', 'key', 's3://bucket/key', 'us-east-1', False))
    name = 'genetics.' + extension
    assert name in duck.parse_s3_ls(f'2026-11-03 12:00:00 100 {name}')
    response = make_client.post('/api/datasets/open', json={'kind': 's3', 'resource_id': 'fixture', 'table': name})
    assert response.status_code == 200, response.text
    did = response.json()['dataset_id']
    try:
        assert s3.request['IfMatch'] == '"etag"'
        assert 'VersionId' not in s3.request
        info = response.json()['source_info']
        assert info['reference'] == 'GRCh38' and info['calls'] == 2
        assert info['source_resource_id'] == 'fixture' and info['source_path'] == name
        assert 'QUAL and INFO are not retained' in info['note']
        result = make_client.post(f'/api/datasets/{did}/query', json={})
        assert result.status_code == 200, result.text
        data = [dict(zip(result.json()['rows']['columns'], row)) for row in result.json()['rows']['data']]
        assert [(x['sample_id'], x['alternate_allele_count']) for x in data] == [('S1', 1), ('S2', None)]
    finally:
        make_client.delete(f'/api/datasets/{did}')


def test_invalid_late_record_does_not_leave_staged_database(make_client, monkeypatch, tmp_path):
    monkeypatch.setattr(disk_data, '_ROOT', tmp_path)
    records = ''.join(ROW.replace('\t42\t', f'\t{i + 1}\t') for i in range(1025))
    s3 = S3((HEADER + records + ROW.replace('\t42\t', '\t1026\t').replace('0/1', '0|1')).encode())
    monkeypatch.setattr(disk_data, '_s3_client', lambda *a: (s3, 'bucket', 'key', 's3://bucket/key', 'us-east-1', False))
    response = make_client.post('/api/datasets/open', json={'kind': 's3', 'resource_id': 'fixture', 'table': 'invalid.vcf'})
    assert response.status_code == 400, response.text
    assert 'unphased' in response.text
    assert list(tmp_path.iterdir()) == []


def test_oversized_decompressed_vcf_rejected_and_cleaned(make_client, monkeypatch, tmp_path):
    monkeypatch.setattr(disk_data, '_ROOT', tmp_path)
    original = vcf_reader.VCFLimits
    monkeypatch.setattr(vcf_reader, 'VCFLimits', lambda: original(max_bytes=100))
    s3 = S3(gzip.compress((HEADER + ROW * 100).encode()))
    monkeypatch.setattr(disk_data, '_s3_client', lambda *a: (s3, 'bucket', 'key', 's3://bucket/key', 'us-east-1', False))
    response = make_client.post('/api/datasets/open', json={'kind': 's3', 'resource_id': 'fixture', 'table': 'oversized.vcf.gz'})
    assert response.status_code == 400, response.text
    assert 'byte limit' in response.text
    assert list(tmp_path.iterdir()) == []


def test_agent_inspects_and_opens_vcf_with_explicit_scope(make_client, monkeypatch):
    s3 = S3((HEADER + ROW).encode())
    monkeypatch.setattr(disk_data, '_s3_client', lambda *a: (s3, 'bucket', 'key', 's3://bucket/key', 'us-east-1', False))
    monkeypatch.setattr(main, 'datasources', lambda: {'sources': [{'kind': 's3', 'id': 'fixture'}]})
    monkeypatch.setattr(main, 'tables', lambda kind, rid: [{'name': 'genetics.vcf', 'table': 'genetics.vcf'}])
    monkeypatch.setattr(agent_mode_api.agent_artifacts, 'save', lambda *a, **k: None)
    ops = agent_mode_api.Operations('vcf-owner')
    assert '.vcf' in ops.list_tables('fixture', kind='s3')['supported_suffixes']
    ref = {'kind': 's3', 'resource_id': 'fixture', 'table': 'genetics.vcf'}
    inspected = ops.inspect_table(json.dumps(ref))
    assert inspected['metadata']['source_info']['reference'] == 'GRCh38'
    result = ops.build_dashboard(json.dumps(ref), 'Genetics')
    try:
        assert result['total'] == 2
        assert ops.actions[0]['dataset']['source_info']['calls'] == 2
    finally:
        datasets.close_dataset(result['dataset_id'])
        agent_mode_api._dashboards.pop(result['dataset_id'], None)


def test_duplicate_variant_fails_without_staging(make_client, monkeypatch, tmp_path):
    monkeypatch.setattr(disk_data, '_ROOT', tmp_path)
    s3 = S3((HEADER + ROW + ROW).encode())
    monkeypatch.setattr(disk_data, '_s3_client', lambda *a: (s3, 'bucket', 'key', 's3://bucket/key', 'us-east-1', False))
    response = make_client.post('/api/datasets/open', json={'kind': 's3', 'resource_id': 'fixture', 'table': 'duplicate.vcf'})
    assert response.status_code == 400, response.text
    assert 'Duplicate VCF' in response.text
    assert list(tmp_path.iterdir()) == []


def test_generic_duckdb_reader_never_misreads_vcf_as_csv():
    with pytest.raises(ValueError, match='VCF files must be opened'):
        duck._reader_sql('s3://bucket/genetics.vcf.gz')


def test_rejects_oversized_sample_name_before_staging(make_client, monkeypatch, tmp_path):
    monkeypatch.setattr(disk_data, '_ROOT', tmp_path)
    header = HEADER.replace('S1\tS2', ('A' * 5000) + '\tS2')
    s3 = S3((header + ROW).encode())
    monkeypatch.setattr(disk_data, '_s3_client', lambda *a: (s3, 'bucket', 'key', 's3://bucket/key', 'us-east-1', False))
    response = make_client.post('/api/datasets/open', json={'kind': 's3', 'resource_id': 'fixture', 'table': 'large.vcf'})
    assert response.status_code == 400, response.text
    assert '4 KB' in response.text
    assert list(tmp_path.iterdir()) == []


def test_empty_vcf_opens_with_stable_columns(make_client, monkeypatch):
    s3 = S3(HEADER.encode())
    monkeypatch.setattr(disk_data, '_s3_client', lambda *a: (s3, 'bucket', 'key', 's3://bucket/key', 'us-east-1', False))
    response = make_client.post('/api/datasets/open', json={'kind': 's3', 'resource_id': 'fixture', 'table': 'empty.vcf'})
    assert response.status_code == 200, response.text
    did = response.json()['dataset_id']
    try:
        assert response.json()['source_info']['calls'] == 0
        assert 'alternate_allele_count' in [col['name'] for col in response.json()['columns']]
    finally:
        make_client.delete(f'/api/datasets/{did}')
