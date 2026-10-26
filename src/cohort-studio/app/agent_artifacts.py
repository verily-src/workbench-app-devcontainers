"""Owner-scoped dashboard recipes in the configured agent database."""
import hashlib

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

import agent_store
from source_models import source_dict


class Artifact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: str = Field(pattern=r"^[a-f0-9]{12}$")
    title: str = Field(min_length=1, max_length=128)
    source_ref: dict
    filters: list[dict] = Field(default_factory=list, max_length=30)
    charts: list[dict] = Field(default_factory=list, max_length=8)
    columns: list[dict] = Field(default_factory=list, max_length=2000)
    plan_id: str | None = None

    @field_validator("source_ref")
    @classmethod
    def source(cls, value):
        return source_dict(value)


def _owner(owner):
    if not isinstance(owner, str) or not 1 <= len(owner) <= 256:
        raise ValueError("Invalid dashboard owner.")
    return hashlib.sha256(owner.encode()).hexdigest()


def save(owner, value):
    artifact = Artifact.model_validate(value)
    payload = artifact.model_dump_json()
    if len(payload.encode()) > 128000:
        raise ValueError("Dashboard recipe is too large to save.")
    try:
        with agent_store.AgentStore().engine.begin() as conn:
            agent_store._set_timeouts(conn)
            conn.execute(text("""
                INSERT INTO _studio_agent.dashboard_artifacts (owner_hash, dataset_id, payload)
                VALUES (:owner, :id, CAST(:payload AS jsonb))
                ON CONFLICT (owner_hash, dataset_id) DO UPDATE
                SET payload=EXCLUDED.payload, updated_at=now()
            """), {"owner": _owner(owner), "id": artifact.dataset_id, "payload": payload})
    except SQLAlchemyError as exc:
        raise agent_store.AgentStoreError("Could not save Agent dashboard to Aurora.") from exc


def list_saved(owner):
    try:
        with agent_store.AgentStore().engine.begin() as conn:
            agent_store._set_timeouts(conn)
            rows = conn.execute(text("""
                SELECT payload FROM _studio_agent.dashboard_artifacts
                WHERE owner_hash=:owner ORDER BY updated_at DESC LIMIT 20
            """), {"owner": _owner(owner)}).scalars().all()
        return [Artifact.model_validate(row).model_dump() for row in rows]
    except SQLAlchemyError as exc:
        raise agent_store.AgentStoreError("Could not list saved Agent dashboards.") from exc


def get(owner, dataset_id):
    try:
        with agent_store.AgentStore().engine.begin() as conn:
            agent_store._set_timeouts(conn)
            row = conn.execute(text("""
                SELECT payload FROM _studio_agent.dashboard_artifacts
                WHERE owner_hash=:owner AND dataset_id=:id
            """), {"owner": _owner(owner), "id": dataset_id}).scalar_one_or_none()
        if row is None:
            raise ValueError("This saved dashboard is not available in your Agent session.")
        return Artifact.model_validate(row).model_dump()
    except SQLAlchemyError as exc:
        raise agent_store.AgentStoreError("Could not read saved Agent dashboard.") from exc
