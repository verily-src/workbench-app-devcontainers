"""Validation for a proposed PLINK 2 hard-call export; this does not write files."""
from __future__ import annotations

import re
from numbers import Integral
from typing import Iterable, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_CALLS = 100_000
_ID = re.compile(r'^[^\s\x00-\x1f\x7f]{1,255}$')
_ALLELE = re.compile(r'^[ACGT]$')


class PlinkMapping(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    sample_id: str = Field(min_length=1, max_length=512)
    variant_id: str = Field(min_length=1, max_length=512)
    chromosome: str = Field(min_length=1, max_length=512)
    position: str = Field(min_length=1, max_length=512)
    reference_allele: str = Field(min_length=1, max_length=512)
    alternate_allele: str = Field(min_length=1, max_length=512)
    alternate_allele_count: str = Field(min_length=1, max_length=512)
    genotype_encoding: Literal['unphased_diploid_alt_hardcall']
    reference_build: str = Field(min_length=1, max_length=255)

    @model_validator(mode='after')
    def _validate_mapping(self):
        fields = [self.sample_id, self.variant_id, self.chromosome, self.position,
                  self.reference_allele, self.alternate_allele, self.alternate_allele_count]
        if any(not name.strip() for name in fields) or len(set(fields)) != len(fields):
            raise ValueError('Map each required field to a distinct column.')
        if not _ID.fullmatch(self.reference_build):
            raise ValueError('An explicit reference build without whitespace is required.')
        return self


def validate_plink_hardcalls(rows: Iterable[Mapping], mapping: PlinkMapping) -> dict:
    """Validate complete biallelic SNP hard calls without creating an export."""
    if not isinstance(mapping, PlinkMapping):
        raise TypeError('Pass an explicitly validated PLINK column mapping.')
    samples = set()
    variants = {}
    loci = {}
    reference_by_position = {}
    pairs = set()
    count = missing = 0
    for row in rows:
        count += 1
        if count > MAX_CALLS:
            raise ValueError('PLINK validation exceeds the 100,000-call limit.')
        try:
            sid, vid, chrom, pos, ref, alt, dosage = (row[name] for name in
                (mapping.sample_id, mapping.variant_id, mapping.chromosome, mapping.position,
                 mapping.reference_allele, mapping.alternate_allele, mapping.alternate_allele_count))
        except KeyError as exc:
            raise ValueError('A mapped PLINK input column is missing.') from exc
        if (any(not isinstance(value, str) or not _ID.fullmatch(value) or value.startswith('#') for value in (sid, vid, chrom))
                or sid in {'0', '.'} or vid == '.'):
            raise ValueError('Sample, variant and chromosome IDs must be nonempty and contain no whitespace.')
        if not isinstance(pos, Integral) or isinstance(pos, bool) or pos < 1 or pos > 2_147_483_646:
            raise ValueError('Variant positions must be positive integers.')
        if not isinstance(ref, str) or not isinstance(alt, str) or not _ALLELE.fullmatch(ref) or not _ALLELE.fullmatch(alt) or ref == alt:
            raise ValueError('Only distinct uppercase A/C/G/T SNP alleles are supported.')
        if dosage is not None and (not isinstance(dosage, Integral) or isinstance(dosage, bool) or dosage not in (0, 1, 2)):
            raise ValueError('Hard calls must be 0, 1, 2 or null; fractional dosage and NaN are unsupported.')
        coordinate = (chrom, int(pos))
        if coordinate in reference_by_position and reference_by_position[coordinate] != ref:
            raise ValueError('Conflicting REF alleles at the same genomic position are not supported.')
        reference_by_position[coordinate] = ref
        locus = (chrom, int(pos), ref, alt)
        if vid in variants and variants[vid] != locus:
            raise ValueError('Each variant ID must have one chromosome, position and REF/ALT pair.')
        if locus in loci and loci[locus] != vid:
            raise ValueError('Each chromosome, position and REF/ALT pair must have one variant ID.')
        key = (sid, vid)
        if key in pairs:
            raise ValueError('Duplicate sample and variant calls are not supported.')
        variants[vid], loci[locus] = locus, vid
        samples.add(sid)
        pairs.add(key)
        missing += dosage is None
    if not count:
        raise ValueError('No genotype calls are available.')
    if len(samples) * len(variants) != count:
        raise ValueError('The sample-by-variant matrix is incomplete; missing calls must be explicit nulls.')
    return {'samples': len(samples), 'variants': len(variants), 'calls': count,
            'missing_calls': missing, 'reference_build': mapping.reference_build,
            'encoding': mapping.genotype_encoding, 'allele_counted': 'ALT'}
