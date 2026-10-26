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
_lane = ContextVar("studio_lane", default=None)
logger = logging.getLogger("studio.execution")
class AdmissionGate:
    def __init__(self, capacity):
        self.capacity = capacity
        self.active = 0
        self.waiters = []
        self.condition = threading.Condition()

    def acquire(self, timeout=None):
        ticket = object()
        deadline = None if timeout is None else time.monotonic() + timeout
        with self.condition:
            self.waiters.append(ticket)
            try:
                while self.waiters[0] is not ticket or self.active >= self.capacity:
                    remaining = None if deadline is None else deadline - time.monotonic()
                    if remaining is not None and remaining <= 0:
                        return False
                    self.condition.wait(remaining)
                self.active += 1
                return True
            finally:
                self.waiters.remove(ticket)
                self.condition.notify_all()

    def release(self):
        with self.condition:
            if self.active <= 0:
                raise RuntimeError("Admission slot released twice")
            self.active -= 1
            self.condition.notify_all()


_gates = {"interactive": AdmissionGate(4), "bulk": AdmissionGate(2)}


class Busy(ValueError):
    pass


def emit(event_name, **fields):
    logger.info(json.dumps({"event": event_name, "trace_id": trace_id.get(), **fields}))


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
            acquired = (_gates[lane].acquire(timeout=0.25) if lane == "interactive"
                        else _gates[lane].acquire())
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
            _gates[lane].release()
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
