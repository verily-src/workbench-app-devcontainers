"""Several OMOP CDM schemas in one database.

A second CDM schema ``alt_cdm`` is loaded next to the session ``cdm`` schema
for this module only and dropped afterwards; other tests assume ``cdm`` alone.
``alt_cdm`` has the same tables but fewer persons (60 vs 100) and sorts first,
so the old "most tables, then name" rule would have picked it: the default must
follow persons. It also carries a marker concept that exists only in its own
vocabulary.
"""
import json

import psycopg
import pytest
from sqlalchemy import text

import agent_mode_api
import agent_store as store_module
import datasets
import main
import omop
import omop_load
import source_models
from tests.conftest import FIXTURE, RID
from tests.test_agent_store import agent_store  # noqa: F401  (fixture)
from tests.test_studio_agent_api import workspace  # noqa: F401  (fixture)

TWO = "alt_cdm"
KEPT = 60
GI_BLEED = 192671
MARKER = 2_000_000_001
SPEC_GI = {"criteria": [{"domain": "condition", "concept_ids": [GI_BLEED]}]}
SPEC_MARKER = {"criteria": [{"domain": "condition", "concept_ids": [MARKER]}]}


@pytest.fixture(scope="module")
def two_schemas(pg, engine):
    try:
        with psycopg.connect(f"{pg['dsn']} dbname=omop") as conn:
            omop_load.load(conn, FIXTURE, TWO, log=lambda *_: None)
        with engine.begin() as conn:
            tables = [row[0] for row in conn.execute(text(
                "SELECT table_name FROM information_schema.columns "
                "WHERE table_schema = :s AND column_name = 'person_id' "
                "AND table_name <> 'person'"), {"s": TWO})]
            keep = f"SELECT person_id FROM {TWO}.person ORDER BY person_id LIMIT {KEPT}"
            for table in tables:
                conn.exec_driver_sql(
                    f'DELETE FROM {TWO}."{table}" WHERE person_id NOT IN ({keep})')
            conn.exec_driver_sql(f"DELETE FROM {TWO}.person WHERE person_id NOT IN ({keep})")
            conn.exec_driver_sql(f"CREATE TEMP TABLE marker AS SELECT * FROM {TWO}.concept "
                                 f"WHERE concept_id = {GI_BLEED}")
            conn.exec_driver_sql(f"UPDATE marker SET concept_id = {MARKER}, "
                                 "concept_name = 'Multischema marker finding', concept_code = 'msm1'")
            conn.exec_driver_sql(f"INSERT INTO {TWO}.concept SELECT * FROM marker")
            conn.exec_driver_sql(f"UPDATE {TWO}.condition_occurrence SET condition_concept_id "
                                 f"= {MARKER} WHERE condition_concept_id = {GI_BLEED}")
            conn.exec_driver_sql(f"ANALYZE {TWO}.person")
            marker_persons = conn.execute(text(
                f"SELECT count(DISTINCT person_id) FROM {TWO}.condition_occurrence "
                "WHERE condition_concept_id = :m"), {"m": MARKER}).scalar_one()
        omop.invalidate()
        assert marker_persons > 0
        yield {"marker_persons": marker_persons}
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql(f"DROP SCHEMA IF EXISTS {TWO} CASCADE")
        omop.invalidate()


@pytest.fixture(autouse=True)
def _clean_detection(two_schemas):
    omop.invalidate()
    yield
    omop.invalidate()


def test_detection_lists_every_cdm_schema_and_defaults_to_most_persons(engine, monkeypatch):
    monkeypatch.delenv(omop.DEFAULT_SCHEMA_ENV, raising=False)
    info = omop.detect(engine)
    assert (info["cdm_schema"], info["vocab_schema"], info["default_cdm_schema"]) == \
        ("cdm", "cdm", "cdm")
    assert omop.schema_summary(info) == [
        {"cdm_schema": TWO, "vocab_schema": TWO, "persons": KEPT, "default": False},
        {"cdm_schema": "cdm", "vocab_schema": "cdm", "persons": 100, "default": True}]
    other = omop.detect(engine, TWO)
    assert (other["cdm_schema"], other["vocab_schema"], other["default_cdm_schema"]) == \
        (TWO, TWO, "cdm")
    assert next(t for t in other["tables"] if t["name"] == "person")["rows"] == KEPT
    public = omop.public(other)
    assert public["cdm_schema"] == TWO and len(public["cdm_schemas"]) == 2
    with pytest.raises(ValueError, match="Available CDM schemas: alt_cdm, cdm"):
        omop.detect(engine, "missing")


def test_default_schema_env_override(engine, monkeypatch):
    monkeypatch.setenv(omop.DEFAULT_SCHEMA_ENV, TWO)
    assert omop.detect(engine)["cdm_schema"] == TWO
    monkeypatch.setenv(omop.DEFAULT_SCHEMA_ENV, f"other=cdm,{RID}={TWO}")
    assert omop.detect(engine, resource_id=RID)["cdm_schema"] == TWO
    assert omop.detect(engine, resource_id="other")["cdm_schema"] == "cdm"
    monkeypatch.setenv(omop.DEFAULT_SCHEMA_ENV, "not_a_cdm")
    assert omop.detect(engine)["cdm_schema"] == "cdm"


def test_cache_and_hint_are_per_schema(client, monkeypatch):
    monkeypatch.delenv(omop.DEFAULT_SCHEMA_ENV, raising=False)
    assert omop.detect_resource(RID, TWO)["cdm_schema"] == TWO
    with omop._hint_lock:
        assert RID not in omop._hints  # a non-default detection leaves the hint alone
    assert omop.detect_resource(RID)["cdm_schema"] == "cdm"
    with omop._hint_lock:
        summary = omop._hints[RID][1]
    assert summary["cdm_schema"] == "cdm" and summary["persons"] == 100
    assert summary["cdm_schemas"] == [{"cdm_schema": TWO, "persons": KEPT},
                                      {"cdm_schema": "cdm", "persons": 100}]


def test_api_takes_an_optional_cdm_schema(client, two_schemas):
    body = client.get(f"/api/omop/{RID}").json()
    assert body["cdm_schema"] == "cdm" and body["default_cdm_schema"] == "cdm"
    assert [s["cdm_schema"] for s in body["cdm_schemas"]] == [TWO, "cdm"]
    assert client.get(f"/api/omop/{RID}?cdm_schema={TWO}").json()["cdm_schema"] == TWO
    bad = client.get(f"/api/omop/{RID}?cdm_schema=nope")
    assert bad.status_code == 400 and "alt_cdm, cdm" in bad.json()["detail"]
    for method, path, payload in [
            ("get", "/concepts?q=marker", None),
            ("post", "/cohort/count", {}),
            ("post", "/cohort/summary", {"spec": {}}),
            ("post", "/cohort/open", {"spec": {}}),
            ("post", "/domain/open", {"table": "person"})]:
        response = getattr(client, method)(
            f"/api/omop/{RID}{path}{'&' if '?' in path else '?'}cdm_schema=nope",
            **({"json": payload} if payload is not None else {}))
        assert response.status_code == 400, (path, response.text)
        assert TWO in response.json()["detail"]

    counts = [client.post(f"/api/omop/{RID}/cohort/count{q}", json={}).json()["total_persons"]
              for q in ("", "?cdm_schema=cdm", f"?cdm_schema={TWO}")]
    assert counts == [100, 100, KEPT]
    marker = client.post(f"/api/omop/{RID}/cohort/count?cdm_schema={TWO}", json=SPEC_MARKER)
    assert marker.json()["persons"] == two_schemas["marker_persons"]
    assert client.post(f"/api/omop/{RID}/cohort/count?cdm_schema={TWO}",
                       json=SPEC_GI).json()["persons"] == 0
    assert client.post(f"/api/omop/{RID}/cohort/count", json=SPEC_GI).json()["persons"] == 40

    def search(query):
        return [c["concept_id"] for c in client.get(
            f"/api/omop/{RID}/concepts?q=Multischema+marker{query}").json()["concepts"]]
    assert search("") == [] and search(f"&cdm_schema={TWO}") == [MARKER]
    summary = client.post(f"/api/omop/{RID}/cohort/summary?cdm_schema={TWO}",
                          json={"spec": {}}).json()
    assert summary["total_persons"] == KEPT
    domain = client.post(f"/api/omop/{RID}/domain/open?cdm_schema={TWO}",
                         json={"table": "person", "concept_names": False}).json()
    try:
        assert domain["rows"] == KEPT and domain["source"] == f"{RID} / {TWO}.person"
    finally:
        datasets.close_dataset(domain["dataset_id"])


def test_omop_cohort_refs_resolve_their_cdm_schema(client, tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    lineage_engine = create_engine(f"sqlite:///{tmp_path / 'lineage.db'}",
                                   connect_args={"check_same_thread": False})
    monkeypatch.setattr(main, "_lineage_engine", lambda: lineage_engine)
    legacy = source_models.source_dict({"kind": "omop_cohort", "resource_id": RID,
                                        "spec": {}, "membership_mode": "live"})
    assert "cdm_schema" not in legacy
    pinned = source_models.source_dict({**legacy, "cdm_schema": TWO})
    opened = []
    try:
        for ref, rows in ((legacy, 100), (pinned, KEPT)):
            result = main._open_source(ref)
            opened.append(result["dataset_id"])
            assert result["rows"] == rows
            assert result["source_ref"].get("cdm_schema") == ref.get("cdm_schema")
        assert TWO in datasets.get(opened[1])["source"]
        api = client.post(f"/api/omop/{RID}/cohort/open?cdm_schema={TWO}",
                          json={"spec": {}, "name": "Second"}).json()
        opened.append(api["dataset_id"])
        assert api["rows"] == KEPT and api["source_ref"]["cdm_schema"] == TWO
        default = client.post(f"/api/omop/{RID}/cohort/open", json={"spec": {}}).json()
        opened.append(default["dataset_id"])
        assert default["rows"] == 100 and "cdm_schema" not in default["source_ref"]
        with pytest.raises(Exception) as bad:
            main._open_source(source_models.source_dict({**legacy, "cdm_schema": "nope"}))
        assert TWO in str(getattr(bad.value, "detail", bad.value))
    finally:
        for dataset_id in opened:
            datasets.close_dataset(dataset_id)


def test_agent_tools_use_cdm_schema_and_key_the_concept_guard(workspace, two_schemas):
    agent_mode_api._dashboards.clear()
    omop.detect_resource(RID)  # feed the hint list_sources reads
    ops = agent_mode_api.Operations("multi-schema-owner")
    entry = ops.list_sources()["sources"][0]
    assert entry["omop"] == {"default_cdm_schema": "cdm", "cdm_schemas": [
        {"cdm_schema": TWO, "persons": KEPT}, {"cdm_schema": "cdm", "persons": 100}]}

    found = ops.search_concepts(RID, "Multischema marker", "condition", cdm_schema=TWO)
    assert [c["concept_id"] for c in found["concepts"]] == [MARKER]
    assert found["cdm_schema"] == TWO and len(found["cdm_schemas"]) == 2
    assert ops.search_concepts(RID, "Multischema marker", "condition")["concepts"] == []
    # An ID found in alt_cdm does not validate a cohort in the default schema.
    with pytest.raises(ValueError, match="Search concepts"):
        ops.count_cohort(RID, json.dumps(SPEC_MARKER))
    result = ops.count_cohort(RID, json.dumps(SPEC_MARKER), cdm_schema=TWO)
    assert result["persons"] == two_schemas["marker_persons"]
    assert result["cdm_schema"] == TWO and result["total_persons"] == KEPT
    assert ops.cohort["cdm_schema"] == TWO

    # And the reverse: a default-schema ID is not accepted for alt_cdm.
    assert GI_BLEED in {c["concept_id"] for c in
                        ops.search_concepts(RID, str(GI_BLEED), "condition")["concepts"]}
    assert ops.count_cohort(RID, json.dumps(SPEC_GI))["persons"] == 40
    assert "cdm_schema" not in ops.cohort
    with pytest.raises(ValueError, match="Search concepts"):
        ops.count_cohort(RID, json.dumps(SPEC_GI), cdm_schema=TWO)
    # Naming the default schema explicitly shares the default guard.
    assert ops.count_cohort(RID, json.dumps(SPEC_GI), cdm_schema="cdm")["persons"] == 40
    with pytest.raises(Exception, match=TWO):
        ops.count_cohort(RID, json.dumps(SPEC_GI), cdm_schema="nope")

    built = ops.build_dashboard(json.dumps({
        "kind": "omop_cohort", "resource_id": RID, "membership_mode": "live",
        "cdm_schema": TWO, "spec": SPEC_MARKER}), "Marker cohort")
    try:
        assert built["total"] == two_schemas["marker_persons"]
        assert built["source_ref"]["cdm_schema"] == TWO
        with pytest.raises(ValueError, match="Search concepts"):
            ops.build_dashboard(json.dumps({
                "kind": "omop_cohort", "resource_id": RID, "membership_mode": "live",
                "spec": SPEC_MARKER}), "Wrong schema")
    finally:
        datasets.close_dataset(built["dataset_id"])
        agent_mode_api._dashboards.clear()

    state = ops.snapshot()
    assert store_module.validate_state(state) is not None
    by_schema = {(c["cdm_schema"], c["concept_id"]) for c in state["concepts"]}
    assert {(TWO, MARKER), (None, GI_BLEED)} <= by_schema
    restored = agent_mode_api.Operations("multi-schema-owner")
    block = restored.restore(store_module.validate_state(state))
    assert f"{RID} (cdm_schema {TWO})" in block
    assert restored._spec((RID, TWO), SPEC_MARKER)
    assert restored._spec(RID, SPEC_GI)
    with pytest.raises(ValueError, match="Search concepts"):
        restored._spec(RID, SPEC_MARKER)
    with pytest.raises(ValueError, match="Search concepts"):
        restored._spec((RID, TWO), SPEC_GI)
    assert restored.cohort["cdm_schema"] == TWO
    # Concepts saved before this change (no cdm_schema) belong to the default schema.
    legacy = agent_mode_api.Operations("multi-schema-owner")
    legacy.restore({"version": 1, "datasets": [], "tables": [], "cohort": None,
                    "concepts": [{"resource_id": RID, "concept_id": GI_BLEED,
                                  "name": "", "domain": ""}]})
    assert legacy.concepts == {RID: {GI_BLEED}}


def test_mcp_omop_tools_take_cdm_schema(client, run_async, two_schemas):
    import mcp_server
    if not mcp_server.AVAILABLE:
        pytest.skip("MCP is not installed")

    def call(name, args):
        result = run_async(mcp_server.mcp.call_tool(name, args))
        content = result[0] if isinstance(result, tuple) else result
        content = getattr(content, "content", content)
        return json.loads(content[0].text)

    schemas = call("omop_cdm_schemas", {"resource_id": RID})
    assert schemas["default_cdm_schema"] == "cdm"
    assert [s["persons"] for s in schemas["cdm_schemas"]] == [KEPT, 100]
    assert call("omop_count_cohort", {"resource_id": RID, "spec_json": "{}"})[
        "total_persons"] == 100
    assert call("omop_count_cohort", {"resource_id": RID, "spec_json": json.dumps(SPEC_MARKER),
                                      "cdm_schema": TWO})["persons"] == \
        two_schemas["marker_persons"]
    found = call("omop_search_concepts", {"resource_id": RID, "q": "Multischema marker",
                                          "cdm_schema": TWO})
    assert [c["concept_id"] for c in found] == [MARKER]
    assert call("omop_search_concepts", {"resource_id": RID, "q": "Multischema marker"}) == []
