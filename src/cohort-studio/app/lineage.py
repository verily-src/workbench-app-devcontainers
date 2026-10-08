"""Lineage and audit events.

Events are written to the same Aurora database the dashboard queries, so
they stay inside the workspace governance boundary and are queryable with
plain SQL. In local CSV mode (no workspace) they fall back to a SQLite
file so the lineage UI still works.

DynamoDB was evaluated and rejected: it is not a Workbench resource type,
and workspace credentials are ABAC-scoped to individual resources, so no
credential path to DynamoDB exists. See README for the full comparison.
"""

import getpass
import json
import logging
import os
import subprocess
from pathlib import Path

import pandas as pd
from sqlalchemy import (Column, DateTime, Engine, ForeignKey, Integer,
                        MetaData, Table, Text, create_engine, func, select)

logger = logging.getLogger(__name__)

metadata = MetaData()

event_table = Table(
    "_lineage_event", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", DateTime(timezone=True), server_default=func.now()),
    Column("actor", Text, nullable=False),
    Column("event_type", Text, nullable=False),
    Column("entity_type", Text, nullable=False),
    Column("entity_id", Text, nullable=False),
    # JSON stored as text so the same DDL works on PostgreSQL and SQLite
    Column("payload", Text, nullable=False, default="{}"),
)

edge_table = Table(
    "_lineage_edge", metadata,
    Column("event_id", Integer, ForeignKey("_lineage_event.id")),
    Column("parent_entity_type", Text, nullable=False),
    Column("parent_entity_id", Text, nullable=False),
)

# OpenTelemetry-shaped record of one chat-agent turn. Stored in Aurora so
# the agent's history lives inside the workspace governance boundary and
# is exportable to an OTel collector later (fields map to span attributes:
# gen_ai.system / gen_ai.request.model / usage.*). No live OTLP exporter
# runs in the Workbench VM, so we persist rather than emit.
agent_turn_table = Table(
    "_agent_turn", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", DateTime(timezone=True), server_default=func.now()),
    Column("trace_id", Text, nullable=False),
    Column("actor", Text, nullable=False),
    Column("provider", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("dataset", Text, nullable=False, default=""),
    Column("prompt", Text, nullable=False, default=""),
    Column("latency_ms", Integer, nullable=False, default=0),
    Column("prompt_tokens", Integer, nullable=False, default=0),
    Column("completion_tokens", Integer, nullable=False, default=0),
    Column("total_tokens", Integer, nullable=False, default=0),
    # JSON-as-text for portability across PostgreSQL and SQLite.
    Column("tool_calls", Text, nullable=False, default="[]"),
    Column("status", Text, nullable=False, default="ok"),
    Column("error", Text, nullable=True),
)

_actor_cache: str | None = None
_prepared_engines: set[int] = set()


def _actor() -> str:
    """The workspace user email, or the OS user outside a workspace."""
    global _actor_cache
    if _actor_cache:
        return _actor_cache
    try:
        result = subprocess.run(
            ["wb", "auth", "status", "--format", "json"],
            capture_output=True, text=True, check=True, timeout=10)
        _actor_cache = json.loads(result.stdout).get("userEmail") or getpass.getuser()
    except Exception:
        _actor_cache = getpass.getuser()
    return _actor_cache


def sqlite_fallback_engine() -> Engine:
    db_path = os.environ.get(
        "LINEAGE_DB", str(Path(__file__).parent / "lineage.db"))
    return create_engine(f"sqlite:///{db_path}",
                         connect_args={"check_same_thread": False})


def _ensure_tables(engine: Engine):
    if id(engine) not in _prepared_engines:
        metadata.create_all(engine)
        _prepared_engines.add(id(engine))


def record(engine: Engine, event_type: str, entity_type: str, entity_id: str,
           payload: dict | None = None, parents: list[tuple[str, str]] | None = None):
    """Append one event. Never raises — lineage must not break the app."""
    try:
        _ensure_tables(engine)
        with engine.connect() as conn:
            result = conn.execute(event_table.insert().values(
                actor=_actor(),
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                payload=json.dumps(payload or {}, default=str),
            ))
            event_id = result.inserted_primary_key[0]
            for parent_type, parent_id in parents or []:
                conn.execute(edge_table.insert().values(
                    event_id=event_id,
                    parent_entity_type=parent_type,
                    parent_entity_id=parent_id,
                ))
            conn.commit()
    except Exception as e:
        logger.warning("Failed to record lineage event %s: %s", event_type, e)


def record_turn(engine: Engine, trace_id: str, provider: str, model: str,
                dataset: str, prompt: str, latency_ms: int,
                usage: dict | None = None, tool_calls: list | None = None,
                status: str = "ok", error: str | None = None):
    """Append one agent-turn telemetry record. Never raises."""
    try:
        _ensure_tables(engine)
        usage = usage or {}
        with engine.connect() as conn:
            conn.execute(agent_turn_table.insert().values(
                trace_id=trace_id, actor=_actor(), provider=provider,
                model=model, dataset=dataset, prompt=prompt[:2000],
                latency_ms=int(latency_ms),
                prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
                completion_tokens=int(usage.get("completion_tokens", 0) or 0),
                total_tokens=int(usage.get("total_tokens", 0) or 0),
                tool_calls=json.dumps(tool_calls or []),
                status=status, error=error))
            conn.commit()
    except Exception as e:
        logger.warning("Failed to record agent turn: %s", e)


def recent_turns(engine: Engine, limit: int = 100) -> pd.DataFrame:
    cols = ["ts", "trace_id", "actor", "provider", "model", "dataset",
            "prompt", "latency_ms", "prompt_tokens", "completion_tokens",
            "total_tokens", "tool_calls", "status", "error"]
    try:
        _ensure_tables(engine)
        t = agent_turn_table.c
        query = (select(*[t[c] for c in cols])
                 .order_by(agent_turn_table.c.id.desc()).limit(limit))
        with engine.connect() as conn:
            return pd.read_sql_query(query, conn)
    except Exception as e:
        logger.warning("Failed to read agent turns: %s", e)
        return pd.DataFrame(columns=cols)


def recent_events(engine: Engine, limit: int = 200) -> pd.DataFrame:
    try:
        _ensure_tables(engine)
        query = (select(event_table.c.ts, event_table.c.actor,
                        event_table.c.event_type, event_table.c.entity_type,
                        event_table.c.entity_id, event_table.c.payload)
                 .order_by(event_table.c.id.desc()).limit(limit))
        with engine.connect() as conn:
            return pd.read_sql_query(query, conn)
    except Exception as e:
        logger.warning("Failed to read lineage events: %s", e)
        return pd.DataFrame(
            columns=["ts", "actor", "event_type", "entity_type", "entity_id",
                     "payload"])
