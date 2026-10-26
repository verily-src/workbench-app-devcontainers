import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

import agent_store
import agent_store_config
import db


RESOURCE_ID = "cohort-dash-db-20261005"


@pytest.mark.parametrize("managed", [False, True])
def test_admin_config_selects_same_resource_for_runtime_and_migration(
        tmp_path, monkeypatch, managed):
    config_file = tmp_path / "studio.json"
    config_file.write_text("{}")
    monkeypatch.setenv("STUDIO_CONFIG", str(config_file))
    monkeypatch.delenv("STUDIO_AGENT_RESOURCE_ID", raising=False)
    agent_store_config.config_path().write_text(
        '{"resource_id": "' + RESOURCE_ID + '"}')

    created = []
    statements = []

    class Connection:
        def execute(self, _statement):
            statements.append(str(_statement))

    class Engine:
        @contextmanager
        def begin(self):
            yield Connection()

    engine = Engine()

    def get_engine(resource_id):
        created.append(resource_id)
        return engine

    monkeypatch.setattr(db, "get_engine_for_resource", get_engine)
    runtime_store = agent_store.AgentStore()
    assert runtime_store.resource_id == RESOURCE_ID
    assert runtime_store.engine is engine

    scripts = Path(__file__).resolve().parents[2] / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        import migrate_agent_store
        migrate_agent_store.main(["--managed-access"] if managed else [])
    finally:
        sys.path.remove(str(scripts))

    assert created == [RESOURCE_ID, RESOURCE_ID]
    assert any(s.startswith("REVOKE ") for s in statements) == (not managed)


def test_managed_migration_creates_working_store(engine, monkeypatch):
    import migrate_agent_store
    from sqlalchemy import text

    monkeypatch.setenv("STUDIO_AGENT_RESOURCE_ID", RESOURCE_ID)
    monkeypatch.setattr(db, "get_engine_for_resource", lambda _: engine)
    migrate_agent_store.main(["--managed-access"])
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema='_studio_agent'" )).scalar() == 6
    store = agent_store.AgentStore()
    turn = store.begin(session_id=None, owner="managed-test-owner", scope="managed-test",
                       system_prompt="Test", user_message="Hello", provider="test", model="test")
    store.finish(turn, "Saved")
    page = store.history(session_id=str(turn.session_id), owner="managed-test-owner", scope="managed-test")
    assert [message.content for message in page.messages] == ["Hello", "Saved"]


def test_environment_resource_takes_precedence(tmp_path, monkeypatch):
    config_file = tmp_path / "studio.json"
    config_file.write_text("{}")
    monkeypatch.setenv("STUDIO_CONFIG", str(config_file))
    agent_store_config.config_path().write_text("invalid")
    monkeypatch.setenv("STUDIO_AGENT_RESOURCE_ID", RESOURCE_ID)

    assert agent_store_config.resource_id() == RESOURCE_ID


def test_invalid_admin_resource_fails_with_clear_error(tmp_path, monkeypatch):
    config_file = tmp_path / "studio.json"
    config_file.write_text("{}")
    monkeypatch.setenv("STUDIO_CONFIG", str(config_file))
    monkeypatch.delenv("STUDIO_AGENT_RESOURCE_ID", raising=False)
    agent_store_config.config_path().write_text('{"resource_id": "bad/resource"}')

    with pytest.raises(agent_store_config.AgentStoreConfigError,
                       match="resource_id.*must contain 1 to 128"):
        agent_store_config.resource_id()


def test_explicit_resource_is_validated(monkeypatch):
    assert agent_store_config.resource_id(RESOURCE_ID) == RESOURCE_ID
    with pytest.raises(agent_store_config.AgentStoreConfigError,
                       match="explicit resource ID.*must contain"):
        agent_store_config.resource_id("bad/resource")
