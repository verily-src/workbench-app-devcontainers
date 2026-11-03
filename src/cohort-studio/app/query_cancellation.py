from contextlib import contextmanager
from contextvars import ContextVar
from threading import Event, Lock, Thread
import os


class Cancelled(Exception):
    pass


def join_timeout_ms(default_ms=0):
    raw = os.environ.get('STUDIO_JOIN_TIMEOUT_MS', str(default_ms))
    if not raw.isascii() or not raw.isdigit() or int(raw) > 3_600_000:
        raise ValueError('STUDIO_JOIN_TIMEOUT_MS must be between 0 and 3600000.')
    return int(raw)


class Scope:
    def __init__(self, timeout_ms=None):
        self._lock = Lock()
        self._cancelled = False
        self._cancel = None
        self._finished = Event()
        self.timeout_ms = timeout_ms

    def cancel(self):
        with self._lock:
            if self._cancelled:
                return
            self._cancelled = True
        Thread(target=self._interrupt_until_unbound, daemon=True).start()

    def _interrupt_until_unbound(self):
        while not self._finished.wait(.05):
            with self._lock:
                callback = self._cancel
                if callback is None:
                    continue
                try:
                    callback()
                except Exception:
                    pass

    def finish(self):
        self._finished.set()

    def check(self):
        with self._lock:
            if self._cancelled:
                raise Cancelled()

    @contextmanager
    def bind(self, callback):
        with self._lock:
            if self._cancelled:
                raise Cancelled()
            if self._cancel is not None:
                raise RuntimeError('A cancellation callback is already active.')
            self._cancel = callback
        try:
            yield
        finally:
            with self._lock:
                self._cancel = None


current = ContextVar('data_job_cancel_scope', default=None)


def check():
    scope = current.get()
    if scope is not None:
        scope.check()


@contextmanager
def postgres_connection(conn):
    scope = current.get()
    if scope is None or conn.dialect.name != 'postgresql':
        yield
    else:
        with scope.bind(conn.connection.driver_connection.cancel):
            yield
