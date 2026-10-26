"""Create Aurora storage for assistant sessions and telemetry."""

import argparse
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import db
import agent_store_config


DDL = """
CREATE SCHEMA IF NOT EXISTS _studio_agent;
REVOKE ALL ON SCHEMA _studio_agent FROM PUBLIC;
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
REVOKE ALL ON ALL TABLES IN SCHEMA _studio_agent FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA _studio_agent FROM PUBLIC;
"""


def main(argv=None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--managed-access", action="store_true",
                        help="Keep existing database permissions; storage is not private.")
    args = parser.parse_args(argv)
    try:
        resource_id = agent_store_config.resource_id()
    except agent_store_config.AgentStoreConfigError as exc:
        raise SystemExit(str(exc)) from exc
    engine = db.get_engine_for_resource(resource_id)
    with engine.begin() as conn:
        for statement in DDL.split(";"):
            statement = statement.strip()
            if statement and not (args.managed_access and statement.startswith("REVOKE ")):
                conn.execute(text(statement))
    mode = "existing managed permissions (not private)" if args.managed_access else "private permissions"
    print(f"Agent store schema ready on {resource_id}: {mode}.")


if __name__ == "__main__":
    main()
