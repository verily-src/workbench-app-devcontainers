import csv
import datetime as dt
import gzip
import json
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from google.cloud import bigquery

import synpuf_export


@pytest.fixture
def small_inventory(tmp_path):
    source = {
        "source": "bigquery-public-data:cms_synthetic_patient_data_omop",
        "tables": [
            {"table": "person", "rows": 2326856, "modified": "1",
             "schema": {"fields": [
                 {"name": "person_id", "type": "INTEGER"},
                 {"name": "gender_concept_id", "type": "INTEGER"},
             ]}},
            {"table": "condition_occurrence", "rows": 289182385,
             "modified": "2", "schema": {"fields": [
                 {"name": "condition_occurrence_id", "type": "INTEGER"},
                 {"name": "person_id", "type": "INTEGER"},
                 {"name": "condition_concept_id", "type": "INTEGER"},
                 {"name": "condition_start_date", "type": "DATE"},
             ]}},
            {"table": "concept_ancestor", "rows": 118150608,
             "modified": "3", "schema": {"fields": [
                 {"name": "ancestor_concept_id", "type": "INTEGER"},
                 {"name": "descendant_concept_id", "type": "INTEGER"},
             ]}},
            {"table": "cost", "rows": 748940384, "modified": "4",
             "schema": {"fields": [
                 {"name": "cost_event_id", "type": "INTEGER"},
                 {"name": "cost_domain_id", "type": "STRING"},
             ]}},
        ],
    }
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    return synpuf_export._load_inventory(path)


def test_query_rules_keep_patient_rows_and_costs_bound_to_events(small_inventory):
    condition = synpuf_export.query_for_table("condition_occurrence", small_inventory)
    assert "WITH sample_person AS" in condition
    assert "WHERE person_id IN (SELECT person_id FROM sample_person)" in condition

    cost = synpuf_export.query_for_table("cost", small_inventory)
    assert "cost_event_id IN" in cost
    assert "condition_occurrence_id" in cost
    assert "device_exposure_id" in cost
    assert "cost_domain_id" in cost

    ancestry = synpuf_export.query_for_table("concept_ancestor", small_inventory)
    assert "selected_concept" in ancestry
    assert "condition_concept_id AS concept_id" in ancestry
    assert "descendant_concept_id IN" in ancestry


def test_query_only_allows_inventory_names(small_inventory):
    with pytest.raises(ValueError, match="not in the source inventory"):
        synpuf_export.query_for_table("person; DROP TABLE person", small_inventory)


@dataclass
class Field:
    name: str
    field_type: str


class Result(list):
    schema = [Field("person_id", "INTEGER"), Field("note", "STRING"),
              Field("created", "DATE"), Field("active", "BOOL")]


class Job:
    job_id = "job-test"
    total_bytes_processed = 64

    def result(self, page_size):
        assert page_size == 10000
        return Result([
            {"person_id": 1, "note": None, "created": dt.date(2020, 1, 2),
             "active": True},
            {"person_id": 2, "note": "", "created": None, "active": False},
        ])


class Client:
    def query(self, sql, job_config):
        assert sql == "SELECT test"
        assert isinstance(job_config, bigquery.QueryJobConfig)
        if job_config.dry_run:
            assert job_config.use_query_cache is False
            return Job()
        assert job_config.maximum_bytes_billed == 1000
        return Job()


def test_streams_atomic_gzip_csv_with_source_null_and_date_contract(tmp_path):
    target = tmp_path / "person.csv.gz"
    out = synpuf_export._write_result(Client(), "SELECT test", target,
                                      bigquery, "person", 1000,
                                      [{"name": "person_id", "type": "INTEGER"},
                                       {"name": "note", "type": "STRING"},
                                       {"name": "created", "type": "DATE"},
                                       {"name": "active", "type": "BOOL"}],
                                      progress=lambda _: None)
    assert out["row_count"] == 2
    assert target.exists()
    assert not target.with_name(target.name + ".part").exists()
    assert out["sha256"] == synpuf_export._sha256(target)
    with gzip.open(target, "rt", encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream))
    assert rows == [
        ["person_id", "note", "created", "active"],
        ["1", r"\N", "2020-01-02", "true"],
        ["2", "", r"\N", "false"],
    ]


def test_rejects_literal_null_marker_collision():
    with pytest.raises(ValueError, match="collides with the configured CSV null marker"):
        synpuf_export._serialize(r"\N")


def test_export_options_lock_to_authorized_scope(tmp_path):
    with pytest.raises(ValueError, match="exactly 100,000"):
        synpuf_export.ExportOptions(project=synpuf_export.DEFAULT_JOB_PROJECT,
                                   output_dir=tmp_path, sample_size=10)
    with pytest.raises(ValueError, match="authorized BigQuery job project"):
        synpuf_export.ExportOptions(project="other-project", output_dir=tmp_path)


def test_gcloud_refresh_uses_naive_utc_expiry_without_logging_token(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(stdout="fake-token-for-unit-test")

    monkeypatch.setattr(synpuf_export.subprocess, "run", run)
    credentials = synpuf_export._gcloud_credentials()
    credentials.refresh(None)
    assert credentials.expiry.tzinfo is None
    assert credentials.expired is False
    assert calls[0][0] == ["gcloud", "auth", "print-access-token"]
    assert calls[0][1]["capture_output"] is True


def test_exports_authoritative_manifest_v1_without_querying_source(
        tmp_path, monkeypatch):
    def fake_write(client, sql, destination, config, table, max_bytes, columns):
        assert max_bytes == synpuf_export.DEFAULT_MAX_BYTES_BILLED
        destination.write_bytes(f"complete:{table}".encode())
        inventory = synpuf_export._load_inventory(synpuf_export.DEFAULT_INVENTORY)
        fields = inventory[table]["schema"]["fields"]
        return {"row_count": 100_000 if table == "person" else 0,
                "bytes": destination.stat().st_size,
                "sha256": synpuf_export._sha256(destination),
                "columns": [{"name": field["name"], "type": field["type"]}
                            for field in fields]}

    monkeypatch.setattr(synpuf_export, "_write_result", fake_write)
    output = tmp_path / "export"
    result = synpuf_export.export(synpuf_export.ExportOptions(
        output_dir=output), client=object())
    assert set(result) == {
        "version", "source", "job_project", "person_limit", "selection_sql",
        "created_at", "tables",
    }
    assert result["version"] == 1
    assert result["source"] == "bigquery-public-data.cms_synthetic_patient_data_omop"
    assert result["job_project"] == synpuf_export.DEFAULT_JOB_PROJECT
    assert result["person_limit"] == 100_000
    assert result["created_at"].endswith("+00:00")
    assert len(result["tables"]) == 24
    person = next(table for table in result["tables"] if table["name"] == "person")
    assert person["file"] == "person.csv.gz"
    assert person["rows"] == 100_000
    assert person["sha256"] == synpuf_export._sha256(output / "person.csv.gz")
    assert set(person) == {"name", "columns", "file", "rows", "sha256"}
    assert (output / "manifest.json").is_file()
