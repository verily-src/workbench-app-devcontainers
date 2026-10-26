import asyncio
import threading
import time

import httpx2
from sqlalchemy import event, text

import datasets
import main
import omop
import views


def test_upload_parsing_does_not_block_health_or_duplicate_file_buffer(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    original = main.pd.read_csv
    def slow_parse(source, **kwargs):
        assert hasattr(source, 'read')
        entered.set()
        assert release.wait(5)
        return original(source, **kwargs)
    monkeypatch.setattr(main.pd, 'read_csv', slow_parse)
    monkeypatch.setattr(main, '_lineage_engine', lambda: None)
    monkeypatch.setattr(main.lineage, 'record', lambda *args, **kwargs: None)
    async def check():
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=main.app), base_url='http://test') as client:
            upload = asyncio.create_task(client.post('/api/datasets/upload', files={'file': ('people.csv', b'person_id,value\n1,10\n2,20\n', 'text/csv')}))
            try:
                deadline = time.monotonic() + 2
                while not entered.is_set() and time.monotonic() < deadline:
                    await asyncio.sleep(.01)
                assert entered.is_set()
                response = await asyncio.wait_for(client.get('/api/health'), .5)
                assert response.status_code == 200 and not release.is_set()
            finally:
                release.set()
            response = await upload
            assert response.status_code == 200, response.text
            result = response.json()
            try:
                assert result['rows'] == 2
                assert [column['name'] for column in result['columns']] == ['person_id', 'value']
            finally:
                datasets.close_dataset(result['dataset_id'])
    asyncio.run(check())


def test_saved_view_listing_is_parallel_bounded_and_keeps_partial_failures(client, monkeypatch):
    lock = threading.Lock()
    active = 0
    peak = 0
    calls = []
    gate = threading.Barrier(4)
    def list_store(kind, resource_id):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(active, peak)
            calls.append(resource_id)
            first_wave = len(calls) <= 4
        try:
            if first_wave:
                gate.wait(timeout=2)
            if resource_id == 's3-3':
                raise ValueError('Access denied')
            return [{'name': resource_id, 'created_by': 'test'}]
        finally:
            with lock:
                active -= 1
    monkeypatch.setattr(main.db, 'list_aurora_resources', lambda: [])
    monkeypatch.setattr(main.db, 'list_s3_folders', lambda: [{'id': f's3-{i}'} for i in range(9)])
    monkeypatch.setattr(views, 'list_views', list_store)
    response = client.get('/api/views/all')
    assert response.status_code == 200
    body = response.json()
    assert peak == 4
    assert len(calls) == 9 and len(set(calls)) == 9
    assert len(body['views']) == 8
    assert [v['name'] for v in body['views']] == sorted(v['name'] for v in body['views'])
    assert body['unavailable'][0]['resource_id'] == 's3-3'


def test_omop_mixed_domain_counts_use_one_database_statement(engine, info):
    rows = [{'concept_id': 192671, 'domain_id': 'Condition', 'persons': None},
            {'concept_id': 1118084, 'domain_id': 'Drug', 'persons': None},
            {'concept_id': 0, 'domain_id': 'Metadata', 'persons': None}]
    statements = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if 'count(DISTINCT person_id)' in statement:
            statements.append(statement)
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        omop._person_counts(engine, info, rows)
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    assert len(statements) == 1 and 'UNION ALL' in statements[0]
    with engine.connect() as conn:
        condition = conn.execute(text('SELECT count(DISTINCT person_id) FROM cdm.condition_occurrence WHERE condition_concept_id=192671')).scalar_one()
        drug = conn.execute(text('SELECT count(DISTINCT person_id) FROM cdm.drug_exposure WHERE drug_concept_id=1118084')).scalar_one()
    assert [row['persons'] for row in rows] == [condition, drug, None]


def test_dashboard_counts_share_one_scan_and_match_direct_sql(engine, monkeypatch):
    import live_query
    monkeypatch.setattr(live_query.db, 'get_engine_for_resource', lambda rid: engine)
    source = {'resource_id': 'batch-counts', 'sql': 'SELECT person_id, gender_concept_id FROM cdm.person',
              'columns': {'person_id': 'person_id', 'gender_concept_id': 'gender_concept_id'}}
    statements = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if 'COUNT(' in statement:
            statements.append(statement)
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        result = live_query.query(source, [{'column': 'gender_concept_id', 'kind': 'categorical', 'values': ['8532']}], [], 0, 5, entity_column='person_id', refresh=True)
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    with engine.connect() as conn:
        expected = conn.execute(text('SELECT count(*), count(*) FILTER (WHERE gender_concept_id=8532), count(DISTINCT person_id), count(DISTINCT person_id) FILTER (WHERE gender_concept_id=8532) FROM cdm.person')).one()
    assert (result['total'], result['filtered'], result['entity']['total'], result['entity']['filtered']) == tuple(expected)
    assert len(result['rows']['data']) == 5
    assert len(statements) == 1 and 'FILTER (WHERE' in statements[0]


def test_slow_store_does_not_hide_completed_views_or_queue_unbounded_work(client, monkeypatch):
    release = threading.Event()
    finished = threading.Event()
    monkeypatch.setattr(views, 'LIST_DEADLINE_SECONDS', .1)
    monkeypatch.setattr(main.db, 'list_aurora_resources', lambda: [])
    monkeypatch.setattr(main.db, 'list_s3_folders', lambda: [{'id': 'slow'}, {'id': 'ready'}])
    def list_store(kind, resource_id):
        if resource_id == 'slow':
            try:
                release.wait(5)
            finally:
                finished.set()
        return [{'name': resource_id}]
    monkeypatch.setattr(views, 'list_views', list_store)
    start = time.monotonic()
    try:
        response = client.get('/api/views/all')
        assert response.status_code == 200
        assert time.monotonic() - start < 1
        assert [v['name'] for v in response.json()['views']] == ['ready']
        assert response.json()['unavailable'][0]['resource_id'] == 'slow'
        assert 'timed out' in response.json()['unavailable'][0]['error']
    finally:
        release.set()
        assert finished.wait(2)
