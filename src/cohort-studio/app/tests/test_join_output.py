"""Join output fields: drop and rename columns of the joined result.

The projection runs after the join on every engine (database SQL, DuckDB,
in-memory) and is stored in the join recipe, so reopening keeps it.
"""
import duckdb
import pandas as pd
import pytest

import disk_data
import joins
from tests.test_join_filters import RID, _open, _request, tables  # noqa: F401

# Joined fields are named "<alias> → <column>".
OUTPUT = {"exclude": ["status"], "rename": {"g → dosage": "dose", "g → gene": "gene_symbol"}}


def _query(client, dataset_id, filters=None):
    response = client.post(f"/api/datasets/{dataset_id}/query", json={"filters": filters or []})
    assert response.status_code == 200, response.text
    return response.json()


def test_database_join_drops_and_renames_fields_and_reopens(client, engine, tables):  # noqa: F811
    people, genotypes = _open(client, tables["people"]), _open(client, tables["genotypes"])
    body = {**_request(people, genotypes), "output": OUTPUT}
    joined = client.post("/api/datasets/join", json=body)
    assert joined.status_code == 200, joined.text
    result = joined.json()
    assert result["join"]["engine"] == "aurora"
    assert [c["name"] for c in result["columns"]] == ["person_id", "dose", "gene_symbol"]
    assert result["source_ref"]["output"] == OUTPUT
    # Live queries work on the renamed field, filters included.
    rows = _query(client, result["dataset_id"])
    assert rows["rows"]["columns"] == ["person_id", "dose", "gene_symbol"]
    narrowed = _query(client, result["dataset_id"], [
        {"column": "dose", "kind": "range", "min": 2, "max": 2}])
    assert narrowed["filtered"] == 1
    # Reopening the saved recipe applies the same fields.
    reopened = client.post("/api/datasets/open", json={"source_ref": result["source_ref"]})
    assert reopened.status_code == 200, reopened.text
    assert [c["name"] for c in reopened.json()["columns"]] == ["person_id", "dose", "gene_symbol"]
    # Preview shows the projected fields too.
    preview = client.post("/api/datasets/join/preview", json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()["columns"] == ["person_id", "dose", "gene_symbol"]


@pytest.mark.parametrize("output, message", [
    ({"exclude": ["nope"]}, "Unknown field"),
    ({"exclude": ["person_id", "status", "g → dosage", "g → gene"]}, "Keep at least one field"),
    ({"rename": {"g → dosage": "status"}}, "must be unique"),
])
def test_invalid_outputs_are_rejected(client, tables, output, message):  # noqa: F811
    people, genotypes = _open(client, tables["people"]), _open(client, tables["genotypes"])
    response = client.post("/api/datasets/join", json={**_request(people, genotypes), "output": output})
    assert response.status_code == 400 and message in response.text


def test_blank_rename_is_rejected(client, tables):  # noqa: F811
    people, genotypes = _open(client, tables["people"]), _open(client, tables["genotypes"])
    response = client.post("/api/datasets/join", json={
        **_request(people, genotypes), "output": {"rename": {"g → dosage": "  "}}})
    assert response.status_code == 422


def test_duckdb_result_gets_a_projected_view(tmp_path):
    path = str(tmp_path / "join.duckdb")
    con = duckdb.connect(path)
    con.execute("CREATE TABLE joined AS SELECT * FROM (VALUES (1, 'case', 2), (2, 'control', 0)) t(person_id, status, dosage)")
    con.close()
    frame = pd.DataFrame({"person_id": [1, 2], "status": ["case", "control"], "dosage": [2, 0]})
    out = joins.project_output({"df": frame, "stats": {}, "disk_source": {
        "path": path, "table": "joined", "columns": list(frame.columns)}},
        {"exclude": ["status"], "rename": {"dosage": "dose"}})
    assert list(out["df"].columns) == ["person_id", "dose"]
    source = out["disk_source"]
    assert source["columns"] == ["person_id", "dose"] and source["table"] != "joined"
    rows = disk_data.export_frame({**source, "scan_bytes": 1}, [], 10)
    assert rows.to_dict("list") == {"person_id": [1, 2], "dose": [2, 0]}


def test_no_output_is_a_no_op():
    out = {"df": pd.DataFrame({"a": [1]})}
    assert joins.project_output(out, None) is out
    assert joins.project_output(out, {"exclude": [], "rename": {}}) is out
