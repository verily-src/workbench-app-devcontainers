from fastapi.testclient import TestClient

import database as db
import main
import omop


def test_tables_refresh_clears_listing_and_omop_caches(monkeypatch):
    cleared, calls = [], []

    def listing(rid):
        calls.append(rid)
        return []
    listing.invalidate = lambda: cleared.append("tables")
    monkeypatch.setattr(db, "list_aurora_tables", listing)
    monkeypatch.setattr(omop, "invalidate", lambda rid=None: cleared.append(("omop", rid)))
    client = TestClient(main.app)
    client.get("/api/tables", params={"kind": "aurora", "resource_id": "omop"})
    assert cleared == []
    client.get("/api/tables", params={"kind": "aurora", "resource_id": "omop", "refresh": "true"})
    assert cleared == ["tables", ("omop", "omop")]
    assert calls == ["omop", "omop"]
