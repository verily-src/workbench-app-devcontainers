"""Tests for joins.py: pure SQL-building/validation logic, no DB required."""
import pytest

from joins import (
    JoinError,
    JoinStep,
    _safe_output_name,
    _validate_steps,
    build_join_select,
)


def test_build_join_select_single_table():
    sql = build_join_select([JoinStep(table="person")])
    assert sql == '"public"."person" AS t0'


def test_build_join_select_chain_of_three():
    """Mirrors the epic's own example: person + condition_occurrence + concept,
    a left join followed by an inner join."""
    steps = [
        JoinStep(table="person"),
        JoinStep(table="condition_occurrence", join_to="person", left_key="person_id", right_key="person_id", join_type="left"),
        JoinStep(table="concept", join_to="condition_occurrence", left_key="condition_concept_id", right_key="concept_id", join_type="inner"),
    ]
    sql = build_join_select(steps)
    assert "LEFT JOIN \"public\".\"condition_occurrence\" AS t1 ON t0.\"person_id\" = t1.\"person_id\"" in sql
    assert "INNER JOIN \"public\".\"concept\" AS t2 ON t1.\"condition_concept_id\" = t2.\"concept_id\"" in sql


def test_rejects_empty_steps():
    with pytest.raises(JoinError):
        build_join_select([])


def test_rejects_more_than_max_tables():
    steps = [JoinStep(table="a")] + [
        JoinStep(table=f"t{i}", join_to="a", left_key="id", right_key="id") for i in range(5)
    ]
    with pytest.raises(JoinError, match="At most"):
        _validate_steps(steps)


def test_rejects_self_join():
    """Epic rule: a table may appear only once per join (no self-joins)."""
    steps = [
        JoinStep(table="person"),
        JoinStep(table="person", join_to="person", left_key="id", right_key="id"),
    ]
    with pytest.raises(JoinError, match="more than once"):
        _validate_steps(steps)


def test_rejects_join_to_unknown_table():
    steps = [
        JoinStep(table="person"),
        JoinStep(table="condition", join_to="nonexistent", left_key="id", right_key="id"),
    ]
    with pytest.raises(JoinError, match="hasn't been added"):
        _validate_steps(steps)


def test_rejects_base_table_with_join_to():
    steps = [JoinStep(table="person", join_to="other", left_key="id", right_key="id")]
    with pytest.raises(JoinError, match="base table"):
        _validate_steps(steps)


def test_rejects_incomplete_step():
    steps = [JoinStep(table="person"), JoinStep(table="condition", join_to="person")]
    with pytest.raises(JoinError, match="missing join_to/left_key/right_key"):
        _validate_steps(steps)


def test_safe_output_name_passes_through_short_unique_names():
    used = set()
    assert _safe_output_name("age", used) == "age"


def test_safe_output_name_truncates_over_63_bytes():
    """Postgres identifiers are capped at 63 bytes (BENCH-10344 J26). A collision
    rename like <table>_<column> can easily blow past that with real UKBB-style
    names; truncation must still produce a valid, unique identifier."""
    long_name = "a_very_long_ukbb_style_table_name_" + "x" * 40 + "_column_suffix"
    assert len(long_name.encode("utf-8")) > 63
    used = set()
    result = _safe_output_name(long_name, used)
    assert len(result.encode("utf-8")) <= 63
    assert result in used


def test_safe_output_name_avoids_reserved_rowid_name():
    """build_select reserves "_rowid" for the synthetic ROW_NUMBER() column
    (see dynamic_model.set_active_join_mapping); a real column that happens
    to be named "_rowid" must not collide with it."""
    from joins import ROWID_COLUMN

    used = {ROWID_COLUMN}
    result = _safe_output_name(ROWID_COLUMN, used)
    assert result != ROWID_COLUMN


def test_safe_output_name_stays_unique_after_truncation():
    """Two different long names that truncate to the same prefix must not
    collide with each other post-truncation."""
    base = "a_very_long_ukbb_style_table_name_" + "x" * 40
    name_a = base + "_suffix_one"
    name_b = base + "_suffix_two"
    used: set[str] = set()
    out_a = _safe_output_name(name_a, used)
    out_b = _safe_output_name(name_b, used)
    assert out_a != out_b
