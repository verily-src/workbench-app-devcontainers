import hashlib
import json
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

import datasets
import execution
import operational_store


from count_contract import Definition

def identity(ds):
    ref = ds.get('source_ref') or ds.get('origin')
    if not ref:
        return None
    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items() if k != 'grain'}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value
    return hashlib.sha256(json.dumps(clean(ref), sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def get(dataset_id):
    ds = datasets.get(dataset_id)
    source = identity(ds)
    definition = ds.get('grain') or (ds.get('source_ref') or {}).get('grain')
    if definition is None and source:
        definition = operational_store.store().grain(source)
    if definition:
        parsed = Definition.model_validate(definition).model_dump()
        missing = [k for k in parsed['keys'] if k not in ds['df'].columns]
        return {'definition': parsed, 'persistent': source is not None, 'missing_columns': missing}
    return {'definition': None, 'persistent': source is not None, 'missing_columns': []}


def save(dataset_id, definition):
    parsed = Definition.model_validate(definition).model_dump()
    ds = datasets.get(dataset_id)
    if any(k not in ds['df'].columns for k in parsed['keys']):
        raise ValueError('Key columns must exist in this dataset.')
    source = identity(ds)
    if source:
        operational_store.store().grain(source, parsed)
    ds['grain'] = parsed
    if ds.get('source_ref'):
        ds['source_ref'] = {**ds['source_ref'], 'grain': parsed}
    return {**get(dataset_id), 'source_ref': ds.get('source_ref')}


def _q(value):
    return '"' + value.replace('"', '""') + '"'


def _count_sql(relation, columns):
    projected = ', '.join(f'{_q(column)} AS k{i}' for i, column in enumerate(columns))
    names = ', '.join(f'k{i}' for i in range(len(columns)))
    valid = ' AND '.join(f'k{i} IS NOT NULL' for i in range(len(columns)))
    return (f'SELECT COALESCE(SUM(n),0), COUNT(*) FILTER (WHERE {valid}), '
            f'COALESCE(SUM(n) FILTER (WHERE NOT ({valid})),0) '
            f'FROM (SELECT {names}, COUNT(*) AS n FROM '
            f'(SELECT {projected} FROM {relation}) AS projected GROUP BY {names}) AS grouped')


@execution.workload('interactive')
def check(dataset_id):
    ds = datasets.get(dataset_id)
    metadata = get(dataset_id)
    definition = metadata['definition']
    if not definition:
        raise ValueError('Set the row grain and key columns first.')
    if metadata['missing_columns']:
        raise ValueError('The saved key columns no longer exist. Update the grain definition.')
    keys = definition['keys']
    live = ds.get('live_source')
    disk = ds.get('disk_source')
    if live:
        import database
        import live_query
        import disk_data
        disk_data.guard_live_query(live, [], keys[0])
        with database.get_engine_for_resource(live['resource_id']).begin() as conn:
            conn.exec_driver_sql('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            conn.exec_driver_sql('SET LOCAL search_path = pg_catalog')
            conn.exec_driver_sql('SET LOCAL statement_timeout = 15000')
            sql = _count_sql(f"({live['sql']}) AS src", [live['columns'][k] for k in keys])
            total, distinct, nulls = live_query._query(conn, live, sql, {}).one()
        scope = 'database'
    elif disk:
        import os
        import disk_data
        disk_data._budget(int(disk.get('scan_bytes') or os.path.getsize(disk['path'])) * 2)
        con = disk_data._connect(disk['path'], read_only=True)
        try:
            total, distinct, nulls = con.execute(_count_sql(_q(disk.get('table', 'data')), keys)).fetchone()
        finally:
            con.close()
        scope = 'loaded'
    else:
        frame = ds['df'][keys]
        total = len(frame)
        valid = frame.dropna()
        distinct = len(valid.drop_duplicates())
        nulls = total - len(valid)
        scope = 'sample' if ds.get('capped') else 'loaded'
    total, distinct, nulls = int(total), int(distinct), int(nulls)
    return {**metadata, 'checked_at': datetime.now(timezone.utc).isoformat(), 'scope': scope,
            'rows': total, 'distinct_keys': distinct, 'null_key_rows': nulls,
            'duplicate_key_rows': total - nulls - distinct,
            'status': 'empty' if not total else 'unique_non_null' if total == distinct else 'violated'}
