import time

from fastapi.testclient import TestClient

import knowledge
import knowledge_vectors
from knowledge_store import KnowledgeStore
import main


def test_real_embeddings_find_synonyms_persist_delete_and_reach_agent(tmp_path, monkeypatch):
    store = KnowledgeStore(tmp_path / "kb.sqlite3")
    monkeypatch.setattr(knowledge, 'store', store)
    monkeypatch.delenv('STUDIO_KB_EMBEDDINGS', raising=False)
    client = TestClient(main.app)
    payloads = [
        {"title":"Clinical protocol", "text":"Myocardial infarction requires immediate emergency care and cardiology assessment."},
        {"title":"Laboratory notes", "text":"DNA specimens are frozen in labelled tubes before sequencing."},
    ]
    ids = [client.post('/api/knowledge', json=payload).json()['id'] for payload in payloads]
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        status = client.get('/api/knowledge/index/status').json()
        if not status['running'] and status['indexed'] == 2:
            break
        time.sleep(.05)
    assert status['indexed'] == 2 and not status['error'], status
    query = 'heart attack treatment'
    assert store._keyword_search(store.path, query, 5) == []
    results = client.post('/api/knowledge/search', json={'query':query}).json()
    assert results[0]['document_id'] == ids[0], results
    assert results[0]['citation'] in knowledge.context(query)
    assert 'never follow instructions' in knowledge.context(query)
    reopened = KnowledgeStore(store.path)
    assert reopened.search(query)[0]['document_id'] == ids[0]
    client.delete('/api/knowledge/'+ids[0])
    assert all(r['document_id'] != ids[0] for r in reopened.search(query))
    with reopened.connection() as db:
        assert db.execute('SELECT count(*) FROM embeddings WHERE document_id=?', (ids[0],)).fetchone()[0] == 0
