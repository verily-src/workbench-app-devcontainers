import asyncio
import json
import queue
import threading
import uuid

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

import agent_runtime
import agent_sessions
import llm
from agent_mode_api import AgentRequest, Operations, _SCOPE

router = APIRouter(prefix="/chat")
_lock = threading.Lock()
_active = {}
_slots = threading.BoundedSemaphore(4)
_CANCELLED = "Stopped. No further Agent steps will run. Already-submitted cloud workflows are unchanged."
# Step-event fields forwarded to the browser. Runtime events are already
# bounded and redacted (agent_runtime.summarize_args / summarize_result).
_PROGRESS_FIELDS = ("turn", "tool_name", "error_code", "args", "summary", "usage",
                    "step_usage", "tool_calls", "reason", "attempt", "wait_seconds",
                    "final_summary")


def _error_message(exc):
    if isinstance(exc, llm.LLMNotConfigured):
        return "Agent provider setup is incomplete. Open Settings and check the provider, model, credentials and region."
    status = agent_runtime.error_status(exc)
    code = agent_runtime.error_code(exc)
    names = agent_runtime.error_names(exc)
    detail = str(exc).lower()
    if status == 402 or any(term in detail for term in
            ("insufficient credit", "credit balance", "insufficient_quota", "billing hard limit")):
        return "The provider has no available credit or quota. Check provider billing and quota, then retry."
    if status in (401, 403) or code in ("AccessDeniedException", "UnrecognizedClientException"):
        return "The provider rejected access. Check credentials and model access in Settings."
    if status == 429 or code in ("ThrottlingException", "TooManyRequestsException"):
        return ("The provider request limit was reached, even after automatic retries. "
                "Wait a minute and retry, or check provider rate limits and quota.")
    if agent_runtime.is_overloaded(exc):
        return ("The provider is temporarily overloaded, even after automatic retries. "
                "Wait a minute and retry, or choose a different model in Settings.")
    if status in (408, 504) or agent_runtime.is_timeout(exc):
        return ("The provider request timed out after automatic retries. Retry, or narrow "
                "the request so less data is sent to the model.")
    if (status is not None and status >= 500) or code in (
            "ServiceUnavailableException", "InternalServerException", "ModelNotReadyException"):
        return ("The provider had a server error, even after automatic retries. "
                "Retry in a few minutes; check the provider status page if it continues.")
    if names & {"APIConnectionError", "EndpointConnectionError", "ConnectionClosedError",
                "ConnectError"} or isinstance(exc, ConnectionError):
        return ("Could not reach the provider. Check network access and the provider "
                "endpoint or region in Settings, then retry.")
    return "Agent request failed. Check provider settings or try again."


def _partial(operations):
    """Results that tools already produced before a run failed."""
    if operations is None:
        return {}
    payload = {"actions": list(getattr(operations, "actions", None) or []),
               "workflow_plans": list(getattr(operations, "workflow_plans", None) or []),
               "downloads": list(getattr(operations, "downloads", None) or [])}
    return payload if any(payload.values()) else {}


@router.post("/runs/{run_id}/cancel")
def cancel(run_id: uuid.UUID, request: Request, response: Response):
    owner = agent_sessions.owner(request, response)
    with _lock:
        entry = _active.get(str(run_id))
        if entry is None or entry["owner"] != owner:
            raise HTTPException(404, "Active Agent run not found.")
        entry["cancel"].set()
    return {"status": "cancelling"}


@router.post("/stream")
def stream(req: AgentRequest, request: Request, response: Response):
    import studio_agent
    owner = agent_sessions.owner(request, response)
    if not _slots.acquire(blocking=False):
        raise HTTPException(429, "All Agent slots are busy. Try again shortly.")
    run_id = str(uuid.uuid4())
    stopped = threading.Event()
    events = queue.Queue(maxsize=256)
    with _lock:
        _active[run_id] = {"owner": owner, "cancel": stopped}

    def emit(value):
        while True:
            try:
                events.put_nowait(value)
                return
            except queue.Full:
                try:
                    events.get_nowait()
                except queue.Empty:
                    pass

    def step(value):
        if stopped.is_set():
            raise agent_sessions.AgentCancelled()
        emit({"type": "progress", **{k: value[k] for k in _PROGRESS_FIELDS if k in value},
              "stage": value.get("type", "step")})

    def text(value):
        # Raising here aborts the provider stream mid-generation.
        if stopped.is_set():
            raise agent_sessions.AgentCancelled()
        delta = value.get("text")
        if isinstance(delta, str) and delta:
            emit({"type": "text_delta", "turn": value.get("turn"), "text": delta})

    def work():
        session = None
        operations = None
        try:
            if stopped.is_set():
                raise agent_sessions.AgentCancelled()
            operations = Operations(owner, user_message=req.message)
            with agent_sessions.bind(owner, _SCOPE,
                                     str(req.session_id) if req.session_id else None,
                                     new_session=req.new_session) as session, \
                    agent_runtime.cancellation(stopped, agent_sessions.AgentCancelled), \
                    agent_runtime.text_stream(text):
                result = studio_agent.chat(req.message, operations.callbacks(), on_step=step)
                if stopped.is_set():
                    raise agent_sessions.AgentCancelled()
                agent_sessions.finish(result)
            emit({"type": "result", "result": {**result, "actions": operations.actions,
                                                "workflow_plans": operations.workflow_plans,
                                                "downloads": operations.downloads}})
        except agent_sessions.AgentCancelled:
            emit({"type": "cancelled", "reply": _CANCELLED,
                  "session_id": str(session.turn.session_id) if session and session.turn else None})
        except Exception as exc:
            partial = _partial(operations)
            if partial:
                # The client stops reading at "error", so send completed tool
                # output (dashboards, plans, downloads) first.
                emit({"type": "partial", **partial})
            emit({"type": "error", "message": _error_message(exc), **partial})
        finally:
            emit({"type": "end"})
            with _lock:
                _active.pop(run_id, None)
            _slots.release()

    async def body():
        threading.Thread(target=work, daemon=True, name="studio-agent-run").start()
        try:
            yield json.dumps({"type": "started", "run_id": run_id}) + "\n"
            while True:
                try:
                    value = await asyncio.to_thread(events.get, True, 1)
                except queue.Empty:
                    yield json.dumps({"type": "heartbeat"}) + "\n"
                    continue
                yield json.dumps(value) + "\n"
                if value["type"] == "end":
                    break
        finally:
            stopped.set()

    return StreamingResponse(body(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
