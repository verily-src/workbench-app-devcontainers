from concurrent.futures import Future
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from functools import wraps
import json
import logging
import threading
import time
import uuid

from sqlalchemy import event
from sqlalchemy.engine import Engine

trace_id = ContextVar("studio_trace_id", default=None)
owner_id = ContextVar("studio_owner", default=None)
_lane = ContextVar("studio_lane", default=None)
logger = logging.getLogger("studio.execution")
class AdmissionGate:
    def __init__(self, capacity, per_owner=None):
        self.capacity = capacity
        self.per_owner = per_owner or capacity
        self.owners = {}
        self.active = 0
        self.waiters = []
        self.condition = threading.Condition()

    def acquire(self, timeout=None, owner=None):
        ticket = (object(), owner)
        deadline = None if timeout is None else time.monotonic() + timeout
        with self.condition:
            self.waiters.append(ticket)
            try:
                def eligible():
                    return next((item for item in self.waiters
                                 if item[1] is None or self.owners.get(item[1], 0) < self.per_owner), None)
                while eligible() is not ticket or self.active >= self.capacity:
                    remaining = None if deadline is None else deadline - time.monotonic()
                    if remaining is not None and remaining <= 0:
                        return False
                    self.condition.wait(remaining)
                self.active += 1
                self.owners[owner] = self.owners.get(owner, 0) + 1
                return True
            finally:
                self.waiters.remove(ticket)
                self.condition.notify_all()

    def release(self, owner=None):
        with self.condition:
            if self.active <= 0:
                raise RuntimeError("Admission slot released twice")
            if self.owners.get(owner, 0) <= 0:
                raise RuntimeError("Admission owner does not hold a slot")
            self.owners[owner] -= 1
            if not self.owners[owner]:
                self.owners.pop(owner)
            self.active -= 1
            self.condition.notify_all()


_gates = {"interactive": AdmissionGate(4, 2), "bulk": AdmissionGate(2, 1)}


class FairExecutor:
    def __init__(self, max_workers=2, thread_name_prefix="studio-worker"):
        self.max_workers = max_workers
        self.prefix = thread_name_prefix
        self.condition = threading.Condition()
        self.pending = []
        self.running_owners = set()
        self.threads = []
        self._shutdown = False

    def submit(self, fn, *args, **kwargs):
        future = Future()
        with self.condition:
            if self._shutdown:
                raise RuntimeError("Executor is shut down")
            self.pending.append((future, owner_id.get(), fn, args, kwargs))
            if not self.threads:
                for index in range(self.max_workers):
                    thread = threading.Thread(target=self._run, name=f"{self.prefix}-{index}", daemon=True)
                    self.threads.append(thread)
                    thread.start()
            self.condition.notify_all()
        return future

    def _run(self):
        while True:
            with self.condition:
                while True:
                    eligible = next((item for item in self.pending if item[1] is None or item[1] not in self.running_owners), None)
                    if eligible is not None:
                        self.pending.remove(eligible)
                        break
                    if self._shutdown and not self.pending:
                        return
                    self.condition.wait()
                future, owner, fn, args, kwargs = eligible
                if not future.set_running_or_notify_cancel():
                    self.condition.notify_all()
                    continue
                if owner is not None:
                    self.running_owners.add(owner)
            try:
                future.set_result(fn(*args, **kwargs))
            except BaseException as exc:
                future.set_exception(exc)
            finally:
                with self.condition:
                    self.running_owners.discard(owner)
                    self.condition.notify_all()

    def shutdown(self, wait=True, *, cancel_futures=False):
        with self.condition:
            self._shutdown = True
            if cancel_futures:
                for future, *_ in self.pending:
                    future.cancel()
                self.pending.clear()
            self.condition.notify_all()
        if wait:
            for thread in self.threads:
                thread.join()


class Busy(ValueError):
    pass


def emit(event_name, **fields):
    payload = {"event": event_name, "trace_id": trace_id.get(), **fields}
    logger.info(json.dumps(payload))
    if owner_id.get():
        try:
            import operational_store
            operational_store.store().record(owner_id.get(), payload)
        except Exception:
            logger.warning("Performance metrics are unavailable")


@contextmanager
def operation(name, lane):
    if lane not in _gates:
        raise ValueError("Invalid workload class")
    token = trace_id.set(trace_id.get() or uuid.uuid4().hex)
    started = time.monotonic()
    acquired = False
    lane_token = None
    try:
        if _lane.get() is None:
            acquired = (_gates[lane].acquire(timeout=0.25, owner=owner_id.get()) if lane == "interactive"
                        else _gates[lane].acquire(owner=owner_id.get()))
            if not acquired:
                emit("operation.rejected", operation=name, lane=lane)
                raise Busy("Dashboard queries are busy. Retry shortly.")
            lane_token = _lane.set(lane)
        admitted = time.monotonic()
        emit("operation.started", operation=name, lane=_lane.get(), queue_ms=round((admitted-started)*1000, 2))
        try:
            yield
        except BaseException:
            emit("operation.finished", operation=name, status="failed", elapsed_ms=round((time.monotonic()-admitted)*1000, 2))
            raise
        else:
            emit("operation.finished", operation=name, status="complete", elapsed_ms=round((time.monotonic()-admitted)*1000, 2))
    finally:
        if acquired:
            _lane.reset(lane_token)
            _gates[lane].release(owner=owner_id.get())
        trace_id.reset(token)


def workload(lane):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            with operation(fn.__module__ + "." + fn.__name__, lane):
                return fn(*args, **kwargs)
        return wrapped
    return decorate


def submit(pool, fn, *args):
    context = copy_context()
    return pool.submit(context.run, fn, *args)


async def trace_request(request, call_next):
    from agent_sessions import owner
    from fastapi import Response
    owner_token = owner_id.set(owner(request, Response()) if request.url.path.startswith("/api/") else None)
    token = trace_id.set(uuid.uuid4().hex)
    started = time.monotonic()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = trace_id.get()
        return response
    finally:
        route = request.scope.get("route")
        emit("http.finished", method=request.method, route=getattr(route, "path", "unmatched"), status=status,
             elapsed_ms=round((time.monotonic()-started)*1000, 2))
        trace_id.reset(token)
        owner_id.reset(owner_token)


@event.listens_for(Engine, "before_cursor_execute")
def before_sql(conn, cursor, statement, parameters, context, executemany):
    context._studio_started = time.monotonic()


@event.listens_for(Engine, "after_cursor_execute")
def after_sql(conn, cursor, statement, parameters, context, executemany):
    emit("sql.finished", engine=conn.dialect.name, status="complete",
         elapsed_ms=round((time.monotonic()-context._studio_started)*1000, 2))


@event.listens_for(Engine, "handle_error")
def failed_sql(context):
    emit("sql.finished", engine=context.engine.dialect.name if context.engine else "unknown", status="failed")
