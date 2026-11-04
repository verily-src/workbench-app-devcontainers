import pytest
from fastapi.testclient import TestClient

import main
import sql_source


@pytest.mark.parametrize("sql,message", [
    ("SELECT person_id FROM person", "Use schema-qualified table names"),
    ("DELETE FROM cdm.person", "Only SELECT queries are allowed"),
    ("SELECT pg_sleep(1) FROM cdm.person", "is not allowed"),
    ("", "SQL query is required"),
])
def test_lint_reports_validation_rules(sql, message):
    result = sql_source.lint(sql)
    assert result["ok"] is False and message in result["message"]


def test_lint_reports_parse_position_and_formats_valid_sql():
    bad = sql_source.lint("SELECT person_id\nFROM cdm.person\nWHERE year_of_birth >")
    assert bad["ok"] is False and bad["line"] == 3
    good = TestClient(main.app).post("/api/sql/lint", json={
        "sql": "select person_id from cdm.person where year_of_birth > 1950"}).json()
    assert good["ok"] is True
    assert good["formatted"] == "SELECT\n  person_id\nFROM cdm.person\nWHERE\n  year_of_birth > 1950"
