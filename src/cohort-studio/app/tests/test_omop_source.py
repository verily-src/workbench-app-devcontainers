import json
import uuid

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

import datasets
import derive
import disk_data
import joins
import live_query
import main
import omop
import source_models
import views

RID = "omopdb"
GI_BLEED = 192671


def test_omop_cohort_source_ref_keeps_the_validated_spec():
    original = {
        "kind": "omop_cohort", "resource_id": RID,
        "spec": {"criteria": [{"domain": "condition",
                                "concept_ids": [GI_BLEED],
                                "descendants": False}],
                 "demographics": {"gender_concept_ids": [8507],
                                  "year_of_birth_min": 1930},
                 "require_observation": True},
    }
    saved = source_models.source_dict(original)
    restored = source_models.source_dict(json.loads(json.dumps(saved)))
    assert restored == saved
    assert restored["spec"] == omop.parse_spec(original["spec"])
    assert restored["membership_mode"] == "live"

    with pytest.raises(ValueError, match="Unknown cohort spec key"):
        source_models.source_dict(original | {"spec": {"patient_ids": [1]}})
    with pytest.raises(ValueError):
        source_models.source_dict(original | {"membership_mode": "snapshot"})


def test_compiler_trust_cannot_be_forged_with_a_dict_marker():
    forged = {"resource_id": RID, "sql": "SELECT pg_sleep(0)",
              "params": {}, "columns": {}, "compiled_omop": True}
    with pytest.raises(ValueError, match="pg_sleep.*not allowed"):
        disk_data._validated_live_sql(forged)
    with pytest.raises(TypeError, match="created by source compilers"):
        disk_data.CompiledSourceQuery(forged, {"kind": "omop_cohort"})


def test_live_cohort_members_match_count_and_filters(engine, info, ref, monkeypatch):
    monkeypatch.setattr(live_query.db, "get_engine_for_resource", lambda _rid: engine)
    spec = {"criteria": [{"domain": "condition", "concept_ids": [GI_BLEED]}],
            "demographics": {"gender_concept_ids": [8507],
                             "year_of_birth_min": 1930,
                             "year_of_birth_max": 1950}}
    preview, live = omop.open_cohort_source(engine, info, RID, spec)
    assert isinstance(live, disk_data.CompiledSourceQuery)
    assert disk_data._validated_live_sql(live) == live["sql"]
    expected = omop.count(engine, info, spec)["persons"]
    members = live_query.fetch_frame(live, max_rows=1000)

    assert len(preview) == expected
    assert len(members) == expected
    assert members.person_id.is_unique
    assert set(members.person_id) == set(omop.open_cohort(engine, info, spec).person_id)
    first_date = "Gastrointestinal hemorrhage first"
    assert {"age", "index_date", first_date} <= set(members.columns)
    dates = pd.to_datetime(members["index_date"])
    assert dates.notna().all()
    assert (members["age"] == dates.dt.year - members["year_of_birth"]).all()
    assert (pd.to_datetime(members[first_date]) == dates).all()
    assert "descendants" in source_models.source_dict({
        "kind": "omop_cohort", "resource_id": RID, "spec": spec})["spec"]["criteria"][0]

    out = live_query._execute_query(
        live, [{"column": "gender", "kind": "categorical", "values": ["MALE"]}],
        [], 0, 1000)
    assert out["total"] == expected
    assert out["filtered"] == len(members[members.gender == "MALE"])
    assert {row[out["rows"]["columns"].index("gender")]
            for row in out["rows"]["data"]} == {"MALE"}
    assert out["rows"]["columns"].count("index_date") == 1
    assert out["rows"]["columns"].count("age") == 1


def test_live_cohort_join_keeps_duplicate_rows_and_saved_recipe(engine, info, monkeypatch):
    for module in (live_query, joins, disk_data):
        monkeypatch.setattr(module.db, "get_engine_for_resource", lambda _rid: engine)
    suffix = uuid.uuid4().hex[:10]
    table = f"cohort_source_join_{suffix}"
    spec = {"criteria": [{"domain": "condition", "concept_ids": [GI_BLEED]}]}
    cohort_ref = source_models.source_dict({
        "kind": "omop_cohort", "resource_id": RID, "spec": spec})
    preview, live = omop.open_cohort_source(engine, info, RID, spec)
    member_ids = sorted(live_query.fetch_frame(live, max_rows=1000).person_id.tolist())
    duplicate_id = member_ids[0]
    join_ref = source_models.source_dict({
        "kind": "join", "base": cohort_ref,
        "steps": [{"source": {"kind": "aurora", "resource_id": RID,
                                "schema": "cdm", "table": table},
                   "how": "inner", "conditions": [{"left": "person_id",
                                                      "right": "person_id"}],
                   "alias": "membership"}],
    })
    assert source_models.source_dict(json.loads(json.dumps(join_ref))) == join_ref

    with engine.begin() as conn:
        conn.execute(text(f'CREATE TABLE cdm."{table}" '
                          "(person_id integer, cohort_tag integer)"))
        conn.execute(text(f'INSERT INTO cdm."{table}" (person_id, cohort_tag) '
                          "SELECT person_id, 1 FROM cdm.person WHERE person_id = ANY(:ids)"),
                     {"ids": member_ids})
        conn.execute(text(f'INSERT INTO cdm."{table}" VALUES (:id, 2)'),
                     {"id": duplicate_id})

    base = right = result = None
    try:
        base_result = datasets.open_dataset(preview, "OMOP cohort", live_source=live,
                                            capped=False)
        base = base_result["dataset_id"]
        datasets.get(base)["source_ref"] = cohort_ref
        right_result = datasets.open_dataset(
            pd.DataFrame({"person_id": member_ids, "cohort_tag": [1] * len(member_ids)}),
            f"{RID} / cdm.{table}",
            origin={"kind": "aurora", "resource_id": RID,
                    "schema": "cdm", "table": table}, capped=False)
        right = right_result["dataset_id"]
        datasets.get(right)["source_ref"] = source_models.source_dict({
            "kind": "aurora", "resource_id": RID, "schema": "cdm", "table": table})
        out = joins.run(base, [{"right_id": right, "how": "inner",
                                "conditions": [{"left": "person_id", "op": "=",
                                                "right": "person_id"}],
                                "alias": "membership"}])
        assert out["stats"]["total_rows"] == len(member_ids) + 1
        joined = live_query.fetch_frame(out["live_source"], max_rows=1000)
        assert len(joined) == len(member_ids) + 1
        result = datasets.open_dataset(out["df"], "joined cohort",
                                       live_source=out["live_source"], capped=False)["dataset_id"]
        filtered = datasets.query(result, [{"column": "membership → cohort_tag",
                                             "kind": "categorical", "values": ["2"]}],
                                  [], 0, 10)
        assert filtered["total"] == len(member_ids) + 1
        assert filtered["filtered"] == 1
        assert filtered["rows"]["data"][0][
            filtered["rows"]["columns"].index("membership → cohort_tag")] == 2
    finally:
        for dataset_id in (result, base, right):
            if dataset_id:
                datasets.close_dataset(dataset_id)
        with engine.begin() as conn:
            conn.execute(text(f'DROP TABLE IF EXISTS cdm."{table}"'))


def test_derived_live_cohort_keeps_compiler_trust_and_reopens(engine, info, monkeypatch):
    monkeypatch.setattr(main, "_omop_cdm", lambda _rid: (engine, info))
    monkeypatch.setattr(disk_data.db, "get_engine_for_resource", lambda _rid: engine)
    spec = {"criteria": [{"domain": "condition", "concept_ids": [GI_BLEED]}],
            "demographics": {"gender_concept_ids": [8507]}}
    cohort_ref = source_models.source_dict({
        "kind": "omop_cohort", "resource_id": RID, "spec": spec,
        "name": "filtered OMOP members"})
    derived_ref = None
    opened = main._open_source(cohort_ref)
    try:
        response = derive.derive(opened["dataset_id"], {
            "op": "formula", "name": "age_plus_one", "left": "age",
            "operator": "+", "right": "1"})
        derived_ref = response["source_ref"]
        source = datasets.get(opened["dataset_id"])["live_source"]
        assert isinstance(source, disk_data.CompiledSourceQuery)
        assert source.source_ref == derived_ref
        assert "EXISTS" in disk_data._validated_live_sql(source).upper()

        current = datasets.query(opened["dataset_id"], [], [], 0, 10)
        assert current["total"] == omop.count(engine, info, spec)["persons"]
        index = current["rows"]["columns"].index("age_plus_one")
        age_index = current["rows"]["columns"].index("age")
        assert current["rows"]["data"][0][index] == current["rows"]["data"][0][age_index] + 1

        reopened = main._open_source(derived_ref)
        try:
            reopened_source = datasets.get(reopened["dataset_id"])["live_source"]
            assert isinstance(reopened_source, disk_data.CompiledSourceQuery)
            assert reopened_source.source_ref == derived_ref
            result = datasets.query(reopened["dataset_id"], [], [], 0, 10)
            assert result["total"] == current["total"]
            assert result["rows"]["columns"] == current["rows"]["columns"]
            assert result["rows"]["data"] == current["rows"]["data"]
        finally:
            datasets.close_dataset(reopened["dataset_id"])
    finally:
        datasets.close_dataset(opened["dataset_id"])


def test_saved_join_view_reopens_live_omop_cohort_recipe(engine, info, monkeypatch):
    for module in (main, views, joins, live_query, disk_data):
        monkeypatch.setattr(module.db, "get_engine_for_resource", lambda _rid: engine)
    monkeypatch.setattr(main.db, "list_aurora_resources", lambda: [{"id": RID}])
    monkeypatch.setattr(main.db, "resources_ready", lambda: True)
    monkeypatch.setattr(main.omop, "detect_resource", lambda _rid: info)
    monkeypatch.setattr(views, "_actor", lambda: "cohort-test")
    suffix = uuid.uuid4().hex[:10]
    table, view_name = f"cohort_saved_join_{suffix}", f"Cohort recipe {suffix}"
    spec = {"criteria": [{"domain": "condition", "concept_ids": [GI_BLEED]}],
            "demographics": {"gender_concept_ids": [8507]}}
    cohort_ref = source_models.source_dict({
        "kind": "omop_cohort", "resource_id": RID, "spec": spec})
    cohort_count = omop.count(engine, info, spec)["persons"]
    _, cohort_live = omop.open_cohort_source(engine, info, RID, spec)
    member_ids = sorted(live_query.fetch_frame(
        cohort_live, max_rows=1000).person_id.tolist())
    assert len(member_ids) == cohort_count > 0
    duplicate_id = member_ids[0]
    with engine.begin() as conn:
        conn.execute(text(f'CREATE TABLE cdm."{table}" '
                          "(person_id integer, cohort_tag integer)"))
        conn.execute(text(f'INSERT INTO cdm."{table}" (person_id, cohort_tag) '
                          "SELECT person_id, 1 FROM cdm.person WHERE person_id = ANY(:ids)"),
                     {"ids": member_ids})
        conn.execute(text(f'INSERT INTO cdm."{table}" VALUES (:id, 2)'),
                     {"id": duplicate_id})
    join_ref = source_models.source_dict({
        "kind": "join", "base": cohort_ref,
        "steps": [{"source": {"kind": "aurora", "resource_id": RID,
                                "schema": "cdm", "table": table},
                   "how": "inner", "conditions": [{"left": "person_id",
                                                      "right": "person_id"}],
                   "alias": "membership"}],
    })
    dataset_id = None
    try:
        opened = main._open_source(join_ref)
        dataset_id = opened["dataset_id"]
        expected_rows = cohort_count + 1
        assert opened["source_ref"] == join_ref
        saved = views.save_view("aurora", RID, view_name, {
            "version": 2, "active": 0,
            "datasets": [{"source": join_ref, "entity_column": "person_id",
                          "title": "OMOP membership", "filters": [], "charts": [],
                          "cohorts": []}],
        })
        assert saved["name"] == view_name
        state = views.get_view("aurora", RID, view_name)
        reopened_ref = source_models.source_dict(state["datasets"][0]["source"])
        assert reopened_ref == join_ref
        datasets.close_dataset(dataset_id)
        dataset_id = main._open_source(reopened_ref)["dataset_id"]
        result = datasets.query(dataset_id, [], [], 0, 1000)
        assert result["total"] == expected_rows
        filtered = datasets.query(
            dataset_id, [{"column": "membership → cohort_tag",
                          "kind": "categorical", "values": ["2"]}], [], 0, 10)
        assert filtered["total"] == expected_rows
        assert filtered["filtered"] == 1
        assert filtered["rows"]["data"][0][
            filtered["rows"]["columns"].index("membership → cohort_tag")] == 2
    finally:
        if dataset_id:
            datasets.close_dataset(dataset_id)
        try:
            views.delete_view("aurora", RID, view_name)
        finally:
            with engine.begin() as conn:
                conn.execute(text(f'DROP TABLE IF EXISTS cdm."{table}"'))


def test_omop_open_api_reopens_full_live_membership_and_links_lineage(
        engine, info, tmp_path, monkeypatch):
    monkeypatch.setattr(main.db, "get_engine_for_resource", lambda _rid: engine)
    monkeypatch.setattr(main.db, "list_aurora_resources", lambda: [{"id": RID}])
    monkeypatch.setattr(main.db, "resources_ready", lambda: True)
    monkeypatch.setattr(main.omop, "detect_resource", lambda _rid: info)
    lineage_engine = create_engine(
        f"sqlite:///{tmp_path / 'lineage.db'}",
        connect_args={"check_same_thread": False})
    monkeypatch.setattr(main, "_lineage_engine", lambda: lineage_engine)
    spec = {"criteria": [{"domain": "condition", "concept_ids": [GI_BLEED]}],
            "demographics": {"gender_concept_ids": [8507]}}
    expected = omop.count(engine, info, spec)["persons"]
    try:
        with TestClient(main.app) as client:
            opened = client.post(f"/api/omop/{RID}/cohort/open",
                                 json={"spec": spec, "name": "live cohort"})
            assert opened.status_code == 200, opened.text
            first = opened.json()
            assert first["query_scope"] == "database"
            assert first["sampled"] is False
            assert first["source_ref"]["membership_mode"] == "live"
            assert first["source_ref"]["spec"] == omop.parse_spec(spec)

            query = client.post(f"/api/datasets/{first['dataset_id']}/query",
                                json={"filters": [], "charts": [], "page": 0,
                                      "page_size": 1000})
            assert query.status_code == 200, query.text
            assert query.json()["total"] == expected

            closed = client.delete(f"/api/datasets/{first['dataset_id']}")
            assert closed.status_code == 200, closed.text
            reopened = client.post("/api/datasets/open",
                                   json={"source_ref": first["source_ref"]})
            assert reopened.status_code == 200, reopened.text
            second = reopened.json()
            assert second["source_ref"] == first["source_ref"]
            query = client.post(f"/api/datasets/{second['dataset_id']}/query",
                                json={"filters": [], "charts": [], "page": 0,
                                      "page_size": 1000})
            assert query.status_code == 200, query.text
            assert query.json()["total"] == expected
        events = main.lineage.recent_events(lineage_engine)
        cohort_events = events[events.event_type == "omop_cohort_opened"]
        assert len(cohort_events) == 1
        payload = json.loads(cohort_events.iloc[0].payload)
        assert payload["dataset_id"] == first["dataset_id"]
        assert payload["source_ref"] == first["source_ref"]
        assert payload["membership_mode"] == "live"
    finally:
        lineage_engine.dispose()
