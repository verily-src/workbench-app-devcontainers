"""Durable owner-scoped storage for approved workflow plans."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

import agent_store


SCHEMA = agent_store.SCHEMA
MAX_PLAN_BYTES = 48_000
MAX_LIST_LIMIT = 100
PLAN_DDL = """
CREATE TABLE IF NOT EXISTS _studio_agent.workflow_plans (
    plan_id uuid PRIMARY KEY,
    owner_hash char(64) NOT NULL,
    status varchar(24) NOT NULL CHECK (status IN
        ('blocked', 'ready', 'submitting', 'submission_unknown', 'submitted', 'running', 'completed', 'failed')),
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    expires_at timestamptz
);
CREATE INDEX IF NOT EXISTS workflow_plans_owner_updated_idx
    ON _studio_agent.workflow_plans (owner_hash, updated_at DESC);
CREATE INDEX IF NOT EXISTS workflow_plans_expiry_idx
    ON _studio_agent.workflow_plans (expires_at) WHERE expires_at IS NOT NULL;
"""


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: uuid.UUID
    owner: str = Field(min_length=1, max_length=256)
    payload: dict[str, Any]
    pending_expires_at: datetime


class AgentPlanStoreError(agent_store.AgentStoreError):
    pass


class AgentPlanStore:
    def __init__(self, resource_id: str | None = None, *, engine: Engine | None = None):
        self.store = (agent_store.AgentStore() if engine is None and resource_id is None else
                      agent_store.AgentStore(resource_id) if engine is None else
                      agent_store.AgentStore(resource_id, engine=engine))
        self.engine = self.store.engine

    def save(self, plan_id: str, owner: str, payload: dict[str, Any],
             pending_expires_at: datetime) -> dict:
        try:
            request = PlanRequest(plan_id=plan_id, owner=owner, payload=payload,
                                  pending_expires_at=pending_expires_at)
        except ValidationError as exc:
            raise AgentPlanStoreError("Invalid workflow plan.") from exc
        encoded = json.dumps(request.payload, separators=(",", ":"), sort_keys=True)
        if len(encoded.encode()) > MAX_PLAN_BYTES:
            raise AgentPlanStoreError("Workflow plan is too large to store.")
        now = datetime.now(timezone.utc)
        owner_hash = _owner_hash(request.owner)
        status = str(request.payload.get("status", ""))
        expires = request.pending_expires_at if status in {"blocked", "ready"} else None
        try:
            with self.engine.begin() as conn:
                agent_store._set_timeouts(conn)
                agent_store._require_schema(conn)
                conn.execute(text(f"""
                    INSERT INTO {SCHEMA}.workflow_plans
                        (plan_id, owner_hash, status, payload, created_at, updated_at, expires_at)
                    VALUES (:plan_id, :owner_hash, :status, CAST(:payload AS jsonb), :now, :now, :expires_at)
                """), {"plan_id": request.plan_id, "owner_hash": owner_hash,
                       "status": status, "payload": encoded, "now": now,
                       "expires_at": expires})
            return request.payload
        except SQLAlchemyError as exc:
            raise AgentPlanStoreError("Could not save workflow plan to Aurora.") from exc

    def get(self, plan_id: str, owner: str) -> dict:
        parsed_id = _plan_id(plan_id)
        owner_hash = _owner_hash(owner)
        try:
            with self.engine.begin() as conn:
                agent_store._set_timeouts(conn)
                agent_store._require_schema(conn)
                row = conn.execute(text(f"""
                    SELECT owner_hash, status, payload, expires_at
                    FROM {SCHEMA}.workflow_plans WHERE plan_id = :plan_id
                """), {"plan_id": parsed_id}).mappings().first()
            if row is None:
                raise agent_store.AgentStoreNotFound("Workflow plan was not found.")
            if row["owner_hash"].strip() != owner_hash:
                raise agent_store.AgentStoreOwnershipError("Workflow plan belongs to another owner.")
            if _is_expired(row):
                raise agent_store.AgentStoreNotFound("Workflow plan expired.")
            return dict(row["payload"])
        except (agent_store.AgentStoreError, AgentPlanStoreError):
            raise
        except SQLAlchemyError as exc:
            raise AgentPlanStoreError("Could not read workflow plan from Aurora.") from exc

    def list(self, owner: str, *, limit: int = 30, session_id: str | None = None) -> list[dict]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_LIST_LIMIT:
            raise AgentPlanStoreError(f"Plan list limit must be from 1 to {MAX_LIST_LIMIT}.")
        owner_hash = _owner_hash(owner)
        now = datetime.now(timezone.utc)
        try:
            with self.engine.begin() as conn:
                agent_store._set_timeouts(conn)
                agent_store._require_schema(conn)
                rows = conn.execute(text(f"""
                    SELECT payload FROM {SCHEMA}.workflow_plans
                    WHERE owner_hash = :owner_hash
                      AND (expires_at IS NULL OR expires_at > :now)
                      AND (CAST(:session_id AS text) IS NULL OR payload->>'session_id' = :session_id)
                    ORDER BY updated_at DESC, plan_id DESC LIMIT :limit
                """), {"owner_hash": owner_hash, "now": now,
                       "limit": limit, "session_id": session_id}).mappings().all()
            return [dict(row["payload"]) for row in rows]
        except SQLAlchemyError as exc:
            raise AgentPlanStoreError("Could not list workflow plans from Aurora.") from exc

    def claim(self, plan_id: str, owner: str) -> dict | None:
        """Atomically move an unexpired ready plan to submitting."""
        parsed_id = _plan_id(plan_id)
        owner_hash = _owner_hash(owner)
        now = datetime.now(timezone.utc)
        try:
            with self.engine.begin() as conn:
                agent_store._set_timeouts(conn)
                agent_store._require_schema(conn)
                row = conn.execute(text(f"""
                    UPDATE {SCHEMA}.workflow_plans
                    SET status = 'submitting', updated_at = :now, expires_at = NULL,
                        payload = jsonb_set(payload, '{{status}}', '"submitting"'::jsonb)
                    WHERE plan_id = :plan_id AND owner_hash = :owner_hash
                      AND status = 'ready' AND expires_at > :now
                    RETURNING payload
                """), {"plan_id": parsed_id, "owner_hash": owner_hash,
                       "now": now}).mappings().first()
            if row is not None:
                return dict(row["payload"])
            self.get(str(parsed_id), owner)
            return None
        except (agent_store.AgentStoreError, AgentPlanStoreError):
            raise
        except SQLAlchemyError as exc:
            raise AgentPlanStoreError("Could not claim workflow plan in Aurora.") from exc

    def update(self, plan_id: str, owner: str, payload: dict[str, Any]) -> dict:
        parsed_id = _plan_id(plan_id)
        owner_hash = _owner_hash(owner)
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        if len(encoded.encode()) > MAX_PLAN_BYTES:
            raise AgentPlanStoreError("Workflow plan is too large to store.")
        now = datetime.now(timezone.utc)
        status = str(payload.get("status", ""))
        try:
            with self.engine.begin() as conn:
                agent_store._set_timeouts(conn)
                agent_store._require_schema(conn)
                row = conn.execute(text(f"""
                    UPDATE {SCHEMA}.workflow_plans
                    SET status = :new_status, payload = CAST(:payload AS jsonb), updated_at = :now,
                        expires_at = CASE WHEN :pending_status IN ('blocked', 'ready') THEN expires_at ELSE NULL END
                    WHERE plan_id = :plan_id AND owner_hash = :owner_hash
                    RETURNING plan_id
                """), {"plan_id": parsed_id, "owner_hash": owner_hash,
                       "new_status": status, "pending_status": status,
                       "payload": encoded, "now": now}).first()
            if row is None:
                self.get(str(parsed_id), owner)
                raise agent_store.AgentStoreNotFound("Workflow plan was not found.")
            return payload
        except (agent_store.AgentStoreError, AgentPlanStoreError):
            raise
        except SQLAlchemyError as exc:
            raise AgentPlanStoreError("Could not update workflow plan in Aurora.") from exc

    def cleanup(self, *, now: datetime | None = None) -> int:
        cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=self.store.retention_days)
        try:
            with self.engine.begin() as conn:
                agent_store._set_timeouts(conn)
                agent_store._require_schema(conn)
                expired = conn.execute(text(f"""
                    DELETE FROM {SCHEMA}.workflow_plans
                    WHERE (status IN ('blocked', 'ready') AND expires_at <= :now)
                       OR (status IN ('completed', 'failed', 'submission_unknown')
                           AND updated_at < :cutoff)
                    RETURNING plan_id
                """), {"now": now or datetime.now(timezone.utc), "cutoff": cutoff}).fetchall()
                return len(expired)
        except SQLAlchemyError as exc:
            raise AgentPlanStoreError("Could not clean expired workflow plans.") from exc


def _owner_hash(owner: str) -> str:
    if not isinstance(owner, str) or not owner.strip():
        raise AgentPlanStoreError("An authenticated owner is required.")
    return hashlib.sha256(owner.encode("utf-8")).hexdigest()


def _plan_id(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise agent_store.AgentStoreNotFound("Workflow plan was not found.") from exc


def _is_expired(row) -> bool:
    return (row["status"] in {"blocked", "ready"} and row["expires_at"] is not None
            and row["expires_at"] <= datetime.now(timezone.utc))
