from contextlib import contextmanager
import json
import logging
import math
import os
from pathlib import Path
import queue
import sqlite3
import threading
import time

import config

MAX_EVENTS = 20000
RETENTION_SECONDS = 7 * 86400


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        self.lock = threading.RLock()
        self.queue = queue.Queue(maxsize=2048)
        self.dropped = 0
        self.closed = False
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS grains (source TEXT PRIMARY KEY, definition TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS metrics (id INTEGER PRIMARY KEY, created REAL NOT NULL, owner TEXT NOT NULL, payload TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS metrics_owner_time ON metrics(owner,created)')
        self.thread = threading.Thread(target=self._run, name='studio-metrics', daemon=True)
        self.thread.start()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=2)
        try:
            with db:
                yield db
        finally:
            db.close()

    def grain(self, source, definition=None):
        with self.lock, self.connect() as db:
            if definition is not None:
                db.execute('INSERT INTO grains VALUES (?,?) ON CONFLICT(source) DO UPDATE SET definition=excluded.definition',
                           (source, json.dumps(definition)))
            row = db.execute('SELECT definition FROM grains WHERE source=?', (source,)).fetchone()
            return json.loads(row[0]) if row else None

    def record(self, owner, payload):
        if self.closed or not owner:
            return
        allowed = {'event', 'trace_id', 'operation', 'lane', 'queue_ms', 'elapsed_ms', 'status', 'engine', 'route', 'method'}
        safe = {k: (v[:512] if isinstance(v, str) else v) for k, v in payload.items() if k in allowed and isinstance(v, (str, int, float))}
        try:
            self.queue.put_nowait((time.time(), owner, json.dumps(safe)))
        except queue.Full:
            self.dropped += 1

    def _run(self):
        while True:
            first = self.queue.get()
            if first is None:
                self.queue.task_done()
                return
            batch = [first]
            while len(batch) < 128:
                try:
                    item = self.queue.get_nowait()
                except queue.Empty:
                    break
                if item is None:
                    self.queue.task_done()
                    break
                batch.append(item)
            try:
                with self.lock, self.connect() as db:
                    db.executemany('INSERT INTO metrics(created,owner,payload) VALUES (?,?,?)', batch)
                    db.execute('DELETE FROM metrics WHERE created<?', (time.time()-RETENTION_SECONDS,))
                    db.execute('DELETE FROM metrics WHERE id IN (SELECT id FROM metrics ORDER BY id DESC LIMIT -1 OFFSET ?)', (MAX_EVENTS,))
            except Exception:
                self.dropped += len(batch)
                logging.getLogger(__name__).warning('Performance metrics could not be persisted')
            finally:
                for _ in batch:
                    self.queue.task_done()

    def summary(self, owner):
        with self.lock, self.connect() as db:
            rows = db.execute('SELECT payload FROM metrics WHERE owner=? AND created>=? ORDER BY id',
                              (owner, time.time()-RETENTION_SECONDS)).fetchall()
        grouped = {}
        for row in rows:
            item = json.loads(row[0])
            name = item.get('operation') or item.get('route') or item.get('engine') or 'other'
            key = (item['event'], name)
            group = grouped.setdefault(key, {'event': key[0], 'name': name, 'count': 0, 'failed': 0, 'timings': []})
            group['count'] += 1
            status = item.get('status')
            group['failed'] += int(status == 'failed' or isinstance(status, int) and status >= 400 or item['event'] == 'operation.rejected')
            latency = item.get('queue_ms') if item['event'] == 'operation.started' else item.get('elapsed_ms')
            if isinstance(latency, (int, float)) and math.isfinite(latency):
                group['timings'].append(latency)
        result = []
        for group in grouped.values():
            values = sorted(group.pop('timings'))
            group['p95_ms'] = values[max(0, math.ceil(len(values)*.95)-1)] if values else None
            result.append(group)
        return {'scope': 'current_session', 'retention_days': 7, 'max_events': MAX_EVENTS,
                'dropped_events_since_restart': self.dropped,
                'groups': sorted(result, key=lambda g: (g['event'], g['name']))}

    def shutdown(self):
        self.closed = True
        self.queue.join()
        self.queue.put(None)
        self.thread.join(timeout=5)


_instance = None
_lock = threading.Lock()


def store():
    global _instance
    with _lock:
        if _instance is None or _instance.closed:
            _instance = Store(os.environ.get('STUDIO_OPERATIONS_PATH', str(config.CONFIG_PATH.parent / '.studio-operations.sqlite3')))
        return _instance


def shutdown():
    if _instance is not None and not _instance.closed:
        _instance.shutdown()
