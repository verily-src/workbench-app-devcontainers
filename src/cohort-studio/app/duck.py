import configparser
import json
import logging
import os
import re
import shlex
import subprocess
import cloud_cli

import duckdb
import pandas as pd

import database as db
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
    result = cloud_cli.run(
        ["aws", "s3", "ls", uri + "/", "--recursive", "--profile", resource_id],
        capture_output=True, text=True, timeout=120)
    if result.returncode != 0:

        detail = (result.stderr or result.stdout or "").strip().split("\n")[-1]
        raise RuntimeError(
            f"aws s3 ls failed for {resource_id}: {detail or 'exit 255'}")
    return result.stdout, prefix


def _registered_s3_files(resource_id: str,
                          suffixes: tuple[str, ...] = DATA_SUFFIXES) -> list[str] | None:
    import boto3
    import source_registry

    location = source_registry.s3_location(resource_id)
    if location is None:
        return None
    _, region, prefix = location
    source = source_registry.get("s3", resource_id.removeprefix("s3:"))
    if source is None:
        raise ValueError("Registered S3 datasource was not found.")
    client = boto3.Session(region_name=region).client("s3", region_name=region)
    files = []
    token = None
    scanned = 0
    base_prefix = prefix.rstrip("/")
    while True:
        request = {"Bucket": source["bucket"],
                   "Prefix": f"{base_prefix}/" if base_prefix else "",
                   "MaxKeys": 1000}
        if token:
            request["ContinuationToken"] = token
        response = client.list_objects_v2(**request)
        for item in response.get("Contents", []):
            scanned += 1
            key = item.get("Key", "")
            relative = key[len(base_prefix) + 1:] if base_prefix else key
            if relative and not relative.endswith("/") and relative.lower().endswith(suffixes):
                files.append(relative)
                if len(files) >= MAX_LISTING:
                    return sorted(files)
            if scanned >= MAX_LISTING * 20:
                return sorted(files)
        token = response.get("NextContinuationToken")
        if not token:
            break
    return sorted(files)

@ttl_cache(ttl=300)
def list_s3_files(resource_id: str) -> list[str]:

    registered = _registered_s3_files(resource_id)
    if registered is not None:
        return registered

    output, prefix = _s3_ls(resource_id)
    files = parse_s3_ls(output, prefix=prefix)
    logger.info("Found %d data files in %s", len(files), resource_id)
    return files

def list_s3_catalogs(resource_id: str) -> list[str]:

    registered = _registered_s3_files(resource_id, suffixes=(CATALOG_SUFFIX,))
    if registered is not None:
        return registered

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
    out = cloud_cli.run(cmd, capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        detail = (out.stderr or out.stdout or "").strip().split("\n")[-1]
        raise RuntimeError(f"credential_process failed: {detail}")
    return json.loads(out.stdout)

def _resolve_credentials(profile: str) -> dict:

    out = cloud_cli.run(
        ["aws", "configure", "export-credentials",
         "--profile", profile, "--format", "json"],
        capture_output=True, text=True, timeout=60)
    if out.returncode == 0 and out.stdout.strip().startswith("{"):
        return json.loads(out.stdout)
    return _run_credential_process(profile)

def _connect(profile: str | None, region: str = DEFAULT_REGION,
             app_credentials: bool = False):
    con = duckdb.connect()
    if not profile and not app_credentials:
        return con
    import boto3
    creds = _resolve_credentials(profile) if profile else None
    if creds is None:
        aws_credentials = boto3.Session(region_name=region).get_credentials()
        if aws_credentials is None:
            con.close()
            raise RuntimeError("AWS application credentials are not available.")
        frozen = aws_credentials.get_frozen_credentials()
        creds = {"AccessKeyId": frozen.access_key,
                 "SecretAccessKey": frozen.secret_key,
                 "SessionToken": frozen.token}

    def lit(v: str) -> str:
        return v.replace("'", "''")

    parts = ["TYPE s3", "PROVIDER config",
             f"KEY_ID '{lit(creds['AccessKeyId'])}'",
             f"SECRET '{lit(creds['SecretAccessKey'])}'",
             f"REGION '{lit(region)}'"]
    if creds.get("SessionToken"):
        parts.append(f"SESSION_TOKEN '{lit(creds['SessionToken'])}'")
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute(f"CREATE OR REPLACE SECRET studio_s3 ({', '.join(parts)})")
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


def _has_hive_path(uri: str) -> bool:
    path = uri.split("?", 1)[0].rstrip("/")
    parts = path.split("/")
    return any("=" in part for part in parts[:-1])

def _validate_relative_key(filename: str) -> str:
    if (not isinstance(filename, str) or not filename or filename.startswith("/")
            or "\\" in filename or ":" in filename):
        raise ValueError("S3 file path must be relative to its configured folder.")
    parts = filename.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("S3 file path cannot contain empty or parent path segments.")
    if not filename.lower().endswith(DATA_SUFFIXES) or not _SAFE_KEY.match(filename):
        raise ValueError("S3 path must name a supported data file.")
    return filename

def fetch_file(uri: str, cap: int, profile: str | None = None,
               region: str = DEFAULT_REGION,
               app_credentials: bool = False) -> pd.DataFrame:

    con = _connect(profile, region, app_credentials=app_credentials)
    try:
        query = (f"SELECT * FROM {_reader_sql(uri, hive=_has_hive_path(uri))} "
                 f"LIMIT {int(cap)}")
        return con.execute(query).df()
    finally:
        con.close()

@ttl_cache(ttl=600, maxsize=4)
def fetch_s3_file(resource_id: str, filename: str, cap: int) -> pd.DataFrame:

    filename = _validate_relative_key(filename)
    import source_registry
    location = source_registry.s3_location(resource_id)
    if location is not None:
        base, region, _ = location
        uri = f"{base.rstrip('/')}/{filename}"
        return fetch_file(uri, cap, region=region, app_credentials=True)
    uri = f"{db.resolve_s3_uri(resource_id).rstrip('/')}/{filename}"
    return fetch_file(uri, cap, profile=resource_id)
