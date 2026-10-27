import duckdb
import pandas as pd
import pytest
from sqlalchemy import text

import datasets
import derive
import live_query
import disk_data


@pytest.fixture
def rows():
    return pd.DataFrame({'person_id': pd.Series([1, 1, 2, 3, 3, None], dtype='float64'),
                         'visit_id': [11, 12, 13, 14, 15, 16]})


def check(dataset_id):
    out = derive.derive(dataset_id, {'op': 'group_count', 'name': 'Visits per person', 'column': 'person_id'})
    profile = next(c for c in out['columns'] if c['name'] == 'Visits per person')
    assert profile['filter_kind'] == 'range'
    filters = [{'kind': 'range', 'column': 'Visits per person', 'min': 2, 'max': 9007199254740991}]
    result = datasets.query(dataset_id, filters, [], 0, 20, entity_column='person_id')
    assert result['total'] == 6 and result['filtered'] == 4
    assert result['entity']['filtered'] == 2
    index = result['rows']['columns'].index('visit_id')
    assert sorted(row[index] for row in result['rows']['data']) == [11, 12, 14, 15]
    for op, name, minimum in [('group_sum', 'Sum per person', 25), ('group_mean', 'Mean per person', 14)]:
        derive.derive(dataset_id, {'op': op, 'name': name, 'column': 'person_id', 'measure': 'visit_id'})
        aggregate_filter = [{'kind': 'range', 'column': name, 'min': minimum, 'max': 1.7976931348623157e308}]
        selected = datasets.query(dataset_id, aggregate_filter, [], 0, 20)
        assert selected['filtered'] == 2
        index = selected['rows']['columns'].index('visit_id')
        assert sorted(row[index] for row in selected['rows']['data']) == [14, 15]
    return filters, out


def test_group_count_loaded_rows_and_null_groups(rows):
    opened = datasets.open_dataset(rows, 'loaded')
    try:
        filters, _ = check(opened['dataset_id'])
        assert sorted(datasets.apply_filters(datasets.get(opened['dataset_id'])['df'], filters)['visit_id']) == [11,12,14,15]
    finally:
        datasets.close_dataset(opened['dataset_id'])


def test_group_count_postgres_full_source_and_reopen(rows, engine, monkeypatch):
    import database
    import main
    monkeypatch.setattr(database, 'get_engine_for_resource', lambda rid: engine)
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE public.group_count_test (person_id bigint, visit_id bigint)'))
        conn.execute(text('INSERT INTO public.group_count_test VALUES (1,11),(1,12),(2,13),(3,14),(3,15),(NULL,16)'))
    ref = {'kind': 'aurora', 'resource_id': 'omopdb', 'schema': 'public', 'table': 'group_count_test'}
    opened = main._open_source(ref)
    try:
        filters, out = check(opened['dataset_id'])
        frame = live_query.fetch_frame(datasets.get(opened['dataset_id'])['live_source'], filters, max_rows=100)
        assert sorted(frame['visit_id'].tolist()) == [11,12,14,15]
        reopened = main._open_source(out['source_ref'])
        try:
            result = datasets.query(reopened['dataset_id'], filters, [], 0, 20)
            assert result['filtered'] == 4
        finally:
            datasets.close_dataset(reopened['dataset_id'])
    finally:
        datasets.close_dataset(opened['dataset_id'])
        with engine.begin() as conn:
            conn.execute(text('DROP TABLE public.group_count_test'))


def test_group_count_duckdb_full_source_and_export(rows, tmp_path):
    path = str(tmp_path / 'counts.duckdb')
    con = duckdb.connect(path)
    con.register('frame', rows)
    con.execute('CREATE TABLE data AS SELECT * FROM frame')
    con.close()
    disk = {'path': path, 'table': 'data', 'columns': list(rows.columns), 'rows': len(rows)}
    opened = datasets.open_dataset(rows, 'file', disk_source=disk)
    try:
        filters, _ = check(opened['dataset_id'])
        frame = disk_data.export_frame(datasets.get(opened['dataset_id'])['disk_source'], filters, max_rows=100)
        assert sorted(frame['visit_id'].tolist()) == [11,12,14,15]
    finally:
        datasets.close_dataset(opened['dataset_id'])
