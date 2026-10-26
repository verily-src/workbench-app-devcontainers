from __future__ import annotations

import os
from contextlib import contextmanager
import sqlite3
import execution
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import config


class Busy(ValueError):
    pass


class DataJobs:
    def __init__(self, path: Path, workers=2, capacity=8):
        self.path = path
        self.capacity = capacity
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="data-job")
        self.results = {}
        self.active = 0
        self.closed = False
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(path, 0o600)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, owner TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL, updated REAL NOT NULL)')
            db.execute("UPDATE jobs SET status='interrupted' WHERE status IN ('queued','running','cancelling','complete')")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def state(self, job_id, status):
        with self.connect() as db:
            db.execute('UPDATE jobs SET status=?, updated=? WHERE id=?', (status, time.time(), job_id))

    def get(self, job_id, owner):
        with self.lock, self.connect() as db:
            row = db.execute('SELECT id,kind,status FROM jobs WHERE id=? AND owner=?', (job_id, owner)).fetchone()
            if not row:
                return None
            result = dict(zip(('job_id', 'kind', 'status'), row))
            if row[2] in {'complete', 'failed'}:
                result.update(self.results.get(job_id, {}))
            return result

    def cancel(self, job_id, owner):
        with self.lock:
            job = self.get(job_id, owner)
            if job and job['status'] in {'queued', 'running'}:
                self.state(job_id, 'cancelling')
            return self.get(job_id, owner)

    def submit(self, kind, owner, work, cleanup):
        if kind not in {'open', 'join'} or not isinstance(owner, str) or not owner:
            raise ValueError('Invalid data job')
        with self.lock:
            if self.closed or self.active >= self.capacity:
                raise Busy('Data jobs are busy. Try again shortly.')
            job_id = uuid.uuid4().hex
            with self.connect() as db:
                owned = db.execute("SELECT count(*) FROM jobs WHERE owner=? AND status IN ('queued','running','cancelling')", (owner,)).fetchone()[0]
                if owned >= 2:
                    raise Busy('Two data jobs are already active for this session. Try again shortly.')
                expired = [r[0] for r in db.execute("SELECT id FROM jobs WHERE updated<? AND status NOT IN ('queued','running','cancelling')", (time.time()-3600,))]
                for old in expired:
                    self.results.pop(old, None)
                db.execute("DELETE FROM jobs WHERE updated<? AND status NOT IN ('queued','running','cancelling')", (time.time()-3600,))
                count = db.execute('SELECT count(*) FROM jobs').fetchone()[0]
                if count >= 128:
                    raise Busy('Data job history is full. Try again later.')
                db.execute('INSERT INTO jobs VALUES (?,?,?,?,?)', (job_id, owner, kind, 'queued', time.time()))
            self.active += 1

            @execution.workload("bulk")
            def run():
                try:
                    with self.lock:
                        if self.get(job_id, owner)['status'] == 'cancelling':
                            self.state(job_id, 'cancelled')
                            return
                        self.state(job_id, 'running')
                    result = work()
                    with self.lock:
                        if self.get(job_id, owner)['status'] == 'cancelling':
                            cleanup(result)
                            self.state(job_id, 'cancelled')
                        else:
                            self.results[job_id] = {'result': result}
                            self.state(job_id, 'complete')
                except Exception as exc:
                    with self.lock:
                        status = self.get(job_id, owner)['status']
                        self.results[job_id] = {'error': getattr(exc, 'detail', 'Data operation failed. Retry or check server logs.'), 'status_code': getattr(exc, 'status_code', 500)}
                        self.state(job_id, 'cancelled' if status == 'cancelling' else 'failed')
                finally:
                    with self.lock:
                        self.active -= 1
            execution.emit("job.submitted", job_id=job_id, kind=kind)
            execution.submit(self.pool, run)
            return self.get(job_id, owner)

    def shutdown(self):
        with self.lock:
            self.closed = True
            with self.connect() as db:
                db.execute("UPDATE jobs SET status='cancelling' WHERE status IN ('queued','running')")
        self.pool.shutdown(wait=True)


_instance = None
_instance_lock = threading.Lock()


def manager():
    global _instance
    with _instance_lock:
        if _instance is None or _instance.closed:
            _instance = DataJobs(Path(os.environ.get('STUDIO_DATA_JOBS_PATH', str(config.CONFIG_PATH.parent / '.studio-data-jobs.sqlite3'))))
        return _instance


def shutdown():
    if _instance is not None:
        _instance.shutdown()
