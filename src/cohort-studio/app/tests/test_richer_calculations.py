import duckdb
import pandas as pd
import pytest
from sqlalchemy import text

import calculations
import database
import datasets
import derive
import main
from source_models import source_dict


ROWS = pd.DataFrame({'row_id': [1, 2, 3, 4, 5], 'cohort': ['A', 'A', 'A', 'B', None],
                     'site': [1, 1, 2, 1, 1], 'value': ['4', None, '-9', '16', '2'],
                     'offset': [2, -2, 3, 4, 5]})


def check(dataset_id):
    derive.derive(dataset_id, {'op': 'expression', 'name': 'score',
        'expression': '(coalesce(col("value"), 0) + abs(offset)) / 2'})
    derive.derive(dataset_id, {'op': 'expression', 'name': 'root',
        'expression': 'sqrt(col("value")) + ln(col("value"))'})
    derive.derive(dataset_id, {'op': 'expression', 'name': 'invalid root', 'expression': 'sqrt(-1)'})
    derive.derive(dataset_id, {'op': 'expression', 'name': 'zero division', 'expression': '1 / (offset - offset)'})
    for op in ('group_count', 'group_min', 'group_max', 'group_mean'):
        spec = {'op': op, 'name': op, 'column': 'cohort', 'group_by': ['cohort', 'site']}
        if op != 'group_count': spec['measure'] = 'value'
        derived = derive.derive(dataset_id, spec)
    result = datasets.query(dataset_id, [], [], 0, 20)
    columns = result['rows']['columns']
    rows = {row[columns.index('row_id')]: dict(zip(columns, row)) for row in result['rows']['data']}
    assert [rows[i]['score'] for i in range(1, 6)] == [3, 1, -3, 10, 3.5]
    assert rows[1]['root'] == pytest.approx(3.3862943611)
    assert rows[2]['root'] is None and rows[3]['root'] is None
    assert all(row['invalid root'] is None and row['zero division'] is None for row in rows.values())
    assert rows[1]['group_count'] == rows[2]['group_count'] == 2
    assert rows[1]['group_min'] == rows[1]['group_max'] == rows[1]['group_mean'] == 4
    assert rows[3]['group_count'] == 1 and rows[3]['group_min'] == -9
    assert rows[5]['group_count'] is None
    return derived


def check_more_aggregates(dataset_id):
    for op in ('group_max', 'group_mean', 'group_sum'):
        derive.derive(dataset_id, {'op': op, 'name': op, 'column': 'cohort',
            'group_by': ['cohort', 'site'], 'measure': 'value'})
    rows = datasets.query(dataset_id, [], [], 0, 20)['rows']
    values = {row[rows['columns'].index('row_id')]: dict(zip(rows['columns'], row)) for row in rows['data']}
    assert values[1]['group_max'] == values[1]['group_mean'] == values[1]['group_sum'] == 4
    assert values[3]['group_max'] == values[3]['group_sum'] == -9
    assert values[5]['group_max'] is None


def test_loaded_calculations():
    opened = datasets.open_dataset(ROWS.copy(), 'memory')
    try: check(opened['dataset_id'])
    finally: datasets.close_dataset(opened['dataset_id'])
    opened = datasets.open_dataset(ROWS.copy(), 'memory')
    try: check_more_aggregates(opened['dataset_id'])
    finally: datasets.close_dataset(opened['dataset_id'])


def test_postgres_calculations_and_recipe(engine, monkeypatch):
    monkeypatch.setattr(database, 'get_engine_for_resource', lambda rid: engine)
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE public.calc_rich_test (row_id integer, cohort text, site integer, value text, "offset" integer)'))
        conn.execute(text("INSERT INTO public.calc_rich_test VALUES (1,'A',1,'4',2),(2,'A',1,NULL,-2),(3,'A',2,'-9',3),(4,'B',1,'16',4),(5,NULL,1,'2',5)"))
    ref = {'kind': 'aurora', 'resource_id': 'omopdb', 'schema': 'public', 'table': 'calc_rich_test'}
    opened = main._open_source(ref)
    try:
        result = check(opened['dataset_id'])
        reopened = main._open_source(result['source_ref'])
        try:
            rows = datasets.query(reopened['dataset_id'], [], [], 0, 20)['rows']
            assert 'score' in rows['columns'] and 'group_max' in rows['columns']
        finally: datasets.close_dataset(reopened['dataset_id'])
        more = main._open_source(ref)
        try: check_more_aggregates(more['dataset_id'])
        finally: datasets.close_dataset(more['dataset_id'])
    finally:
        datasets.close_dataset(opened['dataset_id'])
        with engine.begin() as conn: conn.execute(text('DROP TABLE public.calc_rich_test'))


def test_duckdb_calculations(tmp_path):
    path = str(tmp_path / 'calc.duckdb')
    con = duckdb.connect(path); con.register('frame', ROWS)
    con.execute('CREATE TABLE data AS SELECT * FROM frame'); con.close()
    source = {'path': path, 'table': 'data', 'columns': list(ROWS.columns), 'rows': len(ROWS)}
    opened = datasets.open_dataset(ROWS.copy(), 'disk', disk_source=source)
    try: check(opened['dataset_id'])
    finally: datasets.close_dataset(opened['dataset_id'])
    more = datasets.open_dataset(ROWS.copy(), 'disk', disk_source=source)
    try: check_more_aggregates(more['dataset_id'])
    finally: datasets.close_dataset(more['dataset_id'])


@pytest.mark.parametrize('expression', ["__import__('os')", 'value.__class__', 'value ** 2',
    'col("value") + unknown', '1e999', 'sqrt(1, 2)', 'value; DROP TABLE x'])
def test_unsafe_or_invalid_expressions_are_rejected(expression):
    with pytest.raises(ValueError): calculations.parse(expression, ROWS.columns)


def test_source_steps_remain_bounded():
    ref = {'kind': 'aurora', 'resource_id': 'omopdb', 'schema': 'public', 'table': 'person'}
    for index in range(15):
        ref = {'kind': 'derived', 'base': ref, 'spec': {'op': 'expression', 'name': f'c{index}', 'expression': '1'}}
    source_dict(ref)
    ref = {'kind': 'derived', 'base': ref, 'spec': {'op': 'expression', 'name': 'extra', 'expression': '1'}}
    with pytest.raises(ValueError, match='16 source steps'):
        source_dict(ref)

