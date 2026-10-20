"""Notebook-style joins: types, compound and non-equi conditions, chains,
column picking/naming, type coercion, caps, preview and key suggestions,
row growth, validation, and the Aurora pushdown (SQL shape, engine
selection, results against a SQLite stand-in)."""

import pandas as pd
import pytest

import datasets
import joins


def _open(df: pd.DataFrame, source: str, **meta) -> str:
    return datasets.open_dataset(df, source, **meta)["dataset_id"]


@pytest.fixture
def cohort():
    samples = _open(pd.DataFrame({
        "sample_id": ["a", "b", "c", "d"],
        "donor_id": [1, 1, 2, 3],
        "age": [30, 45, 60, 25],
    }), "folder / samples.csv")
    visits = _open(pd.DataFrame({
        "sample_id": ["a", "a", "b", "x"],
        "visit": [1, 2, 1, 1],
        "age": [31, 32, 46, 99],
    }), "folder / visits.parquet")
    donors = _open(pd.DataFrame({
        "id": [1, 2, 4], "sex": ["F", "M", "F"],
    }), "folder / donors.csv")
    return {"samples": samples, "visits": visits, "donors": donors}


def _step(right, how="left", conds=(("sample_id", "=", "sample_id"),),
          columns=None, alias="visits"):
    return {"right_id": right, "how": how, "alias": alias, "columns": columns,
            "conditions": [{"left": l, "op": o, "right": r} for l, o, r in conds]}


@pytest.mark.parametrize("how,rows", [
    ("inner", 3), ("left", 5), ("right", 4), ("full", 6), ("semi", 2), ("anti", 2)])
def test_join_types_row_counts(cohort, how, rows):
    out = joins.run(cohort["samples"], [_step(cohort["visits"], how)])
    assert out["stats"]["total_rows"] == rows
    assert len(out["df"]) == rows


def test_outer_is_an_alias_for_full(cohort):
    out = joins.run(cohort["samples"], [_step(cohort["visits"], "outer")])
    assert out["stats"]["total_rows"] == 6


def test_semi_and_anti_add_no_columns_and_split_the_cohort(cohort):
    semi = joins.run(cohort["samples"], [_step(cohort["visits"], "semi")])["df"]
    anti = joins.run(cohort["samples"], [_step(cohort["visits"], "anti")])["df"]
    assert list(semi.columns) == ["sample_id", "donor_id", "age"]
    assert sorted(semi.sample_id) == ["a", "b"]
    assert sorted(anti.sample_id) == ["c", "d"]


def test_joined_columns_are_prefixed_by_alias(cohort):
    df = joins.run(cohort["samples"], [_step(cohort["visits"], "inner")])["df"]
    assert list(df.columns) == ["sample_id", "donor_id", "age",
                                "visits → sample_id", "visits → visit",
                                "visits → age"]


def test_column_picker_limits_joined_columns(cohort):
    df = joins.run(cohort["samples"],
                   [_step(cohort["visits"], "inner", columns=["visit"])])["df"]
    assert list(df.columns) == ["sample_id", "donor_id", "age", "visits → visit"]


def test_empty_column_pick_keeps_only_the_left_side(cohort):
    df = joins.run(cohort["samples"],
                   [_step(cohort["visits"], "inner", columns=[])])["df"]
    assert list(df.columns) == ["sample_id", "donor_id", "age"]
    assert len(df) == 3


def test_compound_and_non_equi_conditions(cohort):
    # Visits of the same sample where the visit-time age exceeds the base age.
    out = joins.run(cohort["samples"], [_step(
        cohort["visits"], "inner",
        conds=(("sample_id", "=", "sample_id"), ("age", "<", "age")))])
    df = out["df"]
    assert len(df) == 3
    assert (df["visits → age"] > df["age"]).all()
    none = joins.run(cohort["samples"], [_step(
        cohort["visits"], "inner",
        conds=(("sample_id", "=", "sample_id"), ("age", ">=", "age")))])
    assert none["stats"]["total_rows"] == 0


def test_chained_joins_can_use_earlier_joined_columns(cohort):
    out = joins.run(cohort["samples"], [
        _step(cohort["visits"], "inner", columns=["visit"]),
        _step(cohort["donors"], "left", conds=(("donor_id", "=", "id"),),
              columns=["sex"], alias="donors"),
    ])
    df = out["df"]
    assert list(df.columns)[-2:] == ["visits → visit", "donors → sex"]
    assert set(df["donors → sex"]) == {"F"}
    assert [s["rows"] for s in out["stats"]["steps"]] == [3, 3]


def test_mismatched_key_types_are_compared_as_text(cohort):
    codes = _open(pd.DataFrame({"donor": ["1", "2"], "site": ["n", "s"]}),
                  "codes.csv")
    out = joins.run(cohort["samples"], [_step(
        codes, "inner", conds=(("donor_id", "=", "donor"),), alias="codes")])
    assert out["stats"]["total_rows"] == 3
    assert any("compared as text" in n for n in out["stats"]["notes"])
    with pytest.raises(ValueError, match="can't compare"):
        joins.run(cohort["samples"], [_step(
            codes, "inner", conds=(("donor_id", "<", "donor"),), alias="codes")])


def test_duplicate_output_names_get_a_counter(cohort):
    df = joins.run(cohort["samples"], [
        _step(cohort["donors"], "left", conds=(("donor_id", "=", "id"),),
              columns=["sex"], alias="d"),
        _step(cohort["donors"], "left", conds=(("donor_id", "=", "id"),),
              columns=["sex"], alias="d"),
    ])["df"]
    assert list(df.columns)[-2:] == ["d → sex", "d → sex (2)"]


def test_cap_reports_the_real_total(cohort):
    out = joins.run(cohort["samples"], [_step(cohort["visits"], "full")], cap=2)
    assert len(out["df"]) == 2
    assert out["stats"]["total_rows"] == 6
    assert out["stats"]["truncated"] is True


@pytest.mark.parametrize("step,match", [
    ({"conditions": []}, "at least one join condition"),
    ({"how": "sideways"}, "Join type"),
    ({"conditions": [{"left": "nope", "op": "=", "right": "sample_id"}]}, "left side"),
    ({"conditions": [{"left": "sample_id", "op": "=", "right": "nope"}]}, "joined table"),
    ({"conditions": [{"left": "sample_id", "op": "~", "right": "sample_id"}]}, "operator"),
    ({"columns": ["nope"]}, "unknown column"),
])
def test_validation_errors(cohort, step, match):
    with pytest.raises(ValueError, match=match):
        joins.run(cohort["samples"], [{**_step(cohort["visits"]), **step}])


def test_step_limits(cohort):
    with pytest.raises(ValueError, match="at least one join step"):
        joins.run(cohort["samples"], [])
    with pytest.raises(ValueError, match="At most"):
        joins.run(cohort["samples"], [_step(cohort["visits"])] * (joins.MAX_STEPS + 1))


def test_preview_returns_stats_and_a_sample(cohort):
    p = joins.preview(cohort["samples"], [_step(cohort["visits"], "left")])
    assert p["base_rows"] == 4 and p["total_rows"] == 5
    assert p["columns"][:3] == ["sample_id", "donor_id", "age"]
    assert len(p["sample"]) == 5
    assert any(v is None for row in p["sample"] for v in row)


def test_suggest_ranks_shared_keys_and_table_id_pattern(cohort):
    shared = joins.suggest(cohort["samples"], cohort["visits"])
    assert shared[0]["left"] == "sample_id" and shared[0]["right"] == "sample_id"
    assert shared[0]["overlap"] == 0.5
    fk = joins.suggest(cohort["samples"], cohort["donors"])
    assert {"left": "donor_id", "right": "id"}.items() <= fk[0].items()


def test_default_alias_strips_folder_and_extension():
    assert joins.default_alias("folder1 / visits.parquet") == "visits"
    assert joins.default_alias("a + b") == "a + b"


# ------------------------------------------------- row growth and caps

def test_step_stats_report_growth_and_flag_fanout():
    base = _open(pd.DataFrame({"k": [1, 2]}), "base.csv")
    many = _open(pd.DataFrame({"k": [1, 1, 1, 2, 2, 2], "v": range(6)}), "many.csv")
    one = _open(pd.DataFrame({"k": [1, 2], "w": ["a", "b"]}), "one.csv")
    stats = joins.run(base, [
        _step(many, "inner", conds=(("k", "=", "k"),), alias="many"),
        _step(one, "left", conds=(("k", "=", "k"),), alias="one"),
    ])["stats"]
    first, second = stats["steps"]
    assert first == {"right_rows": 6, "rows": 6, "truncated": False,
                     "rows_before": 2, "growth": 3.0, "fanout": True}
    assert second["rows_before"] == 6 and second["growth"] == 1.0
    assert second["fanout"] is False
    assert stats["engine"] == "duckdb" and stats["capped_inputs"] == []


def test_growth_is_none_when_the_left_side_is_empty():
    empty = _open(pd.DataFrame({"k": pd.Series([], dtype="int64")}), "e.csv")
    right = _open(pd.DataFrame({"k": [1]}), "r.csv")
    step = joins.run(empty, [_step(right, "inner", conds=(("k", "=", "k"),))])["stats"]["steps"][0]
    assert step["growth"] is None and step["fanout"] is False


def test_capped_inputs_are_noted_on_the_in_memory_path(cohort):
    big = _open(pd.DataFrame({"sample_id": ["a"], "x": [1]}), "db1 / big", capped=True)
    stats = joins.run(cohort["samples"], [_step(big, "left", alias="big")])["stats"]
    assert stats["capped_inputs"] == ["db1 / big"]
    assert any("may be incomplete" in n for n in stats["notes"])


def test_frames_at_the_row_cap_count_as_capped(monkeypatch):
    monkeypatch.setattr(joins.queries, "ROW_CAP", 3)
    full = datasets.get(_open(pd.DataFrame({"k": [1, 2, 3]}), "x"))
    assert full["capped"] is True
    assert datasets.get(_open(pd.DataFrame({"k": [1, 2]}), "y"))["capped"] is False


# ------------------------------------------------------------ validate

def test_validate_reports_problems_per_condition_without_running(cohort, monkeypatch):
    def boom():
        raise AssertionError("validate must not execute the join")
    monkeypatch.setattr(joins.duckdb, "connect", boom)
    codes = _open(pd.DataFrame({"donor": ["1"], "site": ["n"]}), "codes.csv")
    out = joins.validate(cohort["samples"], [
        _step(cohort["visits"], "inner",
              conds=(("sample_id", "=", "sample_id"), ("nope", "=", "visit"),
                     ("age", "~", "age")), columns=["visit", "gone"]),
        _step(codes, "inner", conds=(("donor_id", "=", "donor"),
                                     ("donor_id", "<", "donor")), alias="codes"),
    ])
    assert out["ok"] is False and out["engine"] == "duckdb"
    first, second = out["steps"]
    assert [c["problem"] for c in first["conditions"]] == [
        None, "Step 1: 'nope' is not a column of the left side.",
        "Step 1: operator must be one of =, !=, <, <=, >, >=."]
    assert first["problems"] == ["Step 1: unknown column(s) 'gone'."]
    assert second["conditions"][0] == {
        "problem": None, "note": "donor_id (number) and donor (text) compared as text"}
    assert "can't compare" in second["conditions"][1]["problem"]


def test_validate_and_run_agree(cohort):
    steps = [_step(cohort["visits"], "inner", conds=(("age", "<", "nope"),))]
    out = joins.validate(cohort["samples"], steps)
    with pytest.raises(ValueError) as e:
        joins.run(cohort["samples"], steps)
    assert out["steps"][0]["conditions"][0]["problem"] == str(e.value)
    ok = joins.validate(cohort["samples"], [_step(cohort["visits"])])
    assert ok["ok"] is True and ok["problems"] == []


def test_validate_flags_step_count(cohort):
    assert joins.validate(cohort["samples"], [])["problems"] == ["Add at least one join step."]


# ------------------------------------------------------ Aurora pushdown

def _aurora(df: pd.DataFrame, table: str, rid: str = "db1", engine=None,
            **meta) -> str:
    if engine is not None:
        df.to_sql(table, engine, schema="public", index=False, if_exists="replace")
    return _open(df, f"{rid} / {table}", origin=joins.aurora_origin(rid, table), **meta)


SAMPLES = pd.DataFrame({"sample_id": ["a", "b", "c", "d"],
                        "donor_id": [1, 1, 2, 3], "age": [30, 45, 60, 25]})
VISITS = pd.DataFrame({"sample_id": ["a", "a", "b", "x"], "visit": [1, 2, 1, 1],
                       "age": [31, 32, 46, 99]})
DONORS = pd.DataFrame({"id": [1, 2, 4], "sex": ["F", "M", "F"]})


@pytest.fixture
def aurora_cohort(fake_aurora):
    return {"samples": _aurora(SAMPLES, "samples", engine=fake_aurora),
            "visits": _aurora(VISITS, "visits", engine=fake_aurora),
            "donors": _aurora(DONORS, "donors", engine=fake_aurora)}


def _sql(base, steps) -> dict:
    return joins.aurora_sql(joins.plan(base, steps))


def test_engine_selection_by_origin():
    s, v = _aurora(SAMPLES, "samples"), _aurora(VISITS, "visits")
    other_db = _aurora(VISITS, "visits", rid="db2")
    upload = _open(VISITS, "visits.csv")
    assert joins.plan(s, [_step(v)])["engine"] == "aurora"
    assert joins.plan(s, [_step(other_db)])["engine"] == "duckdb"
    assert joins.plan(s, [_step(upload)])["engine"] == "duckdb"
    assert joins.plan(upload, [_step(s)])["engine"] == "duckdb"
    assert "different Aurora" in joins.plan(s, [_step(other_db)])["engine_reason"]
    # Postgres can't run a full join on a non-equality condition.
    full_lt = _step(v, "full", conds=(("sample_id", "=", "sample_id"), ("age", "<", "age")))
    assert joins.plan(s, [full_lt])["engine"] == "duckdb"


def test_derived_column_drops_the_aurora_origin():
    s, v = _aurora(SAMPLES, "samples"), _aurora(VISITS, "visits")
    datasets.set_column(s, "age2", datasets.get(s)["df"]["age"] * 2)
    assert joins.plan(s, [_step(v)])["engine"] == "duckdb"


def test_aurora_sql_for_one_left_join():
    s, v = _aurora(SAMPLES, "samples"), _aurora(VISITS, "visits")
    sql = _sql(s, [_step(v, "left", columns=["visit"])])
    assert sql["ctes"] == [
        's0 AS (SELECT "sample_id", "donor_id", "age" FROM "public"."samples")',
        's1 AS (SELECT l."sample_id", l."donor_id", l."age", r."visit" AS "visits → visit" '
        'FROM s0 AS l LEFT JOIN "public"."visits" AS r '
        'ON CAST(l."sample_id" AS TEXT) = CAST(r."sample_id" AS TEXT))']
    assert sql["count"](1).endswith("SELECT count(*) FROM s1")
    assert sql["select"](20).endswith("SELECT * FROM s1 LIMIT 20")


@pytest.mark.parametrize("how,where", [
    ("semi", "WHERE EXISTS (SELECT 1 FROM"), ("anti", "WHERE NOT EXISTS (SELECT 1 FROM")])
def test_aurora_semi_and_anti_use_exists(how, where):
    s, v = _aurora(SAMPLES, "samples"), _aurora(VISITS, "visits")
    cte = _sql(s, [_step(v, how)])["ctes"][1]
    assert cte == (f's1 AS (SELECT l."sample_id", l."donor_id", l."age" FROM s0 AS l '
                   f'{where} "public"."visits" AS r WHERE '
                   'CAST(l."sample_id" AS TEXT) = CAST(r."sample_id" AS TEXT)))')
    assert "SEMI" not in cte and "ANTI" not in cte


def test_aurora_ops_multi_conditions_and_mismatched_kinds():
    s, v = _aurora(SAMPLES, "samples"), _aurora(VISITS, "visits")
    codes = _aurora(pd.DataFrame({"donor": ["1"]}), "codes")
    cte = _sql(s, [_step(v, "inner", columns=[], conds=(
        ("sample_id", "=", "sample_id"), ("age", "<=", "age"), ("age", "!=", "visit")))])["ctes"][1]
    assert cte.endswith('ON CAST(l."sample_id" AS TEXT) = CAST(r."sample_id" AS TEXT) '
                        'AND l."age" <= r."age" AND l."age" != r."visit")')
    mixed = _sql(s, [_step(codes, "inner", conds=(("donor_id", "=", "donor"),))])["ctes"][1]
    assert 'CAST(l."donor_id" AS TEXT) = CAST(r."donor" AS TEXT)' in mixed
    with pytest.raises(ValueError, match="can't compare"):
        joins.run(s, [_step(codes, "inner", conds=(("donor_id", ">", "donor"),))])


def test_aurora_identifiers_are_quoted():
    odd = pd.DataFrame({'we"ird': [1], "pct %": [2]})
    s = _aurora(odd, 'odd"table')
    r = _aurora(odd, "other")
    sql = _sql(s, [_step(r, "inner", conds=(('we"ird', "=", 'we"ird'),), alias='a"b')])
    assert sql["ctes"][0] == 's0 AS (SELECT "we""ird", "pct %" FROM "public"."odd""table")'
    assert 'r."pct %" AS "a""b → pct %"' in sql["ctes"][1]
    assert 'l."we""ird" = r."we""ird"' in sql["ctes"][1]


def test_pg_name_cuts_long_names_uniquely_and_deterministically():
    used: set[str] = set()
    long_a = "visit_details_for_the_longitudinal_study" + joins.ARROW + "x" * 40 + "_a"
    long_b = long_a[:-2] + "_b"
    a, b = joins._pg_name(long_a, used), joins._pg_name(long_b, used)
    assert a != b
    assert all(len(n.encode()) <= joins.PG_IDENT_BYTES for n in (a, b))
    assert joins._pg_name(long_a, set()) == a
    again = joins._pg_name(long_a, used)  # same name twice still gets a new one
    assert again not in (a, b) and len(again.encode()) <= joins.PG_IDENT_BYTES
    assert joins._pg_name("short", used) == "short"
    # Cuts never split the 3-byte arrow.
    arrowy = joins._pg_name("a" * 52 + joins.ARROW * 4, set())
    assert "\ufffd" not in arrowy and len(arrowy.encode()) <= joins.PG_IDENT_BYTES


def test_long_aliases_run_in_aurora_with_logical_names(aurora_cohort):
    alias = "visits_of_the_longitudinal_cohort_study_2024"
    steps = [_step(aurora_cohort["visits"], "inner", alias=alias),
             _step(aurora_cohort["donors"], "left", alias=alias,
                   conds=(("donor_id", "=", "id"),))]
    sql = _sql(aurora_cohort["samples"], steps)
    assert all(len(n.encode()) <= joins.PG_IDENT_BYTES for n in sql["names"].values())
    assert len(set(sql["names"].values())) == len(sql["names"])
    out = joins.run(aurora_cohort["samples"], steps)
    assert out["stats"]["engine"] == "aurora"
    assert list(out["df"].columns)[3:] == [
        f"{alias} → sample_id", f"{alias} → visit", f"{alias} → age",
        f"{alias} → id", f"{alias} → sex"]


def _rows(df: pd.DataFrame) -> list[tuple]:
    def norm(v):
        if pd.isna(v):
            return None
        if isinstance(v, float) and v.is_integer():
            return int(v)
        return v
    return sorted((tuple(norm(v) for v in row) for row in
                   df.astype(object).values.tolist()), key=repr)


@pytest.mark.parametrize("how", ["inner", "left", "right", "full", "semi", "anti"])
def test_aurora_and_duckdb_paths_agree(aurora_cohort, how):
    steps = [_step(aurora_cohort["visits"], how),
             _step(aurora_cohort["donors"], "left", conds=(("donor_id", "=", "id"),),
                   columns=["sex"], alias="donors")]
    pushed = joins.run(aurora_cohort["samples"], steps)
    local = joins._run_duckdb(joins.plan(aurora_cohort["samples"], steps), joins.queries.ROW_CAP)
    assert pushed["stats"]["engine"] == "aurora"
    assert list(pushed["df"].columns) == list(local["df"].columns)
    assert _rows(pushed["df"]) == _rows(local["df"])
    for key in ("base_rows", "total_rows", "rows", "truncated"):
        assert pushed["stats"][key] == local["stats"][key]
    assert [s["rows"] for s in pushed["stats"]["steps"]] == \
           [s["rows"] for s in local["stats"]["steps"]]


def test_aurora_non_equi_and_cap(aurora_cohort):
    out = joins.run(aurora_cohort["samples"], [_step(
        aurora_cohort["visits"], "inner",
        conds=(("sample_id", "=", "sample_id"), ("age", "<", "age")))], cap=2)
    assert out["stats"]["engine"] == "aurora"
    assert out["stats"]["total_rows"] == 3 and len(out["df"]) == 2
    assert out["stats"]["truncated"] is True and out["stats"]["rows"] == 2


def test_aurora_counts_capped_tables_in_the_database(fake_aurora):
    SAMPLES.to_sql("samples", fake_aurora, schema="public", index=False)
    # Only 2 of the 4 rows were loaded; the base count comes from the table.
    s = _aurora(SAMPLES.head(2), "samples", capped=True)
    v = _aurora(VISITS, "visits", engine=fake_aurora)
    stats = joins.run(s, [_step(v, "left")])["stats"]
    assert stats["base_rows"] == 4 and stats["total_rows"] == 5
    assert stats["capped_inputs"] == []


def test_aurora_preview_fetches_a_sample(aurora_cohort):
    p = joins.preview(aurora_cohort["samples"], [_step(aurora_cohort["visits"], "left")])
    assert p["engine"] == "aurora" and p["total_rows"] == 5 and len(p["sample"]) == 5
    assert p["steps"][0]["rows_before"] == 4


class _QueryCanceled(Exception):
    sqlstate = "57014"


class _BrokenEngine:
    def __init__(self, exc):
        self.exc = exc

    def begin(self):
        raise self.exc


def test_aurora_preview_timeout_raises_and_run_falls_back(monkeypatch):
    s, v = _aurora(SAMPLES, "samples"), _aurora(VISITS, "visits")
    monkeypatch.setattr(joins.db, "get_engine_for_resource",
                        lambda rid: _BrokenEngine(_QueryCanceled("canceling statement")))
    with pytest.raises(joins.JoinTimeout, match="longer than 10 s"):
        joins.preview(s, [_step(v, "left")])
    out = joins.run(s, [_step(v, "left")])
    assert out["stats"]["engine"] == "duckdb" and out["stats"]["total_rows"] == 5
    assert "Ran in memory instead" in out["stats"]["notes"][0]


def test_aurora_errors_fall_back_to_memory(monkeypatch):
    s, v = _aurora(SAMPLES, "samples"), _aurora(VISITS, "visits")
    monkeypatch.setattr(joins.db, "get_engine_for_resource",
                        lambda rid: _BrokenEngine(RuntimeError("connection refused")))
    p = joins.preview(s, [_step(v, "left")])
    assert p["engine"] == "duckdb" and p["notes"][0].startswith("Aurora: connection refused")
