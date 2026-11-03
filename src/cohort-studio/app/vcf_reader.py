"""Bounded prototype for diploid, biallelic SNP hard calls in VCF text."""

from dataclasses import dataclass
from typing import Iterator, TextIO


@dataclass(frozen=True)
class VCFLimits:
    max_bytes: int = 128 * 1024 * 1024
    max_line_bytes: int = 1024 * 1024
    max_samples: int = 5000
    max_records: int = 100_000
    max_calls: int = 1_000_000

    def __post_init__(self):
        if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0
               for value in vars(self).values()):
            raise ValueError('VCF limits must be positive integers.')


@dataclass(frozen=True)
class VCFCall:
    sample_id: str
    chromosome: str
    position: int
    variant_id: str | None
    reference_allele: str
    alternate_allele: str
    genotype: str
    alternate_allele_count: int | None
    site_filter: str


class VCFReader:
    """Parse a narrow VCF subset. Callers must discard output if iteration raises.

    Input is decoded text, including decompressed text if applicable. Only
    diploid, unphased GT calls at biallelic single-base A/C/G/T variants are
    accepted. Other FORMAT fields, including imputed dosage, are rejected.
    A missing ./., represented by None, is never a reference call. QUAL, INFO,
    and header metadata except reference are not retained; this is not a
    lossless VCF round-trip parser.
    """

    def __init__(self, stream: TextIO, limits: VCFLimits | None = None):
        self.stream = stream
        self.limits = limits or VCFLimits()
        self.bytes_read = 0
        self.line_number = 0
        self.samples: tuple[str, ...] = ()
        self.reference: str | None = None
        self._used = False
        self._read_header()

    def _line(self) -> str:
        line = self.stream.readline(self.limits.max_line_bytes + 1)
        if not isinstance(line, str):
            raise ValueError('VCF input must be decoded text.')
        if line:
            self.line_number += 1
            size = len(line.encode('utf-8'))
            self.bytes_read += size
            if size > self.limits.max_line_bytes or self.bytes_read > self.limits.max_bytes:
                raise ValueError('VCF input exceeds the configured byte limit.')
        return line

    def _read_header(self):
        first = self._line().rstrip('\r\n')
        if first not in {f'##fileformat=VCFv4.{version}' for version in range(2, 6)}:
            raise ValueError('Expected a supported VCF version header (4.2 to 4.5).')
        while line := self._line():
            line = line.rstrip('\r\n')
            if line.startswith('##reference='):
                if self.reference is not None:
                    raise ValueError('Duplicate VCF reference metadata.')
                self.reference = line.removeprefix('##reference=') or None
            elif line.startswith('##'):
                continue
            elif line.startswith('#CHROM\t'):
                columns = line.split('\t')
                if columns[:9] != ['#CHROM', 'POS', 'ID', 'REF', 'ALT', 'QUAL',
                                   'FILTER', 'INFO', 'FORMAT']:
                    raise ValueError('Invalid VCF header columns.')
                samples = columns[9:]
                if (not samples or len(samples) > self.limits.max_samples or
                        any(not item or item.strip() != item for item in samples) or
                        len(set(samples)) != len(samples)):
                    raise ValueError('VCF sample IDs must be present, unique and within the sample limit.')
                self.samples = tuple(samples)
                return
            else:
                raise ValueError('Expected the VCF column header.')
        raise ValueError('VCF column header is missing.')

    def __iter__(self) -> Iterator[VCFCall]:
        if self._used:
            raise ValueError('VCF input can only be read once.')
        self._used = True
        records = 0
        while line := self._line():
            records += 1
            if records > self.limits.max_records or records * len(self.samples) > self.limits.max_calls:
                raise ValueError('VCF input exceeds the configured record or call limit.')
            fields = line.rstrip('\r\n').split('\t')
            if len(fields) != 9 + len(self.samples):
                raise ValueError(f'Invalid VCF record width at line {self.line_number}.')
            chrom, pos, vid, ref, alt, _qual, site_filter, _info, fmt, *genotypes = fields
            if not chrom or chrom == '.' or not pos.isascii() or not pos.isdigit() or int(pos) < 1:
                raise ValueError(f'Invalid VCF position at line {self.line_number}.')
            if ref not in 'ACGT' or len(ref) != 1 or alt not in 'ACGT' or len(alt) != 1 or ref == alt:
                raise ValueError(f'Only biallelic A/C/G/T SNPs are supported at line {self.line_number}.')
            if fmt != 'GT':
                raise ValueError(f'Only GT format is supported at line {self.line_number}.')
            values = {'0/0': 0, '0/1': 1, '1/0': 1, '1/1': 2, './.': None}
            if any(gt not in values for gt in genotypes):
                raise ValueError(f'Only unphased diploid GT or fully missing ./., are supported at line {self.line_number}.')
            for sample, gt in zip(self.samples, genotypes):
                yield VCFCall(sample, chrom, int(pos), None if vid == '.' else vid,
                              ref, alt, gt, values[gt], site_filter)
