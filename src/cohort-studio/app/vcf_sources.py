from __future__ import annotations

import gzip
import io
import os
from dataclasses import astuple

import pandas as pd

import duck
import query_cancellation
from vcf_reader import VCFReader


_COLUMNS = ('sample_id', 'chromosome', 'position', 'variant_id', 'reference_allele',
            'alternate_allele', 'genotype', 'alternate_allele_count', 'site_filter')


def open_s3(resource_id: str, filename: str):
    import disk_data

    filename = duck._validate_relative_key(filename)
    client, bucket, key, uri, _, _ = disk_data._s3_client(resource_id, filename)
    try:
        head = client.head_object(Bucket=bucket, Key=key)
        size = int(head['ContentLength'])
    except Exception as exc:
        raise disk_data.SourceSizeUnknown(
            'The S3 object size could not be checked, so Studio cannot safely load it.') from exc
    if size < 0:
        raise disk_data.SourceSizeUnknown('The S3 object size is not available.')
    disk_data._budget(size, size)
    version_id = head.get('VersionId')
    etag = head.get('ETag')
    request = {'Bucket': bucket, 'Key': key}
    if etag:
        request['IfMatch'] = etag
    elif version_id and version_id != 'null':
        request['VersionId'] = version_id
    else:
        raise disk_data.SourceSizeUnknown('The S3 object version could not be checked.')
    try:
        response = client.get_object(**request)
    except Exception as exc:
        raise ValueError('The S3 object could not be read or changed during opening. Check access and retry.') from exc
    version_id = response.get('VersionId') or (version_id if 'VersionId' in request else None)
    body = response['Body']
    path = None
    try:
        if int(response.get('ContentLength', -1)) != size:
            raise ValueError('The S3 object changed while it was being opened. Retry.')
        raw = gzip.GzipFile(fileobj=body, mode='rb') if filename.lower().endswith('.gz') else body
        with io.TextIOWrapper(io.BufferedReader(raw), encoding='utf-8', errors='strict', newline='') as stream:
            reader = VCFReader(stream)
            if (reader.reference is not None and len(reader.reference.encode('utf-8')) > 4096) or any(
                    len(sample.encode('utf-8')) > 4096 for sample in reader.samples):
                raise ValueError('VCF reference and sample identifiers must fit within 4 KB.')
            path = disk_data._new_path()
            con = disk_data._connect(path)
            rows = 0
            materialized_bytes = 0
            try:
                con.execute('CREATE TABLE data (sample_id VARCHAR, chromosome VARCHAR, position BIGINT, '
                            'variant_id VARCHAR, reference_allele VARCHAR, alternate_allele VARCHAR, '
                            'genotype VARCHAR, alternate_allele_count INTEGER, site_filter VARCHAR)')
                batch = []
                variants = set()
                def insert():
                    nonlocal rows, materialized_bytes
                    if not batch:
                        return
                    frame = pd.DataFrame.from_records(batch, columns=_COLUMNS)
                    frame['alternate_allele_count'] = pd.array(frame['alternate_allele_count'], dtype='Int32')
                    materialized_bytes += int(frame.memory_usage(index=False, deep=True).sum())
                    disk_data._actual_budget(size + reader.bytes_read + materialized_bytes)
                    con.register('_studio_vcf_batch', frame)
                    try:
                        con.execute('INSERT INTO data SELECT * FROM _studio_vcf_batch')
                    finally:
                        con.unregister('_studio_vcf_batch')
                    rows += len(batch)
                    batch.clear()
                for call in reader:
                    query_cancellation.check()
                    if any(len(value.encode('utf-8')) > 4096 for value in
                           (call.chromosome, call.variant_id or '', call.site_filter)):
                        raise ValueError('VCF chromosome, variant ID and FILTER must fit within 4 KB.')
                    if call.sample_id == reader.samples[0]:
                        variant = (call.chromosome, call.position, call.reference_allele, call.alternate_allele)
                        if variant in variants:
                            raise ValueError('Duplicate VCF variant records are not supported.')
                        variants.add(variant)
                    batch.append(astuple(call))
                    if len(batch) >= disk_data._BATCH_ROWS:
                        insert()
                insert()
            finally:
                con.close()
            reference = reader.reference
            samples = len(reader.samples)
            expanded_bytes = reader.bytes_read
        frame = disk_data._preview(path)
        info = {
            'format': 'vcf', 'reference': reference,
            'sample_count': samples, 'calls': rows,
            'source_resource_id': resource_id, 'source_path': filename,
            'object_version': version_id, 'object_etag': etag,
            'note': 'VCF 4.2–4.5: unphased diploid GT-only biallelic SNPs. Missing allele counts are null; genotype retains ./.. QUAL and INFO are not retained.',
        }
        return frame, {'path': path, 'table': 'data', 'columns': list(_COLUMNS),
                       'rows': rows, 'estimated_bytes': size,
                       'scan_bytes': os.path.getsize(path), 'large_warning': False,
                       'materialized_bytes': materialized_bytes,
                       'expanded_bytes': expanded_bytes, 'source_info': info}
    except Exception:
        if path:
            disk_data.remove({'path': path})
        raise
    finally:
        body.close()
