"""Constant-value join filters ({column, op, value}) on join inputs.

Filters run against each input before it is joined, so a left join keeps
unmatched left rows even when the joined table is filtered.
"""
import re
import uuid

import pandas as pd
import pytest
from sqlalchemy import text

import datasets
import main
import source_models

RID = "omopdb"
_NS = re.compile(r"\bjf[0-9a-f]{8}_")


def _short(value):
    """Drop the per-join parameter namespace (jf<digest>_ -> jf_) for asserts."""
    if isinstance(value, dict):
        return {_NS.sub("jf_", k): v for k, v in value.items()}
    return _NS.sub("jf_", value)


@pytest.fixture
def tables(client, engine, monkeypatch):
    suffix = uuid.uuid4().hex[:8]
    people, genotypes = f"jf_people_{suffix}", f"jf_genotypes_{suffix}"
    with engine.begin() as conn:
        conn.execute(text(f'CREATE TABLE public."{people}" (person_id integer, status text)'))
        conn.execute(text(
            f'CREATE TABLE public."{genotypes}" (person_id integer, dosage integer, '
            "quality_score double precision, gene text, called_on date, is_pass boolean)"))
        conn.execute(text(
            f'INSERT INTO public."{people}" VALUES '
            "(1, 'case'), (2, 'case'), (3, 'control'), (4, 'control')"))
        conn.execute(text(
            f'INSERT INTO public."{genotypes}" VALUES '
            "(1, 2, 45.0, 'BRCA1', '2024-01-10', true), "
            "(1, 0, 12.5, 'TP53', '2024-02-10', false), "
            "(2, 1, 31.0, 'BRCA2', '2024-03-10', true), "
            "(3, 1, 29.9, 'brca_1', '2024-04-10', true), "
            "(3, NULL, NULL, NULL, NULL, NULL)"))
    datasets._store.clear()
    monkeypatch.setattr(main.lineage, "record", lambda *args, **kwargs: None)
    yield {"people": people, "genotypes": genotypes}
    datasets._store.clear()
    with engine.begin() as conn:
        for table in (people, genotypes):
            conn.execute(text(f'DROP TABLE IF EXISTS public."{table}"'))


def _open(client, table):
    response = client.post("/api/datasets/open", json={"source_ref": {
        "kind": "aurora", "resource_id": RID, "table": table}})
    assert response.status_code == 200, response.text
    return response.json()["dataset_id"]


def _request(base_id, right_id, filters=None, how="left", base_filters=None):
    body = {"base_id": base_id, "steps": [{
        "right_id": right_id, "how": how, "alias": "g",
        "columns": ["dosage", "gene"],
        "conditions": [{"left": "person_id", "op": "=", "right": "person_id"}],
        "filters": filters or [],
    }]}
    if base_filters:
        body["base_filters"] = base_filters
    return body


def _rows(client, engine, body):
    """Rows of the generated Aurora SQL, run with its bound parameters."""
    checked = client.post("/api/datasets/join/validate", json=body).json()
    assert checked["ok"], checked
    generated = checked["generated_sql"]
    with engine.connect() as conn:
        rows = conn.execute(text(generated["sql"]), generated["parameters"]).fetchall()
    return checked, sorted(tuple(r) for r in rows)


def test_left_join_keeps_unmatched_rows_when_right_side_is_filtered(client, engine, tables):
    people, genotypes = _open(client, tables["people"]), _open(client, tables["genotypes"])
    body = _request(people, genotypes, [
        {"column": "dosage", "op": ">=", "value": 1},
        {"column": "quality_score", "op": ">", "value": 30},
    ])
    checked, rows = _rows(client, engine, body)
    generated = checked["generated_sql"]
    assert checked["engine"] == "aurora"
    assert _short(generated["parameters"]) == {"jf_s1_0_0": 1, "jf_s1_1_0": 30}
    assert ":jf_s1_0_0" in _short(generated["sql"]) and ":jf_s1_1_0" in _short(generated["sql"])
    assert "WHERE" in generated["sql"].split("LEFT JOIN", 1)[1]
    assert "> 30" in generated["copyable_sql"]
    # Every person stays: 3 and 4 have no qualifying genotype, so NULLs.
    assert rows == [(1, "case", 2, "BRCA1"), (2, "case", 1, "BRCA2"),
                    (3, "control", None, None), (4, "control", None, None)]

    joined = client.post("/api/datasets/join", json=body)
    assert joined.status_code == 200, joined.text
    result = joined.json()
    assert result["join"]["engine"] == "aurora"
    assert result["rows"] == 4
    step = result["join"]["steps"][0]
    assert step["right_rows"] == 2          # genotypes after its filters
    assert result["join"]["base_rows"] == 4

    preview = client.post("/api/datasets/join/preview", json=body)
    assert preview.status_code == 200, preview.text
    assert len(preview.json()["sample"]) == 4


def test_filters_with_inner_semi_and_base_filters(client, engine, tables):
    people, genotypes = _open(client, tables["people"]), _open(client, tables["genotypes"])
    brca = [{"column": "gene", "op": "contains", "value": "brca"}]
    _, inner = _rows(client, engine, _request(people, genotypes, brca, how="inner"))
    assert inner == [(1, "case", 2, "BRCA1"), (2, "case", 1, "BRCA2"), (3, "control", 1, "brca_1")]
    semi_body = _request(people, genotypes, brca, how="semi",
                         base_filters=[{"column": "status", "op": "=", "value": "control"}])
    semi_body["steps"][0]["columns"] = None
    checked, semi = _rows(client, engine, semi_body)
    assert _short(checked["generated_sql"]["parameters"])["jf_base_0_0"] == "control"
    assert semi == [(3, "control")]
    joined = client.post("/api/datasets/join", json=semi_body).json()
    assert joined["join"]["base_rows"] == 2 and joined["rows"] == 1


@pytest.mark.parametrize("flt, people_ids", [
    ({"column": "gene", "op": "=", "value": "BRCA1"}, [1]),
    ({"column": "gene", "op": "!=", "value": "BRCA1"}, [1, 2, 3]),
    ({"column": "dosage", "op": "<", "value": 1}, [1]),
    ({"column": "dosage", "op": "<=", "value": "1"}, [1, 2, 3]),
    ({"column": "quality_score", "op": ">", "value": 30.5}, [1, 2]),
    ({"column": "quality_score", "op": ">=", "value": "31"}, [1, 2]),
    ({"column": "gene", "op": "in", "value": ["BRCA1", "BRCA2"]}, [1, 2]),
    ({"column": "dosage", "op": "not in", "value": [0, 2]}, [2, 3]),
    ({"column": "gene", "op": "is null"}, [3]),
    ({"column": "gene", "op": "is not null"}, [1, 2, 3]),
    ({"column": "gene", "op": "contains", "value": "a_1"}, [3]),     # _ is literal
    ({"column": "gene", "op": "contains", "value": "%"}, []),        # % is literal
    ({"column": "called_on", "op": ">=", "value": "2024-03-01"}, [2, 3]),
    ({"column": "is_pass", "op": "=", "value": False}, [1]),
    ({"column": "is_pass", "op": "=", "value": "true"}, [1, 2, 3]),
])
def test_each_operator(client, engine, tables, flt, people_ids):
    people, genotypes = _open(client, tables["people"]), _open(client, tables["genotypes"])
    body = _request(people, genotypes, [flt], how="semi")
    body["steps"][0]["columns"] = None
    _, rows = _rows(client, engine, body)
    assert [r[0] for r in rows] == people_ids
    joined = client.post("/api/datasets/join", json=body)
    assert joined.status_code == 200, joined.text
    assert joined.json()["rows"] == len(people_ids)


def test_values_are_bound_never_interpolated(client, engine, tables):
    people, genotypes = _open(client, tables["people"]), _open(client, tables["genotypes"])
    attack = "x' OR '1'='1'; DROP TABLE public.\"" + tables["people"] + "\"; --"
    body = _request(people, genotypes, [{"column": "gene", "op": "=", "value": attack}],
                    how="inner")
    checked, rows = _rows(client, engine, body)
    generated = checked["generated_sql"]
    assert attack not in generated["sql"]
    assert _short(generated["parameters"])["jf_s1_0_0"] == attack
    assert "x'' OR ''1''=''1''" in generated["copyable_sql"]   # quoted in the copy
    assert rows == []
    assert client.post("/api/datasets/join", json=body).json()["rows"] == 0
    with engine.connect() as conn:   # the table survived
        assert conn.execute(text(f'SELECT count(*) FROM public."{tables["people"]}"')).scalar() == 4
    # The copyable SQL runs as-is and matches nothing.
    with engine.connect() as conn:
        assert conn.execute(text(generated["copyable_sql"])).fetchall() == []


@pytest.mark.parametrize("flt, message", [
    ({"column": "dosage", "op": "=", "value": "abc"}, "'dosage' is a number column"),
    ({"column": "is_pass", "op": "<", "value": True}, "'is_pass' is true/false"),
    ({"column": "is_pass", "op": "=", "value": "maybe"}, "not true or false"),
    ({"column": "called_on", "op": "=", "value": "next week"}, "is not a date"),
    ({"column": "called_on", "op": "=", "value": 5}, "date/time column"),
    ({"column": "gene", "op": "in", "value": []}, "needs at least one value"),
    ({"column": "gene", "op": "=", "value": True}, "is a text column"),
    ({"column": "nope", "op": "=", "value": 1}, "'nope' is not a column"),
    ({"column": "gene", "op": "contains", "value": ""}, "needs some text"),
    ({"column": "dosage", "op": "=", "value": ["1"]}, "use 'in' for a list"),
    ({"column": "dosage", "op": "in", "value": [1, "x"]}, "'x' is not a number"),
])
def test_type_mismatches_are_rejected_with_step_and_column(client, tables, flt, message):
    people, genotypes = _open(client, tables["people"]), _open(client, tables["genotypes"])
    body = _request(people, genotypes, [{"column": "gene", "op": "is not null"}, flt])
    checked = client.post("/api/datasets/join/validate", json=body).json()
    assert checked["ok"] is False and checked["generated_sql"] is None
    problems = checked["steps"][0]["filters"]
    assert problems[0]["problem"] is None
    assert problems[1]["problem"].startswith("Step 1 filter 2: ")
    assert message in problems[1]["problem"]
    response = client.post("/api/datasets/join", json=body)
    assert response.status_code == 400 and message in response.text


def test_base_filter_problems_are_reported_separately(client, tables):
    people, genotypes = _open(client, tables["people"]), _open(client, tables["genotypes"])
    body = _request(people, genotypes, base_filters=[{"column": "person_id", "op": ">", "value": "two"}])
    checked = client.post("/api/datasets/join/validate", json=body).json()
    assert checked["ok"] is False
    assert checked["base_filters"][0]["problem"].startswith("Start table filter 1: 'person_id'")


def test_unknown_operator_and_extra_fields_are_rejected(client, tables):
    people, genotypes = _open(client, tables["people"]), _open(client, tables["genotypes"])
    body = _request(people, genotypes, [{"column": "gene", "op": "LIKE", "value": "x"}])
    assert client.post("/api/datasets/join/validate", json=body).status_code == 422
    body = _request(people, genotypes, [{"column": "gene", "op": "=", "value": "x", "sql": "1=1"}])
    assert client.post("/api/datasets/join/validate", json=body).status_code == 422


def test_saved_ref_keeps_filters_and_reopens(client, engine, tables):
    people, genotypes = _open(client, tables["people"]), _open(client, tables["genotypes"])
    body = _request(people, genotypes, [{"column": "dosage", "op": ">=", "value": "1"}],
                    base_filters=[{"column": "status", "op": "in", "value": ["case", "control"]}])
    joined = client.post("/api/datasets/join", json=body)
    assert joined.status_code == 200, joined.text
    ref = joined.json()["source_ref"]
    assert ref["base_filters"] == [{"column": "status", "op": "in", "value": ["case", "control"]}]
    assert ref["steps"][0]["filters"] == [{"column": "dosage", "op": ">=", "value": "1"}]
    rows = joined.json()["rows"]

    datasets._store.clear()
    reopened = client.post("/api/datasets/open", json={"source_ref": ref})
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["rows"] == rows == 4   # 1, 2, 3 matched once; 4 unmatched
    assert reopened.json()["source_ref"]["steps"][0]["filters"] == ref["steps"][0]["filters"]


def test_refs_without_filters_are_unchanged():
    old = {"kind": "join", "base": {"kind": "aurora", "resource_id": RID, "table": "a"},
           "steps": [{"source": {"kind": "aurora", "resource_id": RID, "table": "b"},
                      "how": "left", "alias": "b",
                      "conditions": [{"left": "id", "op": "=", "right": "id"}]}]}
    assert source_models.source_dict(old) == old
    assert source_models.source_dict({**old, "base_filters": []}) == old
    with_null = {**old, "steps": [{**old["steps"][0], "filters": [
        {"column": "x", "op": "is null", "value": None}]}]}
    assert source_models.source_dict(with_null)["steps"][0]["filters"] == [
        {"column": "x", "op": "is null"}]


def test_cross_source_join_filters_in_duckdb_and_pushes_down_live_inputs(
        client, engine, tables, monkeypatch):
    people = _open(client, tables["people"])
    loaded = datasets.open_dataset(pd.DataFrame({
        "person_id": [1, 1, 2, 3], "dosage": [2, 0, 1, 1],
        "gene": ["BRCA1", "TP53", "BRCA2", "brca_1"]}), "genotypes.csv")["dataset_id"]
    staged = []
    import disk_data
    original = disk_data.stage_live

    def spy(con, live, dataset, table, budget):
        staged.append((live["sql"], dict(live.get("params") or {})))
        return original(con, live, dataset, table, budget)

    monkeypatch.setattr(disk_data, "stage_live", spy)
    body = {**_request(people, loaded, [{"column": "dosage", "op": ">=", "value": 1},
                                        {"column": "gene", "op": "not in", "value": ["BRCA2"]}],
                       base_filters=[{"column": "status", "op": "=", "value": "case"}]),
            "allow_loaded": True}
    checked = client.post("/api/datasets/join/validate", json=body).json()
    assert checked["ok"] and checked["engine"] == "duckdb"
    generated = checked["generated_sql"]
    assert "$jf_s1_0_0" in _short(generated["sql"]) and "$jf_base_0_0" in _short(generated["sql"])
    assert _short(generated["parameters"]) == {"jf_base_0_0": "case", "jf_s1_0_0": 1,
                                       "jf_s1_1_0": "BRCA2"}
    assert "'BRCA2'" in generated["display_sql"]

    joined = client.post("/api/datasets/join", json=body)
    assert joined.status_code == 200, joined.text
    result = joined.json()
    assert result["join"]["engine"] == "duckdb"
    # Base filtered to cases (1, 2); person 2's only genotype is BRCA2, excluded.
    assert result["rows"] == 2
    assert result["join"]["base_rows"] == 2
    assert result["join"]["steps"][0]["right_rows"] == 2
    # The live Aurora base was filtered in PostgreSQL while staging.
    assert any(":jf_base_0_0" in _short(sql) and _short(params).get("jf_base_0_0") == "case"
               for sql, params in staged)
    frame = datasets.get(result["dataset_id"])["df"]
    assert sorted(frame["person_id"].tolist()) == [1, 2]
    assert frame.loc[frame["person_id"] == 2, "g → gene"].isna().all()

    preview = client.post("/api/datasets/join/preview", json=body)
    assert preview.status_code == 200, preview.text
    assert len(preview.json()["sample"]) == 2


def test_omop_cohort_inputs_take_filters_on_both_engines(engine, info, monkeypatch):
    """A compiled (OMOP cohort) live input keeps compiler trust when filtered."""
    import disk_data
    import joins
    import live_query
    import omop

    for module in (live_query, joins, disk_data):
        monkeypatch.setattr(module.db, "get_engine_for_resource", lambda _rid: engine)
    table = f"jf_cohort_tags_{uuid.uuid4().hex[:8]}"
    spec = {"criteria": [{"domain": "condition", "concept_ids": [192671]}]}
    cohort_ref = source_models.source_dict({"kind": "omop_cohort", "resource_id": RID, "spec": spec})
    preview, live = omop.open_cohort_source(engine, info, RID, spec)
    members = sorted(live_query.fetch_frame(live, max_rows=1000).person_id.tolist())
    assert len(members) >= 2
    cutoff = members[0]
    with engine.begin() as conn:
        conn.execute(text(f'CREATE TABLE cdm."{table}" (person_id integer, tag integer)'))
        conn.execute(text(f'INSERT INTO cdm."{table}" SELECT person_id, 1 FROM cdm.person '
                          "WHERE person_id = ANY(:ids)"), {"ids": members})
        conn.execute(text(f'INSERT INTO cdm."{table}" VALUES (:id, 2)'), {"id": members[-1]})
    opened = []
    try:
        base = datasets.open_dataset(preview, "OMOP cohort", live_source=live, capped=False)["dataset_id"]
        datasets.get(base)["source_ref"] = cohort_ref
        right = datasets.open_dataset(
            pd.DataFrame({"person_id": members, "tag": [1] * len(members)}), f"cdm.{table}",
            origin={"kind": "aurora", "resource_id": RID, "schema": "cdm", "table": table},
            capped=False)["dataset_id"]
        datasets.get(right)["source_ref"] = source_models.source_dict(
            {"kind": "aurora", "resource_id": RID, "schema": "cdm", "table": table})
        opened += [base, right]
        step = {"right_id": right, "how": "inner", "alias": "tags",
                "conditions": [{"left": "person_id", "op": "=", "right": "person_id"}],
                "filters": [{"column": "tag", "op": "=", "value": 1}]}
        base_filters = [{"column": "person_id", "op": ">", "value": cutoff}]
        out = joins.run(base, [step], base_filters=base_filters)
        assert out["stats"]["engine"] == "aurora"
        assert out["stats"]["total_rows"] == len(members) - 1     # cutoff excluded, tag 2 excluded
        assert len(live_query.fetch_frame(out["live_source"], max_rows=1000)) == len(members) - 1
        ref = joins._source_ref(joins.plan(base, [step], base_filters))
        assert ref["base_filters"] == base_filters
        assert ref["steps"][0]["filters"] == step["filters"]
        assert source_models.source_dict(ref) == ref

        # Cross-source: the cohort is filtered in PostgreSQL while staging.
        frame = datasets.open_dataset(pd.DataFrame({"person_id": members, "tag": [1] * len(members)}),
                                      "tags.csv")["dataset_id"]
        opened.append(frame)
        out = joins.run(base, [{**step, "right_id": frame}], base_filters=base_filters,
                        allow_loaded=True)
        assert out["stats"]["engine"] == "duckdb"
        assert out["stats"]["base_rows"] == len(members) - 1
        assert len(out["df"]) == len(members) - 1
        disk_data.remove(out["disk_source"])
    finally:
        for dataset_id in opened:
            datasets.close_dataset(dataset_id)
        with engine.begin() as conn:
            conn.execute(text(f'DROP TABLE IF EXISTS cdm."{table}"'))


def test_filtered_join_can_feed_another_filtered_join(client, engine, tables):
    """Nested filtered joins keep separate parameter names (no false conflicts)."""
    people, genotypes = _open(client, tables["people"]), _open(client, tables["genotypes"])
    inner = _request(people, genotypes, [{"column": "dosage", "op": ">=", "value": 1}],
                     how="inner", base_filters=[{"column": "status", "op": "=", "value": "case"}])
    joined = client.post("/api/datasets/join", json=inner)
    assert joined.status_code == 200, joined.text
    first = joined.json()["dataset_id"]
    assert joined.json()["rows"] == 2              # persons 1 and 2
    genotypes_again = _open(client, tables["genotypes"])

    def outer(base_id, right_id, filters, base_filters, right_key="person_id"):
        return {"base_id": base_id, "base_filters": base_filters, "steps": [{
            "right_id": right_id, "how": "left", "alias": "q", "columns": ["gene"],
            "conditions": [{"left": "person_id", "op": "=", "right": right_key}],
            "filters": filters}]}

    # The filtered join as the base, with the same filter values as the inner join.
    body = outer(first, genotypes_again, [{"column": "dosage", "op": ">=", "value": 1}],
                 [{"column": "status", "op": "=", "value": "case"}])
    checked, rows = _rows(client, engine, body)
    assert checked["engine"] == "aurora"
    assert [r[0] for r in rows] == [1, 2]
    with engine.connect() as conn:   # the copyable SQL still runs
        assert len(conn.execute(text(checked["generated_sql"]["copyable_sql"])).fetchall()) == 2
    preview = client.post("/api/datasets/join/preview", json=body)
    assert preview.status_code == 200, preview.text
    assert len(preview.json()["sample"]) == 2
    out = client.post("/api/datasets/join", json=body)
    assert out.status_code == 200, out.text
    assert out.json()["rows"] == 2

    # The filtered join as a step's table, next to another filtered join.
    second = client.post("/api/datasets/join", json=_request(
        people, genotypes, [{"column": "dosage", "op": "=", "value": 2}], how="inner"))
    assert second.status_code == 200, second.text
    body = outer(second.json()["dataset_id"], first,
                 [{"column": "status", "op": "=", "value": "case"}],
                 [{"column": "status", "op": "!=", "value": "control"}])
    body["steps"][0]["columns"] = ["g → gene"]
    checked, rows = _rows(client, engine, body)
    assert checked["engine"] == "aurora"
    assert rows == [(1, "case", 2, "BRCA1", "BRCA1")]
    out = client.post("/api/datasets/join", json=body)
    assert out.status_code == 200, out.text
    assert out.json()["rows"] == 1
    # And it reopens from its saved recipe.
    ref = out.json()["source_ref"]
    datasets._store.clear()
    reopened = client.post("/api/datasets/open", json={"source_ref": ref})
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["rows"] == 1
