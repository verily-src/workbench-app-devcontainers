import hashlib
import json
import re
import secrets
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from fastapi import Request, Response

import datasets

_current = ContextVar("agent_session", default=None)
_COOKIE = "studio_chat_owner"
_TOOL_ERROR_CODES = {
    "invalid_cohort_spec", "invalid_tool_input", "query_timeout",
    "cohort_service_unavailable", "tool_error", "unknown_tool",
    "tool_result_too_large", "invalid_arguments", "runtime_limit",
    "no_progress",
}
_LIMIT_REASONS = {"wall_clock", "tool_calls", "turn_budget"}


def owner(request: Request, response: Response) -> str:
    value = getattr(request.state, "chat_owner", None) or request.cookies.get(_COOKIE, "")
    if not re.fullmatch(r"[a-f0-9]{64}", value):
        value = secrets.token_hex(32)
        response.set_cookie(_COOKIE, value, httponly=True, samesite="strict",
                            secure=request.url.scheme == "https", max_age=31536000)
    return hashlib.sha256(value.encode()).hexdigest()


async def preserve_owner_cookie(request: Request, call_next):
    path = request.url.path
    active = "/chat" in path or "/cohort/agent" in path
    existing = request.cookies.get(_COOKIE, "")
    fresh = active and not re.fullmatch(r"[a-f0-9]{64}", existing)
    if fresh:
        request.state.chat_owner = secrets.token_hex(32)
    response = await call_next(request)
    if fresh:
        response.set_cookie(_COOKIE, request.state.chat_owner, httponly=True,
                            samesite="strict", secure=request.url.scheme == "https",
                            max_age=31536000)
    return response


def dataset_scope(dataset_id: str) -> str:
    ds = datasets.get(dataset_id)
    ref = ds.get("source_ref") or ds.get("origin")
    def semantic(value):
        if isinstance(value, dict):
            return {key: semantic(item) for key, item in value.items() if key != "settings"}
        if isinstance(value, list):
            return [semantic(item) for item in value]
        return value
    identity = json.dumps(semantic(ref), sort_keys=True, default=str) if ref else dataset_id
    return "dataset:" + hashlib.sha256(identity.encode()).hexdigest()


@dataclass
class Session:
    store: object
    owner: str
    scope: str
    session_id: str | None
    turn: object = None
    timings: dict = field(default_factory=dict)
    new_session: bool = False


@contextmanager
def bind(owner_id: str, scope: str, session_id: str | None, *, new_session: bool = False):
    if new_session and session_id is not None:
        raise ValueError("Choose an existing conversation or start a new one.")
    from agent_store import AgentStore
    session = Session(AgentStore(), owner_id, scope, session_id,
                      new_session=new_session)
    token = _current.set(session)
    try:
        yield session
    except Exception as exc:
        if session.turn is not None:
            session.store.fail(session.turn, error_class=type(exc).__name__)
        raise
    finally:
        _current.reset(token)


def start(system: str, cfg: dict, message: str) -> list[dict] | None:
    session = _current.get()
    if session is None:
        return None
    identifier = session.session_id
    if identifier is None and not session.new_session:
        identifier = session.store.latest(owner=session.owner, scope=session.scope)
    session.turn = session.store.begin(
        session_id=identifier, owner=session.owner, scope=session.scope,
        system_prompt=system, user_message=message,
        provider=cfg["provider"], model=cfg["model"])
    return session.turn.history


def event(value: dict):
    session = _current.get()
    if session is None or session.turn is None:
        return
    kind = value.get("type", "step")
    name = value.get("tool_name") or value.get("model") or "model"
    key = (name, value.get("turn"))
    latency = None
    if kind.endswith("_start"):
        session.timings[key] = time.monotonic()
    elif key in session.timings:
        latency = (time.monotonic() - session.timings.pop(key)) * 1000
    metadata = {"turn": value.get("turn"), "usage": value.get("usage")}
    error_code = value.get("error_code")
    if kind == "tool_end" and error_code in _TOOL_ERROR_CODES:
        metadata["error_code"] = error_code
    limit_reason = value.get("reason")
    if kind == "runtime_limit" and limit_reason in _LIMIT_REASONS:
        metadata["limit_reason"] = limit_reason
    is_error = ((kind == "tool_end" and error_code in _TOOL_ERROR_CODES)
                or kind == "runtime_limit")
    session.store.record_event(
        session.turn.run_id, kind=kind, name=name,
        status="error" if is_error else "ok", metadata=metadata,
        latency_ms=int(latency) if latency is not None else None,
        error_class=("AgentLimitReached" if kind == "runtime_limit" else
                     "ToolError" if is_error else None))


def finish(result: dict) -> dict:
    session = _current.get()
    if session is not None and session.turn is not None:
        usage = result.get("usage") or {}
        stored_usage = {
            "input_tokens": usage.get("prompt_tokens", usage.get("input_tokens")),
            "output_tokens": usage.get("completion_tokens", usage.get("output_tokens"))}
        if result.get("limit_reached") or result.get("stop_reason"):
            error_class = ("AgentLimitReached" if result.get("limit_reached") else
                           "ToolFailureLoopStopped")
            session.store.fail(session.turn, error_class=error_class,
                               assistant_message=result["reply"], usage=stored_usage)
            result["run_status"] = "failed"
        else:
            session.store.finish(session.turn, result["reply"], usage=stored_usage)
            result["run_status"] = "completed"
        result["session_id"] = str(session.turn.session_id)
        result["trace_id"] = str(session.turn.run_id)
    return result


def history(owner_id: str, scope: str, session_id=None, before=None):
    from agent_store import AgentStore
    store = AgentStore()
    identifier = session_id or store.latest(owner=owner_id, scope=scope)
    if identifier is None:
        return {"session_id": None, "messages": [], "has_more": False,
                "next_before_message_id": None}
    page = store.history(session_id=identifier, owner=owner_id, scope=scope, before_message_id=before)
    result = page.model_dump(mode="json") if hasattr(page, "model_dump") else dict(page)
    return {"session_id": str(identifier), **result}
