"""DuckDB engine: SQL over Parquet/CSV files in workspace S3 folders.

This is the Athena-shaped capability inside the Workbench credential
model: for each read we export concrete temporary credentials from the
per-resource AWS profile (which `wb workspace configure-aws` backs with
credential_process) and hand them to a DuckDB S3 secret, so files are
read straight from S3 with no cluster and no download step. Also the
bridge until aurora_analytics (pg 17.11+) is available on the cluster.
"""

import configparser
import json
import logging
import os
import re
import shlex
import subprocess

import duckdb
import pandas as pd

import db
from cache import ttl_cache

logger = logging.getLogger(__name__)

DATA_SUFFIXES = (".parquet", ".csv", ".tsv", ".txt")
_SAFE_KEY = re.compile(r"^[A-Za-z0-9._\-/ ()+=]+$")
# Workspace S3 buckets live in the Aurora cluster's region.
DEFAULT_REGION = os.environ.get("STUDIO_S3_REGION", "us-east-1")


MAX_LISTING = 500


def parse_s3_ls(output: str, prefix: str = "") -> list[str]:
    """File keys from `aws s3 ls [--recursive]` lines: 'date time size key'.

    With --recursive the key is the full path from the bucket root;
    passing the folder's own prefix strips it so the UI shows paths
    relative to the workspace folder (including subfolders).
    """
    files = []
    for line in output.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and parts[0] != "PRE" and not line.rstrip().endswith("/"):
            key = parts[3]
            if prefix and key.startswith(prefix):
                key = key[len(prefix):].lstrip("/")
            files.append(key)
    return [f for f in files if f.lower().endswith(DATA_SUFFIXES)][:MAX_LISTING]


@ttl_cache(ttl=300)
def list_s3_files(resource_id: str) -> list[str]:
    """Recursive listing: workspace folders often nest files in subfolders."""
    uri = db.resolve_s3_uri(resource_id)
    # s3://bucket/some/prefix -> "some/prefix" (what --recursive keys start with)
    prefix = uri.removeprefix("s3://").partition("/")[2]
    result = subprocess.run(
        ["aws", "s3", "ls", uri + "/", "--recursive", "--profile", resource_id],
        capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        # Surface aws's own stderr — "exit status 255" alone is useless.
        detail = (result.stderr or result.stdout or "").strip().split("\n")[-1]
        raise RuntimeError(
            f"aws s3 ls failed for {resource_id}: {detail or 'exit 255'}")
    files = parse_s3_ls(result.stdout, prefix=prefix)
    logger.info("Found %d data files in %s", len(files), uri)
    return files


def _run_credential_process(profile: str) -> dict:
    """Execute the profile's credential_process directly.

    This is what the aws CLI runs under the hood for the profile, so it
    works whenever `aws s3 ls --profile X` works — and doesn't depend on
    the CLI version. The process emits the standard JSON contract
    {Version, AccessKeyId, SecretAccessKey, SessionToken, Expiration}.
    """
    config_file = os.environ.get("AWS_CONFIG_FILE")
    if not config_file or not os.path.exists(config_file):
        raise RuntimeError("AWS_CONFIG_FILE is not set — profiles not "
                           "configured yet.")
    parser = configparser.RawConfigParser()
    parser.read(config_file)
    section = (f"profile {profile}" if parser.has_section(f"profile {profile}")
               else profile)
    if not parser.has_section(section) \
            or not parser.has_option(section, "credential_process"):
        raise RuntimeError(f"profile {profile} has no credential_process")
    cmd = shlex.split(parser.get(section, "credential_process"))
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        detail = (out.stderr or out.stdout or "").strip().split("\n")[-1]
        raise RuntimeError(f"credential_process failed: {detail}")
    return json.loads(out.stdout)


def _resolve_credentials(profile: str) -> dict:
    """Concrete temporary credentials for a wb-generated AWS profile.

    DuckDB's credential_chain provider does NOT run credential_process,
    so we resolve the keys ourselves and hand DuckDB a PROVIDER config
    secret. Prefer `aws configure export-credentials` (CLI >= 2.9); fall
    back to running the profile's credential_process directly on older
    CLIs (where that subcommand prints usage and exits non-zero).
    """
    out = subprocess.run(
        ["aws", "configure", "export-credentials",
         "--profile", profile, "--format", "json"],
        capture_output=True, text=True, timeout=60)
    if out.returncode == 0 and out.stdout.strip().startswith("{"):
        return json.loads(out.stdout)
    return _run_credential_process(profile)


def _connect(profile: str | None, region: str = DEFAULT_REGION):
    con = duckdb.connect()
    if profile:
        creds = _resolve_credentials(profile)

        def lit(v: str) -> str:  # escape single quotes for the SQL literal
            return v.replace("'", "''")

        parts = ["TYPE s3", "PROVIDER config",
                 f"KEY_ID '{lit(creds['AccessKeyId'])}'",
                 f"SECRET '{lit(creds['SecretAccessKey'])}'",
                 f"REGION '{lit(region)}'"]
        if creds.get("SessionToken"):
            parts.append(f"SESSION_TOKEN '{lit(creds['SessionToken'])}'")
        con.execute("INSTALL httpfs; LOAD httpfs;")
        con.execute(f"CREATE OR REPLACE SECRET wb ({', '.join(parts)})")
    return con


def _reader_sql(uri: str) -> str:
    if not _SAFE_KEY.match(uri.replace("s3://", "")):
        raise ValueError(f"Unsupported characters in path: {uri!r}")
    if uri.lower().endswith(".parquet"):
        return f"read_parquet('{uri}')"
    return f"read_csv_auto('{uri}')"


def fetch_file(uri: str, cap: int, profile: str | None = None,
               region: str = DEFAULT_REGION) -> pd.DataFrame:
    """Read a Parquet/CSV file (s3:// or local path) into a DataFrame."""
    con = _connect(profile, region)
    try:
        query = f"SELECT * FROM {_reader_sql(uri)} LIMIT {int(cap)}"
        return con.execute(query).df()
    finally:
        con.close()


@ttl_cache(ttl=600, maxsize=4)
def fetch_s3_file(resource_id: str, filename: str, cap: int) -> pd.DataFrame:
    """Cached capped read. The DataFrame is shared — do not mutate it."""
    uri = f"{db.resolve_s3_uri(resource_id)}/{filename}"
    return fetch_file(uri, cap, profile=resource_id)
