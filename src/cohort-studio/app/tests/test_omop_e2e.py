import socket
import threading
import time
from pathlib import Path
import asyncio
import json

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

pytestmark = pytest.mark.e2e

APP_DIR = Path(__file__).parent.parent
GI_BLEED = 192671
DICLOFENAC = 1124300


@pytest.fixture(scope="session")
def omop_app_url(engine, tmp_path_factory):

    if not (APP_DIR / "static" / "index.html").exists():
        pytest.skip("frontend is not built")

    patches = pytest.MonkeyPatch()
    patches.setattr(db, "resources_ready", lambda: True)
    patches.setattr(db, "warm_resource_cache", lambda: None)
    patches.setattr(db, "retry_if_empty", lambda: None)
    patches.setattr(db, "list_aurora_resources", lambda *a, **k: [{"id": "omopdb"}])
    patches.setattr(db, "list_s3_folders", lambda: [])
    patches.setattr(db, "list_bq_datasets", lambda: [])
    patches.setattr(db, "get_engine_for_resource", lambda _resource_id: engine)
    patches.setattr(catalog, "discover", lambda _folders: ([], False))
    temp_dir = tmp_path_factory.mktemp("omop-e2e")
    lineage_engine = create_engine(f"sqlite:///{temp_dir / 'lineage.db'}")
    patches.setattr(main, "_lineage_engine", lambda: lineage_engine)
    datasets._store.clear()

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


def test_omop_cohort_browser_flow(ref, page: Page, omop_app_url: str):
    expected = _expected_before_index(ref)
    assert expected
    page.goto(omop_app_url)
    expect(page.locator(".topnav-link", has_text="OMOP cohorts")).to_have_count(0)
    expect(page.get_by_label("OMOP datasource")).to_have_count(0)
    page.locator(".sidebar select").nth(0).select_option("aurora:omopdb")
    page.get_by_role("group", name="Explore view").get_by_role("button", name="OMOP").click()

    search = page.get_by_label("Concept name, ID or code")
    domain = page.get_by_label("Domain")
    search.fill("Gastrointestinal hemorrhage")
    page.get_by_role("button", name="Search concepts").click()
    gi_result = page.locator(".omop-result", has_text="Gastrointestinal hemorrhage")
    expect(gi_result).to_be_visible(timeout=15000)
    gi_result.locator("input").check()
    page.get_by_role("button", name="Add criterion (1 concepts)").click()

    domain.select_option("drug")
    search.fill("diclofenac")
    page.get_by_role("button", name="Search concepts").click()
    drug_result = page.locator(".omop-result", has_text="Diclofenac").first
    expect(drug_result).to_be_visible(timeout=15000)
    drug_result.locator("input").check()
    page.get_by_role("button", name="Add criterion (1 concepts)").click()
    expect(page.locator(".omop-rule")).to_have_count(2, timeout=5000)
    page.locator(".omop-rule").nth(1).locator("select").nth(1).select_option("before")

    page.get_by_role("button", name="Count cohort").click()
    count = page.locator(".omop-count")
    expect(count).to_contain_text(f"{len(expected)} of 100 persons", timeout=15000)
    page.screenshot(path="/tmp/cohort-studio-omop.png", full_page=True)
    page.get_by_label("Cohort name").fill("OMOP E2E cohort")
    page.get_by_role("button", name="Open cohort").click()
    expect(page.locator(".tab.active", has_text="OMOP E2E cohort")).to_be_visible(timeout=15000)
    expect(page.locator(".data-table thead")).to_contain_text("Gastrointestinal hemorrhage events")
    expect(page.get_by_role("group", name="Explore view").get_by_role("button", name="Tables")).to_have_attribute("aria-pressed", "true")
    page.get_by_role("group", name="Explore view").get_by_role("button", name="OMOP").click()
    expect(page.locator(".omop-rule")).to_have_count(2)
    page.get_by_label("Clinical table").select_option("condition_occurrence")
    page.get_by_role("button", name="Open clinical table").click()
    expect(page.locator(".tab.active", has_text="condition_occurrence")).to_be_visible(timeout=15000)
    expect(page.locator(".data-table thead")).to_contain_text("condition_concept_name")
    page.get_by_role("group", name="Explore view").get_by_role("button", name="OMOP").click()
    page.locator(".omop-rule").nth(1).get_by_role("button", name="Remove criterion 2").click()
    expect(page.locator(".omop-count")).to_have_count(0)
    expect(page.get_by_role("button", name="Open cohort")).to_be_disabled()
    page.get_by_role("button", name="Count cohort").click()
    gi_ids = set(ref["concept_ancestor"].loc[
        ref["concept_ancestor"].ancestor_concept_id == GI_BLEED,
        "descendant_concept_id"]) | {GI_BLEED}
    observed_gi = ref["condition_occurrence"]
    observed_gi = observed_gi[observed_gi.condition_concept_id.isin(gi_ids)]
    observed_gi = observed_gi.merge(ref["observation_period"], on="person_id")
    observed_gi = observed_gi[(observed_gi.condition_start_date >=
                               observed_gi.observation_period_start_date)
                              & (observed_gi.condition_start_date <=
                                 observed_gi.observation_period_end_date)]
    gi_people = set(observed_gi.person_id)
    expect(page.locator(".omop-count")).to_contain_text(
        f"{len(gi_people)} of 100 persons", timeout=15000)
    page.get_by_role("button", name="Open cohort").click()
    expect(page.locator(".tab.active", has_text="OMOP E2E cohort")).to_be_visible(timeout=15000)
    expect(page.locator(".tabs .tab")).to_have_count(2)
    expect(page.locator(".data-table thead")).not_to_contain_text("Diclofenac events")


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
        monkeypatch, page: Page, omop_app_url: str):
    import config

    datasets._store.clear()
    monkeypatch.setattr(config, "get_llm_config", lambda: {
        "provider": "openrouter", "api_key": "e2e-test-key",
        "model": "test/deterministic", "base_url": "https://example.invalid"})

    def fake_provider(_provider, _model, _key, _base, _system, _messages,
                      tool_impls, tool_schemas=None, vertex_config=None):
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
    page.goto(omop_app_url)
    page.locator(".sidebar select").nth(0).select_option("aurora:omopdb")
    page.get_by_role("group", name="Explore view").get_by_role("button", name="OMOP").click()
    page.get_by_label("Ask the cohort assistant").fill(
        "Find people with concept 192671 and prepare a cohort.")
    page.get_by_role("button", name="Ask assistant").click()
    proposal = page.locator(".omop-proposal")
    expect(proposal).to_be_visible(timeout=15000)
    expect(page.locator(".omop-chat")).to_contain_text(
        "I found 40 people and prepared the cohort.")
    proposal.get_by_text("Review proposed criteria").click()
    expect(proposal.locator("pre")).to_contain_text("192671")
    proposal.get_by_role("button", name="Apply proposed cohort").click()
    expect(page.locator(".omop-rule")).to_have_count(1)
    expect(page.locator(".omop-count")).to_have_count(0)
    page.get_by_role("button", name="Count cohort").click()
    expect(page.locator(".omop-count")).to_contain_text("40 of 100 persons", timeout=15000)
    page.get_by_label("Cohort name").fill("Assistant GI bleed")
    page.get_by_role("button", name="Open cohort").click()
    expect(page.locator(".tab.active", has_text="Assistant GI bleed")).to_be_visible(timeout=15000)
    expect(page.locator(".data-table thead")).to_contain_text(
        "Gastrointestinal hemorrhage events")
