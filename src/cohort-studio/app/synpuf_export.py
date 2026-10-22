"""Export a deterministic CMS SynPUF OMOP subset to local CSV.GZ files."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import os
import re
import subprocess
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

SOURCE_PROJECT = "bigquery-public-data"
SOURCE_DATASET = "cms_synthetic_patient_data_omop"
DEFAULT_SAMPLE_SIZE = 100_000
DEFAULT_MAX_BYTES_BILLED = 200_000_000_000
DEFAULT_JOB_PROJECT = "vwb-dev-affable-olive-9580"
DEFAULT_INVENTORY = Path(__file__).parent.parent / "docs/imports/cms_synpuf_source_inventory.json"
MANIFEST_NAME = "manifest.json"
STATE_NAME = ".export-state.json"
NULL_MARKER = r"\N"
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SELECTION_SQL = (
    "SELECT DISTINCT person_id "
    f"FROM `{SOURCE_PROJECT}.{SOURCE_DATASET}.person` "
    "WHERE person_id IS NOT NULL "
    "ORDER BY FARM_FINGERPRINT(CAST(person_id AS STRING)), person_id "
    f"LIMIT {DEFAULT_SAMPLE_SIZE}"
)

PERSON_TABLES = {
    "condition_era", "condition_occurrence", "death", "device_exposure",
    "dose_era", "drug_era", "drug_exposure", "observation",
    "observation_period", "payer_plan_period", "person",
    "procedure_occurrence",
}
VOCABULARY_TABLES = {
    "concept", "concept_class", "concept_relationship", "domain",
    "drug_strength", "relationship", "vocabulary",
}
EVENT_ID_TABLES = {
    "CONDITION": ("condition_occurrence", "condition_occurrence_id"),
    "DRUG": ("drug_exposure", "drug_exposure_id"),
    "PROCEDURE": ("procedure_occurrence", "procedure_occurrence_id"),
    "OBSERVATION": ("observation", "observation_id"),
    "DEVICE": ("device_exposure", "device_exposure_id"),
}


class ExportOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    project: str = DEFAULT_JOB_PROJECT
    output_dir: Path
    sample_size: int = DEFAULT_SAMPLE_SIZE
    max_bytes_billed: int = DEFAULT_MAX_BYTES_BILLED
    inventory_path: Path = DEFAULT_INVENTORY

    @field_validator("project")
    @classmethod
    def validate_project(cls, value: str) -> str:
        if not value.replace("-", "").replace("_", "").isalnum():
            raise ValueError("Invalid BigQuery job project id.")
        if value != DEFAULT_JOB_PROJECT:
            raise ValueError("Use the authorized BigQuery job project.")
        return value

    @field_validator("sample_size")
    @classmethod
    def validate_sample_size(cls, value: int) -> int:
        if value != DEFAULT_SAMPLE_SIZE:
            raise ValueError("This export is authorized for exactly 100,000 people.")
        return value

    @field_validator("max_bytes_billed")
    @classmethod
    def validate_max_bytes(cls, value: int) -> int:
        if value <= 0 or value > DEFAULT_MAX_BYTES_BILLED:
            raise ValueError("Maximum bytes billed must be between 1 and 200 GB.")
        return value


def _gcloud_credentials():
    import google.auth.credentials

    class ActiveGcloudCredentials(google.auth.credentials.Credentials):
        def __init__(self):
            super().__init__()
            self.token = None
            self.expiry = None

        def refresh(self, request):
            try:
                result = subprocess.run(
                    ["gcloud", "auth", "print-access-token"],
                    check=True, capture_output=True, text=True, timeout=30)
            except (OSError, subprocess.SubprocessError) as exc:
                raise RuntimeError(
                    "Could not refresh Google credentials with gcloud.") from exc
            token = result.stdout.strip()
            if not token:
                raise RuntimeError("gcloud returned an empty access token.")
            self.token = token
            self.expiry = (dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
                           + dt.timedelta(minutes=50))

        def apply(self, headers, token=None):
            if not self.token or self.expired:
                self.refresh(None)
            super().apply(headers, token=token)

    return ActiveGcloudCredentials()


def _load_inventory(path: Path) -> dict[str, dict[str, Any]]:
    source = json.loads(path.read_text(encoding="utf-8"))
    if source.get("source") != f"{SOURCE_PROJECT}:{SOURCE_DATASET}":
        raise ValueError("Inventory does not match the CMS SynPUF source.")
    tables = source.get("tables")
    if not isinstance(tables, list) or not tables:
        raise ValueError("Source inventory has no table metadata.")
    out = {}
    for table in tables:
        name = table.get("table")
        fields = table.get("schema", {}).get("fields", [])
        if not isinstance(name, str) or not IDENT_RE.fullmatch(name) or not fields:
            raise ValueError("Source inventory contains invalid table metadata.")
        column_names = [field.get("name") for field in fields]
        if (any(not isinstance(column, str) or not IDENT_RE.fullmatch(column)
                for column in column_names)
                or len(column_names) != len(set(column_names))):
            raise ValueError(f"Source inventory contains invalid columns for {name}.")
        rows = table.get("rows")
        if isinstance(rows, str) and rows.isdecimal():
            table["rows"] = int(rows)
        elif not isinstance(rows, int) or isinstance(rows, bool) or rows < 0:
            raise ValueError(f"Source inventory has an invalid row count for {name}.")
        modified = table.get("modified")
        if isinstance(modified, int) and not isinstance(modified, bool):
            table["modified"] = str(modified)
        elif isinstance(modified, str) and modified.isdecimal():
            pass
        else:
            raise ValueError(f"Source inventory has an invalid modified time for {name}.")
        out[name] = table
    if not {"person", "concept_ancestor", "cost"} <= out.keys():
        raise ValueError("Source inventory is missing required OMOP tables.")
    return out


def _qualified(table: str) -> str:
    return f"`{SOURCE_PROJECT}.{SOURCE_DATASET}.{table}`"


def _sample_cte() -> str:
    return ("sample_person AS (SELECT DISTINCT person_id FROM "
            f"{_qualified('person')} WHERE person_id IS NOT NULL "
            "ORDER BY FARM_FINGERPRINT(CAST(person_id AS STRING)), person_id "
            f"LIMIT {DEFAULT_SAMPLE_SIZE})")


def query_for_table(table: str, inventory: dict[str, dict[str, Any]]) -> str:
    if table not in inventory:
        raise ValueError(f"Table is not in the source inventory: {table}.")
    fields = inventory[table]["schema"]["fields"]
    columns = [field["name"] for field in fields]
    if table == "concept_ancestor":
        ids = []
        for name, metadata in inventory.items():
            names = {field["name"] for field in metadata["schema"]["fields"]}
            if "person_id" in names:
                ids.extend(
                    f"SELECT {field['name']} AS concept_id FROM {_qualified(name)} "
                    f"WHERE person_id IN (SELECT person_id FROM sample_person) "
                    f"AND {field['name']} IS NOT NULL"
                    for field in metadata["schema"]["fields"]
                    if field["name"].endswith("_concept_id"))
        if not ids:
            raise ValueError("No concept-id fields found in person-linked tables.")
        return (f"WITH {_sample_cte()}, selected_concept AS (" + " UNION DISTINCT ".join(ids)
                + f") SELECT * FROM {_qualified(table)} AS ca "
                "WHERE ca.descendant_concept_id IN "
                "(SELECT concept_id FROM selected_concept)")
    if table == "cost":
        domain_clauses = []
        for domain, (event_table, event_id) in EVENT_ID_TABLES.items():
            domain_clauses.append(
                f"(UPPER(c.cost_domain_id) = '{domain}' AND c.cost_event_id IN ("
                f"SELECT e.{event_id} FROM {_qualified(event_table)} AS e "
                "WHERE e.person_id IN (SELECT person_id FROM sample_person)))")
        return (f"WITH {_sample_cte()} SELECT c.* FROM {_qualified(table)} AS c WHERE "
                + " OR ".join(domain_clauses))
    if table in PERSON_TABLES or "person_id" in columns:
        query = f"SELECT * FROM {_qualified(table)} WHERE person_id IN (SELECT person_id FROM sample_person)"
        return f"WITH {_sample_cte()} {query}"
    if table in VOCABULARY_TABLES or table in {"care_site", "location", "provider"}:
        return f"SELECT * FROM {_qualified(table)}"
    raise ValueError(f"No inclusion rule is defined for table {table}.")


def _source_fingerprint(inventory: dict[str, dict[str, Any]]) -> str:
    stable = {name: {"modified": table.get("modified"),
                     "rows": table.get("rows"),
                     "schema": table["schema"]}
              for name, table in sorted(inventory.items())}
    return hashlib.sha256(json.dumps(stable, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def _verify_source_snapshot(client, inventory: dict[str, dict[str, Any]]) -> None:
    if not callable(getattr(client, "get_table", None)):
        return
    for name, expected in inventory.items():
        source = client.get_table(f"{SOURCE_PROJECT}.{SOURCE_DATASET}.{name}")
        modified = source.modified
        if modified.tzinfo is None:
            modified = modified.replace(tzinfo=dt.timezone.utc)
        actual_modified = str(round(modified.timestamp() * 1000))
        actual_schema = [(field.name, field.field_type.upper())
                         for field in source.schema]
        expected_schema = [(field["name"], field["type"].upper())
                           for field in expected["schema"]["fields"]]
        if (actual_modified != str(expected.get("modified"))
                or source.num_rows != expected.get("rows")
                or actual_schema != expected_schema):
            raise RuntimeError(f"Source metadata changed since inventory: {name}.")


def _serialize(value: Any) -> str:
    if value is None:
        return NULL_MARKER
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dt.datetime):
        if value.tzinfo is not None:
            value = value.astimezone(dt.timezone.utc)
        return value.isoformat(sep=" ")
    if isinstance(value, (dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, str) and value == NULL_MARKER:
        raise ValueError("Source text collides with the configured CSV null marker.")
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".part")
    if temporary.is_symlink():
        raise ValueError("Refusing to write through a symlink in export directory.")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    os.replace(temporary, path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_type(value: str) -> str:
    value = value.upper()
    return {"INT64": "INTEGER", "FLOAT64": "FLOAT",
            "BOOL": "BOOLEAN"}.get(value, value)


def _write_result(client, sql: str, path: Path, bigquery, table: str,
                  max_bytes_billed: int,
                  expected_columns: list[dict[str, str]],
                  progress=print) -> dict[str, Any]:
    dry_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
    dry_job = client.query(sql, job_config=dry_config)
    estimate = dry_job.total_bytes_processed or 0
    if estimate > max_bytes_billed:
        raise ValueError(f"{table} query estimate exceeds the configured billing cap.")
    progress(f"{table}: dry-run estimate {estimate:,} bytes.")
    job_config = bigquery.QueryJobConfig(
        maximum_bytes_billed=max_bytes_billed,
        use_query_cache=False)
    job = client.query(sql, job_config=job_config)
    progress(f"{table}: BigQuery job {job.job_id} started.")
    result = job.result(page_size=10000)
    schema = list(result.schema)
    actual_columns = [(field.name, _normalize_type(field.field_type)) for field in schema]
    expected = [(field["name"], _normalize_type(field["type"]))
                for field in expected_columns]
    if actual_columns != expected:
        raise ValueError(f"BigQuery result schema does not match source inventory for {table}.")
    temporary = path.with_name(path.name + ".part")
    if path.is_symlink() or temporary.is_symlink():
        raise ValueError("Refusing to write through a symlink in export directory.")
    rows = 0
    with temporary.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            with io.TextIOWrapper(zipped, encoding="utf-8", newline="") as text:
                writer = csv.writer(text, lineterminator="\n")
                writer.writerow([field.name for field in schema])
                for row in result:
                    values = [_serialize(row.get(field.name))
                              for field in result.schema]
                    if len(values) != len(schema):
                        raise ValueError(f"Invalid row width in {table} export.")
                    writer.writerow(values)
                    rows += 1
                    if rows % 100_000 == 0:
                        text.flush()
                        raw.flush()
                        progress(f"{table}: {rows:,} rows written.")
    os.replace(temporary, path)
    return {"row_count": rows, "bytes": path.stat().st_size,
            "sha256": _sha256(path),
            "columns": [{"name": field.name, "type": field.field_type}
                        for field in schema]}


def export(options: ExportOptions, client=None) -> dict[str, Any]:
    inventory = _load_inventory(options.inventory_path)
    if client is None:
        from google.cloud import bigquery
        client = bigquery.Client(project=options.project,
                                 location="US",
                                 credentials=_gcloud_credentials())
    else:
        from google.cloud import bigquery
    _verify_source_snapshot(client, inventory)
    options.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = options.output_dir / MANIFEST_NAME
    fingerprint = _source_fingerprint(inventory)
    base = {"version": 1,
            "source": f"{SOURCE_PROJECT}.{SOURCE_DATASET}",
            "job_project": options.project,
            "person_limit": options.sample_size,
            "selection_sql": SELECTION_SQL,
            "created_at": None,
            "tables": []}
    state_path = options.output_dir / STATE_NAME
    previous = {}
    if state_path.exists():
        try:
            old = json.loads(state_path.read_text(encoding="utf-8"))
            if (old.get("source_snapshot_sha256") == fingerprint
                    and old.get("job_project") == options.project
                    and old.get("max_bytes_billed") == options.max_bytes_billed):
                previous = old.get("tables", {})
        except (OSError, json.JSONDecodeError):
            previous = {}
    state = {"source_snapshot_sha256": fingerprint,
             "job_project": options.project,
             "max_bytes_billed": options.max_bytes_billed,
             "tables": previous}
    _atomic_json(state_path, state)

    table_names = ["person", *sorted(set(inventory) - {"person"})]
    for table in table_names:
        filename = f"{table}.csv.gz"
        destination = options.output_dir / filename
        entry = state["tables"].get(table, {})
        if (destination.is_file() and entry.get("file") == filename
                and (table != "person" or entry.get("row_count") == options.sample_size)
                and entry.get("sha256") == _sha256(destination)):
            continue
        sql = query_for_table(table, inventory)
        metadata = _write_result(client, sql, destination, bigquery, table,
                                 options.max_bytes_billed,
                                 inventory[table]["schema"]["fields"])
        if table == "person" and metadata["row_count"] != options.sample_size:
            raise ValueError(f"Expected {options.sample_size} sampled persons; "
                             f"exported {metadata['row_count']}.")
        metadata.update({"file": filename, "query_sha256": hashlib.sha256(sql.encode()).hexdigest()})
        state["tables"][table] = metadata
        _atomic_json(state_path, state)
    _verify_source_snapshot(client, inventory)
    base["created_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    for table in table_names:
        entry = state["tables"][table]
        base["tables"].append({
            "name": table,
            "columns": [{"name": field["name"], "type": field["type"]}
                        for field in inventory[table]["schema"]["fields"]],
            "file": entry["file"],
            "rows": entry["row_count"],
            "sha256": entry["sha256"],
        })
    _atomic_json(manifest_path, base)
    return base


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=DEFAULT_JOB_PROJECT,
                        help="Authorized BigQuery job/billing project id")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-bytes-billed", type=int,
                        default=DEFAULT_MAX_BYTES_BILLED)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    args = parser.parse_args(argv)
    result = export(ExportOptions(project=args.project,
                                  output_dir=args.output_dir,
                                  max_bytes_billed=args.max_bytes_billed,
                                  inventory_path=args.inventory))
    print(f"Export complete: {len(result['tables'])} tables.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
