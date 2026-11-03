import io
import json
import zipfile

import duckdb
import numpy as np
import pandas as pd
import pgenlib
import pytest
from fastapi.testclient import TestClient

import datasets
import main

MAPPING = dict(sample_id='sample_id', variant_id='variant_id', chromosome='chromosome', position='position',
               reference_allele='reference_allele', alternate_allele='alternate_allele',
               alternate_allele_count='alternate_allele_count', genotype_encoding='unphased_diploid_alt_hardcall',
               reference_build='GRCh38')


@pytest.fixture
def opened(tmp_path):
    path = str(tmp_path/'source.duckdb')
    conn = duckdb.connect(path)
    conn.execute('CREATE TABLE data (sample_id VARCHAR, chromosome VARCHAR, position BIGINT, variant_id VARCHAR, '
                 'reference_allele VARCHAR, alternate_allele VARCHAR, alternate_allele_count INTEGER)')
    conn.executemany('INSERT INTO data VALUES (?, ?, ?, ?, ?, ?, ?)', [
        ['S1','1',10,'rs1','A','G',0], ['S2','1',10,'rs1','A','G',None],
        ['S1','1',20,'rs2','C','T',1], ['S2','1',20,'rs2','C','T',2]])
    frame = conn.execute('SELECT * FROM data').df()
    conn.close()
    columns = list(frame.columns)
    did = datasets.open_dataset(frame, 'source', disk_source={'path':path,'table':'data','columns':columns})['dataset_id']
    yield did
    datasets.close_dataset(did)


def test_download_real_plink_zip_and_preserve_filtered_scope(opened, tmp_path, monkeypatch):
    import disk_data
    monkeypatch.setattr(disk_data, '_ROOT', tmp_path)
    client = TestClient(main.app)
    response = client.post(f'/api/datasets/{opened}/export/plink2', json={'mapping': MAPPING, 'confirm_hardcalls': True,
        'filters': [{'column':'position','kind':'range','min':10,'max':20}]})
    assert response.status_code == 200, response.text
    assert 'cohort.plink2.zip' in response.headers['content-disposition']
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist()) == {'cohort.pgen','cohort.pvar','cohort.psam','manifest.json'}
        archive.extractall(tmp_path/'out')
    out=tmp_path/'out'
    assert (out/'cohort.psam').read_text().splitlines() == ['#IID','S1','S2']
    with pgenlib.PvarReader(str(out/'cohort.pvar').encode()) as pvar:
        assert [(pvar.get_variant_id(i),pvar.get_allele_code(i,0),pvar.get_allele_code(i,1)) for i in range(2)] == [(b'rs1',b'A',b'G'),(b'rs2',b'C',b'T')]
        with pgenlib.PgenReader(str(out/'cohort.pgen').encode(),pvar=pvar) as reader:
            vector=np.empty(2, dtype=np.int8)
            reader.read(0,vector); assert vector.tolist()==[0,-9]
            reader.read(1,vector); assert vector.tolist()==[1,2]
    assert json.loads((out/'manifest.json').read_text())['reference_status'].startswith('provisional')
    assert not list(tmp_path.glob('plink-*'))


def test_invalid_mapping_and_incomplete_filter_never_download(opened):
    client=TestClient(main.app)
    request={'mapping':MAPPING,'confirm_hardcalls':True}
    assert client.post(f'/api/datasets/{opened}/export/plink2',json={**request, 'confirm_hardcalls':False}).status_code == 422
    invalid={**MAPPING,'reference_build':''}
    assert client.post(f'/api/datasets/{opened}/export/plink2',json={**request,'mapping':invalid}).status_code == 422
    request['filters']=[{'column':'alternate_allele_count','kind':'range','min':0,'max':2}]
    response = client.post(f'/api/datasets/{opened}/export/plink2',json=request)
    assert response.status_code == 400 and 'incomplete' in response.text


def test_wide_mapped_values_are_rejected_before_export(opened):
    import disk_data
    source = datasets.get(opened)['disk_source']
    conn = disk_data._connect(source['path'])
    try: conn.execute("UPDATE data SET sample_id = repeat('A', 100000) WHERE sample_id = 'S1'")
    finally: conn.close()
    response = TestClient(main.app).post(f'/api/datasets/{opened}/export/plink2', json={'mapping':MAPPING,'confirm_hardcalls':True})
    assert response.status_code == 400
    assert '255 characters' in response.text


def set_vcf_source(did):
    import disk_data
    source = datasets.get(did)['disk_source']
    conn = disk_data._connect(source['path'])
    try:
        conn.execute('ALTER TABLE data ADD COLUMN genotype VARCHAR')
        conn.execute('ALTER TABLE data ADD COLUMN site_filter VARCHAR')
        conn.execute("UPDATE data SET genotype = CASE alternate_allele_count WHEN 0 THEN '0/0' WHEN 1 THEN '0/1' WHEN 2 THEN '1/1' ELSE './.' END, site_filter='PASS'")
    finally:
        conn.close()
    source['columns'].extend(['genotype','site_filter'])
    source['source_info'] = {'format':'vcf','reference':'GRCh37', 'source_resource_id':'lake',
                             'source_path':'g.vcf.gz','object_version':'version-1','object_etag':'etag'}
    return source


def test_vcf_requires_canonical_mapping_and_explicit_filter_policy(opened):
    source = set_vcf_source(opened)
    client = TestClient(main.app)
    request={'mapping': MAPPING,'confirm_hardcalls':True}
    response = client.post(f'/api/datasets/{opened}/export/plink2', json=request)
    assert response.status_code == 400 and 'Choose whether' in response.text
    swapped={**MAPPING, 'reference_allele':'alternate_allele', 'alternate_allele':'reference_allele'}
    response = client.post(f'/api/datasets/{opened}/export/plink2', json={**request,'mapping':swapped,'vcf_filter_policy':'include_all'})
    assert response.status_code == 400 and 'canonical' in response.text


def test_vcf_filter_policy_and_reference_provenance(opened, tmp_path):
    import disk_data
    source = set_vcf_source(opened)
    con=disk_data._connect(source['path'])
    try: con.execute("UPDATE data SET site_filter='q10' WHERE variant_id='rs2'")
    finally: con.close()
    client=TestClient(main.app)
    request={'mapping':MAPPING,'confirm_hardcalls':True}
    def fetch(policy):
        response=client.post(f'/api/datasets/{opened}/export/plink2',json={**request,'vcf_filter_policy':policy})
        assert response.status_code == 200, response.text
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            return json.loads(archive.read('manifest.json'))
    safe=fetch('pass_only'); include=fetch('include_all')
    assert safe['variants']==1 and include['variants']==2
    assert safe['source']['vcf_filter_policy']=='pass_only'
    assert safe['source']['resource_id']=='lake' and safe['source']['path']=='g.vcf.gz'
    assert safe['source']['object_version']=='version-1' and safe['source']['object_etag']=='etag'
    assert safe['source']['reference_header']=='GRCh37'
    assert safe['source']['declared_reference_build']=='GRCh38' and safe['source']['reference_verified'] is False


def test_vcf_mismatched_genotype_never_exports(opened):
    import disk_data
    source=set_vcf_source(opened)
    con=disk_data._connect(source['path'])
    try: con.execute("UPDATE data SET genotype='1/1' WHERE sample_id='S1' AND variant_id='rs2'")
    finally: con.close()
    response=TestClient(main.app).post(f'/api/datasets/{opened}/export/plink2',json={'mapping':MAPPING,'confirm_hardcalls':True,'vcf_filter_policy':'include_all'})
    assert response.status_code == 400 and 'disagree' in response.text


def test_conflicting_reference_at_same_position_fails(opened):
    import disk_data
    source=datasets.get(opened)['disk_source']
    con=disk_data._connect(source['path'])
    try: con.execute("UPDATE data SET position=10 WHERE variant_id='rs2'")
    finally: con.close()
    response=TestClient(main.app).post(f'/api/datasets/{opened}/export/plink2',json={'mapping':MAPPING,'confirm_hardcalls':True})
    assert response.status_code == 400 and 'Conflicting REF' in response.text


def test_open_vcf_then_export_plink_with_missing_call(tmp_path, monkeypatch):
    from botocore.response import StreamingBody
    import disk_data
    raw = (b'##fileformat=VCFv4.2\n##reference=GRCh38\n'
           b'#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\tS2\n'
           b'1\t10\trs1\tA\tG\t.\tPASS\t.\tGT\t0/1\t./.\n')
    class S3:
        def head_object(self, **kwargs):
            return {'ContentLength': len(raw), 'ETag': '"etag"'}
        def get_object(self, **kwargs):
            return {'Body': StreamingBody(io.BytesIO(raw), len(raw)), 'ContentLength': len(raw)}
    monkeypatch.setattr(disk_data, '_s3_client', lambda *args: (S3(), 'bucket', 'key', 's3://bucket/key', 'us-east-1', False))
    client = TestClient(main.app)
    opened = client.post('/api/datasets/open', json={'kind': 's3', 'resource_id': 'fixture', 'table': 'input.vcf'})
    assert opened.status_code == 200, opened.text
    did = opened.json()['dataset_id']
    try:
        response = client.post(f'/api/datasets/{did}/export/plink2', json={
            'mapping': MAPPING, 'confirm_hardcalls': True, 'vcf_filter_policy': 'pass_only'})
        assert response.status_code == 200, response.text
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            archive.extractall(tmp_path/'vcf-out')
        out = tmp_path/'vcf-out'
        with pgenlib.PvarReader(str(out/'cohort.pvar').encode()) as pvar:
            with pgenlib.PgenReader(str(out/'cohort.pgen').encode(), pvar=pvar) as reader:
                vector = np.empty(2, dtype=np.int8)
                reader.read(0, vector)
                assert vector.tolist() == [1, -9]
        assert json.loads((out/'manifest.json').read_text())['source']['reference_header'] == 'GRCh38'
    finally:
        datasets.close_dataset(did)
