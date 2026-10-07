"""DuckDB engine: SQL over Parquet/CSV files in workspace S3 folders.

This is the Athena-shaped capability inside the Workbench credential
model: DuckDB's credential_chain provider reads the per-resource AWS
profiles that `wb workspace configure-aws` generates (via
AWS_CONFIG_FILE), so files are read straight from S3 with no cluster
and no download step. Also the bridge until aurora_analytics (pg 17.11+)
is available on the workspace cluster.
"""

import logging
import re
import subprocess

import duckdb
import pandas as pd

import db
from cache import ttl_cache

logger = logging.getLogger(__name__)

DATA_SUFFIXES = (".parquet", ".csv", ".tsv", ".txt")
_SAFE_KEY = re.compile(r"^[A-Za-z0-9._\-/ ()+=]+$")


def parse_s3_ls(output: str) -> list[str]:
    """File names from `aws s3 ls` output lines: 'date time size name'."""
    files = []
    for line in output.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and parts[0] != "PRE" and not line.rstrip().endswith("/"):
            files.append(parts[3])
    return [f for f in files if f.lower().endswith(DATA_SUFFIXES)]


@ttl_cache(ttl=300)
def list_s3_files(resource_id: str) -> list[str]:
    uri = db.resolve_s3_uri(resource_id)
    result = subprocess.run(
        ["aws", "s3", "ls", uri + "/", "--profile", resource_id],
        capture_output=True, text=True, check=True, timeout=120)
    files = parse_s3_ls(result.stdout)
    logger.info("Found %d data files in %s", len(files), uri)
    return files


def _connect(profile: str | None):
    con = duckdb.connect()
    if profile:
        con.execute("INSTALL httpfs; LOAD httpfs;")
        con.execute(f"""
            CREATE OR REPLACE SECRET wb (
                TYPE s3, PROVIDER credential_chain, PROFILE '{profile}'
            )""")
    return con


def _reader_sql(uri: str) -> str:
    if not _SAFE_KEY.match(uri.replace("s3://", "")):
        raise ValueError(f"Unsupported characters in path: {uri!r}")
    if uri.lower().endswith(".parquet"):
        return f"read_parquet('{uri}')"
    return f"read_csv_auto('{uri}')"


def fetch_file(uri: str, cap: int, profile: str | None = None) -> pd.DataFrame:
    """Read a Parquet/CSV file (s3:// or local path) into a DataFrame."""
    con = _connect(profile)
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
