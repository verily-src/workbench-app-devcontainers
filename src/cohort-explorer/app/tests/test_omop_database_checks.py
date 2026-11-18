import pytest

from omop_criteria import OmopSpecError, build_person_list_sql
from omop_database_checks import (
    check_tables_exist,
    count_people_with_time_limit,
    list_tables_needed_by_spec,
)

SCHEMA_MESSAGE = (
    "The schema name may use only letters, digits and underscores, "
    "and must start with a letter or underscore."
)
TOO_SLOW_MESSAGE = "This cohort is too large to count. Add more rules and try again."
A_QUERY_THAT_TAKES_TWO_SECONDS = "SELECT 1 FROM pg_sleep(2)"


def make_spec(*rules):
    """Build a spec for the schema "omop". Each rule is (domain, concept_ids, exclude)."""
    return {
        "schema": "omop",
        "criteria": [
            {"domain": domain, "concept_ids": ids, "exclude": exclude}
            for domain, ids, exclude in rules
        ],
    }


# ---- which tables a spec reads (no database needed) ----


def test_tables_needed_are_person_concept_then_event_tables_in_rule_order():
    spec = make_spec(("drug", [40000001], False), ("condition", [201826], True))
    assert list_tables_needed_by_spec(spec) == [
        "person", "concept", "drug_exposure", "condition_occurrence"
    ]


def test_tables_needed_list_each_event_table_once():
    spec = make_spec(("condition", [201826], False), ("condition", [320128], True))
    assert list_tables_needed_by_spec(spec) == ["person", "concept", "condition_occurrence"]


def test_tables_needed_rejects_bad_spec():
    with pytest.raises(OmopSpecError):
        list_tables_needed_by_spec(make_spec(("procedure", [1], False)))


# ---- the table check (against the test database) ----


def test_all_omop_tables_present_passes(omop_connection):
    tables = ["person", "concept", "condition_occurrence", "drug_exposure"]
    check_tables_exist(omop_connection, "omop", tables)


def test_missing_concept_table_named_in_message(omop_connection):
    omop_connection.execute("CREATE SCHEMA omop_partial")
    omop_connection.execute("CREATE TABLE omop_partial.person (person_id integer)")
    with pytest.raises(OmopSpecError) as error:
        check_tables_exist(omop_connection, "omop_partial", ["person", "concept"])
    assert str(error.value) == (
        "This database does not look like OMOP data. "
        "Table concept was not found in schema omop_partial."
    )


def test_missing_event_table_named_in_message(omop_connection):
    omop_connection.execute("CREATE SCHEMA omop_no_events")
    omop_connection.execute("CREATE TABLE omop_no_events.person (person_id integer)")
    omop_connection.execute("CREATE TABLE omop_no_events.concept (concept_id integer)")
    needed = ["person", "concept", "condition_occurrence"]
    with pytest.raises(OmopSpecError) as error:
        check_tables_exist(omop_connection, "omop_no_events", needed)
    assert str(error.value) == (
        "This database does not look like OMOP data. "
        "Table condition_occurrence was not found in schema omop_no_events."
    )


def test_schema_that_does_not_exist_names_the_person_table(omop_connection):
    with pytest.raises(OmopSpecError) as error:
        check_tables_exist(omop_connection, "no_such_schema", ["person", "concept"])
    assert str(error.value) == (
        "This database does not look like OMOP data. "
        "Table person was not found in schema no_such_schema."
    )


def test_view_counts_as_a_table(omop_connection):
    omop_connection.execute("CREATE SCHEMA omop_views")
    omop_connection.execute("CREATE VIEW omop_views.person AS SELECT * FROM omop.person")
    check_tables_exist(omop_connection, "omop_views", ["person"])


def test_table_check_rejects_unsafe_schema_name(omop_connection):
    with pytest.raises(OmopSpecError) as error:
        check_tables_exist(omop_connection, 'omop"; DROP TABLE person;--', ["person"])
    assert str(error.value) == SCHEMA_MESSAGE


# ---- the timed count (against the test database) ----


def test_count_equals_number_of_matching_people(omop_connection):
    # Has type 2 diabetes AND has either metformin tablet: persons 1 and 2.
    spec = make_spec(("condition", [201826], False), ("drug", [40000001, 40000002], False))
    assert count_people_with_time_limit(omop_connection, build_person_list_sql(spec)) == 2


def test_count_for_a_does_not_have_rule_alone(omop_connection):
    # Does not have type 2 diabetes: persons 3, 5 and 6.
    spec = make_spec(("condition", [201826], True))
    assert count_people_with_time_limit(omop_connection, build_person_list_sql(spec)) == 3


def test_slow_count_rejected_with_message(omop_connection):
    with pytest.raises(OmopSpecError) as error:
        count_people_with_time_limit(
            omop_connection, A_QUERY_THAT_TAKES_TWO_SECONDS, seconds=0.2
        )
    assert str(error.value) == TOO_SLOW_MESSAGE


def test_connection_usable_after_slow_count(omop_connection):
    with pytest.raises(OmopSpecError):
        count_people_with_time_limit(
            omop_connection, A_QUERY_THAT_TAKES_TWO_SECONDS, seconds=0.2
        )
    assert omop_connection.execute("SELECT 1").fetchall() == [(1,)]


def test_time_limit_does_not_last_after_a_count(omop_connection):
    spec = make_spec(("condition", [201826], False))
    count_people_with_time_limit(omop_connection, build_person_list_sql(spec), seconds=5)
    assert omop_connection.execute("SHOW statement_timeout").fetchall() == [("0",)]
