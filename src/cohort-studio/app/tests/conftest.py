import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def fake_aurora(tmp_path, monkeypatch):
    """SQLite with an attached `public` schema stands in for an Aurora
    database, so the pushdown SQL runs for real (minus Postgres-only
    statements such as SET LOCAL)."""
    from sqlalchemy import create_engine, event

    import db
    engine = create_engine(f"sqlite:///{tmp_path / 'main.db'}")
    public = tmp_path / "public.db"

    @event.listens_for(engine, "connect")
    def _attach(dbapi_conn, _record):
        dbapi_conn.execute(f"ATTACH DATABASE '{public}' AS public")

    monkeypatch.setattr(db, "get_engine_for_resource", lambda rid: engine)
    return engine
