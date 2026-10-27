import duckdb
import pandas as pd
import pytest
from sqlalchemy import text
from pydantic import ValidationError

import datasets
import group_summary


@pytest.fixture
def frame():
    return pd.DataFrame({'group': ['A', 'A', 'B', None, 'B'], 'part': [1, 1, 2, 1, 2], 'value': ['1', '3', 'bad', '4', None]})


def verify(dataset_id):
    summarize = lambda **kw: group_summary.summarize(dataset_id, {'group_by': ['group'], 'measure': 'value', **kw})
    result = summarize(page_size=1)
    assert result['total_groups'] == 3 and result['input_rows'] == 5
    assert result['rows'] == [['A', 2, 2, 4, 2, 1, 3]]
    assert summarize(page_size=1, page=1)['rows'] == [['B', 2, 0, None, None, None, None]]
    assert summarize(page_size=1, page=2)['rows'] == [[None, 1, 1, 4, 4, 4, 4]]
    filtered = summarize(filters=[{'column': 'group', 'kind': 'categorical', 'values': ['A']}])
    assert filtered['input_rows'] == 2 and filtered['total_groups'] == 1
    multi = group_summary.summarize(dataset_id, {'group_by': ['group', 'part']})
    assert multi['total_groups'] == 3
    with pytest.raises(ValidationError):
        group_summary.summarize(dataset_id, {'group_by': ['group', 'group']})
    with pytest.raises(ValueError):
        group_summary.summarize(dataset_id, {'group_by': ['not a column']})


def test_loaded(frame):
    opened = datasets.open_dataset(frame, 'loaded')
    try: verify(opened['dataset_id'])
    finally: datasets.close_dataset(opened['dataset_id'])


def test_duckdb(frame, tmp_path):
    path = str(tmp_path / 'data.duckdb')
    con = duckdb.connect(path)
    con.register('frame', frame)
    con.execute('CREATE TABLE data AS SELECT * FROM frame')
    con.close()
    opened = datasets.open_dataset(frame, 'file', disk_source={'path': path, 'table': 'data', 'columns': list(frame.columns), 'rows': len(frame)})
    try: verify(opened['dataset_id'])
    finally: datasets.close_dataset(opened['dataset_id'])


def test_postgres(frame, engine, monkeypatch):
    import database
    import main
    monkeypatch.setattr(database, 'get_engine_for_resource', lambda rid: engine)
    with engine.begin() as con:
        con.execute(text('CREATE TABLE public.group_summary_test ("group" text, part bigint, value text)'))
        con.execute(text("INSERT INTO public.group_summary_test VALUES ('A',1,'1'),('A',1,'3'),('B',2,'bad'),(NULL,1,'4'),('B',2,NULL)"))
    opened = main._open_source({'kind': 'aurora', 'resource_id': 'omopdb', 'schema': 'public', 'table': 'group_summary_test'})
    try: verify(opened['dataset_id'])
    finally:
        datasets.close_dataset(opened['dataset_id'])
        with engine.begin() as con: con.execute(text('DROP TABLE public.group_summary_test'))


def test_summary_http_validation_and_empty_result(client, frame):
    opened = datasets.open_dataset(frame, 'loaded')
    try:
        path = f"/api/datasets/{opened['dataset_id']}/summary"
        response = client.post(path, json={'group_by': ['group'], 'measure': 'value', 'filters': [{'column': 'group', 'kind': 'categorical', 'values': ['absent']}]})
        assert response.status_code == 200, response.text
        assert response.json()['input_rows'] == 0 and response.json()['rows'] == []
        assert client.post(path, json={'group_by': ['group', 'group']}).status_code == 422
        assert client.post(path, json={'group_by': ['group'], 'page_size': 201}).status_code == 422
        assert client.post(path, json={'group_by': ['unknown']}).status_code == 400
    finally:
        datasets.close_dataset(opened['dataset_id'])
