import duckdb
import pandas as pd
from sqlalchemy import text
import datasets


def verify(client, did):
    path=f'/api/datasets/{did}/query'
    def query(direction, page=0):
        result=client.post(path,json={'sort':{'column':'value','direction':direction},'page_size':2,'page':page})
        assert result.status_code == 200, result.text
        rows=result.json()['rows']
        return [r[rows['columns'].index('value')] for r in rows['data']]
    assert query('asc') == [1,2]
    assert query('asc',1) == [3,None]
    assert query('desc') == [3,2]
    assert query('desc',1) == [1,None]
    assert client.post(path,json={'sort':{'column':'value','direction':'garbage'}}).status_code == 422
    assert client.post(path,json={'sort':{'column':'missing','direction':'asc'}}).status_code == 400


def test_sort_loaded_and_disk(client,tmp_path):
    frame=pd.DataFrame({'value':pd.Series([3,1,None,2],dtype='float64')})
    path=str(tmp_path/'rows.duckdb'); con=duckdb.connect(path);con.register('frame',frame);con.execute('CREATE TABLE data AS SELECT * FROM frame');con.close()
    for source in (None, {'path':path,'table':'data','columns':['value'],'rows':4}):
        opened=datasets.open_dataset(frame,'test',disk_source=source)
        try: verify(client,opened['dataset_id'])
        finally: datasets.close_dataset(opened['dataset_id'])


def test_sort_postgres(client,engine,monkeypatch):
    import database,main
    monkeypatch.setattr(database,'get_engine_for_resource',lambda rid:engine)
    with engine.begin() as con:
        con.execute(text('CREATE TABLE public.row_sort_test (value int)'))
        con.execute(text('INSERT INTO public.row_sort_test VALUES (3),(1),(NULL),(2)'))
    opened=main._open_source({'kind':'aurora','resource_id':'db','schema':'public','table':'row_sort_test'})
    try: verify(client,opened['dataset_id'])
    finally:
        datasets.close_dataset(opened['dataset_id'])
        with engine.begin() as con: con.execute(text('DROP TABLE public.row_sort_test'))


def test_sql_source_opens_directly_without_preview(client,engine,monkeypatch):
    import database
    monkeypatch.setattr(database,'get_engine_for_resource',lambda rid:engine)
    with engine.begin() as con:
        con.execute(text('CREATE TABLE public.sql_direct_test (person_id int)'))
        con.execute(text('INSERT INTO public.sql_direct_test VALUES (3),(1),(2)'))
    opened=None
    try:
        ref={'kind':'sql','resource_id':'db','sql':'SELECT person_id FROM public.sql_direct_test','name':'My cohort'}
        response=client.post('/api/datasets/open',json={'source_ref':ref})
        assert response.status_code==200, response.text
        opened=response.json()['dataset_id']
        result=client.post(f'/api/datasets/{opened}/query',json={'sort':{'column':'person_id','direction':'desc'},'page_size':2})
        assert result.status_code==200 and result.json()['rows']['data']==[[3],[2]]
        unsafe=client.post('/api/datasets/open',json={'source_ref':{**ref,'sql':'DELETE FROM public.sql_direct_test'}})
        assert unsafe.status_code==422
    finally:
        if opened: datasets.close_dataset(opened)
        with engine.begin() as con: con.execute(text('DROP TABLE public.sql_direct_test'))
