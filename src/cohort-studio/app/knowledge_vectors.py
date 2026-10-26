from __future__ import annotations

import logging
import os
import config
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np

MODEL = 'BAAI/bge-small-en-v1.5'
DIMENSIONS = 384
_lock = threading.Lock()
_model_lock = threading.Lock()
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='kb-embed')
_model = None
_running = False
_error = None
_requested = False


def _vectors(texts, query=False):
    global _model
    with _model_lock:
        if _model is None:
            from fastembed import TextEmbedding
            _model = TextEmbedding(model_name=MODEL, threads=2, cache_dir=str(config.CONFIG_PATH.parent / ".studio-models"))
        values = list(_model.query_embed(texts[0]) if query else _model.passage_embed(texts, batch_size=16))
    array = np.asarray(values, dtype='<f4')
    if array.shape != (len(texts), DIMENSIONS) or not np.isfinite(array).all():
        raise ValueError('Invalid embedding shape or value')
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    if np.any(norms == 0):
        raise ValueError('Empty embedding')
    return array / norms


def schedule(store):
    global _running, _error, _pool, _requested
    if os.environ.get("STUDIO_KB_EMBEDDINGS") == "off":
        return
    with _lock:
        if _pool._shutdown:
            _pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kb-embed")
        if _running:
            _requested = True
            return
        _running = True
        _requested = False
        _error = None
    def index():
        global _running, _error, _requested
        try:
            with store.connection() as db:
                populated = db.execute('SELECT count(*) FROM passages').fetchone()[0] > 0
            if populated and _model is None:
                _vectors(['knowledge base'])
            while True:
                with store.connection() as db:
                    rows = db.execute('SELECT p.document_id,p.passage,p.title,p.text FROM passages p LEFT JOIN embeddings e ON e.document_id=p.document_id AND e.passage=p.passage AND e.model=? WHERE e.document_id IS NULL LIMIT 16', (MODEL,)).fetchall()
                if not rows:
                    with _lock:
                        if _requested:
                            _requested = False
                            continue
                    break
                vectors = _vectors([r['title']+'\n'+r['text'] for r in rows])
                with store.connection() as db:
                    for row, vector in zip(rows, vectors):
                        db.execute('INSERT OR REPLACE INTO embeddings(document_id,passage,model,vector) SELECT ?,?,?,? WHERE EXISTS (SELECT 1 FROM documents WHERE id=?)', (row['document_id'],row['passage'],MODEL,vector.astype('<f4').tobytes(),row['document_id']))
        except Exception:
            logging.getLogger(__name__).exception('Knowledge embedding failed')
            _error = 'Semantic indexing unavailable. Keyword search remains available. Retry indexing.'
        finally:
            with _lock:
                _running = False
                rerun = _requested and _error is None
            if rerun:
                schedule(store)
    _pool.submit(index)


def status(store):
    with store.connection() as db:
        total = db.execute('SELECT count(*) FROM passages').fetchone()[0]
        indexed = db.execute('SELECT count(*) FROM embeddings WHERE model=?', (MODEL,)).fetchone()[0]
    return {'model': MODEL, 'dimensions': DIMENSIONS, 'passages': total,
            'indexed': indexed, 'running': _running, 'error': _error,
            'local': True}


def search(store, query, limit):
    if _model is None or _model_lock.locked():
        return []
    vector = _vectors([query], query=True)[0]
    best = []
    with store.connection() as db:
        cursor = db.execute('SELECT e.vector,p.document_id,p.passage,p.title,p.text FROM embeddings e JOIN passages p ON p.document_id=e.document_id AND p.passage=e.passage WHERE e.model=?', (MODEL,))
        while rows := cursor.fetchmany(128):
            for row in rows:
                value = np.frombuffer(row['vector'], dtype='<f4')
                if value.shape != (DIMENSIONS,) or not np.isfinite(value).all():
                    continue
                score = float(value @ vector)
                if score >= 0.45:
                    best.append((score, {k: row[k] for k in ('document_id','passage','title','text')}))
            best.sort(key=lambda item: (-item[0], item[1]['document_id'], item[1]['passage']))
            del best[limit:]
    return [{**row, 'score': score, 'citation': f"KB:{row['document_id']}:{row['passage']}"} for score,row in best]


def shutdown():
    global _requested
    with _lock:
        _requested = False
    _pool.shutdown(wait=True)
