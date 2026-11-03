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


class _Binding:
    def __init__(self, callback):
        self.callback = callback
        self.lock = Lock()
        self.active = True

    def interrupt_until_unbound(self, finished):
        while not finished.wait(.05):
            with self.lock:
                if not self.active:
                    return
                try:
                    self.callback()
                except Exception:
                    pass


class Scope:
    def __init__(self, timeout_ms=None):
        self._lock = Lock()
        self._cancelled = False
        self._bindings = set()
        self._finished = Event()
        self.timeout_ms = timeout_ms

    def cancel(self):
        with self._lock:
            if self._cancelled:
                return
            self._cancelled = True
            bindings = tuple(self._bindings)
        for binding in bindings:
            Thread(target=binding.interrupt_until_unbound, args=(self._finished,), daemon=True).start()

    def finish(self):
        self._finished.set()

    def check(self):
        with self._lock:
            if self._cancelled:
                raise Cancelled()

    @contextmanager
    def bind(self, callback):
        binding = _Binding(callback)
        with self._lock:
            if self._cancelled:
                raise Cancelled()
            self._bindings.add(binding)
        try:
            yield
        finally:
            with self._lock:
                self._bindings.discard(binding)
            with binding.lock:
                binding.active = False


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
        issued = Event()
        driver = conn.connection.driver_connection

        def interrupt():
            issued.set()
            driver.cancel()

        try:
            with scope.bind(interrupt):
                yield
        finally:
            if issued.is_set():
                conn.invalidate()


@contextmanager
def duckdb_connection(conn):
    scope = current.get()
    if scope is None:
        yield
    else:
        with scope.bind(conn.interrupt):
            yield
