import subprocess

import psycopg
import pytest

import db
from omop_concept_search import search_concepts
from omop_criteria import build_person_list_sql

READ_ONLY_ROLE = "omop_reader"


# ---- the command the app runs to get a connection (no database needed) ----


class FakeWbRun:
    """Stands in for subprocess.run. Remembers each command it was asked to run."""

    def __init__(self):
        self.commands = []

    def __call__(self, command, **options):
        self.commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="postgresql://fake\n", stderr="")


@pytest.fixture
def fake_wb_run(monkeypatch):
    fake = FakeWbRun()
    monkeypatch.setattr(db.subprocess, "run", fake)
    monkeypatch.setattr(db, "_conn_string_cache", {})
    monkeypatch.setattr(db, "_conn_string_events", {})
    return fake


def test_wb_resolve_asks_for_read_only_access(fake_wb_run):
    db.resolve_connection_string("some-resource")
    command = fake_wb_run.commands[0]
    assert command[command.index("--access-mode") + 1] == "READ_ONLY"


def test_wb_resolve_still_sends_resource_id_and_password_flag(fake_wb_run):
    db.resolve_connection_string("some-resource")
    command = fake_wb_run.commands[0]
    assert command[command.index("--id") + 1] == "some-resource"
    assert "--include-password" in command


def test_connection_pre_warm_uses_read_only_access(fake_wb_run):
    # warm_connection_string resolves in a background thread. Wait for it to finish.
    db.warm_connection_string("some-resource")
    db.wait_connection_string("some-resource", timeout=10)
    command = fake_wb_run.commands[0]
    assert command[command.index("--access-mode") + 1] == "READ_ONLY"


# ---- what a read-only database user can and cannot do (against the test database) ----


@pytest.fixture
def reader_connection(omop_database):
    """Connect as a database user that has only SELECT rights on the omop schema."""
    with psycopg.connect(omop_database, autocommit=True) as admin:
        admin.execute(f"DROP ROLE IF EXISTS {READ_ONLY_ROLE}")
        admin.execute(f"CREATE ROLE {READ_ONLY_ROLE} LOGIN")
        admin.execute(f"GRANT USAGE ON SCHEMA omop TO {READ_ONLY_ROLE}")
        admin.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA omop TO {READ_ONLY_ROLE}")
    reader_url = omop_database.replace("postgres@", f"{READ_ONLY_ROLE}@")
    with psycopg.connect(reader_url) as connection:
        yield connection
    with psycopg.connect(omop_database, autocommit=True) as admin:
        admin.execute(f"DROP OWNED BY {READ_ONLY_ROLE}")
        admin.execute(f"DROP ROLE {READ_ONLY_ROLE}")


def test_read_only_user_can_search_concepts(reader_connection):
    results = search_concepts(reader_connection, "omop", "drug", "metformin")
    assert [r["concept_id"] for r in results] == [40000001, 40000002]


def test_read_only_user_can_list_people(reader_connection):
    spec = {
        "schema": "omop",
        "criteria": [{"domain": "condition", "concept_ids": [201826], "exclude": False}],
    }
    rows = reader_connection.execute(build_person_list_sql(spec)).fetchall()
    assert sorted(row[1] for row in rows) == [1, 2, 4]


def test_read_only_user_can_make_a_temporary_table(reader_connection):
    # /api/filters copies the cohort into a temporary table, once per request.
    reader_connection.execute("CREATE TEMPORARY TABLE copy_of_people AS SELECT * FROM omop.person")
    rows = reader_connection.execute("SELECT count(*) FROM copy_of_people").fetchall()
    assert rows == [(6,)]


def test_read_only_user_cannot_drop_a_table(reader_connection):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        reader_connection.execute("DROP TABLE omop.person")


def test_read_only_user_cannot_change_rows(reader_connection):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        reader_connection.execute("UPDATE omop.person SET year_of_birth = 1900")
