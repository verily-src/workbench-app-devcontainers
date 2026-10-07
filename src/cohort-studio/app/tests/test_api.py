"""API tests: the full upload → profile → cross-filter → export loop
against the real FastAPI app, no workspace needed."""

from pathlib import Path

from fastapi.testclient import TestClient

import main

FIXTURE = Path(__file__).parent / "fixtures" / "samples.csv"
client = TestClient(main.app)


def _open_fixture() -> dict:
    with open(FIXTURE, "rb") as f:
        resp = client.post("/api/datasets/upload",
                           files={"file": ("samples.csv", f, "text/csv")})
    assert resp.status_code == 200
    return resp.json()


def test_health():
    assert client.get("/api/health").json() == {"ok": True}


def test_upload_profiles_columns():
    body = _open_fixture()
    assert body["rows"] == 100
    cols = {c["name"]: c for c in body["columns"]}
    assert cols["tissue"]["filter_kind"] == "categorical"
    assert sorted(cols["tissue"]["values"]) == ["heart", "liver", "lung", "skin"]
    assert cols["rin_score"]["filter_kind"] == "range"
    assert cols["sample_id"]["filter_kind"] == "none"


def test_query_crossfilters_charts_and_rows():
    body = _open_fixture()
    resp = client.post(f"/api/datasets/{body['dataset_id']}/query", json={
        "filters": [{"column": "tissue", "kind": "categorical",
                     "values": ["liver"]}],
        "charts": [{"kind": "bar", "x": "tissue"},
                   {"kind": "histogram", "x": "rin_score"}],
        "page": 0, "page_size": 10,
    })
    assert resp.status_code == 200
    out = resp.json()
    assert out["total"] == 100
    assert out["filtered"] == 25
    bar = out["charts"][0]
    by_cat = {r["category"]: r for r in bar["data"]}
    assert by_cat["liver"] == {"category": "liver", "all": 25, "selected": 25}
    assert by_cat["lung"]["selected"] == 0
    hist = out["charts"][1]
    assert sum(b["all"] for b in hist["data"]) == 100
    assert sum(b["selected"] for b in hist["data"]) == 25
    assert len(out["rows"]["data"]) == 10


def test_export_respects_filters():
    body = _open_fixture()
    resp = client.post(f"/api/datasets/{body['dataset_id']}/export", json={
        "filters": [{"column": "tissue", "kind": "categorical",
                     "values": ["liver"]}]})
    assert resp.status_code == 200
    lines = resp.text.strip().split("\n")
    assert len(lines) == 26  # header + 25 liver rows


def test_unknown_dataset_is_404():
    resp = client.post("/api/datasets/nope/query", json={})
    assert resp.status_code == 404
