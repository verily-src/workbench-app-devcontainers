import psycopg
import pytest


@pytest.fixture
def fixture_connection(omop_database):
    with psycopg.connect(omop_database) as connection:
        yield connection


def test_fixture_has_six_persons(fixture_connection):
    rows = fixture_connection.execute("SELECT person_id FROM omop.person ORDER BY 1").fetchall()
    assert [row[0] for row in rows] == [1, 2, 3, 4, 5, 6]


def test_fixture_race_code_without_concept_row(fixture_connection):
    rows = fixture_connection.execute(
        "SELECT count(*) FROM omop.concept WHERE concept_id = 99999999"
    ).fetchall()
    assert rows == [(0,)]


def test_fixture_person_one_has_condition_twice(fixture_connection):
    rows = fixture_connection.execute(
        "SELECT count(*) FROM omop.condition_occurrence "
        "WHERE person_id = 1 AND condition_concept_id = 201826"
    ).fetchall()
    assert rows == [(2,)]
