"""Create Aurora storage for assistant sessions and telemetry.

Shared by scripts/migrate_agent_store.py and the Settings "Agent memory"
setup action, so a deployed app can be set up without a shell.
"""
from sqlalchemy import text

import db

DDL = """
CREATE SCHEMA IF NOT EXISTS _studio_agent;
REVOKE ALL ON SCHEMA _studio_agent FROM PUBLIC;
CREATE TABLE IF NOT EXISTS _studio_agent.dashboard_artifacts (
    owner_hash char(64) NOT NULL,
    dataset_id varchar(12) NOT NULL,
    payload jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (owner_hash, dataset_id)
);
CREATE INDEX IF NOT EXISTS dashboard_artifacts_owner_updated_idx
    ON _studio_agent.dashboard_artifacts (owner_hash, updated_at DESC);
CREATE SEQUENCE IF NOT EXISTS _studio_agent.prompt_version_seq;
CREATE TABLE IF NOT EXISTS _studio_agent.prompts (
    digest char(64) PRIMARY KEY,
    version bigint NOT NULL UNIQUE,
    body text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS _studio_agent.sessions (
    session_id uuid PRIMARY KEY,
    owner_hash char(64) NOT NULL,
    scope varchar(128) NOT NULL,
    active_run_id uuid,
    lease_until timestamptz,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS _studio_agent.runs (
    run_id uuid PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES _studio_agent.sessions(session_id) ON DELETE CASCADE,
    prompt_digest char(64) NOT NULL REFERENCES _studio_agent.prompts(digest),
    provider varchar(100) NOT NULL,
    model varchar(200) NOT NULL,
    status varchar(16) NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    started_at timestamptz NOT NULL,
    completed_at timestamptz,
    duration_ms bigint,
    input_tokens integer,
    output_tokens integer,
    error_class varchar(120)
);
CREATE INDEX IF NOT EXISTS runs_session_idx ON _studio_agent.runs (session_id, started_at);
CREATE TABLE IF NOT EXISTS _studio_agent.messages (
    message_id bigserial PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES _studio_agent.sessions(session_id) ON DELETE CASCADE,
    run_id uuid NOT NULL,
    role varchar(16) NOT NULL CHECK (role IN ('user', 'assistant')),
    content text NOT NULL,
    created_at timestamptz NOT NULL
);
ALTER TABLE _studio_agent.messages ALTER COLUMN content TYPE text;
CREATE INDEX IF NOT EXISTS messages_session_idx ON _studio_agent.messages (session_id, message_id);
CREATE TABLE IF NOT EXISTS _studio_agent.events (
    event_id bigserial PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES _studio_agent.runs(run_id) ON DELETE CASCADE,
    kind varchar(32) NOT NULL,
    name varchar(160) NOT NULL,
    status varchar(32) NOT NULL,
    latency_ms integer,
    error_class varchar(120),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS events_run_idx ON _studio_agent.events (run_id, event_id);
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
CREATE TABLE IF NOT EXISTS _studio_agent.session_state (
    session_id uuid PRIMARY KEY REFERENCES _studio_agent.sessions(session_id) ON DELETE CASCADE,
    payload jsonb NOT NULL,
    updated_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS session_state_updated_idx
    ON _studio_agent.session_state (updated_at);
REVOKE ALL ON ALL TABLES IN SCHEMA _studio_agent FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA _studio_agent FROM PUBLIC;
"""


def migrate(resource_id: str, managed_access: bool) -> str:
    """Create the _studio_agent schema (idempotent).

    managed_access keeps existing database permissions (readers may read
    conversations); otherwise access is revoked from PUBLIC.
    """
    engine = db.get_engine_for_resource(resource_id)
    with engine.begin() as conn:
        for statement in DDL.split(";"):
            statement = statement.strip()
            if statement and not (managed_access and statement.startswith("REVOKE ")):
                conn.execute(text(statement))
    return ("existing managed permissions (not private)" if managed_access
            else "private permissions")


def ready(resource_id: str) -> bool:
    engine = db.get_engine_for_resource(resource_id)
    with engine.connect() as conn:
        return bool(conn.execute(text(
            "SELECT to_regclass('_studio_agent.sessions') IS NOT NULL")).scalar())
