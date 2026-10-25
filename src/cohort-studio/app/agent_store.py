"""Durable storage for isolated assistant sessions and telemetry."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

import db
import agent_store_config

SCHEMA = "_studio_agent"
MAX_MESSAGE = 24_000
MAX_ASSISTANT_MESSAGE = 200_000
MAX_PROMPT = 48_000
MAX_HISTORY = 30
MAX_EVENT_BYTES = 4_000
MAX_EVENTS_PER_RUN = 200
DEFAULT_RETENTION_DAYS = 30
FAILED_TURN_MESSAGE = "The previous assistant turn did not complete."
SECRET_TEXT = re.compile(
    r"(?i)(\b(?:api[_ -]?key|password|passwd|secret|access[_ -]?token|"
    r"refresh[_ -]?token|authorization)\b\s*[:=]\s*)([^\s,;]+)"
)
BEARER_TEXT = re.compile(r"(?i)(\bbearer\s+)[A-Za-z0-9._~+/-]+=*")
KNOWN_SECRET_TOKEN = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16}|gh[pousr]_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,})\b"
)
SECRET_KEYS = re.compile(r"(?i)(secret|password|passwd|token|credential|api[_-]?key|authorization)")
OMIT_KEYS = re.compile(r"(?i)^(output|result|rows?|preview|content|arguments?|args|tool_output)$")
SAFE_USAGE_KEYS = {"input_tokens", "output_tokens", "prompt_tokens",
                   "completion_tokens", "total_tokens"}


class StoreInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class BeginRequest(StoreInput):
    session_id: uuid.UUID | None = None
    owner: str = Field(min_length=16, max_length=256)
    scope: str = Field(min_length=1, max_length=128)
    system_prompt: str = Field(min_length=1, max_length=MAX_PROMPT)
    user_message: str = Field(min_length=1, max_length=MAX_MESSAGE)
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)


class EventRequest(StoreInput):
    kind: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=160)
    status: str = Field(min_length=1, max_length=32)
    metadata: dict[str, Any] = Field(default_factory=dict)
    latency_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    error_class: str | None = Field(default=None, max_length=120)


class AssistantMessage(StoreInput):
    content: str = Field(max_length=MAX_ASSISTANT_MESSAGE)


class Usage(StoreInput):
    input_tokens: int | None = Field(default=None, ge=0, le=2_000_000)
    output_tokens: int | None = Field(default=None, ge=0, le=2_000_000)


class TurnContext(BaseModel):
    session_id: uuid.UUID
    run_id: uuid.UUID
    history: list[dict[str, str]]
    prompt_version: int
    prompt_digest: str


class HistoryMessage(BaseModel):
    message_id: int
    role: str
    content: str
    created_at: datetime


class HistoryPage(BaseModel):
    messages: list[HistoryMessage]
    has_more: bool
    next_before_message_id: int | None


class AgentStoreError(RuntimeError):
    pass


class AgentStoreBusy(AgentStoreError):
    pass


class AgentStoreOwnershipError(AgentStoreError):
    pass


class AgentStoreNotFound(AgentStoreError):
    pass


class AgentStore:
    def __init__(self, resource_id: str | None = None, *, engine: Engine | None = None,
                 retention_days: int | None = None, lease_seconds: int = 1800):
        try:
            self.resource_id = (resource_id or
                                (agent_store_config.resource_id() if engine is None else ""))
        except agent_store_config.AgentStoreConfigError as exc:
            raise AgentStoreError(str(exc)) from exc
        if engine is None and not self.resource_id:
            raise AgentStoreError("Agent persistence needs a configured Aurora resource.")
        self.engine = engine or db.get_engine_for_resource(self.resource_id)
        configured_days = os.environ.get("STUDIO_AGENT_RETENTION_DAYS")
        try:
            days = retention_days if retention_days is not None else int(
                configured_days or DEFAULT_RETENTION_DAYS)
        except ValueError as exc:
            raise AgentStoreError("STUDIO_AGENT_RETENTION_DAYS must be an integer.") from exc
        if not 1 <= days <= 3650:
            raise AgentStoreError("Agent retention must be between 1 and 3650 days.")
        if not 30 <= lease_seconds <= 86_400:
            raise AgentStoreError("Agent session lease must be between 30 and 86400 seconds.")
        self.retention_days = days
        self.lease_seconds = lease_seconds

    def begin(self, *, session_id: str | uuid.UUID | None, owner: str, scope: str,
              system_prompt: str, user_message: str, provider: str, model: str) -> TurnContext:
        try:
            request = BeginRequest(session_id=session_id, owner=owner, scope=scope,
                                   system_prompt=system_prompt, user_message=user_message,
                                   provider=provider, model=model)
        except ValidationError as exc:
            raise AgentStoreError("Invalid agent session request.") from exc
        sid = request.session_id or uuid.uuid4()
        run_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        owner_hash = hashlib.sha256(request.owner.encode()).hexdigest()
        prompt = _sanitize_text(request.system_prompt, MAX_PROMPT)
        digest = hashlib.sha256(prompt.encode()).hexdigest()
        user_text = _sanitize_text(request.user_message)
        try:
            with self.engine.begin() as conn:
                _set_timeouts(conn)
                _require_schema(conn)
                conn.execute(text(f"""
                    INSERT INTO {SCHEMA}.prompts (digest, version, body)
                    VALUES (:digest, nextval('{SCHEMA}.prompt_version_seq'), :body)
                    ON CONFLICT (digest) DO NOTHING
                """), {"digest": digest, "body": prompt})
                prompt_row = conn.execute(text(f"""
                    SELECT version FROM {SCHEMA}.prompts WHERE digest = :digest
                """), {"digest": digest}).one()
                conn.execute(text(f"""
                    INSERT INTO {SCHEMA}.sessions
                        (session_id, owner_hash, scope, created_at, updated_at)
                    VALUES (CAST(:sid AS uuid), :owner_hash, :scope, :now, :now)
                    ON CONFLICT (session_id) DO NOTHING
                """), {"sid": str(sid), "owner_hash": owner_hash,
                       "scope": request.scope, "now": now})
                session = conn.execute(text(f"""
                    SELECT owner_hash, scope, active_run_id, lease_until
                    FROM {SCHEMA}.sessions WHERE session_id = CAST(:sid AS uuid)
                    FOR UPDATE
                """), {"sid": str(sid)}).mappings().one()
                if session["owner_hash"] != owner_hash or session["scope"] != request.scope:
                    raise AgentStoreOwnershipError("Session does not belong to this owner and scope.")
                if session["active_run_id"] is not None and session["lease_until"] > now:
                    raise AgentStoreBusy("An assistant turn is already active for this session.")
                if session["active_run_id"] is not None:
                    conn.execute(text(f"""
                        UPDATE {SCHEMA}.runs SET status = 'failed', error_class = 'lease_expired',
                            completed_at = :now
                        WHERE run_id = :run_id AND status = 'running'
                    """), {"now": now, "run_id": session["active_run_id"]})
                    conn.execute(text(f"""
                        INSERT INTO {SCHEMA}.messages
                            (session_id, run_id, role, content, created_at)
                        VALUES (CAST(:sid AS uuid), :run_id, 'assistant', :content, :now)
                    """), {"sid": str(sid), "run_id": session["active_run_id"],
                           "content": FAILED_TURN_MESSAGE, "now": now})
                history = conn.execute(text(f"""
                    SELECT role, content FROM (
                        SELECT role, content, message_id FROM {SCHEMA}.messages
                        WHERE session_id = CAST(:sid AS uuid)
                        ORDER BY message_id DESC LIMIT :limit
                    ) recent ORDER BY message_id
                """), {"sid": str(sid), "limit": MAX_HISTORY}).mappings().all()
                conn.execute(text(f"""
                    INSERT INTO {SCHEMA}.runs
                        (run_id, session_id, prompt_digest, provider, model, status, started_at)
                    VALUES (:run_id, CAST(:sid AS uuid), :digest, :provider, :model, 'running', :now)
                """), {"run_id": run_id, "sid": str(sid), "digest": digest,
                       "provider": request.provider, "model": request.model, "now": now})
                conn.execute(text(f"""
                    INSERT INTO {SCHEMA}.messages (session_id, run_id, role, content, created_at)
                    VALUES (CAST(:sid AS uuid), :run_id, 'user', :content, :now)
                """), {"sid": str(sid), "run_id": run_id, "content": user_text, "now": now})
                conn.execute(text(f"""
                    UPDATE {SCHEMA}.sessions SET active_run_id = :run_id,
                        lease_until = :lease_until, updated_at = :now
                    WHERE session_id = CAST(:sid AS uuid)
                """), {"sid": str(sid), "run_id": run_id,
                       "lease_until": now + timedelta(seconds=self.lease_seconds), "now": now})
            prior = [{"role": row["role"], "content": row["content"]} for row in history]
            return TurnContext(session_id=sid, run_id=run_id, history=prior,
                               prompt_version=prompt_row.version, prompt_digest=digest)
        except (AgentStoreError, AgentStoreBusy, AgentStoreOwnershipError):
            raise
        except SQLAlchemyError as exc:
            raise AgentStoreError(
                "Agent persistence is unavailable; verify the configured Aurora resource "
                "and run scripts/migrate_agent_store.py.") from exc

    def record_event(self, run_id: str | uuid.UUID, *, kind: str, name: str, status: str,
                     metadata: dict[str, Any] | None = None, latency_ms: int | None = None,
                     error_class: str | None = None) -> None:
        try:
            event = EventRequest(kind=kind, name=name, status=status,
                                 metadata=metadata or {}, latency_ms=latency_ms,
                                 error_class=error_class)
        except ValidationError as exc:
            raise AgentStoreError("Invalid agent event.") from exc
        safe = _sanitize_metadata(event.metadata)
        payload = json.dumps(safe, separators=(",", ":"))
        if len(payload.encode()) > MAX_EVENT_BYTES:
            payload = json.dumps({"truncated": True})
        try:
            with self.engine.begin() as conn:
                _set_timeouts(conn)
                run_session = conn.execute(text(f"""
                    SELECT session_id FROM {SCHEMA}.runs
                    WHERE run_id = :run_id AND status = 'running'
                """), {"run_id": uuid.UUID(str(run_id))}).first()
                if run_session is None:
                    raise AgentStoreError("Agent turn is already closed or unknown.")
                session = conn.execute(text(f"""
                    SELECT active_run_id FROM {SCHEMA}.sessions
                    WHERE session_id = :sid FOR UPDATE
                """), {"sid": run_session.session_id}).first()
                if session is None or session.active_run_id != uuid.UUID(str(run_id)):
                    raise AgentStoreError("Agent turn is no longer active.")
                run_exists = conn.execute(text(f"""
                    SELECT 1 FROM {SCHEMA}.runs WHERE run_id = :run_id AND status = 'running'
                    FOR UPDATE
                """), {"run_id": uuid.UUID(str(run_id))}).first()
                if run_exists is None:
                    raise AgentStoreError("Agent turn is already closed or unknown.")
                now = datetime.now(timezone.utc)
                conn.execute(text(f"""
                    UPDATE {SCHEMA}.sessions SET lease_until = :lease_until, updated_at = :now
                    WHERE session_id = :sid AND active_run_id = :run_id
                """), {"lease_until": now + timedelta(seconds=self.lease_seconds),
                       "now": now, "sid": run_session.session_id,
                       "run_id": uuid.UUID(str(run_id))})
                event_count = conn.execute(text(f"""
                    SELECT count(*) FROM {SCHEMA}.events WHERE run_id = :run_id
                """), {"run_id": uuid.UUID(str(run_id))}).scalar_one()
                if event_count >= MAX_EVENTS_PER_RUN:
                    return
                conn.execute(text(f"""
                    INSERT INTO {SCHEMA}.events
                        (run_id, kind, name, status, latency_ms, error_class, metadata)
                    VALUES (:run_id, :kind, :name, :status, :latency, :error, CAST(:metadata AS jsonb))
                """), {"run_id": uuid.UUID(str(run_id)), "kind": event.kind,
                       "name": event.name, "status": event.status,
                       "latency": event.latency_ms, "error": event.error_class,
                       "metadata": payload})
        except SQLAlchemyError as exc:
            raise AgentStoreError("Could not persist agent event.") from exc

    def finish(self, context: TurnContext, assistant_message: str, *,
               usage: dict[str, int | None] | None = None) -> None:
        self._close(context, status="completed", assistant_message=assistant_message,
                    usage=usage, error_class=None)

    def fail(self, context: TurnContext, *, error_class: str,
             usage: dict[str, int | None] | None = None) -> None:
        self._close(context, status="failed", assistant_message=FAILED_TURN_MESSAGE,
                    usage=usage, error_class=error_class)

    def latest(self, *, owner: str, scope: str) -> uuid.UUID | None:
        owner_hash = hashlib.sha256(owner.encode()).hexdigest()
        try:
            with self.engine.connect() as conn:
                _set_timeouts(conn)
                row = conn.execute(text(f"""
                    SELECT session_id FROM {SCHEMA}.sessions
                    WHERE owner_hash = :owner_hash AND scope = :scope
                    ORDER BY updated_at DESC LIMIT 1
                """), {"owner_hash": owner_hash, "scope": scope}).first()
                return row.session_id if row else None
        except SQLAlchemyError as exc:
            raise AgentStoreError("Could not load agent session.") from exc

    def history(self, *, session_id: str | uuid.UUID, owner: str, scope: str,
                before_message_id: int | None = None, limit: int = 100) -> HistoryPage:
        try:
            sid = uuid.UUID(str(session_id))
            page_size = min(max(int(limit), 1), 100)
            if before_message_id is not None and before_message_id < 1:
                raise ValueError("Invalid message cursor")
        except (ValueError, TypeError) as exc:
            raise AgentStoreError("Invalid agent history request.") from exc
        owner_hash = hashlib.sha256(owner.encode()).hexdigest()
        try:
            with self.engine.connect() as conn:
                _set_timeouts(conn)
                allowed = conn.execute(text(f"""
                    SELECT 1 FROM {SCHEMA}.sessions
                    WHERE session_id = :sid AND owner_hash = :owner_hash AND scope = :scope
                """), {"sid": sid, "owner_hash": owner_hash, "scope": scope}).first()
                if allowed is None:
                    raise AgentStoreNotFound("Agent session was not found.")
                rows = conn.execute(text(f"""
                    SELECT message_id, role, content, created_at
                    FROM {SCHEMA}.messages WHERE session_id = :sid
                      AND (CAST(:before_id AS bigint) IS NULL
                           OR message_id < CAST(:before_id AS bigint))
                    ORDER BY message_id DESC LIMIT :limit
                """), {"sid": sid, "before_id": before_message_id,
                       "limit": page_size + 1}).mappings().all()
            has_more = len(rows) > page_size
            page_rows = list(reversed(rows[:page_size]))
            messages = [HistoryMessage(**row) for row in page_rows]
            return HistoryPage(messages=messages, has_more=has_more,
                               next_before_message_id=(messages[0].message_id
                                                       if has_more and messages else None))
        except AgentStoreNotFound:
            raise
        except SQLAlchemyError as exc:
            raise AgentStoreError("Could not load agent history.") from exc

    def _close(self, context: TurnContext, *, status: str,
               assistant_message: str | None, usage: dict[str, int | None] | None,
               error_class: str | None) -> None:
        try:
            parsed_usage = Usage(**(usage or {}))
            answer = (_sanitize_text(AssistantMessage(content=assistant_message).content,
                                     MAX_ASSISTANT_MESSAGE)
                      if assistant_message is not None else None)
        except (ValidationError, TypeError) as exc:
            raise AgentStoreError("Invalid agent completion.") from exc
        now = datetime.now(timezone.utc)
        try:
            with self.engine.begin() as conn:
                _set_timeouts(conn)
                run_session = conn.execute(text(f"""
                    SELECT session_id FROM {SCHEMA}.runs
                    WHERE run_id = :run_id AND session_id = CAST(:sid AS uuid)
                      AND status = 'running'
                """), {"run_id": context.run_id,
                       "sid": str(context.session_id)}).first()
                if run_session is None:
                    raise AgentStoreError("Agent turn is already closed or unknown.")
                session = conn.execute(text(f"""
                    SELECT active_run_id FROM {SCHEMA}.sessions
                    WHERE session_id = :sid FOR UPDATE
                """), {"sid": run_session.session_id}).first()
                if session is None or session.active_run_id != context.run_id:
                    raise AgentStoreError("Agent turn is no longer active.")
                run = conn.execute(text(f"""
                    UPDATE {SCHEMA}.runs SET status = :status, completed_at = :now,
                        duration_ms = GREATEST(0, (EXTRACT(EPOCH FROM (:now - started_at)) * 1000)::bigint),
                        input_tokens = :input_tokens, output_tokens = :output_tokens,
                        error_class = :error_class
                    WHERE run_id = :run_id AND session_id = CAST(:sid AS uuid) AND status = 'running'
                    RETURNING run_id
                """), {"status": status, "now": now,
                       "input_tokens": parsed_usage.input_tokens,
                       "output_tokens": parsed_usage.output_tokens,
                       "error_class": error_class, "run_id": context.run_id,
                       "sid": str(context.session_id)}).first()
                if run is None:
                    raise AgentStoreError("Agent turn is already closed or unknown.")
                if answer is not None:
                    conn.execute(text(f"""
                        INSERT INTO {SCHEMA}.messages (session_id, run_id, role, content, created_at)
                        VALUES (CAST(:sid AS uuid), :run_id, 'assistant', :content, :now)
                    """), {"sid": str(context.session_id), "run_id": context.run_id,
                           "content": answer, "now": now})
                conn.execute(text(f"""
                    UPDATE {SCHEMA}.sessions SET active_run_id = NULL, lease_until = NULL, updated_at = :now
                    WHERE session_id = CAST(:sid AS uuid) AND active_run_id = :run_id
                """), {"sid": str(context.session_id), "run_id": context.run_id, "now": now})
        except AgentStoreError:
            raise
        except SQLAlchemyError as exc:
            raise AgentStoreError("Could not close agent turn.") from exc

    def cleanup(self, *, now: datetime | None = None) -> int:
        cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=self.retention_days)
        try:
            with self.engine.begin() as conn:
                _set_timeouts(conn)
                deleted = conn.execute(text(f"""
                    DELETE FROM {SCHEMA}.runs
                    WHERE status <> 'running' AND completed_at < :cutoff
                    RETURNING run_id
                """), {"cutoff": cutoff}).fetchall()
                conn.execute(text(f"""
                    DELETE FROM {SCHEMA}.prompts p
                    WHERE NOT EXISTS (
                        SELECT 1 FROM {SCHEMA}.runs r WHERE r.prompt_digest = p.digest
                    )
                """))
                return len(deleted)
        except SQLAlchemyError as exc:
            raise AgentStoreError("Could not clean expired agent telemetry.") from exc


def _require_schema(conn) -> None:
    exists = conn.execute(text("SELECT to_regclass('_studio_agent.sessions') IS NOT NULL")).scalar()
    if not exists:
        raise AgentStoreError(
            "Agent store schema is missing; run scripts/migrate_agent_store.py.")


def _set_timeouts(conn) -> None:
    conn.execute(text("SET LOCAL statement_timeout = '5000ms'"))
    conn.execute(text("SET LOCAL lock_timeout = '1000ms'"))


def _sanitize_text(value: str | None, limit: int = MAX_MESSAGE) -> str | None:
    if value is None:
        return None
    safe = SECRET_TEXT.sub(r"\1[REDACTED]", value[:limit])
    safe = BEARER_TEXT.sub(r"\1[REDACTED]", safe)
    return KNOWN_SECRET_TOKEN.sub("[REDACTED]", safe)


def _sanitize_metadata(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        safe = {}
        for key, item in list(value.items())[:40]:
            label = str(key)[:80]
            if label.lower() in SAFE_USAGE_KEYS:
                if isinstance(item, int) and 0 <= item <= 2_000_000:
                    safe[label] = item
                continue
            if SECRET_KEYS.search(label) or OMIT_KEYS.match(label):
                continue
            safe[label] = _sanitize_metadata(item, depth + 1)
        return safe
    if isinstance(value, (list, tuple)):
        return [_sanitize_metadata(v, depth + 1) for v in value[:40]]
    if isinstance(value, str):
        return _sanitize_text(value[:500])
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return str(value)[:120]
