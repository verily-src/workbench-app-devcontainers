"""Load OHDSI Eunomia GiBleed (or any CDM CSV export) into Postgres as an
OMOP CDM v5.4 schema.

    python -m omop_load --url postgresql://user@host/db [--schema cdm] [--replace]
    python -m omop_load --resource-id <aurora resource>   # Workbench workspace

The default source is Eunomia's GiBleed_5.5.zip (~2.7k Synthea persons),
downloaded once to ~/.cache/cohort-studio/eunomia. Its columns are a
superset of 5.4, so it loads into the official 5.4 DDL (omop_ddl/) with
the 5.5-only columns dropped; 5.3 exports are renamed to 5.4 names.
--source takes a local zip or a directory of <table>.csv[.gz] files.
Tables load in one transaction via COPY, then get primary keys, indexes
on person_id and the domain concept columns, and ANALYZE. Vocabulary
tables go into the same schema.
"""

import argparse
import csv
import gzip
import io
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator

EUNOMIA_URL = ("https://github.com/OHDSI/EunomiaDatasets/raw/main/datasets/"
               "GiBleed/GiBleed_5.5.zip")
CACHE_DIR = Path(os.environ.get("STUDIO_EUNOMIA_CACHE",
                                "~/.cache/cohort-studio/eunomia")).expanduser()
DDL = Path(__file__).parent / "omop_ddl" / "OMOPCDM_postgresql_5.4_ddl.sql"
CDM_VERSION = "v5.4"
CDM_VERSION_CONCEPT_ID = 756265  # "OMOP CDM Version 5.4.0"
# CDM 5.3 column names renamed in 5.4.
RENAMES_53 = {
    "admitting_source_concept_id": "admitted_from_concept_id",
    "admitting_source_value": "admitted_from_source_value",
    "discharge_to_concept_id": "discharged_to_concept_id",
    "discharge_to_source_value": "discharged_to_source_value",
    "visit_detail_parent_id": "parent_visit_detail_id",
}
_SCHEMA = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_TABLE = re.compile(r"CREATE TABLE @cdmDatabaseSchema\.(\w+) \((.*?)\);", re.S)
_COLUMN = re.compile(r'^\s*"?(\w+)"?\s+(.+?)\s+(NOT NULL|NULL)\s*,?\s*$')
S3_DOWNLOAD_TIMEOUT = 3600


class S3Source(BaseModel):
    """A Workbench S3 folder and a relative ZIP key or CSV prefix."""

    model_config = ConfigDict(extra="forbid", strict=True)

    resource_id: str
    path: str

    @field_validator("resource_id")
    @classmethod
    def resource_id_is_set(cls, value: str) -> str:
        if not value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError("S3 resource id must be a non-empty resource id.")
        return value

    @field_validator("path")
    @classmethod
    def path_is_relative(cls, value: str) -> str:
        value = value.strip()
        parts = value.rstrip("/").split("/")
        if (not value or value.startswith("/") or "\\" in value
                or value.startswith("s3://") or any(p in (".", "..") for p in parts)
                or any(not p for p in parts)
                or any(ord(c) < 32 for c in value)):
            raise ValueError("S3 path must be a relative ZIP key or CSV prefix.")
        if value.rstrip("/") == "":
            raise ValueError("S3 path must name a ZIP key or CSV prefix.")
        return value


def _q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def parse_ddl(path: Path = DDL) -> dict[str, dict]:
    """table -> {sql, columns: [(name, not_null)]} from the OHDSI DDL."""
    out = {}
    for table, body in _TABLE.findall(path.read_text()):
        cols = []
        for line in body.splitlines():
            m = _COLUMN.match(line)
            if m:
                cols.append((m[1], m[3] == "NOT NULL"))
        out[table] = {"sql": f"CREATE TABLE @cdmDatabaseSchema.{table} ({body});",
                      "columns": cols}
    return out


def fetch(url: str = EUNOMIA_URL, cache_dir: Path = CACHE_DIR) -> Path:
    """The zip at url, downloaded once into cache_dir."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / url.rsplit("/", 1)[-1]
    if not target.exists():
        print(f"Downloading {url} -> {target}")
        tmp = target.with_suffix(".part")
        urllib.request.urlretrieve(url, tmp)
        tmp.rename(target)
    return target


def open_sources(source: Path) -> dict:
    """table -> zero-arg opener of a text stream, from a zip or CSV tree.

    Nested exports are supported. Two files with the same table basename are
    rejected instead of silently choosing one.
    """
    out = {}

    def add(table: str, opener, source_name: str):
        if table in out:
            raise ValueError(f"Duplicate CSV source for OMOP table {table!r}: "
                             f"{source_name}.")
        out[table] = opener

    if source.is_dir():
        for f in sorted(source.rglob("*")):
            if not f.is_file():
                continue
            name = f.name.lower()
            if name.endswith(".csv.gz"):
                add(name[:-7], lambda f=f: gzip.open(
                    f, "rt", encoding="utf-8-sig", newline=""), str(f.relative_to(source)))
            elif name.endswith(".csv"):
                add(name[:-4], lambda f=f: open(
                    f, encoding="utf-8-sig", newline=""), str(f.relative_to(source)))
        return out
    zf = zipfile.ZipFile(source)
    for info in zf.infolist():
        name = info.filename
        if "__MACOSX" in name or name.endswith("/"):
            continue
        lowered = name.lower()
        if lowered.endswith(".csv.gz"):
            table = Path(name[:-7]).name.lower()

            def open_gzip(n=name):
                return io.TextIOWrapper(gzip.GzipFile(fileobj=zf.open(n)),
                                        encoding="utf-8-sig", newline="")
            add(table, open_gzip, name)
        elif lowered.endswith(".csv"):
            table = Path(name[:-4]).name.lower()
            add(table, lambda n=name: io.TextIOWrapper(
                zf.open(n), encoding="utf-8-sig", newline=""), name)
    return out


def _validate_sources(sources: dict, ddl: dict[str, dict]):
    """Check that input is a recognizable OMOP export before DDL changes."""
    import omop

    missing = {"person", "observation_period", "concept", "concept_ancestor"} - set(sources)
    event_tables = {domain["table"] for domain in omop.DOMAINS.values()}
    if not (event_tables & set(sources)):
        missing.add("at least one clinical event table")
    if missing:
        raise ValueError("Source is not a recognizable OMOP CDM export; missing "
                         + ", ".join(sorted(missing)) + ".")

    headers: dict[str, set[str]] = {}
    for table, opener in sources.items():
        if table not in ddl:
            continue
        try:
            with opener() as stream:
                row = next(csv.reader(stream))
        except (OSError, EOFError, StopIteration, zipfile.BadZipFile) as e:
            raise ValueError(f"Could not read the {table} CSV header: {e}.") from e
        header = [RENAMES_53.get(c.strip().lower(), c.strip().lower()) for c in row]
        if not header or any(not h for h in header) or len(header) != len(set(header)):
            raise ValueError(f"The {table} CSV has an empty or duplicate column name.")
        headers[table] = set(header)

    required_columns = {
        "person": {"person_id"},
        "observation_period": {"person_id", "observation_period_start_date",
                               "observation_period_end_date"},
        "concept": {"concept_id", "concept_name", "domain_id"},
        "concept_ancestor": {"ancestor_concept_id", "descendant_concept_id"},
    }
    for table, columns in required_columns.items():
        missing_columns = columns - headers.get(table, set())
        if missing_columns:
            raise ValueError(f"The {table} CSV is missing required OMOP column(s): "
                             + ", ".join(sorted(missing_columns)) + ".")
    event_columns = {domain["table"]: {"person_id", domain["concept"], domain["date"]}
                     for domain in omop.DOMAINS.values()}
    valid_event = any(columns <= headers.get(table, set())
                      for table, columns in event_columns.items())
    if not valid_event:
        raise ValueError("No clinical event CSV has the required person, concept, "
                         "and event date columns.")


def download_s3_source(resource_id: str, path: str, destination: Path) -> Path:
    """Download one ZIP object or all CSV files under a relative S3 prefix."""
    import db

    source = S3Source(resource_id=resource_id, path=path)
    db.configure_aws_profiles()
    base = db.resolve_s3_uri(source.resource_id).rstrip("/")
    relative = source.path.strip("/")
    is_zip = relative.lower().endswith(".zip")
    uri = f"{base}/{relative}" + ("" if is_zip else "/")
    local = destination / (Path(relative).name if is_zip else "csv-source")
    local.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["aws", "s3", "cp", uri, str(local), "--profile", source.resource_id,
           "--only-show-errors"]
    if not is_zip:
        local.mkdir(parents=True, exist_ok=True)
        cmd.extend(["--recursive", "--exclude", "*", "--include", "*.[cC][sS][vV]",
                    "--include", "*.[cC][sS][vV].[gG][zZ]"])
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=S3_DOWNLOAD_TIMEOUT)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"S3 source download timed out after "
                           f"{S3_DOWNLOAD_TIMEOUT} seconds.") from e
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip().split("\n")[-1]
        raise RuntimeError(f"S3 source download failed: {detail or 'aws exited with an error'}")
    if is_zip and not local.is_file():
        raise RuntimeError("S3 ZIP download completed but the local file is missing.")
    return local


def _copy(cur, schema: str, table: str, stream, ddl_cols: dict[str, bool]) -> list[str]:
    """COPY the CSV columns the DDL knows; returns the dropped ones."""
    reader = csv.reader(stream)
    raw_header = next(reader)
    header = [RENAMES_53.get(h.strip().lower(), h.strip().lower()) for h in raw_header]
    keep = [i for i, h in enumerate(header) if h in ddl_cols]
    cols = ", ".join(_q(header[i]) for i in keep)
    with cur.copy(f"COPY {_q(schema)}.{_q(table)} ({cols}) FROM STDIN") as cp:
        for row in reader:
            if len(row) != len(header):
                raise ValueError(f"{table} CSV line {reader.line_num}: expected "
                                 f"{len(header)} columns, got {len(row)}.")
            cp.write_row([row[i] if row[i] != "" else None for i in keep])
    return [h for h in header if h not in ddl_cols]


def _primary_key(cur, t: str, cols: str, log) -> bool:
    """Some exports repeat ids (GiBleed_5.3 drug_exposure); those tables
    get a plain index instead."""
    import psycopg
    try:
        with cur.connection.transaction():
            cur.execute(f"ALTER TABLE {t} ADD PRIMARY KEY ({cols})")
        return True
    except psycopg.errors.UniqueViolation:
        log(f"  {t}: duplicate ({cols}), indexed without a primary key")
        cur.execute(f"CREATE INDEX ON {t} ({cols})")
        return False


def _keys_and_indexes(cur, schema: str, tables: dict[str, list[str]], log=print):
    import omop
    concept_cols = {d["table"]: d["concept"] for d in omop.DOMAINS.values()}
    s = _q(schema)
    for table, cols in tables.items():
        t = f"{s}.{_q(table)}"
        if table == "concept_ancestor":
            _primary_key(cur, t, "ancestor_concept_id, descendant_concept_id", log)
            cur.execute(f"CREATE INDEX ON {t} (descendant_concept_id)")
        elif cols[0] == f"{table}_id":
            _primary_key(cur, t, _q(cols[0]), log)
        if "person_id" in cols and table != "person":
            cur.execute(f"CREATE INDEX ON {t} (person_id)")
        if table in concept_cols:
            cur.execute(f"CREATE INDEX ON {t} ({_q(concept_cols[table])})")
        if table == "concept":
            cur.execute(f"CREATE INDEX ON {t} (concept_code)")


def load(conn, source: Path, schema: str = "cdm", replace: bool = False,
         log=print) -> dict[str, int]:
    """Create and fill `schema` on a psycopg connection; returns row counts.
    Without replace, an existing CDM in the schema is left as is."""
    if not _SCHEMA.match(schema):
        raise ValueError(f"Invalid schema name {schema!r}.")
    s = _q(schema)
    ddl = parse_ddl()
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = %s AND table_name = 'person'", (schema,))
        if cur.fetchone() and not replace:
            log(f"Schema {schema} already has a CDM; use --replace to reload.")
            cur.execute("SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = %s", (schema,))
            present = {r[0] for r in cur.fetchall()}
            return _counts(cur, schema, [t for t in ddl if t in present])
        sources = open_sources(source)
        _validate_sources(sources, ddl)
        if replace:
            cur.execute(f"DROP SCHEMA IF EXISTS {s} CASCADE")
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {s}")
        for spec in ddl.values():
            cur.execute(spec["sql"].replace("@cdmDatabaseSchema", s))
        for table in sorted(set(sources) - set(ddl)):
            log(f"  skipped {table}: not a CDM 5.4 table")
        for table in sorted(set(sources) & set(ddl)):
            ddl_cols = dict(ddl[table]["columns"])
            with sources[table]() as stream:
                header = {RENAMES_53.get(h.strip().lower(), h.strip().lower())
                          for h in next(csv.reader(stream))}
            for col, not_null in ddl_cols.items():
                if not_null and col not in header:
                    log(f"  {table}: source omits NOT NULL column {col}; "
                        "making the column nullable")
                    cur.execute(f"ALTER TABLE {s}.{_q(table)} "
                                f"ALTER COLUMN {_q(col)} DROP NOT NULL")
            with sources[table]() as stream:
                dropped = _copy(cur, schema, table, stream, ddl_cols)
            if dropped:
                log(f"  {table}: dropped non-5.4 column(s) {', '.join(dropped)}")
        cur.execute(f"UPDATE {s}.cdm_source SET cdm_version = %s, "
                    "cdm_version_concept_id = %s", (CDM_VERSION, CDM_VERSION_CONCEPT_ID))
        _keys_and_indexes(cur, schema, {t: [c for c, _ in d["columns"]]
                                        for t, d in ddl.items()}, log)
        for table in ddl:
            cur.execute(f"ANALYZE {s}.{_q(table)}")
        counts = _counts(cur, schema, list(ddl))
    conn.commit()
    return counts


def _counts(cur, schema: str, tables: list[str]) -> dict[str, int]:
    out = {}
    for t in tables:
        cur.execute(f"SELECT count(*) FROM {_q(schema)}.{_q(t)}")
        out[t] = cur.fetchone()[0]
    return out


def _connect(args):
    if args.url:
        import psycopg
        return psycopg.connect(args.url)
    import db
    # Keep SQLAlchemy's pool proxy checked out until the caller closes it.
    return db.get_engine_for_resource(args.resource_id).raw_connection()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    target = ap.add_mutually_exclusive_group(required=True)
    target.add_argument("--url", help="postgresql:// connection string")
    target.add_argument("--resource-id", help="Workbench Aurora resource id")
    ap.add_argument("--schema", default="cdm")
    source = ap.add_mutually_exclusive_group()
    source.add_argument("--source", help="local zip or CSV directory")
    source.add_argument("--s3-resource-id", help="Workbench S3 folder resource id")
    ap.add_argument("--s3-path", help="relative ZIP key or CSV prefix in that S3 folder")
    ap.add_argument("--cache-dir", default=str(CACHE_DIR))
    ap.add_argument("--replace", action="store_true", help="drop the schema first")
    args = ap.parse_args(argv)
    if ((args.s3_resource_id is None) != (args.s3_path is None)):
        ap.error("--s3-resource-id and --s3-path must be used together")
    if args.s3_resource_id is not None:
        try:
            s3_source = S3Source(resource_id=args.s3_resource_id, path=args.s3_path)
        except ValueError as e:
            ap.error(str(e))
        # Keep the downloaded source alive only for this import.
        with tempfile.TemporaryDirectory(prefix="omop-s3-") as temp_dir:
            try:
                local_source = download_s3_source(
                    s3_source.resource_id, s3_source.path, Path(temp_dir))
                conn = _connect(args)
                try:
                    counts = load(conn, local_source, args.schema, replace=args.replace)
                finally:
                    conn.close()
            except Exception as e:
                ap.error(str(e))
    else:
        local_source = (Path(args.source) if args.source
                        else fetch(cache_dir=Path(args.cache_dir)))
        conn = _connect(args)
        try:
            counts = load(conn, local_source, args.schema, replace=args.replace)
        finally:
            conn.close()
    width = max(map(len, counts))
    for table, n in counts.items():
        if n:
            print(f"{table:<{width}}  {n:>9,}")
    print(f"{sum(1 for n in counts.values() if n)} non-empty of {len(counts)} tables "
          f"in schema {args.schema}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    sys.exit(main())
