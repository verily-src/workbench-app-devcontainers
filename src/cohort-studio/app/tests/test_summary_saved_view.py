from sqlalchemy import create_engine
import views
import main


def test_summary_recipe_saved_and_validated(client, monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'views.db'}")
    monkeypatch.setattr(main.db, 'get_engine_for_resource', lambda rid: engine)
    monkeypatch.setattr(views.db, 'get_engine_for_resource', lambda rid: engine)
    monkeypatch.setattr(main.lineage, 'record', lambda *a, **k: None)
    views._prepared.clear()
    dataset = {'source': {'kind': 's3', 'resource_id': 'folder', 'table': 'x.csv'},
        'filters': [{'column': 'tissue', 'kind': 'categorical', 'values': ['liver']}],
        'group_summary': {'group_by': ['tissue'], 'measure': 'rin'},
        'sort': {'column': 'tissue', 'direction': 'desc'}}
    body = {'kind': 'aurora', 'resource_id': 'db1', 'name': 'summary', 'datasets': [dataset]}
    assert client.post('/api/views', json=body).status_code == 200
    saved = client.get('/api/views/one', params={'kind':'aurora','resource_id':'db1','name':'summary'}).json()['datasets'][0]
    assert saved['group_summary'] == dataset['group_summary']
    assert saved['filters'] == dataset['filters']
    assert saved['sort'] == dataset['sort']
    dataset['group_summary']['group_by'] = ['tissue', 'tissue']
    assert client.post('/api/views', json=body).status_code == 422
