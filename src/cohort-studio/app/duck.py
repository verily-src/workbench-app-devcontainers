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

DATA_SUFFIXES = (".parquet", ".csv", ".tsv", ".txt", ".json", ".ndjson")
CATALOG_SUFFIX = ".duckdb"
_SAFE_KEY = re.compile(r"^[A-Za-z0-9._\-/ ()+=]+$")

DEFAULT_REGION = os.environ.get("STUDIO_S3_REGION", "us-east-1")

MAX_LISTING = 500

def parse_s3_ls(output: str, prefix: str = "",
                suffixes: tuple[str, ...] = DATA_SUFFIXES) -> list[str]:

    files = []
    for line in output.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and parts[0] != "PRE" and not line.rstrip().endswith("/"):
            key = parts[3]
            if prefix and key.startswith(prefix):
                key = key[len(prefix):].lstrip("/")
            files.append(key)
    return [f for f in files if f.lower().endswith(suffixes)][:MAX_LISTING]

@ttl_cache(ttl=300)
def _s3_ls(resource_id: str) -> tuple[str, str]:

    uri = db.resolve_s3_uri(resource_id)

    prefix = uri.removeprefix("s3://").partition("/")[2]
    result = subprocess.run(
        ["aws", "s3", "ls", uri + "/", "--recursive", "--profile", resource_id],
        capture_output=True, text=True, timeout=120)
    if result.returncode != 0:

        detail = (result.stderr or result.stdout or "").strip().split("\n")[-1]
        raise RuntimeError(
            f"aws s3 ls failed for {resource_id}: {detail or 'exit 255'}")
    return result.stdout, prefix

@ttl_cache(ttl=300)
def list_s3_files(resource_id: str) -> list[str]:

    output, prefix = _s3_ls(resource_id)
    files = parse_s3_ls(output, prefix=prefix)
    logger.info("Found %d data files in %s", len(files), resource_id)
    return files

def list_s3_catalogs(resource_id: str) -> list[str]:

    output, prefix = _s3_ls(resource_id)
    return parse_s3_ls(output, prefix=prefix, suffixes=(CATALOG_SUFFIX,))

def _run_credential_process(profile: str) -> dict:

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

        def lit(v: str) -> str:
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

def _reader_sql(uri: str, hive: bool = False) -> str:

    key = uri.replace("s3://", "").replace("gs://", "")
    if hive:
        key = key.replace("*", "")
    if not _SAFE_KEY.match(key):
        raise ValueError(f"Unsupported characters in path: {uri!r}")
    opts = ", hive_partitioning = true" if hive else ""
    low = uri.lower()
    if low.endswith(".parquet"):
        return f"read_parquet('{uri}'{opts})"
    if low.endswith((".json", ".ndjson")):
        return f"read_json_auto('{uri}'{opts})"
    return f"read_csv_auto('{uri}'{opts})"

def fetch_file(uri: str, cap: int, profile: str | None = None,
               region: str = DEFAULT_REGION) -> pd.DataFrame:

    con = _connect(profile, region)
    try:
        query = f"SELECT * FROM {_reader_sql(uri)} LIMIT {int(cap)}"
        return con.execute(query).df()
    finally:
        con.close()

@ttl_cache(ttl=600, maxsize=4)
def fetch_s3_file(resource_id: str, filename: str, cap: int) -> pd.DataFrame:

    uri = f"{db.resolve_s3_uri(resource_id)}/{filename}"
    return fetch_file(uri, cap, profile=resource_id)
