import asyncio
import json
import queue
import threading
import uuid

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

import agent_sessions
import llm
from agent_mode_api import AgentRequest, Operations, _SCOPE

router = APIRouter(prefix="/chat")
_lock = threading.Lock()
_active = {}
_slots = threading.BoundedSemaphore(4)
_CANCELLED = "Stopped. No further Agent steps will run. Already-submitted cloud workflows are unchanged."


def _error_message(exc):
    if isinstance(exc, llm.LLMNotConfigured):
        return "Agent provider setup is incomplete. Open Settings and check the provider, model, credentials and region."
    status = getattr(exc, "status_code", None)
    detail = str(exc).lower()
    if status == 402 or any(term in detail for term in
            ("insufficient credit", "credit balance", "insufficient_quota", "billing hard limit")):
        return "The provider has no available credit or quota. Check provider billing and quota, then retry."
    if status in (401, 403):
        return "The provider rejected access. Check credentials and model access in Settings."
    if status == 429:
        return "The provider request limit was reached. Wait and retry, or check provider quota."
    if status in (408, 504) or isinstance(exc, TimeoutError):
        return "The provider request timed out. Retry with a smaller request."
    return "Agent request failed. Check provider settings or try again."


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
        emit({"type": "progress", **{k: value[k] for k in
              ("turn", "tool_name", "error_code") if k in value},
              "stage": value.get("type", "step")})

    def work():
        session = None
        try:
            if stopped.is_set():
                raise agent_sessions.AgentCancelled()
            operations = Operations(owner)
            with agent_sessions.bind(owner, _SCOPE,
                                     str(req.session_id) if req.session_id else None,
                                     new_session=req.new_session) as session:
                result = studio_agent.chat(req.message, operations.callbacks(), on_step=step)
                if stopped.is_set():
                    raise agent_sessions.AgentCancelled()
                agent_sessions.finish(result)
            emit({"type": "result", "result": {**result, "actions": operations.actions,
                                                "workflow_plans": operations.workflow_plans}})
        except agent_sessions.AgentCancelled:
            emit({"type": "cancelled", "reply": _CANCELLED,
                  "session_id": str(session.turn.session_id) if session and session.turn else None})
        except Exception as exc:
            emit({"type": "error", "message": _error_message(exc)})
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
