import contextlib
import functools
import json
import subprocess

import psycopg
import pytest
from fastapi import HTTPException
from starlette.requests import Request

import db
import dynamic_model
import main
import omop_cohort

SCHEMA_MESSAGE = (
    "The schema name may use only letters, digits and underscores, "
    "and must start with a letter or underscore."
)
NOT_OMOP_MESSAGE = (
    "This database does not look like OMOP data. "
    "Table person was not found in schema no_such_schema."
)
COUNT_TOO_SLOW_MESSAGE = (
    "The count took longer than 15 seconds and was stopped. Try again, or add more rules."
)
NO_DATABASE_MESSAGE = "Choose a database first."
CANNOT_CONNECT_MESSAGE = (
    "Could not connect to the database. Check the database choice and try again."
)

DYNAMIC_MODEL_STATE_NAMES = [
    "_active_mapping", "_active_model", "_active_table_name", "_entity_column",
]


def point_app_at_database(monkeypatch, tmp_path, connection_string):
    """Make the app use the test database, and keep the app's global state out of other tests."""
    monkeypatch.setattr(omop_cohort, "_connect_aurora", lambda resource_id: psycopg.connect(connection_string))
    monkeypatch.setattr(db, "resolve_connection_string", lambda *arguments, **options: connection_string)
    monkeypatch.setattr(db, "_engines", {})
    monkeypatch.setattr(db, "_session_factories", {})
    monkeypatch.setattr(db, "_conn_string_cache", {})
    monkeypatch.setattr(db, "_active_resource_id", None)
    monkeypatch.setattr(dynamic_model, "_SCHEMA_FILE", tmp_path / "active_schema.json")
    for name in DYNAMIC_MODEL_STATE_NAMES:
        monkeypatch.setattr(dynamic_model, name, None)
    monkeypatch.setattr(dynamic_model, "_pk_name", "id")


@pytest.fixture
def omop_app(monkeypatch, tmp_path, omop_database):
    point_app_at_database(monkeypatch, tmp_path, omop_database)
    yield
    for engine in db._engines.values():
        engine.dispose()


@pytest.fixture
def omop_app_as_reader(monkeypatch, tmp_path, reader_url):
    point_app_at_database(monkeypatch, tmp_path, reader_url)
    yield
    for engine in db._engines.values():
        engine.dispose()


def make_spec(*rules, schema="omop"):
    """Build a spec. Each rule is (domain, concept_ids, exclude)."""
    return {
        "schema": schema,
        "criteria": [
            {"domain": domain, "concept_ids": ids, "exclude": exclude}
            for domain, ids, exclude in rules
        ],
    }


def diabetes_and_metformin_spec():
    """Has type 2 diabetes AND has either metformin tablet: persons 1 and 2."""
    return make_spec(("condition", [201826], False), ("drug", [40000001, 40000002], False))


def request_cohort(spec, resource_id="test-resource"):
    return main.create_omop_cohort({"resource_id": resource_id, "spec": spec})


def a_plain_request():
    return Request({"type": "http", "query_string": b""})


@contextlib.contextmanager
def active_session():
    """Open a database session for the active resource, as the endpoints do."""
    sessions = db.get_db()
    session = next(sessions)
    try:
        yield session
    finally:
        sessions.close()


def saved_schema_text(tmp_path):
    return (tmp_path / "active_schema.json").read_text()


def request_and_expect_rejection(spec, resource_id="test-resource"):
    """Make the request, expect HTTP 400, and return the message."""
    with pytest.raises(HTTPException) as error:
        request_cohort(spec, resource_id)
    assert error.value.status_code == 400
    return error.value.detail


# ---- a valid request (AC19, AC20) ----


def test_valid_request_returns_people_count(omop_app):
    assert request_cohort(diabetes_and_metformin_spec()) == {"count": 2}


def test_active_model_is_the_omop_model(omop_app, tmp_path):
    request_cohort(diabetes_and_metformin_spec())
    saved = json.loads(saved_schema_text(tmp_path))
    assert saved["table_name"] == "omop:omop"
    assert saved["entity_column"] == "person_id"
    assert [mapping["column"] for mapping in saved["mappings"]] == [
        "person_id", "gender", "race", "ethnicity", "year_of_birth",
        "rule1_items", "rule1_first_date",
        "rule2_items", "rule2_first_date",
    ]
    assert db.get_active_resource_id() == "test-resource"


def test_summary_columns_get_readable_labels(omop_app, tmp_path):
    request_cohort(diabetes_and_metformin_spec())
    saved = json.loads(saved_schema_text(tmp_path))
    labels = [mapping["label"] for mapping in saved["mappings"]][5:]
    assert labels == [
        "Condition (rule 1): items", "Condition (rule 1): first date",
        "Drug (rule 2): items", "Drug (rule 2): first date",
    ]


def test_samples_include_the_summary_values(omop_app):
    request_cohort(diabetes_and_metformin_spec())
    with active_session() as session:
        rows = main.get_samples(a_plain_request(), session)
    person_one = next(row for row in rows if row["person_id"] == 1)
    assert person_one["rule1_items"] == "Type 2 diabetes mellitus"
    assert person_one["rule1_first_date"] == "2020-01-10"
    assert person_one["rule2_items"] == "Metformin 500 MG Oral Tablet"


# ---- the value range of a measurement rule (AC56) ----


def test_range_cohort_counts_only_people_with_a_result_inside_it(omop_app):
    # Person 1 has 6.1 and 7.4, person 3 has 5.2. Only person 1 has a result from 6.0 to 6.5.
    assert request_cohort(a1c_range_spec(6.0, 6.5)) == {"count": 1}


def test_range_cohort_with_no_matching_result_is_empty(omop_app):
    assert request_cohort(a1c_range_spec(6.5, 7.0)) == {"count": 0}


def test_range_cohort_rows_are_the_people_inside_the_range(omop_app):
    request_cohort(a1c_range_spec(value_max=5.5))
    with active_session() as session:
        rows = main.get_samples(a_plain_request(), session)
    assert [row["person_id"] for row in rows] == [3]


def test_range_adds_no_columns_to_the_explorer(omop_app, tmp_path):
    request_cohort(a1c_range_spec(6.0, 8.0))
    saved = json.loads(saved_schema_text(tmp_path))
    assert [mapping["column"] for mapping in saved["mappings"]][5:] == ["rule1_items", "rule1_first_date"]


def test_range_that_is_backwards_rejected_with_a_plain_message(omop_app):
    message = request_and_expect_rejection(a1c_range_spec(8, 7))
    assert message == "The lowest value must not be higher than the highest value."


def test_two_measurements_in_one_rule_rejected_with_a_plain_message(omop_app):
    message = request_and_expect_rejection(make_spec(("measurement", [4200001, 4200002], False)))
    assert message == "A measurement rule can hold only one item."


def test_range_on_a_condition_rejected_with_a_plain_message(omop_app):
    spec = make_spec(("condition", [201826], False))
    spec["criteria"][0]["value_min"] = 1
    assert request_and_expect_rejection(spec) == "A value range applies to measurements only."


def test_samples_return_the_matching_people(omop_app):
    request_cohort(diabetes_and_metformin_spec())
    with active_session() as session:
        rows = main.get_samples(a_plain_request(), session)
    assert sorted(row["person_id"] for row in rows) == [1, 2]


def test_filters_show_gender_options_with_counts(omop_app):
    request_cohort(diabetes_and_metformin_spec())
    with active_session() as session:
        result = main.get_filters(a_plain_request(), session)
    assert result["gender"] == [
        {"value": "Female", "label": "Female", "count": 1},
        {"value": "Male", "label": "Male", "count": 1},
    ]


def test_cohort_survives_an_app_restart(omop_app, monkeypatch):
    request_cohort(diabetes_and_metformin_spec())
    for name in DYNAMIC_MODEL_STATE_NAMES:
        monkeypatch.setattr(dynamic_model, name, None)

    dynamic_model.load_schema_from_disk()

    with active_session() as session:
        rows = main.get_samples(a_plain_request(), session)
    assert sorted(row["person_id"] for row in rows) == [1, 2]


# ---- a wrong request changes nothing (AC21, AC22, AC23, AC46) ----


def test_database_that_is_not_omop_rejected_and_previous_cohort_kept(omop_app, tmp_path):
    request_cohort(diabetes_and_metformin_spec(), resource_id="first-resource")
    before = saved_schema_text(tmp_path)

    message = request_and_expect_rejection(
        make_spec(("condition", [201826], False), schema="no_such_schema"),
        resource_id="second-resource",
    )

    assert message == NOT_OMOP_MESSAGE
    assert saved_schema_text(tmp_path) == before
    assert db.get_active_resource_id() == "first-resource"


def test_slow_count_rejected_and_previous_cohort_kept(omop_app, tmp_path, monkeypatch):
    request_cohort(diabetes_and_metformin_spec(), resource_id="first-resource")
    before = saved_schema_text(tmp_path)
    # Make the count slow, and shorten the limit so the test stays fast.
    monkeypatch.setattr(omop_cohort, "build_person_list_sql", lambda spec: "SELECT 1 AS x FROM pg_sleep(2)")
    monkeypatch.setattr(
        omop_cohort,
        "count_people_with_time_limit",
        functools.partial(omop_cohort.count_people_with_time_limit, seconds=0.2),
    )

    message = request_and_expect_rejection(diabetes_and_metformin_spec(), "second-resource")

    assert message == COUNT_TOO_SLOW_MESSAGE
    assert saved_schema_text(tmp_path) == before
    assert db.get_active_resource_id() == "first-resource"


@pytest.fixture
def omop_schema_without_dates(omop_database):
    """A schema with all four OMOP tables, but no start date columns. Removed after the test."""
    with psycopg.connect(omop_database, autocommit=True) as admin:
        admin.execute("CREATE SCHEMA omop_no_dates")
        admin.execute("CREATE TABLE omop_no_dates.person (person_id integer)")
        admin.execute("CREATE TABLE omop_no_dates.concept (concept_id integer)")
        admin.execute(
            "CREATE TABLE omop_no_dates.condition_occurrence (person_id integer, condition_concept_id integer)"
        )
    yield
    with psycopg.connect(omop_database, autocommit=True) as admin:
        admin.execute("DROP SCHEMA omop_no_dates CASCADE")


def test_database_without_date_column_rejected_and_previous_cohort_kept(
    omop_app, tmp_path, omop_schema_without_dates
):
    request_cohort(diabetes_and_metformin_spec(), resource_id="first-resource")
    before = saved_schema_text(tmp_path)

    message = request_and_expect_rejection(
        make_spec(("condition", [201826], False), schema="omop_no_dates"), "second-resource"
    )

    assert message == (
        "This database does not look like OMOP data. "
        "Column condition_start_date was not found in table condition_occurrence of schema omop_no_dates."
    )
    assert saved_schema_text(tmp_path) == before
    assert db.get_active_resource_id() == "first-resource"


@pytest.fixture
def omop_schema_without_values(omop_database):
    """A schema with the tables a measurement rule needs, but no value column. Removed after the test."""
    with psycopg.connect(omop_database, autocommit=True) as admin:
        admin.execute("CREATE SCHEMA omop_no_values")
        admin.execute("CREATE TABLE omop_no_values.person (person_id integer)")
        admin.execute("CREATE TABLE omop_no_values.concept (concept_id integer)")
        admin.execute(
            "CREATE TABLE omop_no_values.measurement "
            "(person_id integer, measurement_concept_id integer, measurement_date date)"
        )
    yield
    with psycopg.connect(omop_database, autocommit=True) as admin:
        admin.execute("DROP SCHEMA omop_no_values CASCADE")


def a1c_range_spec(value_min=None, value_max=None, schema="omop"):
    spec = make_spec(("measurement", [4200001], False), schema=schema)
    spec["criteria"][0]["value_min"] = value_min
    spec["criteria"][0]["value_max"] = value_max
    return spec


def test_database_without_value_column_rejected_when_a_range_is_set(
    omop_app, tmp_path, omop_schema_without_values
):
    request_cohort(diabetes_and_metformin_spec(), resource_id="first-resource")
    before = saved_schema_text(tmp_path)

    message = request_and_expect_rejection(a1c_range_spec(6.5, schema="omop_no_values"), "second-resource")

    assert message == (
        "This database does not look like OMOP data. "
        "Column value_as_number was not found in table measurement of schema omop_no_values."
    )
    assert saved_schema_text(tmp_path) == before
    assert db.get_active_resource_id() == "first-resource"


@pytest.mark.parametrize("resource_id", [None, "", "   "])
def test_missing_database_choice_rejected(omop_app, resource_id):
    assert request_and_expect_rejection(diabetes_and_metformin_spec(), resource_id) == NO_DATABASE_MESSAGE


def test_request_without_resource_id_key_rejected(omop_app):
    with pytest.raises(HTTPException) as error:
        main.create_omop_cohort({"spec": diabetes_and_metformin_spec()})
    assert (error.value.status_code, error.value.detail) == (400, NO_DATABASE_MESSAGE)


@pytest.mark.parametrize(
    "connection_error",
    [
        pytest.param(subprocess.CalledProcessError(1, "wb"), id="wb-command-failed"),
        pytest.param(psycopg.OperationalError("connection refused"), id="connection-refused"),
    ],
)
def test_unreachable_database_rejected_and_previous_cohort_kept(
    omop_app, tmp_path, monkeypatch, connection_error
):
    request_cohort(diabetes_and_metformin_spec(), resource_id="first-resource")
    before = saved_schema_text(tmp_path)

    def fail_to_connect(resource_id):
        raise connection_error

    monkeypatch.setattr(omop_cohort, "_connect_aurora", fail_to_connect)

    message = request_and_expect_rejection(diabetes_and_metformin_spec(), "second-resource")

    assert message == CANNOT_CONNECT_MESSAGE
    assert saved_schema_text(tmp_path) == before
    assert db.get_active_resource_id() == "first-resource"


# ---- bad input cannot change data (AC34, AC36) ----


def count_all_omop_rows(omop_database):
    with psycopg.connect(omop_database) as connection:
        return connection.execute(
            "SELECT (SELECT count(*) FROM omop.person), (SELECT count(*) FROM omop.concept), "
            "(SELECT count(*) FROM omop.condition_occurrence), (SELECT count(*) FROM omop.drug_exposure)"
        ).fetchall()


@pytest.mark.parametrize(
    "spec, expected_message",
    [
        pytest.param(
            make_spec(("condition", [201826], False), schema='omop"; DROP TABLE person;--'),
            SCHEMA_MESSAGE,
            id="sql-in-schema-name",
        ),
        pytest.param(
            make_spec(("condition", ["1); DROP TABLE person;--"], False)),
            "Concept IDs must be whole numbers.",
            id="sql-in-concept-id",
        ),
    ],
)
def test_sql_in_request_rejected_and_data_unchanged(omop_app, omop_database, spec, expected_message):
    rows_before = count_all_omop_rows(omop_database)
    assert request_and_expect_rejection(spec) == expected_message
    assert count_all_omop_rows(omop_database) == rows_before


def test_successful_request_does_not_change_omop_tables(omop_app, omop_database):
    rows_before = count_all_omop_rows(omop_database)
    request_cohort(diabetes_and_metformin_spec())
    assert count_all_omop_rows(omop_database) == rows_before


# ---- read-only connection (AC37 b) ----


def test_cohort_works_for_read_only_user(omop_app_as_reader):
    assert request_cohort(diabetes_and_metformin_spec()) == {"count": 2}
    with active_session() as session:
        rows = main.get_samples(a_plain_request(), session)
        filters = main.get_filters(a_plain_request(), session)
    assert sorted(row["person_id"] for row in rows) == [1, 2]
    assert [option["value"] for option in filters["gender"]] == ["Female", "Male"]


# ---- the concept search endpoint (AC25, AC36) ----

UNKNOWN_DOMAIN_MESSAGE = (
    "Choose a valid OMOP domain. "
    "Current valid choices: condition, drug, observation, procedure, measurement."
)
METFORMIN_RESULTS = [
    {"concept_id": 40000001, "name": "Metformin 500 MG Oral Tablet", "vocabulary": "RxNorm", "persons": 2},
    {"concept_id": 40000002, "name": "Metformin 1000 MG Oral Tablet", "vocabulary": "RxNorm", "persons": 1},
]


def search_concepts_endpoint(resource_id="test-resource", schema="omop", domain="drug", q="metformin"):
    return main.search_omop_concepts(resource_id=resource_id, schema=schema, domain=domain, q=q)


def search_and_expect_rejection(**request):
    """Make the search, expect HTTP 400, and return the message."""
    with pytest.raises(HTTPException) as error:
        search_concepts_endpoint(**request)
    assert error.value.status_code == 400
    return error.value.detail


def test_search_endpoint_returns_matching_concepts(omop_app):
    assert search_concepts_endpoint() == METFORMIN_RESULTS


def test_search_endpoint_rejects_missing_database_choice(omop_app):
    assert search_and_expect_rejection(resource_id="") == NO_DATABASE_MESSAGE


def test_search_endpoint_rejects_unsafe_schema_name(omop_app):
    assert search_and_expect_rejection(schema='omop"; DROP TABLE person;--') == SCHEMA_MESSAGE


def test_search_endpoint_rejects_unknown_domain(omop_app):
    assert search_and_expect_rejection(domain="visit") == UNKNOWN_DOMAIN_MESSAGE


def test_search_endpoint_rejects_database_that_is_not_omop(omop_app):
    assert search_and_expect_rejection(schema="no_such_schema") == (
        "This database does not look like OMOP data. "
        "Table concept was not found in schema no_such_schema."
    )


def test_search_endpoint_rejects_unreachable_database(omop_app, monkeypatch):
    def fail_to_connect(resource_id):
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(omop_cohort, "_connect_aurora", fail_to_connect)
    assert search_and_expect_rejection() == CANNOT_CONNECT_MESSAGE


def test_search_endpoint_does_not_change_the_active_cohort(omop_app, tmp_path):
    request_cohort(diabetes_and_metformin_spec(), resource_id="first-resource")
    before = saved_schema_text(tmp_path)

    search_concepts_endpoint(resource_id="second-resource")

    assert saved_schema_text(tmp_path) == before
    assert db.get_active_resource_id() == "first-resource"


def test_search_endpoint_does_not_change_omop_tables(omop_app, omop_database):
    rows_before = count_all_omop_rows(omop_database)
    search_concepts_endpoint()
    assert count_all_omop_rows(omop_database) == rows_before


def test_search_endpoint_works_for_read_only_user(omop_app_as_reader):
    assert search_concepts_endpoint() == METFORMIN_RESULTS
