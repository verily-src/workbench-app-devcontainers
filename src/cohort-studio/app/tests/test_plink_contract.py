import math
import pytest
from pydantic import ValidationError

from plink_contract import PlinkMapping, validate_plink_hardcalls

MAPPING = dict(sample_id='s', variant_id='v', chromosome='chr', position='pos',
               reference_allele='ref', alternate_allele='alt', alternate_allele_count='count',
               genotype_encoding='unphased_diploid_alt_hardcall', reference_build='GRCh38')


def calls():
    return [dict(s=sample, v=vid, chr='1', pos=pos, ref='A', alt='G', count=count)
            for sample, vid, pos, count in [('S1','rs1',10,0),('S2','rs1',10,None),
                                             ('S1','rs2',20,1),('S2','rs2',20,2)]]


def test_preserves_missing_and_explicit_allele_semantics():
    summary = validate_plink_hardcalls(calls(), PlinkMapping(**MAPPING))
    assert summary == {'samples':2,'variants':2,'calls':4,'missing_calls':1,
                       'reference_build':'GRCh38', 'encoding':'unphased_diploid_alt_hardcall','allele_counted':'ALT'}


@pytest.mark.parametrize('value', [0.5, 1.0, float('nan'), True, '1', -1, 3])
def test_rejects_dosage_interpretation_or_coercion(value):
    rows = calls(); rows[0]['count'] = value
    with pytest.raises(ValueError, match='Hard calls'):
        validate_plink_hardcalls(rows, PlinkMapping(**MAPPING))


def test_missing_rows_are_not_assumed_reference_or_missing():
    with pytest.raises(ValueError, match='incomplete'):
        validate_plink_hardcalls(calls()[:-1], PlinkMapping(**MAPPING))


@pytest.mark.parametrize('change', [dict(ref='G'), dict(alt='C'), dict(pos=11), dict(chr='2')])
def test_rejects_inconsistent_variant_metadata(change):
    rows = calls(); rows[1].update(change)
    with pytest.raises(ValueError):
        validate_plink_hardcalls(rows, PlinkMapping(**MAPPING))


def test_rejects_duplicate_calls_or_loci():
    rows = calls(); rows.append(rows[0])
    with pytest.raises(ValueError, match='Duplicate'):
        validate_plink_hardcalls(rows, PlinkMapping(**MAPPING))
    rows = calls(); rows[2].update(v='rs3', pos=10)
    with pytest.raises(ValueError):
        validate_plink_hardcalls(rows, PlinkMapping(**MAPPING))


def test_requires_explicit_distinct_mapping_and_reference_build():
    with pytest.raises(ValidationError): PlinkMapping(**{**MAPPING,'alternate_allele_count':'v'})
    with pytest.raises(ValidationError): PlinkMapping(**{**MAPPING,'reference_build':'  '})
    with pytest.raises(ValidationError): PlinkMapping(**{**MAPPING,'genotype_encoding':'dosage'})
    with pytest.raises(ValueError, match='missing'):
        validate_plink_hardcalls([{'s':'S1'}], PlinkMapping(**MAPPING))
