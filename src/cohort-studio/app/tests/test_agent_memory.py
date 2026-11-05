"""Studio Agent working state saved between turns of one conversation."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

import agent_mode_api
import agent_store as store_module
import datasets
import main
import providers
import studio_agent
from agent_store import AgentStoreNotFound, AgentStoreOwnershipError
from tests.test_agent_store import agent_store  # noqa: F401  (fixture)
from tests.test_studio_agent_api import workspace  # noqa: F401  (fixture)

OWNER = "owner-binding-value-memory"
SCOPE = "workspace:agent-mode"
PERSON = {"kind": "aurora", "resource_id": "omopdb", "schema": "cdm", "table": "person"}
STATE = {"version": 1,
         "datasets": [{"dataset_id": "abc123abc123", "title": "People",
                       "source_ref": PERSON, "filters": [], "charts": []}],
         "concepts": [{"resource_id": "omopdb", "concept_id": 192671,
                       "name": "Gastrointestinal hemorrhage", "domain": "Condition"}],
         "tables": [{"source_ref": PERSON, "columns": ["person_id", "year_of_birth"]}],
         "cohort": None}


def _begin(store, session_id=None, owner=OWNER):
    return store.begin(session_id=session_id, owner=owner, scope=SCOPE,
                       system_prompt="Use the available tools.", user_message="question",
                       provider="test", model="fixture")


def _reference(messages):
    found = [m["content"] for m in messages if m["role"] == "reference"
             and m["content"].startswith("Working state saved")]
    return found[0] if found else None


def test_store_round_trips_owner_scoped_state(agent_store):
    first = _begin(agent_store)
    assert first.working_state is None
    agent_store.finish(first, "done", working_state=STATE)
    second = _begin(agent_store, first.session_id)
    assert second.working_state["concepts"][0]["concept_id"] == 192671
    assert second.working_state["tables"][0]["columns"] == ["person_id", "year_of_birth"]
    agent_store.fail(second, error_class="AgentCancelled",
                     working_state={**STATE, "concepts": []})
    assert agent_store.working_state(session_id=first.session_id, owner=OWNER,
                                     scope=SCOPE)["concepts"] == []
    with pytest.raises(AgentStoreNotFound):
        agent_store.working_state(session_id=first.session_id,
                                  owner="other-owner-binding-value", scope=SCOPE)
    with pytest.raises(AgentStoreNotFound):
        agent_store.working_state(session_id=first.session_id, owner=OWNER,
                                  scope="dataset:other")
    with pytest.raises(AgentStoreOwnershipError):
        _begin(agent_store, first.session_id, owner="other-owner-binding-value")


def test_invalid_or_oversized_state_is_dropped_and_turn_still_closes(agent_store):
    first = _begin(agent_store)
    agent_store.finish(first, "done", working_state={"version": 1, "unexpected": True})
    second = _begin(agent_store, first.session_id)  # not AgentStoreBusy
    assert second.working_state is None
    huge = {**STATE, "concepts": [{"resource_id": "omopdb", "concept_id": i, "name": "x" * 250}
                                  for i in range(120)]}
    agent_store.finish(second, "done", working_state=huge)
    assert _begin(agent_store, first.session_id).working_state is None


def test_missing_state_table_keeps_sessions_working(agent_store, engine):
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE _studio_agent.session_state"))
    first = _begin(agent_store)
    agent_store.finish(first, "done", working_state=STATE)
    second = _begin(agent_store, first.session_id)
    assert second.working_state is None and second.history[-1]["content"] == "done"
    agent_store.finish(second, "done again")
    assert agent_store.cleanup() == 0


def test_cleanup_removes_state_past_retention(agent_store, engine):
    first = _begin(agent_store)
    agent_store.finish(first, "done", working_state=STATE)
    agent_store.cleanup(now=datetime.now(timezone.utc) + timedelta(days=31))
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM _studio_agent.session_state")).scalar() == 0


def _ops(monkeypatch, sources=({"kind": "aurora", "id": "omopdb"},)):
    monkeypatch.setattr(main, "datasources", lambda: {"ready": True, "sources": list(sources)})
    return agent_mode_api.Operations("memory-owner")


def test_restore_seeds_guards_only_for_available_resources(monkeypatch):
    agent_mode_api._dashboards.clear()
    ops = _ops(monkeypatch)
    other = {**STATE, "concepts": STATE["concepts"] + [
        {"resource_id": "gone", "concept_id": 7, "name": "", "domain": ""}],
        "tables": STATE["tables"] + [{"source_ref": {**PERSON, "resource_id": "gone"},
                                      "columns": ["x"]}]}
    block = ops.restore(other)
    assert ops.concepts == {"omopdb": {192671}}
    assert ops.inspected == {ops._identity(PERSON)}
    assert ops._spec("omopdb", {"criteria": [{"domain": "condition", "concept_ids": [192671]}]})
    with pytest.raises(ValueError, match="Search concepts"):
        ops._spec("omopdb", {"criteria": [{"domain": "condition", "concept_ids": [7]}]})
    assert '"status":"expired"' in block and "abc123abc123" in block
    assert "open_dashboard" in block and "aurora:omopdb:cdm.person" in block
    assert ops.restore(None) == ""


def test_memory_block_and_snapshot_are_bounded(monkeypatch):
    agent_mode_api._dashboards.clear()
    ops = _ops(monkeypatch)
    for i in range(30):
        ops._remember_table({**PERSON, "table": f"table_{i}"},
                            [f"column_name_{j}_" + "x" * 40 for j in range(200)])
        ops._remember_dataset(f"{i:012x}", {"title": "T" * 128, "source_ref": PERSON,
            "filters": [{"column": "c", "kind": "categorical", "values": ["v" * 100] * 30}],
            "charts": [{"kind": "bar", "x": "c"}]})
    ops.concept_names["omopdb"] = {i: ("n" * 255, "Condition") for i in range(40)}
    ops.cohort = {"resource_id": "omopdb", "spec": {"criteria": []}, "persons": 3}
    snapshot = ops.snapshot()
    assert store_module.validate_state(snapshot) is not None
    restored = _ops(monkeypatch)
    block = restored.restore(snapshot)
    assert len(block.encode()) <= agent_mode_api.MEMORY_BLOCK_BYTES
    assert block.startswith("Working state saved")
    assert len(restored.inspected) == len(snapshot["tables"]) > 0


def test_system_prompt_with_new_tools_fits_the_store_limit():
    assert len(studio_agent._system_prompt()) < store_module.MAX_PROMPT - 4000


def test_working_state_carries_between_api_turns(workspace, monkeypatch):
    seen = []
    def turn(script):
        def provider(provider, model, api_key, base_url, system, messages, impls, **kwargs):
            seen.append(messages)
            return {"reply": script(impls), "usage": {}, "tool_calls": []}
        monkeypatch.setattr(providers, "run", provider)

    built = {}
    def first(impls):
        concepts = json.loads(impls["search_concepts"](resource_id="omopdb", q="192671",
                                                       domain="condition"))["concepts"]
        assert any(c["concept_id"] == 192671 for c in concepts)
        json.loads(impls["inspect_table"](source_json=json.dumps(PERSON)))
        built.update(json.loads(impls["build_dashboard"](
            source_json=json.dumps(PERSON), title="People", charts_json="[]",
            filters_json="[]")))
        assert "dataset_id" in built, built
        spec = {"criteria": [{"domain": "condition", "concept_ids": [192671]}]}
        assert json.loads(impls["count_cohort"](resource_id="omopdb",
                                                spec_json=json.dumps(spec)))["persons"] == 40
        return "Found the cohort."
    turn(first)
    response = workspace.post("/api/agent/chat", json={"message": "Find GI bleeding"})
    assert response.status_code == 200, response.text
    session_id = response.json()["session_id"]
    assert _reference(seen[0]) is None

    def second(impls):
        spec = {"criteria": [{"domain": "condition", "concept_ids": [192671]}],
                "demographics": {"age_min": 65}}
        counted = json.loads(impls["count_cohort"](resource_id="omopdb",
                                                   spec_json=json.dumps(spec)))
        assert "error" not in counted, counted
        rebuilt = json.loads(impls["build_dashboard"](
            source_json=json.dumps(PERSON), title="People again", charts_json="[]",
            filters_json="[]"))
        assert "error" not in rebuilt, rebuilt
        queried = json.loads(impls["query_dashboard"](
            dataset_id=built["dataset_id"], filters_json="[]", charts_json="[]"))
        assert queried["total"] == 100
        return "Restricted."
    turn(second)
    response = workspace.post("/api/agent/chat", json={
        "message": "Now restrict that cohort to age > 65", "session_id": session_id})
    assert response.status_code == 200, response.text
    block = _reference(seen[1])
    assert built["dataset_id"] in block and '"status":"open"' in block
    assert "192671" in block and "cdm.person" in block and "person_id" in block
    assert '"cohort"' in block

    datasets.close_dataset(built["dataset_id"])
    def third(impls):
        result = json.loads(impls["query_dashboard"](
            dataset_id=built["dataset_id"], filters_json="[]", charts_json="[]"))
        assert "error" in result
        return "It expired."
    turn(third)
    response = workspace.post("/api/agent/chat", json={"message": "Show it",
                                                       "session_id": session_id})
    assert response.status_code == 200, response.text
    block = _reference(seen[2])
    expired = [item for item in json.loads(block.split("\n", 1)[1])["datasets"]
               if item["id"] == built["dataset_id"]]
    assert expired[0]["status"] == "expired"

    turn(lambda impls: "Fresh.")
    response = workspace.post("/api/agent/chat", json={"message": "Start over",
                                                       "new_session": True})
    assert response.status_code == 200, response.text
    assert _reference(seen[3]) is None
