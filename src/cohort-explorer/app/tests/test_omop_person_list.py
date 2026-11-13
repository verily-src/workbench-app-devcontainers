import psycopg
import pytest

from omop_criteria import OmopSpecError, build_person_list_sql

# Concept IDs from the test data in omop_fixture_data.py.
TYPE_2_DIABETES = 201826
METFORMIN_500, METFORMIN_1000 = 40000001, 40000002


def make_spec(*rules):
    """Build a spec for the schema "omop". Each rule is (domain, concept_ids, exclude)."""
    return {
        "schema": "omop",
        "criteria": [
            {"domain": domain, "concept_ids": ids, "exclude": exclude}
            for domain, ids, exclude in rules
        ],
    }


def has_diabetes():
    return ("condition", [TYPE_2_DIABETES], False)


def has_metformin():
    return ("drug", [METFORMIN_500, METFORMIN_1000], False)


def lacks_metformin():
    return ("drug", [METFORMIN_500, METFORMIN_1000], True)


# ---- the shape of the SQL text (no database needed) ----


def test_has_rule_uses_exists_clause():
    sql = build_person_list_sql(make_spec(has_diabetes()))
    assert 'WHERE EXISTS (SELECT 1 FROM "omop"."condition_occurrence" e' in sql
    assert 'e."condition_concept_id" IN (201826))' in sql


def test_does_not_have_rule_uses_not_exists_clause():
    sql = build_person_list_sql(make_spec(lacks_metformin()))
    assert 'WHERE NOT EXISTS (SELECT 1 FROM "omop"."drug_exposure" e' in sql


def test_concept_ids_written_as_plain_integers():
    sql = build_person_list_sql(make_spec(has_metformin()))
    assert 'IN (40000001, 40000002)' in sql


def test_rules_joined_with_and():
    sql = build_person_list_sql(make_spec(has_diabetes(), lacks_metformin()))
    assert "\n  AND NOT EXISTS (" in sql


def test_schema_name_is_quoted():
    sql = build_person_list_sql(make_spec(has_diabetes()))
    assert 'FROM "omop"."person" p' in sql


def test_bad_spec_raises_before_sql_is_built():
    spec = make_spec(has_diabetes())
    spec["schema"] = 'omop"; DROP TABLE person;--'
    with pytest.raises(OmopSpecError):
        build_person_list_sql(spec)


def test_sql_has_no_colon_for_sqlalchemy_text():
    # SQLAlchemy text() reads ":name" as a bound parameter. The app wraps this SQL in text().
    assert ":" not in build_person_list_sql(make_spec(has_diabetes(), lacks_metformin()))


# ---- the people the SQL finds (against the test database) ----


@pytest.fixture
def connection(omop_database):
    with psycopg.connect(omop_database) as open_connection:
        yield open_connection


def run_person_list(connection, spec):
    """Run the generated SQL as is, with no parameters. Return (column names, rows)."""
    cursor = connection.execute(build_person_list_sql(spec))
    column_names = [column.name for column in cursor.description]
    return column_names, cursor.fetchall()


def person_ids(connection, spec):
    """Return the person IDs found, in the order returned, sorted. Duplicates stay visible."""
    _, rows = run_person_list(connection, spec)
    return sorted(row[1] for row in rows)


def test_one_rule_finds_each_person_once(connection):
    # Person 1 has the condition in two rows, and must still appear once.
    assert person_ids(connection, make_spec(has_diabetes())) == [1, 2, 4]


def test_several_concept_ids_in_one_rule_mean_any(connection):
    assert person_ids(connection, make_spec(has_metformin())) == [1, 2, 3]


def test_two_rules_mean_both(connection):
    assert person_ids(connection, make_spec(has_diabetes(), has_metformin())) == [1, 2]


def test_does_not_have_removes_people(connection):
    assert person_ids(connection, make_spec(has_diabetes(), lacks_metformin())) == [4]


def test_does_not_have_rule_works_alone(connection):
    spec = make_spec(("condition", [TYPE_2_DIABETES], True))
    assert person_ids(connection, spec) == [3, 5, 6]


def test_person_list_has_fixed_columns_in_order(connection):
    column_names, rows = run_person_list(connection, make_spec(has_diabetes()))
    assert column_names == [
        "_rowid", "person_id", "gender", "race", "ethnicity", "year_of_birth"
    ]
    assert all(row[0] == row[1] for row in rows)


def test_codes_show_as_names(connection):
    _, rows = run_person_list(connection, make_spec(has_diabetes()))
    gender_by_person = {row[1]: row[2] for row in rows}
    assert gender_by_person == {1: "Male", 2: "Female", 4: "Female"}


def test_person_with_unnamed_code_is_kept_with_empty_name(connection):
    # Person 6 has a race code that has no row in the concept table.
    spec = make_spec(("condition", [TYPE_2_DIABETES], True))
    _, rows = run_person_list(connection, spec)
    race_by_person = {row[1]: row[3] for row in rows}
    assert race_by_person[6] is None
