"""Write a bounded, explicitly mapped PLINK 2 hard-call archive."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from itertools import islice
from pathlib import Path

import numpy as np
import pgenlib

from plink_contract import MAX_CALLS, PlinkMapping, validate_plink_hardcalls


def write_plink_zip(rows, mapping: PlinkMapping, destination: Path, provenance: dict | None = None):
    """Write validated unphased SNP hard calls to a new local archive."""
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError('Destination already exists.')
    if not destination.parent.is_dir():
        raise ValueError('Destination parent directory does not exist.')
    values = list(islice(rows, MAX_CALLS + 1))
    summary = validate_plink_hardcalls(values, mapping)
    if any(row[mapping.chromosome] not in {str(i) for i in range(1, 23)} for row in values):
        raise ValueError('Prototype supports human autosomes 1–22 only; sex chromosomes need ploidy handling.')
    samples = sorted({r[mapping.sample_id] for r in values})
    variants = {r[mapping.variant_id]: (r[mapping.chromosome], int(r[mapping.position]),
                r[mapping.reference_allele], r[mapping.alternate_allele]) for r in values}
    variant_ids = sorted(variants, key=lambda vid: (int(variants[vid][0]), variants[vid][1], vid))
    calls = {(r[mapping.sample_id], r[mapping.variant_id]): r[mapping.alternate_allele_count] for r in values}
    staging = Path(tempfile.mkdtemp(prefix='.plink-stage-', dir=destination.parent))
    try:
        with (staging / 'cohort.psam').open('w', encoding='utf-8', newline='\n') as f:
            f.write('#IID\n')
            for sample in samples:
                f.write(sample + '\n')
        with (staging / 'cohort.pvar').open('w', encoding='utf-8', newline='\n') as f:
            f.write('##INFO=<ID=PR,Number=0,Type=Flag,Description="Provisional REF">\n')
            f.write('#CHROM\tPOS\tID\tREF\tALT\tINFO\n')
            for vid in variant_ids:
                chrom, pos, ref, alt = variants[vid]
                f.write(f'{chrom}\t{pos}\t{vid}\t{ref}\t{alt}\tPR\n')
        pgen = staging / 'cohort.pgen'
        with pgenlib.PgenWriter(os.fsencode(pgen), len(samples), variant_ct=len(variant_ids), nonref_flags=True) as writer:
            for vid in variant_ids:
                vector = np.array([calls[(sid, vid)] if calls[(sid, vid)] is not None else -9
                                   for sid in samples], dtype=np.int8)
                writer.append_biallelic(vector)
        summary['reference_status'] = 'provisional; not verified against a reference genome'
        summary['reference_verified'] = False
        summary['mapping'] = mapping.model_dump()
        if provenance is not None:
            summary['source'] = provenance
        summary['sample_id_policy'] = 'one unique IID per source sample; omitted FID is interpreted as 0 by PLINK 2'
        summary['limitations'] = 'human autosomes 1-22; unphased diploid biallelic SNP hard calls; no INFO, QUAL, FILTER or phenotype metadata'
        (staging / 'manifest.json').write_text(json.dumps(summary, ensure_ascii=False) + '\n', encoding='utf-8')
        bundle = staging / 'bundle.zip'
        with zipfile.ZipFile(bundle, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name in ('cohort.pgen', 'cohort.pvar', 'cohort.psam', 'manifest.json'):
                archive.write(staging / name, arcname=name)
        os.link(bundle, destination)
        return summary
    finally:
        shutil.rmtree(staging, ignore_errors=True)
