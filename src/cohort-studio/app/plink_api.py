from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.background import BackgroundTask

import datasets
import disk_data
import execution
from plink_contract import MAX_CALLS, PlinkMapping
from plink_writer import write_plink_zip

router = APIRouter()


class ExportFilter(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    column: str = Field(min_length=1, max_length=512)
    kind: Literal['categorical', 'range']
    values: list[str] | None = Field(default=None, max_length=10000)
    min: float | None = None
    max: float | None = None

    @model_validator(mode='after')
    def valid_filter(self):
        if self.kind == 'categorical' and not self.values:
            raise ValueError('Categorical filters need at least one value.')
        if self.kind == 'range' and (self.min is None or self.max is None or self.min > self.max):
            raise ValueError('Range filters need ordered minimum and maximum.')
        return self


class PlinkExportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    mapping: PlinkMapping
    confirm_hardcalls: Literal[True]
    vcf_filter_policy: Literal['pass_only', 'include_all'] | None = None
    filters: list[ExportFilter] = Field(default_factory=list, max_length=200)


@disk_data._bounded_materialization
@execution.workload('bulk')
def _create_archive(source, filters, mapping, vcf_filter_policy, source_label):
    where, params = disk_data._where(filters, source['columns'])
    names = [mapping.sample_id, mapping.variant_id, mapping.chromosome, mapping.position,
             mapping.reference_allele, mapping.alternate_allele, mapping.alternate_allele_count]
    if any(name not in source['columns'] for name in names):
        raise ValueError('A mapped PLINK column is missing from this dataset.')
    info = source.get('source_info') or {}
    is_vcf = info.get('format') == 'vcf'
    if is_vcf:
        expected = ('sample_id', 'variant_id', 'chromosome', 'position',
                    'reference_allele', 'alternate_allele', 'alternate_allele_count')
        if tuple(names) != expected:
            raise ValueError('VCF export requires the original canonical VCF columns.')
        if any(name not in source['columns'] for name in ('genotype', 'site_filter')):
            raise ValueError('VCF genotype and FILTER columns are required for export.')
        if vcf_filter_policy not in ('pass_only', 'include_all'):
            raise ValueError('Choose whether to export only PASS variants or include all FILTER values.')
        if vcf_filter_policy == 'pass_only':
            where = f'({where}) AND src.{disk_data._q("site_filter")} = ?'
            params.append('PASS')
        names.extend(['genotype', 'site_filter'])
    elif vcf_filter_policy is not None:
        raise ValueError('VCF FILTER policy applies only to an unmodified VCF source.')
    provenance = {'source': source_label, 'format': info.get('format'),
                  'resource_id': info.get('source_resource_id'), 'path': info.get('source_path'),
                  'object_version': info.get('object_version'), 'object_etag': info.get('object_etag'),
                  'reference_header': info.get('reference'), 'declared_reference_build': mapping.reference_build,
                  'reference_verified': False, 'filters': filters, 'vcf_filter_policy': vcf_filter_policy}
    disk_data._budget(int(source.get('scan_bytes') or Path(source['path']).stat().st_size))
    root = Path(tempfile.mkdtemp(prefix='plink-', dir=disk_data._ROOT))
    try:
        archive = root / 'cohort.plink2.zip'
        con = disk_data._connect(source['path'], read_only=True)
        try:
            con.execute('BEGIN TRANSACTION')
            columns = ', '.join(f'src.{disk_data._q(name)}' for name in names)
            table = disk_data._q(source.get('table', 'data'))
            length_limits = [255, 255, 255, 32, 1, 1, 32] + ([3, 4096] if is_vcf else [])
            checks = ' OR '.join(f'LENGTH(CAST(src.{disk_data._q(name)} AS VARCHAR)) > {limit}'
                                 for name, limit in zip(names, length_limits))
            oversized = con.execute(f'SELECT 1 FROM {table} AS src WHERE ({where}) AND ({checks}) LIMIT 1', params).fetchone()
            if oversized:
                raise ValueError('Mapped IDs may contain at most 255 characters; alleles must be single bases.')
            result = con.execute(f'SELECT {columns} FROM {table} AS src WHERE {where} LIMIT {MAX_CALLS + 1}', params)
            def rows():
                while batch := result.fetchmany(2048):
                    disk_data._check_disk_space()
                    for row in batch:
                        values = dict(zip(names, row))
                        if is_vcf:
                            expected_gt = {'0/0': 0, '0/1': 1, '1/0': 1, '1/1': 2, './.': None}
                            gt = values['genotype']
                            if gt not in expected_gt or values['alternate_allele_count'] != expected_gt[gt]:
                                raise ValueError('VCF genotype and ALT hard-call count disagree.')
                            if not isinstance(values['site_filter'], str) or not values['site_filter']:
                                raise ValueError('VCF FILTER must be present for each call.')
                        yield values
            write_plink_zip(rows(), mapping, archive, provenance=provenance)
        finally:
            con.close()
        return archive
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise


@router.post('/api/datasets/{dataset_id}/export/plink2')
def export_plink(dataset_id: str, req: PlinkExportRequest):
    try:
        dataset = datasets.get(dataset_id)
    except datasets.DatasetNotFound as exc:
        raise HTTPException(404, 'Dataset expired or unknown — reload it.') from exc
    if not dataset.get('disk_source'):
        raise HTTPException(400, 'PLINK 2 export currently requires a disk-backed dataset.')
    try:
        path = _create_archive(dataset['disk_source'],
                               [f.model_dump(exclude_none=True) for f in req.filters], req.mapping,
                               req.vcf_filter_policy, dataset['source'])
    except disk_data.OperationTooLarge as exc:
        raise HTTPException(413, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return FileResponse(path, media_type='application/zip', filename='cohort.plink2.zip',
                        background=BackgroundTask(shutil.rmtree, path.parent, True))
