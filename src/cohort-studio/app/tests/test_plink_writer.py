import json
import zipfile
from pathlib import Path

import numpy as np
import pgenlib
import pytest

from plink_contract import PlinkMapping
from plink_writer import write_plink_zip

MAPPING = dict(sample_id='s', variant_id='v', chromosome='chr', position='pos',
               reference_allele='ref', alternate_allele='alt', alternate_allele_count='count',
               genotype_encoding='unphased_diploid_alt_hardcall', reference_build='GRCh38')


def calls():
    return [dict(s=sample, v=vid, chr='1', pos=pos, ref=ref, alt=alt, count=count)
            for sample, vid, pos, ref, alt, count in [
                ('S1','rs1',10,'A','G',0),('S2','rs1',10,'A','G',None),
                ('S1','rs2',20,'C','T',1),('S2','rs2',20,'C','T',2)]]


def test_real_pgen_pvar_psam_roundtrip(tmp_path):
    target = tmp_path / 'dataset.zip'
    result = write_plink_zip(calls(), PlinkMapping(**MAPPING), target)
    assert result['missing_calls'] == 1
    extracted = tmp_path / 'extracted'
    with zipfile.ZipFile(target) as archive:
        assert set(archive.namelist()) == {'cohort.pgen','cohort.pvar','cohort.psam','manifest.json'}
        archive.extractall(extracted)
    target = extracted
    assert (target/'cohort.psam').read_text().splitlines() == ['#IID','S1','S2']
    with pgenlib.PvarReader(str(target/'cohort.pvar').encode()) as reader:
        assert reader.get_variant_ct() == 2
        metadata = [(reader.get_variant_chrom(i), reader.get_variant_pos(i), reader.get_variant_id(i),
                     reader.get_allele_code(i, 0), reader.get_allele_code(i, 1)) for i in range(2)]
    assert metadata == [(b'1',10,b'rs1',b'A',b'G'),(b'1',20,b'rs2',b'C',b'T')]
    with pgenlib.PvarReader(str(target/'cohort.pvar').encode()) as pvar, pgenlib.PgenReader(str(target/'cohort.pgen').encode(), raw_sample_ct=2, pvar=pvar) as reader:
        assert reader.get_variant_ct() == 2
        output = np.empty(2, dtype=np.int8)
        reader.read(0, output); assert output.tolist() == [0, -9]
        reader.read(1, output); assert output.tolist() == [1, 2]
        reader.read(1, output, allele_idx=0); assert output.tolist() == [1, 0]
    manifest=json.loads((target/'manifest.json').read_text())
    assert manifest['reference_build']=='GRCh38'
    assert manifest['reference_status'].startswith('provisional')


def test_invalid_input_never_creates_output_or_partial_files(tmp_path):
    target = tmp_path / 'dataset'
    with pytest.raises(ValueError, match='incomplete'):
        write_plink_zip(calls()[:-1], PlinkMapping(**MAPPING), target)
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_writer_failure_cleans_staging_and_refuses_existing_target(tmp_path, monkeypatch):
    target = tmp_path / 'dataset'
    def broken(*args, **kwargs): raise RuntimeError('writer failed')
    monkeypatch.setattr(pgenlib, 'PgenWriter', broken)
    with pytest.raises(RuntimeError, match='writer failed'):
        write_plink_zip(calls(), PlinkMapping(**MAPPING), target)
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []
    target.write_text('keep')
    with pytest.raises(FileExistsError):
        write_plink_zip(calls(), PlinkMapping(**MAPPING), target)
    assert target.read_text() == 'keep'


def test_sex_chromosome_requires_ploidy_handling(tmp_path):
    rows = calls()
    for row in rows: row['chr'] = 'X'
    with pytest.raises(ValueError, match='autosomes'):
        write_plink_zip(rows, PlinkMapping(**MAPPING), tmp_path / 'dataset')
    assert list(tmp_path.iterdir()) == []


def test_variants_are_sorted_by_numeric_autosome(tmp_path):
    rows = [dict(s='S1', v='v10', chr='10', pos=1, ref='A', alt='G', count=0),
            dict(s='S1', v='v2', chr='2', pos=1, ref='A', alt='G', count=1)]
    target = tmp_path/'dataset.zip'
    write_plink_zip(rows, PlinkMapping(**MAPPING), target)
    with zipfile.ZipFile(target) as archive:
        lines = archive.read('cohort.pvar').decode().splitlines()
    assert [line.split('\t')[0] for line in lines if not line.startswith('#')] == ['2','10']
