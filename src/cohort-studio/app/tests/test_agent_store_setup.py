import json

from fastapi.testclient import TestClient

import db
import main


def test_settings_setup_creates_agent_storage(engine, monkeypatch, tmp_path):
    monkeypatch.setenv("STUDIO_CONFIG", str(tmp_path / "studio_config.json"))
    monkeypatch.delenv("STUDIO_AGENT_RESOURCE_ID", raising=False)
    monkeypatch.setattr(db, "list_aurora_resources", lambda wait=False: [{"id": "omop-data-source"}])
    monkeypatch.setattr(db, "get_engine_for_resource", lambda _rid: engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP SCHEMA IF EXISTS _studio_agent CASCADE")
    client = TestClient(main.app)
    try:
        before = client.get("/api/admin/agent-store").json()
        assert before == {"resource_id": None, "from_environment": False, "ready": False,
                          "aurora": ["omop-data-source"]}
        assert client.get("/api/agent/chat/sessions").status_code == 503

        assert client.post("/api/admin/agent-store", json={"resource_id": "other"}).status_code == 400
        done = client.post("/api/admin/agent-store", json={"resource_id": "omop-data-source"})
        assert done.status_code == 200, done.text
        assert done.json()["ready"] is True
        saved = tmp_path / "agent_store_config.json"
        assert json.loads(saved.read_text()) == {"resource_id": "omop-data-source"}
        assert oct(saved.stat().st_mode & 0o777) == "0o600"
        assert client.get("/api/admin/agent-store").json()["ready"] is True
        assert client.get("/api/agent/chat/sessions").status_code == 200

        monkeypatch.setenv("STUDIO_AGENT_RESOURCE_ID", "omop-data-source")
        assert client.post("/api/admin/agent-store", json={"resource_id": "omop-data-source"}).status_code == 409
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql("DROP SCHEMA IF EXISTS _studio_agent CASCADE")
