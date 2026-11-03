import gzip
import io

import pytest

from vcf_reader import VCFReader, VCFLimits


HEADER = ('##fileformat=VCFv4.2\n##reference=GRCh38\n'
          '#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\tS2\n')


def row(alt='G', fmt='GT', first='0/1', second='./.'):
    return f'1\t42\trs42\tA\t{alt}\t.\tPASS\t.\t{fmt}\t{first}\t{second}\n'


def test_reads_compressed_vcf_hard_calls_without_fabricating_missing(tmp_path):
    path = tmp_path / 'samples.vcf.gz'
    with gzip.open(path, 'wt', encoding='utf-8') as stream:
        stream.write(HEADER + row() + row(first='1/1', second='1/0'))
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        reader = VCFReader(stream)
        assert reader.reference == 'GRCh38'
        calls = list(reader)
    assert [(c.sample_id, c.genotype, c.alternate_allele_count) for c in calls] == [
        ('S1', '0/1', 1), ('S2', './.', None), ('S1', '1/1', 2), ('S2', '1/0', 1)]
    assert (calls[0].chromosome, calls[0].position, calls[0].variant_id,
            calls[0].reference_allele, calls[0].alternate_allele, calls[0].site_filter) == (
                '1', 42, 'rs42', 'A', 'G', 'PASS')
    with pytest.raises(ValueError, match='only be read once'):
        list(reader)


@pytest.mark.parametrize('record', [
    row(alt='G,T'), row(alt='<DEL>'), row(first='0|1'), row(first='./1'),
    row(first='1'), row(fmt='GT:DS', first='0/1:0.7', second='./.:.'),
])
def test_rejects_calls_that_need_different_semantics(record):
    with pytest.raises(ValueError):
        list(VCFReader(io.StringIO(HEADER + record)))


def test_bounds_and_duplicate_samples_are_enforced():
    with pytest.raises(ValueError, match='sample'):
        VCFReader(io.StringIO(HEADER.replace('\tS1\tS2', '\tS1\tS1')))
    with pytest.raises(ValueError, match='call limit'):
        list(VCFReader(io.StringIO(HEADER + row()), VCFLimits(max_calls=1)))
    with pytest.raises(ValueError, match='byte limit'):
        list(VCFReader(io.StringIO(HEADER + row()), VCFLimits(max_bytes=len(HEADER) + 4)))
    with pytest.raises(ValueError, match='positive integers'):
        VCFLimits(max_calls=0)
