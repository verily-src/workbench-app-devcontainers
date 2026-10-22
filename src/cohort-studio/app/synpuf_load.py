"""Import a verified 100,000-person CMS SynPUF BigQuery export into Aurora."""

import argparse
import csv
import gzip
import hashlib
import io
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

TARGET_RESOURCE = "cohort-dash-db-20261005"
TARGET_SCHEMA = "cms_synpuf_100k"
SOURCE = "bigquery-public-data.cms_synthetic_patient_data_omop"
JOB_PROJECT = "vwb-dev-affable-olive-9580"
PERSON_LIMIT = 100_000
MAX_MANIFEST_BYTES = 10 * 1024 * 1024
MAX_CSV_FIELD_CHARS = 16 * 1024 * 1024
SCHEMA_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
IDENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")

SQL_TYPES = {
    "INTEGER": "BIGINT", "INT64": "BIGINT",
    "FLOAT": "DOUBLE PRECISION", "FLOAT64": "DOUBLE PRECISION",
    "NUMERIC": "NUMERIC", "BIGNUMERIC": "NUMERIC",
    "STRING": "TEXT", "DATE": "DATE",
    "DATETIME": "TIMESTAMP WITHOUT TIME ZONE",
    "TIMESTAMP": "TIMESTAMP WITH TIME ZONE",
    "BOOLEAN": "BOOLEAN", "BOOL": "BOOLEAN",
}
EVENT_TABLES = {
    "condition_occurrence", "drug_exposure", "procedure_occurrence",
    "measurement", "observation", "device_exposure", "death",
}


class ExportColumn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: StrictStr = Field(min_length=1, max_length=63)
    type: StrictStr = Field(min_length=1, max_length=32)


class ExportTable(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: StrictStr = Field(min_length=1, max_length=63)
    columns: list[ExportColumn] = Field(min_length=1, max_length=512)
    file: StrictStr = Field(min_length=1, max_length=128)
    rows: StrictInt = Field(ge=0)
    sha256: StrictStr

    @model_validator(mode="after")
    def validate_table(self):
        if not IDENT_RE.fullmatch(self.name):
            raise ValueError(f"Invalid table name: {self.name!r}.")
        if self.file != f"{self.name}.csv.gz":
            raise ValueError(f"Expected {self.name}.csv.gz as the table file.")
        names = [column.name for column in self.columns]
        if any(not IDENT_RE.fullmatch(name) for name in names):
            raise ValueError(f"Invalid column name in table {self.name}.")
        if len(names) != len(set(names)):
            raise ValueError(f"Duplicate source column in table {self.name}.")
        if any(column.type.upper() not in SQL_TYPES for column in self.columns):
            raise ValueError(f"Unsupported BigQuery type in table {self.name}.")
        if not SHA_RE.fullmatch(self.sha256):
            raise ValueError(f"Invalid SHA-256 digest for table {self.name}.")
        if self.name == "procedure_occurrence":
            source_names = set(names)
            if "procedure_dat" in source_names and "procedure_date" in source_names:
                raise ValueError("procedure_occurrence has both procedure_dat and procedure_date.")
            if "procedure_dat" in source_names and next(
                    c.type.upper() for c in self.columns if c.name == "procedure_dat") != "DATE":
                raise ValueError("procedure_dat must have BigQuery type DATE.")
        return self


class ExportManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1]
    source: StrictStr
    job_project: StrictStr
    person_limit: StrictInt
    selection_sql: StrictStr = Field(min_length=1, max_length=100_000)
    created_at: datetime
    tables: list[ExportTable] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_manifest(self):
        if self.source != SOURCE or self.job_project != JOB_PROJECT:
            raise ValueError("Manifest source or BigQuery job project does not match the approved export.")
        if self.person_limit != PERSON_LIMIT:
            raise ValueError("Manifest must describe the authorized 100,000-person selection.")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() != timezone.utc.utcoffset(self.created_at):
            raise ValueError("Manifest creation time must be UTC.")
        names = [table.name for table in self.tables]
        files = [table.file for table in self.tables]
        if len(names) != len(set(names)) or len(files) != len(set(files)):
            raise ValueError("Manifest has duplicate table names or files.")
        required = {"person", "observation_period", "concept", "concept_ancestor"}
        missing = required - set(names)
        if missing:
            raise ValueError("Manifest is missing required table(s): " + ", ".join(sorted(missing)))
        if not (EVENT_TABLES & set(names)):
            raise ValueError("Manifest must include at least one clinical event table.")
        person = next(table for table in self.tables if table.name == "person")
        if person.rows != PERSON_LIMIT or "person_id" not in {c.name for c in person.columns}:
            raise ValueError("Manifest person table must contain exactly 100,000 people and person_id.")
        for table in self.tables:
            columns = {column.name for column in table.columns}
            if table.name == "observation_period" and not {"person_id", "observation_period_start_date",
                                                               "observation_period_end_date"} <= columns:
                raise ValueError("observation_period is missing person or period columns.")
            if table.name in EVENT_TABLES and "person_id" not in columns:
                raise ValueError(f"Clinical table {table.name} is missing person_id.")
        return self


class _DigestReader:
    def __init__(self, stream):
        self.stream = stream
        self.digest = hashlib.sha256()

    def read(self, size=-1):
        chunk = self.stream.read(size)
        self.digest.update(chunk)
        return chunk

    def readinto(self, buffer):
        chunk = self.read(len(buffer))
        buffer[:len(chunk)] = chunk
        return len(chunk)

    def readable(self):
        return True


def _q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _target_column(table: str, column: str) -> str:
    if table == "procedure_occurrence" and column == "procedure_dat":
        return "procedure_date"
    return column


def _manifest(source_dir: Path) -> tuple[ExportManifest, bytes, str]:
    directory = source_dir.resolve(strict=True)
    if not directory.is_dir():
        raise ValueError("Source export path must be a directory.")
    manifest_path = directory / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("Source directory must contain a regular manifest.json file.")
    raw = manifest_path.read_bytes()
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError("Manifest is too large.")
    manifest = ExportManifest.model_validate_json(raw)
    manifest_hash = hashlib.sha256(raw).hexdigest()
    for table in manifest.tables:
        path = directory / table.file
        if path.is_symlink() or path.parent.resolve() != directory or not path.is_file():
            raise ValueError(f"Missing or unsafe export file: {table.file}.")
        _verify_file(path, table)
    return manifest, raw, manifest_hash


def _verify_file(path: Path, table: ExportTable) -> None:
    prior_limit = csv.field_size_limit()
    csv.field_size_limit(MAX_CSV_FIELD_CHARS)
    try:
        with path.open("rb") as raw:
            digest_reader = _DigestReader(raw)
            with gzip.GzipFile(fileobj=digest_reader, mode="rb") as compressed:
                with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as stream:
                    reader = csv.reader(stream, strict=True)
                    try:
                        header = next(reader)
                    except StopIteration as e:
                        raise ValueError(f"Empty CSV file: {table.file}.") from e
                    expected = [column.name for column in table.columns]
                    if header != expected:
                        raise ValueError(f"CSV header does not match manifest for {table.name}.")
                    count = 0
                    for row in reader:
                        if len(row) != len(expected):
                            raise ValueError(
                                f"Wrong CSV field count in {table.file}, record {count + 2}.")
                        count += 1
                    if count != table.rows:
                        raise ValueError(
                            f"Row count mismatch for {table.name}: manifest {table.rows}, file {count}.")
            for chunk in iter(lambda: digest_reader.read(1024 * 1024), b""):
                pass
            if digest_reader.digest.hexdigest() != table.sha256:
                raise ValueError(f"SHA-256 mismatch for {table.file}.")
    except (gzip.BadGzipFile, EOFError, UnicodeDecodeError, csv.Error) as e:
        raise ValueError(f"Could not validate {table.file}: {e}.") from e
    finally:
        csv.field_size_limit(prior_limit)


def validate_export(source_dir: Path) -> tuple[ExportManifest, bytes, str]:
    return _manifest(Path(source_dir))


def _create_tables(cur, schema: str, manifest: ExportManifest):
    s = _q(schema)
    for table in manifest.tables:
        columns = []
        targets = []
        for column in table.columns:
            target_name = _target_column(table.name, column.name)
            if target_name in targets:
                raise ValueError(f"Column mapping creates a duplicate in {table.name}.")
            targets.append(target_name)
            columns.append(f"{_q(target_name)} {SQL_TYPES[column.type.upper()]}")
        cur.execute(f"CREATE TABLE {s}.{_q(table.name)} ({', '.join(columns)})")
    cur.execute(
        f"CREATE TABLE {s}._synpuf_import_metadata ("
        "manifest_sha256 text PRIMARY KEY, imported_at timestamptz NOT NULL, "
        "manifest jsonb NOT NULL, table_counts jsonb NOT NULL, "
        "column_mappings jsonb NOT NULL)")


def _copy_table(cur, schema: str, source_dir: Path, table: ExportTable) -> None:
    target_columns = [_target_column(table.name, column.name) for column in table.columns]
    columns = ", ".join(_q(name) for name in target_columns)
    statement = (f"COPY {_q(schema)}.{_q(table.name)} ({columns}) FROM STDIN "
                 "WITH (FORMAT CSV, HEADER TRUE, NULL E'\\\\N', ENCODING 'UTF8')")
    with (source_dir / table.file).open("rb") as raw:
        digest_reader = _DigestReader(raw)
        with gzip.GzipFile(fileobj=digest_reader, mode="rb") as stream:
            with cur.copy(statement) as copy:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    copy.write(chunk)
        for chunk in iter(lambda: digest_reader.read(1024 * 1024), b""):
            pass
    if digest_reader.digest.hexdigest() != table.sha256:
        raise ValueError(f"SHA-256 changed while loading {table.file}; import rolled back.")


def _index(cur, schema: str, table: str, columns: list[str]) -> None:
    token = hashlib.sha256((table + ":" + ":".join(columns)).encode()).hexdigest()[:10]
    name = f"syn_{table[:36]}_{token}"
    cur.execute(f"CREATE INDEX {_q(name)} ON {_q(schema)}.{_q(table)} "
                f"({', '.join(_q(c) for c in columns)})")


def _indexes_and_relations(cur, schema: str, manifest: ExportManifest):
    s = _q(schema)
    person_table = next(table for table in manifest.tables if table.name == "person")
    person_cols = {column.name for column in person_table.columns}
    _index(cur, schema, "person", ["person_id"])
    for table in manifest.tables:
        names = {_target_column(table.name, column.name) for column in table.columns}
        if table.name != "person" and "person_id" in names:
            _index(cur, schema, table.name, ["person_id"])
            check = (f"SELECT EXISTS (SELECT 1 FROM {s}.{_q(table.name)} AS event "
                     f"LEFT JOIN {s}.person AS person ON event.person_id = person.person_id "
                     "WHERE event.person_id IS NULL OR person.person_id IS NULL LIMIT 1)")
            if cur.execute(check).fetchone()[0]:
                raise ValueError(f"{table.name} contains person IDs outside the selected people.")
        for name in sorted(names):
            if table.name != "concept_ancestor" and name.endswith("_concept_id"):
                _index(cur, schema, table.name, [name])
            elif (table.name in EVENT_TABLES | {"observation_period"}
                  and name.endswith(("_date", "_datetime"))):
                _index(cur, schema, table.name, [name])
        if table.name == "concept" and "concept_id" in names:
            _index(cur, schema, table.name, ["concept_id"])
        if table.name == "concept_relationship":
            for name in ("concept_id_1", "concept_id_2", "relationship_id"):
                if name in names:
                    _index(cur, schema, table.name, [name])
    if "concept_ancestor" in {t.name for t in manifest.tables}:
        _index(cur, schema, "concept_ancestor", ["ancestor_concept_id"])
        _index(cur, schema, "concept_ancestor", ["descendant_concept_id"])
    if not {"person_id"} <= person_cols:
        raise ValueError("Person table is missing person_id.")
    person_count = cur.execute(f"SELECT count(*) FROM {s}.person").fetchone()[0]
    distinct_count = cur.execute(
        f"SELECT count(DISTINCT person_id) FROM {s}.person").fetchone()[0]
    if person_count != PERSON_LIMIT or distinct_count != PERSON_LIMIT:
        raise ValueError("Imported person table must contain 100,000 distinct person IDs.")


def load(conn, source_dir: Path, schema: str = TARGET_SCHEMA, log=print,
         _validated=None) -> dict[str, int]:
    if not SCHEMA_RE.fullmatch(schema):
        raise ValueError(f"Invalid target schema name: {schema!r}.")
    directory = Path(source_dir).resolve(strict=True)
    manifest, raw_manifest, manifest_hash = _validated or _manifest(directory)
    counts = {}
    mappings = {
        table.name: {column.name: _target_column(table.name, column.name)
                     for column in table.columns
                     if _target_column(table.name, column.name) != column.name}
        for table in manifest.tables
    }
    mappings = {table: mapping for table, mapping in mappings.items() if mapping}
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name = %s",
                        (schema,))
            if cur.fetchone():
                raise ValueError(f"Target schema {schema} already exists; refusing to replace it.")
            cur.execute(f"CREATE SCHEMA {_q(schema)}")
            _create_tables(cur, schema, manifest)
            for table in manifest.tables:
                _copy_table(cur, schema, directory, table)
                counts[table.name] = cur.execute(
                    f"SELECT count(*) FROM {_q(schema)}.{_q(table.name)}").fetchone()[0]
                if counts[table.name] != table.rows:
                    raise ValueError(f"Loaded row count mismatch for {table.name}.")
                log(f"Loaded {table.name}: {counts[table.name]:,} rows")
            _indexes_and_relations(cur, schema, manifest)
            for table in manifest.tables:
                cur.execute(f"ANALYZE {_q(schema)}.{_q(table.name)}")
            cur.execute(
                f"INSERT INTO {_q(schema)}._synpuf_import_metadata "
                "(manifest_sha256, imported_at, manifest, table_counts, column_mappings) "
                "VALUES (%s, now(), %s::jsonb, %s::jsonb, %s::jsonb)",
                (manifest_hash, json.dumps({**manifest.model_dump(mode="json"),
                                            "raw_manifest_sha256": manifest_hash}),
                 json.dumps(counts), json.dumps(mappings)))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return counts


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resource-id", default=TARGET_RESOURCE, choices=[TARGET_RESOURCE])
    parser.add_argument("--source-dir", required=True,
                        help="directory containing manifest.json and table CSV.GZ files")
    args = parser.parse_args(argv)
    try:
        validated = validate_export(Path(args.source_dir))
        import db
        conn = db.get_engine_for_resource(args.resource_id).raw_connection()
        try:
            counts = load(conn, Path(args.source_dir), _validated=validated)
        finally:
            conn.close()
    except Exception as e:
        parser.error(str(e))
    width = max(map(len, counts))
    for table, count in counts.items():
        print(f"{table:<{width}}  {count:>12,}")
    print(f"{sum(counts.values()):,} total rows committed to {TARGET_SCHEMA}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    raise SystemExit(main())
