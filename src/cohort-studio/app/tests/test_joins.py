"""Notebook-style joins: types, compound and non-equi conditions, chains,
column picking/naming, type coercion, caps, preview and key suggestions."""

import pandas as pd
import pytest

import datasets
import joins


def _open(df: pd.DataFrame, source: str) -> str:
    return datasets.open_dataset(df, source)["dataset_id"]


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
