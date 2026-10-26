import json
import uuid

import pytest
from sqlalchemy import text

import join_discovery
import config
import secret_store


@pytest.fixture(autouse=True)
def isolated_jev_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(secret_store, "read_keys", lambda: {})
    for name in ("TYPESAFE_API_KEY", "STUDIO_JEV_MODEL", "TYPESAFE_MODEL"):
        monkeypatch.delenv(name, raising=False)


def _ref(table, resource="omopdb"):
    return {"kind": "aurora", "resource_id": resource,
            "schema": "public", "table": table}


@pytest.fixture
def discovery_tables(client, engine, monkeypatch):
    suffix = uuid.uuid4().hex[:8]
    parent = f"jd_parent_{suffix}"
    child = f"jd_child_{suffix}"
    generic_a = f"jd_generic_a_{suffix}"
    generic_b = f"jd_generic_b_{suffix}"
    with engine.begin() as conn:
        conn.execute(text(
            f'CREATE TABLE public."{parent}" (tenant_id integer, person_id integer, '
            'PRIMARY KEY (tenant_id, person_id))'))
        conn.execute(text(
            f'CREATE TABLE public."{child}" (tenant_id integer, person_id integer, '
            f'CONSTRAINT "fk_{suffix}" FOREIGN KEY (tenant_id, person_id) '
            f'REFERENCES public."{parent}" (tenant_id, person_id))'))
        conn.execute(text(
            f'INSERT INTO public."{parent}" VALUES (1, 10)'))
        conn.execute(text(
            f'INSERT INTO public."{child}" VALUES (1, 10)'))
        conn.execute(text(
            f'INSERT INTO public."{parent}" VALUES (2, 10)'))
        conn.execute(text(
            f'INSERT INTO public."{child}" VALUES (2, 10)'))
        conn.execute(text(
            f'CREATE TABLE public."{generic_a}" (id integer, age integer, gender text, '
            'cost_event_id integer, left_value text)'))
        conn.execute(text(
            f'CREATE TABLE public."{generic_b}" (id integer, age integer, gender text, '
            'variant_id integer, right_value text)'))
        conn.execute(text(
            f'INSERT INTO public."{generic_a}" VALUES '
            "(1, 44, 'F', 3, 'private-row-value')"))
        conn.execute(text(
            f'INSERT INTO public."{generic_b}" VALUES '
            "(1, 44, 'F', 3, 'private-row-value')"))
    yield {"parent": parent, "child": child,
           "generic_a": generic_a, "generic_b": generic_b}
    join_discovery.invalidate_resource("omopdb")
    with engine.begin() as conn:
        for table in (parent, child, generic_a, generic_b):
            conn.execute(text(f'DROP TABLE IF EXISTS public."{table}" CASCADE'))


def test_recommendation_returns_declared_composite_foreign_key(
        client, discovery_tables, monkeypatch):
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    left, right = discovery_tables["child"], discovery_tables["parent"]
    response = client.post("/api/joins/recommend", json={
        "left": _ref(left), "right": _ref(right),
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["candidates"][0]["method"] == "foreign_key"
    assert body["candidates"][0]["keys"] == [
        {"left": "tenant_id", "right": "tenant_id"},
        {"left": "person_id", "right": "person_id"},
    ]
    assert not any(candidate["method"] == "exact_name" for candidate in body["candidates"])
    assert body["jev"]["status"] == "not_configured"
    assert any("LIMIT 1" in warning for warning in body["warnings"])
    left_ds = client.post("/api/datasets/open", json={"source_ref": _ref(left)})
    right_ds = client.post("/api/datasets/open", json={"source_ref": _ref(right)})
    assert left_ds.status_code == right_ds.status_code == 200
    joined = client.post("/api/datasets/join", json={
        "base_id": left_ds.json()["dataset_id"],
        "steps": [{"right_id": right_ds.json()["dataset_id"], "how": "inner",
                   "conditions": [{"left": key["left"], "op": "=",
                                   "right": key["right"]}
                                  for key in body["candidates"][0]["keys"]]}],
    })
    assert joined.status_code == 200, joined.text
    assert joined.json()["rows"] == 2


def test_generic_id_does_not_create_a_key_recommendation(
        client, discovery_tables, monkeypatch):
    for name in ("JEV_API_KEY", "TYPESAFE_API_KEY", "OPENROUTER_API_KEY",
                 "STUDIO_JEV_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    response = client.post("/api/joins/recommend", json={
        "left": _ref(discovery_tables["generic_a"]),
        "right": _ref(discovery_tables["generic_b"]),
    })
    assert response.status_code == 200, response.text
    assert response.json()["candidates"] == []
    assert response.json()["jev"]["status"] == "not_configured"


@pytest.mark.parametrize("key_source", ["environment", "saved", "saved_default"])
def test_jev_receives_metadata_only_and_returns_validated_classification(
        client, engine, monkeypatch, tmp_path, key_source):
    suffix = uuid.uuid4().hex[:8]
    left, right = f"jd_person_{suffix}", f"jd_subject_{suffix}"
    with engine.begin() as conn:
        conn.execute(text(f'CREATE TABLE public."{left}" '
                          '(person_id integer, age integer, gender text)'))
        conn.execute(text(f'CREATE TABLE public."{right}" '
                          '(subject_id integer, age integer, gender text)'))
        conn.execute(text(f'INSERT INTO public."{left}" VALUES '
                          "(987654321, 44, 'F'), (987654322, 50, 'M')"))
        conn.execute(text(f'INSERT INTO public."{right}" VALUES (987654321, 44, ' 
                          "'F')"))
    join_discovery.invalidate_resource("omopdb")
    token = "test-secret"
    expected_model = "jev-latest" if key_source == "saved_default" else "jev-test-pinned"
    if key_source == "environment":
        monkeypatch.setenv("TYPESAFE_API_KEY", token)
        monkeypatch.setenv("STUDIO_JEV_MODEL", "jev-test-pinned")
    else:
        monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "studio-config.json")
        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
        monkeypatch.delenv("STUDIO_JEV_MODEL", raising=False)
        monkeypatch.delenv("TYPESAFE_MODEL", raising=False)
        stored = {}
        monkeypatch.setattr(secret_store, "read_keys", lambda: dict(stored))
        monkeypatch.setattr(secret_store, "write_keys",
                            lambda values: stored.update(values))
        monkeypatch.setattr(secret_store, "remove_key", stored.pop)
        monkeypatch.setattr(secret_store, "key_source",
                            lambda name: "local_encrypted" if name in stored else None)
        monkeypatch.setattr(secret_store, "is_available", lambda: True)
        monkeypatch.setattr(secret_store, "is_configured", lambda: True)
        config.update_jev_config(api_key=token, model="" if key_source == "saved_default" else expected_model)
        assert config.get_integration_key("jev") == token
        assert config.get_jev_model() == expected_model
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    requests = []
    roles = ("person", "sample", "variant", "clinical_event",
             "concept", "other", "unknown")

    def response_for(request):
        payload = json.loads(request.data)
        requests.append((request, payload))
        if "best_pair" in payload["questions"]:
            options = payload["questions"]["best_pair"]["criteria"]
            probability = {key: 0.9 if key == "pair_0" else 0.1 / (len(options) - 1)
                          for key in options}
            answer = {"type": "choice", "choice": "pair_0",
                      "confidence": 0.9, "probabilities": probability}
            return {"answers": {"best_pair": answer}}
        answers = {}
        for key in payload["questions"]:
            probability = {role: 0.9 if role == "person" else 0.1 / 6
                           for role in roles}
            answers[key] = {"type": "choice", "choice": "person",
                            "confidence": 0.9, "probabilities": probability}
        return {"answers": answers}

    class Response:
        def __init__(self, body):
            self.body = json.dumps(body).encode()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self, size):
            return self.body[:size]

    monkeypatch.setattr(join_discovery.urllib.request, "urlopen",
                        lambda request, timeout: Response(response_for(request)))
    result = client.post("/api/joins/recommend", json={
        "left": _ref(left), "right": _ref(right),
    })
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["jev"] == {
        "status": "used", "configured": True, "model": expected_model,
    }
    assert body["candidates"][0]["keys"] == [
        {"left": "person_id", "right": "subject_id"},
    ]
    assert body["candidates"][0]["method"] == "jev"
    assert body["candidates"][0]["confidence"] == 0.9
    assert {item["column"] for item in body["classifications"]} == {
        "person_id", "subject_id", "age", "gender"}
    assert all(item["role"] == "person" and item["probability"] == 0.9
               for item in body["classifications"])
    opened = []
    try:
        for table in (left, right):
            response = client.post("/api/datasets/open", json={"source_ref": _ref(table)})
            assert response.status_code == 200, response.text
            opened.append(response.json()["dataset_id"])
        joined = client.post("/api/datasets/join", json={
            "base_id": opened[0], "steps": [{"right_id": opened[1], "how": "inner",
            "conditions": [{"left": key["left"], "right": key["right"], "op": "="}
                           for key in body["candidates"][0]["keys"]]}]})
        assert joined.status_code == 200, joined.text
        opened.append(joined.json()["dataset_id"])
        assert joined.json()["rows"] == 1
        queried = client.post(f"/api/datasets/{opened[-1]}/query", json={}).json()
        assert queried["rows"]["data"][0][0] == 987654321
    finally:
        import datasets
        for did in opened:
            datasets.close_dataset(did)
    assert len(requests) == 2
    request, payload = requests[0]
    assert request.full_url == "https://api.typesafe.ai/v1/systemone"
    assert request.get_header("Authorization") == "Bearer test-secret"
    public_config = client.get("/api/config").json()["jev"]
    assert public_config["api_key_set"] is True
    assert public_config["api_key_source"] == (
        "environment" if key_source == "environment" else "local_encrypted")
    assert token not in json.dumps(public_config)
    assert "987654321" not in json.dumps(payload)
    assert "987654322" not in json.dumps(payload)
    assert "sample_row_non_null" in json.dumps(payload)
    assert "source_metadata" in requests[1][1]["state"]
    assert f"public.{left}.person_id" in json.dumps(requests[0][1]["questions"])
    join_discovery.invalidate_resource("omopdb")
    with engine.begin() as conn:
        conn.execute(text(f'DROP TABLE IF EXISTS public."{left}"'))
        conn.execute(text(f'DROP TABLE IF EXISTS public."{right}"'))


@pytest.mark.parametrize("failure", ["request", "invalid", "malformed_choice", "oversize"])
def test_jev_failure_or_invalid_answer_keeps_only_deterministic_candidate(
        client, engine, monkeypatch, failure):
    suffix = uuid.uuid4().hex[:8]
    left, right = f"jd_patient_{suffix}", f"jd_subject_{suffix}"
    with engine.begin() as conn:
        conn.execute(text(f'CREATE TABLE public."{left}" (person_id integer UNIQUE)'))
        conn.execute(text(f'CREATE TABLE public."{right}" (person_id integer UNIQUE)'))
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-secret")
    monkeypatch.setenv("STUDIO_JEV_MODEL", "jev-test-pinned")
    if failure == "request":
        def fail(*_args, **_kwargs):
            raise join_discovery.urllib.error.URLError("offline")
        monkeypatch.setattr(join_discovery.urllib.request, "urlopen", fail)
    elif failure == "oversize":
        def fail(*_args, **_kwargs):
            raise ValueError("Jev response exceeded the size limit.")
        monkeypatch.setattr(join_discovery, "_decision", fail)
    elif failure == "malformed_choice":
        monkeypatch.setattr(join_discovery, "_decision", lambda *_args: {
            "l0": {"type": "choice", "choice": [], "confidence": 0.8,
                   "probabilities": {}},
        })
    else:
        monkeypatch.setattr(join_discovery, "_decision", lambda *_args: {
            "l0": {"type": "score", "score": 0.8},
        })
    try:
        response = client.post("/api/joins/recommend", json={
            "left": _ref(left), "right": _ref(right), "refresh": True,
        })
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["jev"]["status"] == "unavailable"
        assert [candidate["method"] for candidate in body["candidates"]] == ["exact_name"]
        assert body["candidates"][0]["keys"] == [
            {"left": "person_id", "right": "person_id"}]
    finally:
        join_discovery.invalidate_resource("omopdb")
        with engine.begin() as conn:
            conn.execute(text(f'DROP TABLE IF EXISTS public."{left}"'))
            conn.execute(text(f'DROP TABLE IF EXISTS public."{right}"'))


@pytest.mark.parametrize("left_role,right_role,probability,right_family,expected", [
    ("person", "person", 0.9, "number", True),
    ("sample", "sample", 0.9, "number", True),
    ("variant", "variant", 0.9, "number", True),
    ("person", "clinical_event", 0.9, "number", False),
    ("concept", "variant", 0.9, "number", False),
    ("unknown", "unknown", 0.9, "number", False),
    ("person", "person", 0.55, "number", False),
    ("person", "person", 0.9, "text", False),
])
def test_jev_entity_classification_abstains_without_compatible_evidence(
        monkeypatch, left_role, right_role, probability, right_family, expected):
    def metadata(name, family):
        return {"columns": [{"name": name, "type": "INTEGER" if family == "number" else "TEXT",
                "family": family, "primary_key": False, "unique": False,
                "indexed": False, "probe_non_null": True}]}
    roles = join_discovery._ROLES
    def choice(role, options, confidence):
        return {"type": "choice", "choice": role, "confidence": confidence,
                "probabilities": {key: confidence if key == role else (1-confidence)/(len(options)-1)
                                  for key in options}}
    def decide(key, model, state, questions):
        if "best_pair" in questions:
            return {"best_pair": choice("pair_0", questions["best_pair"]["criteria"], 0.9)}
        return {"l0": choice(left_role, roles, probability),
                "r0": choice(right_role, roles, probability)}
    monkeypatch.setattr(join_discovery, "_decision", decide)
    classified = []
    result = join_discovery._jev(
        join_discovery.AuroraTableRef.model_validate(_ref("left")),
        join_discovery.AuroraTableRef.model_validate(_ref("right")),
        metadata("entity_id", "number"), metadata("subject_id", right_family),
        [], "fixture-key", "fixture-model", classified)
    assert bool(result) is expected
    assert [(c["side"], c["role"]) for c in classified] == [("left", left_role), ("right", right_role)]
