import sys
from pathlib import Path

import pytest
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import migrate_agent_store
from agent_store import (AgentStore, AgentStoreBusy, AgentStoreNotFound,
                         AgentStoreError, FAILED_TURN_MESSAGE)


def test_agent_store_requires_an_explicit_resource(monkeypatch):
    monkeypatch.delenv("STUDIO_AGENT_RESOURCE_ID", raising=False)
    with pytest.raises(AgentStoreError, match="STUDIO_AGENT_RESOURCE_ID"):
        AgentStore()
    selected = []
    marker = object()
    resource_id = "6f1d7cf0-40d6-4a5d-8a68-1e0fd7345eaa"
    monkeypatch.setenv("STUDIO_AGENT_RESOURCE_ID", resource_id)
    monkeypatch.setattr("agent_store.db.get_engine_for_resource",
                        lambda resource_id: selected.append(resource_id) or marker)
    assert AgentStore().engine is marker
    assert selected == [resource_id]


@pytest.fixture
def agent_store(engine):
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS _studio_agent CASCADE"))
        for statement in migrate_agent_store.DDL.split(";"):
            if statement.strip():
                conn.execute(text(statement))
    yield AgentStore("test-resource", engine=engine, retention_days=30)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS _studio_agent CASCADE"))


def test_agent_store_round_trip_history_lease_and_redaction(agent_store, engine):
    first = agent_store.begin(
        session_id=None, owner="owner-binding-value-001", scope="dataset:alpha",
        system_prompt="Use the available tools.", user_message="api_key=secret123 list people",
        provider="test", model="fixture")
    assert first.history == []

    with pytest.raises(AgentStoreBusy):
        agent_store.begin(session_id=first.session_id, owner="owner-binding-value-001",
                          scope="dataset:alpha", system_prompt="Use the available tools.",
                          user_message="second turn", provider="test", model="fixture")

    agent_store.record_event(first.run_id, kind="tool", name="search", status="completed",
                             latency_ms=8, metadata={"row_count": 3,
                                                     "input_tokens": 11,
                                                     "output": [{"person_id": 9}],
                                                     "api_key": "secret123"})
    agent_store.finish(first, "Found 3 records. password:pw123", usage={
        "input_tokens": 11, "output_tokens": 6})

    second = agent_store.begin(
        session_id=first.session_id, owner="owner-binding-value-001", scope="dataset:alpha",
        system_prompt="Use the available tools.", user_message="next question",
        provider="test", model="fixture")
    assert second.history == [
        {"role": "user", "content": "api_key=[REDACTED] list people"},
        {"role": "assistant", "content": "Found 3 records. password:[REDACTED]"},
    ]
    assert second.prompt_digest == first.prompt_digest
    assert second.prompt_version == first.prompt_version
    page = agent_store.history(session_id=first.session_id, owner="owner-binding-value-001",
                               scope="dataset:alpha", limit=1)
    assert page.has_more and page.messages[0].role == "user"
    older = agent_store.history(session_id=first.session_id, owner="owner-binding-value-001",
                                scope="dataset:alpha", limit=1,
                                before_message_id=page.next_before_message_id)
    assert older.has_more and older.messages[0].role == "assistant"
    oldest = agent_store.history(session_id=first.session_id, owner="owner-binding-value-001",
                                 scope="dataset:alpha", limit=1,
                                 before_message_id=older.next_before_message_id)
    assert not oldest.has_more and oldest.messages[0].role == "user"
    assert agent_store.latest(owner="owner-binding-value-001",
                              scope="dataset:alpha") == first.session_id
    with pytest.raises(AgentStoreNotFound):
        agent_store.history(session_id=first.session_id, owner="different-owner-binding-001",
                            scope="dataset:alpha")
    agent_store.fail(second, error_class="TimeoutError", usage={"input_tokens": 7})

    with engine.connect() as conn:
        event = conn.execute(text("""SELECT metadata FROM _studio_agent.events
            WHERE run_id = :run_id"""), {"run_id": first.run_id}).scalar_one()
        runs = conn.execute(text("""SELECT status, input_tokens, output_tokens, error_class
            FROM _studio_agent.runs ORDER BY started_at""")).all()
        messages = conn.execute(text("""SELECT content FROM _studio_agent.messages
            ORDER BY message_id""")).scalars().all()
    assert event == {"row_count": 3, "input_tokens": 11}
    assert runs == [("completed", 11, 6, None), ("failed", 7, None, "TimeoutError")]
    assert all("secret123" not in message and "pw123" not in message for message in messages)

    third = agent_store.begin(session_id=first.session_id, owner="owner-binding-value-001",
                              scope="dataset:alpha", system_prompt="prompt v2",
                              user_message="after failure", provider="test", model="fixture")
    assert third.history[-2:] == [
        {"role": "user", "content": "next question"},
        {"role": "assistant", "content": FAILED_TURN_MESSAGE},
    ]
    agent_store.fail(third, error_class="CancelledError")


def test_agent_store_binds_owner_and_scope_and_requires_migration(engine):
    store = AgentStore("test-resource", engine=engine)
    with pytest.raises(AgentStoreError, match="schema is missing"):
        store.begin(session_id=None, owner="owner-binding-value-002", scope="dataset:alpha",
                    system_prompt="system", user_message="hello", provider="test", model="fixture")


def test_expired_lease_closes_old_turn_before_a_new_turn(agent_store, engine):
    old = agent_store.begin(session_id=None, owner="owner-binding-value-004",
                            scope="dataset:alpha", system_prompt="system",
                            user_message="first", provider="test", model="fixture")
    with engine.begin() as conn:
        conn.execute(text("""UPDATE _studio_agent.sessions
            SET lease_until = now() - interval '1 second' WHERE session_id = :sid"""),
                     {"sid": old.session_id})
    new = agent_store.begin(session_id=old.session_id, owner="owner-binding-value-004",
                            scope="dataset:alpha", system_prompt="system",
                            user_message="retry", provider="test", model="fixture")
    assert new.history == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": FAILED_TURN_MESSAGE},
    ]
    with pytest.raises(AgentStoreError, match="already closed"):
        agent_store.record_event(old.run_id, kind="tool", name="write", status="started")
    with pytest.raises(AgentStoreError, match="already closed"):
        agent_store.finish(old, "stale result")
    agent_store.fail(new, error_class="CancelledError")
    with engine.connect() as conn:
        assert conn.execute(text("""SELECT status, error_class FROM _studio_agent.runs
            WHERE run_id = :run_id"""), {"run_id": old.run_id}).one() == (
                "failed", "lease_expired")


def test_agent_store_cleanup_removes_telemetry_but_keeps_conversation(agent_store, engine):
    context = agent_store.begin(session_id=None, owner="owner-binding-value-003",
                                scope="dataset:alpha", system_prompt="system",
                                user_message="hello", provider="test", model="fixture")
    agent_store.fail(context, error_class="CancelledError")
    with engine.begin() as conn:
        conn.execute(text("UPDATE _studio_agent.runs SET completed_at = now() - interval '31 days'"))
    assert agent_store.cleanup() == 1
    page = agent_store.history(session_id=context.session_id, owner="owner-binding-value-003",
                               scope="dataset:alpha")
    assert [message.content for message in page.messages] == ["hello", FAILED_TURN_MESSAGE]
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM _studio_agent.sessions")).scalar_one() == 1
        assert conn.execute(text("SELECT count(*) FROM _studio_agent.runs")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM _studio_agent.prompts")).scalar_one() == 0


def test_long_assistant_message_is_preserved_without_silent_truncation(agent_store):
    context = agent_store.begin(session_id=None, owner="owner-binding-value-005",
                                scope="dataset:alpha", system_prompt="system",
                                user_message="explain", provider="test", model="fixture")
    answer = "Detailed explanation. " * 1500 + "End of answer."
    agent_store.finish(context, answer)
    page = agent_store.history(session_id=context.session_id, owner="owner-binding-value-005",
                               scope="dataset:alpha")
    assert page.messages[-1].content == answer
