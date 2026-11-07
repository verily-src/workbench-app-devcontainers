import socket
import threading
import time
from pathlib import Path
import asyncio
import json

import httpx
import pandas as pd
import pytest
import uvicorn
from playwright.sync_api import Page, expect
from sqlalchemy import create_engine

import catalog
import cohort_agent
import datasets
import db
import main
from tests.test_agent_store import agent_store
from tests.conftest import remount_mcp_if_started
from tests.ui_helpers import load_table, menu

pytestmark = pytest.mark.e2e

APP_DIR = Path(__file__).parent.parent
GI_BLEED = 192671
DICLOFENAC = 1124300


@pytest.fixture(scope="module")
def omop_app_url(engine, tmp_path_factory):

    if not (APP_DIR / "static" / "index.html").exists():
        pytest.skip("frontend is not built")

    patches = pytest.MonkeyPatch()
    patches.setattr(db, "resources_ready", lambda: True)
    patches.setattr(db, "warm_resource_cache", lambda: None)
    patches.setattr(db, "retry_if_empty", lambda: None)
    patches.setattr(db, "list_aurora_resources", lambda *a, **k: [{"id": "omopdb"}])
    patches.setattr(db, "list_s3_folders", lambda *a, **k: [])
    patches.setattr(db, "list_bq_datasets", lambda *a, **k: [])
    patches.setattr(db, "get_engine_for_resource", lambda _resource_id: engine)
    patches.setattr(catalog, "discover", lambda _folders, *a, **k: ([], False))
    temp_dir = tmp_path_factory.mktemp("omop-e2e")
    lineage_engine = create_engine(f"sqlite:///{temp_dir / 'lineage.db'}")
    patches.setattr(main, "_lineage_engine", lambda: lineage_engine)
    datasets._store.clear()

    # pytest may set this module fixture up more than once per session when
    # it regroups parametrized tests; each server lifespan needs a manager
    # that has not run yet.
    remount_mcp_if_started()
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(main.app, log_level="error", lifespan="on"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and not server.started:
        if not thread.is_alive():
            pytest.fail("uvicorn stopped before startup")
        time.sleep(0.05)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=5)
        pytest.fail("uvicorn did not start")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        lineage_engine.dispose()
        datasets._store.clear()
        patches.undo()


def _expected_before_index(ref):
    ancestors = ref["concept_ancestor"]
    gi_ids = set(ancestors.loc[ancestors.ancestor_concept_id == GI_BLEED,
                               "descendant_concept_id"]) | {GI_BLEED}
    dic_ids = set(ancestors.loc[ancestors.ancestor_concept_id == DICLOFENAC,
                                "descendant_concept_id"]) | {DICLOFENAC}
    obs = ref["observation_period"]

    def observed_rows(events, date_col):
        rows = events[events[date_col].notna()].merge(obs, on="person_id")
        return rows[(rows[date_col] >= rows.observation_period_start_date)
                    & (rows[date_col] <= rows.observation_period_end_date)]

    conditions = ref["condition_occurrence"]
    conditions = observed_rows(conditions[conditions.condition_concept_id.isin(gi_ids)],
                               "condition_start_date")
    index = conditions.groupby("person_id").condition_start_date.min()
    drugs = ref["drug_exposure"]
    drugs = observed_rows(drugs[drugs.drug_concept_id.isin(dic_ids)],
                          "drug_exposure_start_date")
    before = drugs[drugs.apply(
        lambda row: row.drug_exposure_start_date < index.get(row.person_id, pd.NaT), axis=1)]
    return set(index.index) & set(before.person_id)


def _observed_gi_people(ref):
    ancestors = ref["concept_ancestor"]
    gi_ids = set(ancestors.loc[ancestors.ancestor_concept_id == GI_BLEED,
                               "descendant_concept_id"]) | {GI_BLEED}
    events = ref["condition_occurrence"]
    events = events[events.condition_concept_id.isin(gi_ids)].merge(
        ref["observation_period"], on="person_id")
    events = events[(events.condition_start_date >= events.observation_period_start_date)
                    & (events.condition_start_date <= events.observation_period_end_date)]
    return set(events.person_id)


def test_omop_cohort_api_on_real_postgres(ref, omop_app_url: str):
    """The cohort API the Agent uses returns correct real-Postgres results."""
    expected = _expected_before_index(ref)
    assert expected
    api = f"{omop_app_url}/api/omop/omopdb"
    with httpx.Client(timeout=60) as client:
        assert client.get(api).json()["cdm"] is True
        gi = client.get(f"{api}/concepts", params={
            "q": "Gastrointestinal hemorrhage", "domain": "condition"}).json()
        assert any(c["concept_id"] == GI_BLEED for c in gi["concepts"])
        drug = client.get(f"{api}/concepts", params={
            "q": "diclofenac", "domain": "drug"}).json()
        assert any(c["concept_id"] == DICLOFENAC for c in drug["concepts"])

        gi_only = {"criteria": [{"domain": "condition", "concept_ids": [GI_BLEED]}]}
        spec = {"criteria": [*gi_only["criteria"], {
            "domain": "drug", "concept_ids": [DICLOFENAC],
            "index_relation": "before"}]}
        count = client.post(f"{api}/cohort/count", json=spec)
        assert count.status_code == 200, count.text
        assert count.json()["persons"] == len(expected)
        assert count.json()["total_persons"] == 100
        summary = client.post(f"{api}/cohort/summary", json={"spec": spec}).json()
        assert summary["persons"] == len(expected)
        assert sum(item["persons"] for item in summary["charts"]["gender"]) == len(expected)

        opened = client.post(f"{api}/cohort/open",
                             json={"spec": spec, "name": "OMOP E2E cohort"})
        assert opened.status_code == 200, opened.text
        opened = opened.json()
        assert opened["rows"] == len(expected)
        assert opened["source_ref"]["kind"] == "omop_cohort"
        assert "Gastrointestinal hemorrhage events" in [c["name"] for c in opened["columns"]]

        events = client.post(f"{api}/domain/open", json={
            "table": "condition_occurrence", "spec": spec}).json()
        assert "condition_concept_name" in [c["name"] for c in events["columns"]]

        gi_people = _observed_gi_people(ref)
        assert client.post(f"{api}/cohort/count", json=gi_only).json()["persons"] \
            == len(gi_people)
        gi_open = client.post(f"{api}/cohort/open",
                              json={"spec": gi_only, "name": "GI only"}).json()
        assert gi_open["rows"] == len(gi_people)
        assert "Diclofenac events" not in [c["name"] for c in gi_open["columns"]]


def test_aggregation_filter_on_real_postgres(ref, page: Page, omop_app_url: str):
    page.goto(omop_app_url)
    load_table(page, "aurora:omopdb", "cdm.person")
    expect(page.locator('.hero .count')).to_have_text('100', timeout=30000)
    menu(page, 'Add to this view').get_by_role('button', name='+ Aggregation filter').click()
    panel = page.get_by_role('region', name='Aggregation filter')
    panel.get_by_label('Group by').select_option('gender_concept_id')
    panel.get_by_label('At least', exact=True).fill('2')
    panel.get_by_role('button', name='Apply filter').click()
    expect(panel).to_have_count(0, timeout=30000)
    expect(page.locator('.chip', has_text='Rows per group')).to_be_visible(timeout=30000)
    expect(page.locator('.hero .count')).to_have_text('100', timeout=30000)


def test_omop_mcp_streamable_http(omop_app_url: str):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async def exercise_client():
        async with streamable_http_client(f"{omop_app_url}/mcp/") as streams:
            read_stream, write_stream = streams
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                found = await session.call_tool("omop_search_concepts", {
                    "resource_id": "omopdb", "q": "hemorrhage",
                    "domain": "condition"})
                concepts = json.loads(found.content[0].text)
                assert concepts[0]["concept_id"] == GI_BLEED
                spec_json = json.dumps({"criteria": [{
                    "domain": "condition", "concept_ids": [GI_BLEED]}]})
                counted = await session.call_tool("omop_count_cohort", {
                    "resource_id": "omopdb", "spec_json": spec_json})
                assert json.loads(counted.content[0].text)["persons"] == 40

    errors = []

    def run_client():
        try:
            asyncio.run(exercise_client())
        except BaseException as error:
            errors.append(error)

    client_thread = threading.Thread(target=run_client)
    client_thread.start()
    client_thread.join(timeout=30)
    assert not client_thread.is_alive(), "MCP client did not finish"
    if errors:
        raise errors[0]


def test_omop_assistant_proposes_and_opens_real_cohort(
        monkeypatch, agent_store, omop_app_url: str):
    import config

    monkeypatch.setenv("STUDIO_AGENT_RESOURCE_ID", "omopdb")
    datasets._store.clear()
    monkeypatch.setattr(config, "get_llm_config", lambda: {
        "provider": "openrouter", "api_key": "e2e-test-key",
        "model": "test/deterministic", "base_url": "https://example.invalid"})

    def fake_provider(_provider, _model, _key, _base, _system, _messages,
                      tool_impls, tool_schemas=None, vertex_config=None, on_step=None):
        assert [s["function"]["name"] for s in tool_schemas][:3] == [
            "search_concepts", "count_cohort", "propose_cohort"]
        found = json.loads(tool_impls["search_concepts"]("192671", "condition"))
        assert any(c["concept_id"] == GI_BLEED for c in found["concepts"])
        spec_json = json.dumps({"criteria": [{
            "domain": "condition", "concept_ids": [GI_BLEED]}]})
        count = json.loads(tool_impls["count_cohort"](spec_json))
        assert count["persons"] == 40
        proposal = json.loads(tool_impls["propose_cohort"](
            spec_json, "Gastrointestinal hemorrhage cohort"))
        assert proposal["proposed"] and proposal["counted"]
        return {"reply": "I found 40 people and prepared the cohort.",
                "usage": {"total_tokens": 12}}

    monkeypatch.setattr(cohort_agent.providers, "run", fake_provider)
    api = f"{omop_app_url}/api/omop/omopdb"
    with httpx.Client(timeout=60) as client:
        response = client.post(f"{api}/cohort/agent", json={
            "message": "Find people with concept 192671 and prepare a cohort."})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["reply"] == "I found 40 people and prepared the cohort."
        assert [cid for criterion in body["spec"]["criteria"]
                for cid in criterion["concept_ids"]] == [GI_BLEED]
        assert body["count"]["persons"] == 40
        opened = client.post(f"{api}/cohort/open", json={
            "spec": body["spec"], "name": "Assistant GI bleed"})
        assert opened.status_code == 200, opened.text
        assert opened.json()["rows"] == 40
        assert "Gastrointestinal hemorrhage events" in [
            c["name"] for c in opened.json()["columns"]]
