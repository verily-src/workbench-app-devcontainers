from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from urllib.parse import urlsplit

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

import duck
import disk_data

logger = logging.getLogger(__name__)
MAX_ATHENA_ROWS = 100_000
MAX_TABLES = 10_000
MAX_QUERY_SECONDS = 120
POLL_SECONDS = 0.5
_RESOURCE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class AthenaResource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    region: str = Field(pattern=r"^[a-z]{2}(-gov)?-[a-z]+-\d+$", max_length=32)
    catalog: Literal["AwsDataCatalog"]
    workgroup: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    output_location: str = Field(min_length=10, max_length=1024)
    databases: list[str] = Field(min_length=1, max_length=500)
    profile: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.-]{1,128}$")
    timeout_seconds: int = Field(default=60, ge=1, le=MAX_QUERY_SECONDS)

    @field_validator("databases")
    @classmethod
    def validate_databases(cls, values: list[str]) -> list[str]:
        if any(not _IDENTIFIER.fullmatch(value) for value in values):
            raise ValueError("Athena database names must use letters, digits, underscore or dash.")
        if len(set(values)) != len(values):
            raise ValueError("Athena database allowlist cannot contain duplicates.")
        return values

    @field_validator("output_location")
    @classmethod
    def validate_output_location(cls, value: str) -> str:
        parsed = urlsplit(value)
        parts = [part for part in parsed.path.split("/") if part]
        if (parsed.scheme != "s3" or not parsed.netloc or parsed.query or parsed.fragment
                or parsed.username or parsed.password or any(p in {".", ".."} for p in parts)
                or any(c.isspace() for c in value)):
            raise ValueError("Athena output_location must be a safe s3:// URI.")
        return value.rstrip("/") + "/"

class AthenaError(RuntimeError):
    pass


class AthenaTimeout(AthenaError):
    pass


def _resources() -> dict[str, AthenaResource]:
    raw = os.environ.get("STUDIO_ATHENA_RESOURCES", "{}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("STUDIO_ATHENA_RESOURCES must be valid JSON.") from exc
    if not isinstance(data, dict):
        raise ValueError("STUDIO_ATHENA_RESOURCES must be a JSON object keyed by resource ID.")
    result = {}
    for resource_id, config in data.items():
        if not isinstance(resource_id, str) or not _RESOURCE_ID.fullmatch(resource_id):
            raise ValueError("Athena resource ID is invalid.")
        try:
            result[resource_id] = AthenaResource.model_validate(config)
        except Exception:
            raise ValueError(f"Athena resource {resource_id!r} has invalid server configuration.") from None
    import source_registry
    for item in source_registry.entries("athena"):
        resource_id = item["id"]
        if resource_id in result:
            continue
        values = {key: item[key] for key in (
            "region", "catalog", "workgroup", "output_location", "databases")}
        try:
            result[resource_id] = AthenaResource.model_validate(values)
        except Exception:
            raise ValueError(f"Registered Athena source {resource_id!r} is invalid.") from None
    return result


def athena_resources() -> list[dict]:
    resources = _resources()
    import source_registry
    registered = source_registry.entries("athena")
    env_ids = set(json.loads(os.environ.get("STUDIO_ATHENA_RESOURCES", "{}")))
    labels = {item["id"]: item["label"] for item in registered
              if item["id"] not in env_ids}
    return [{"kind": "athena", "id": resource_id,
             "label": labels.get(resource_id) or f"{resource_id} · Athena"}
            for resource_id in sorted(resources)]


def _settings(resource_id: str) -> AthenaResource:
    if not isinstance(resource_id, str) or not _RESOURCE_ID.fullmatch(resource_id):
        raise ValueError("Athena resource ID is invalid.")
    config = _resources().get(resource_id)
    if config is None:
        raise ValueError(f"Unknown Athena resource: {resource_id}.")
    return config


def _session(settings: AthenaResource):
    import boto3

    if not settings.profile:
        return boto3.Session(region_name=settings.region)
    credentials = duck._resolve_credentials(settings.profile)
    return boto3.Session(
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials.get("SessionToken"),
        region_name=settings.region)


def _client(settings: AthenaResource, service: str):
    from botocore.config import Config

    return _session(settings).client(
        service, region_name=settings.region,
        config=Config(connect_timeout=min(5, settings.timeout_seconds),
                      read_timeout=min(15, settings.timeout_seconds),
                      retries={"max_attempts": 2, "mode": "standard"}))


def _allowed_database(settings: AthenaResource, database: str) -> str:
    if not isinstance(database, str) or database not in settings.databases:
        raise ValueError("Athena database is not in the server allowlist.")
    return database


def _quote(identifier: str) -> str:
    if not isinstance(identifier, str) or not identifier or "\x00" in identifier:
        raise ValueError("Athena table identifier is invalid.")
    return '"' + identifier.replace('"', '""') + '"'


def list_athena_tables(resource_id: str, database: str | None = None) -> list[dict]:
    settings = _settings(resource_id)
    databases = [_allowed_database(settings, database)] if database is not None else settings.databases
    glue = _client(settings, "glue")
    out = []
    for db_name in databases:
        token = None
        while True:
            request = {"DatabaseName": db_name, "MaxResults": 100}
            if token:
                request["NextToken"] = token
            response = glue.get_tables(**request)
            for table in response.get("TableList", []):
                name = table.get("Name")
                if not isinstance(name, str) or not name:
                    continue
                parameters = table.get("Parameters") or {}
                is_iceberg = (str(parameters.get("table_type", "")).casefold() == "iceberg"
                              or str(table.get("TableType", "")).casefold() == "iceberg")
                out.append({"name": f"{db_name}.{name}", "table": name,
                            "schema": db_name,
                            "detail": "iceberg" if is_iceberg else "table"})
                if len(out) > MAX_TABLES:
                    raise ValueError(f"Athena source has more than {MAX_TABLES:,} tables.")
            token = response.get("NextToken")
            if not token:
                break
    return sorted(out, key=lambda item: (item["schema"], item["table"]))


def _table_exists(settings: AthenaResource, database: str, table: str) -> bool:
    glue = _client(settings, "glue")
    try:
        response = glue.get_table(DatabaseName=database, Name=table)
    except Exception as exc:
        code = getattr(exc, "response", {}).get("Error", {}).get("Code")
        if code in {"EntityNotFoundException", "TableNotFoundException"}:
            return False
        raise AthenaError(f"Glue table lookup failed: {str(exc).splitlines()[0][:250]}") from exc
    return bool(response.get("Table", {}).get("Name") == table)


def _workgroup(settings: AthenaResource, client) -> tuple[str, int]:
    try:
        workgroup = client.get_work_group(WorkGroup=settings.workgroup)["WorkGroup"]
    except Exception as exc:
        raise AthenaError(f"Athena workgroup could not be checked: {str(exc).splitlines()[0][:250]}") from exc
    if workgroup.get("State") != "ENABLED":
        raise ValueError("Configured Athena workgroup is not enabled.")
    configuration = workgroup.get("Configuration") or {}
    if configuration.get("EnforceWorkGroupConfiguration") is not True:
        raise ValueError("Athena workgroup must enforce its configuration.")
    cutoff = configuration.get("BytesScannedCutoffPerQuery")
    if not isinstance(cutoff, int) or isinstance(cutoff, bool) or cutoff <= 0:
        raise ValueError("Athena workgroup needs a positive bytes-scanned cutoff.")
    engine_version = (configuration.get("EngineVersion") or {}).get(
        "EffectiveEngineVersion", "")
    if not re.search(r"\bversion\s*3\b", engine_version, re.IGNORECASE):
        raise ValueError("Athena workgroup must use effective engine version 3.")
    effective_output = ((configuration.get("ResultConfiguration") or {})
                        .get("OutputLocation"))
    if effective_output and effective_output.rstrip("/") != settings.output_location.rstrip("/"):
        raise ValueError("Athena output_location must match the enforced workgroup location.")
    return effective_output or settings.output_location, cutoff


def _decode(value: str | None, type_name: str):
    if value is None:
        return None
    kind = type_name.casefold().split("(", 1)[0].strip()
    try:
        if kind in {"tinyint", "smallint", "integer", "int", "bigint"}:
            return int(value)
        if kind in {"real", "float", "double"}:
            return float(value)
        if kind == "decimal":
            return Decimal(value)
        if kind == "boolean":
            return value.casefold() == "true"
        if kind == "date":
            return date.fromisoformat(value)
        if kind == "timestamp":
            return datetime.fromisoformat(value.replace(" ", "T", 1))
    except (ValueError, ArithmeticError):
        return value
    return value


def _stop(client, query_id: str) -> None:
    try:
        client.stop_query_execution(QueryExecutionId=query_id)
    except Exception as exc:
        logger.warning("Could not stop timed-out Athena query %s: %s",
                       query_id, str(exc).splitlines()[0][:200])


def _wait(client, query_id: str, deadline: float) -> dict:
    while time.monotonic() < deadline:
        try:
            response = client.get_query_execution(QueryExecutionId=query_id)
        except Exception as exc:
            _stop(client, query_id)
            raise AthenaError(f"Athena query status failed: {str(exc).splitlines()[0][:250]}") from exc
        execution = response.get("QueryExecution", {})
        status = execution.get("Status", {})
        state = status.get("State")
        if state == "SUCCEEDED":
            return execution
        if state in {"FAILED", "CANCELLED"}:
            reason = status.get("StateChangeReason") or state
            raise AthenaError(f"Athena query {state.lower()}: {str(reason).splitlines()[0][:250]}")
        time.sleep(min(POLL_SECONDS, max(0, deadline - time.monotonic())))
    _stop(client, query_id)
    raise AthenaTimeout("Athena query exceeded the configured time limit and was cancelled.")


def fetch_athena_table(resource_id: str, database: str,
                       table: str, cap: int) -> pd.DataFrame:
    settings = _settings(resource_id)
    database = _allowed_database(settings, database)
    if not isinstance(cap, int) or isinstance(cap, bool) or not 1 <= cap <= MAX_ATHENA_ROWS:
        raise ValueError(f"Athena row limit must be from 1 to {MAX_ATHENA_ROWS:,}.")
    if not isinstance(table, str) or not table or len(table) > 255:
        raise ValueError("Athena table name is invalid.")
    if not _table_exists(settings, database, table):
        raise ValueError("Athena table is not available in the configured Glue database.")
    client = _client(settings, "athena")
    output_location, scan_cap = _workgroup(settings, client)
    query = (f"SELECT * FROM {_quote(settings.catalog)}.{_quote(database)}."
             f"{_quote(table)} LIMIT {cap + 1}")
    try:
        started = client.start_query_execution(
            QueryString=query,
            QueryExecutionContext={"Catalog": settings.catalog, "Database": database},
            ResultConfiguration={"OutputLocation": output_location},
            WorkGroup=settings.workgroup)
    except Exception as exc:
        raise AthenaError(f"Athena query could not start: {str(exc).splitlines()[0][:250]}") from exc
    query_id = started.get("QueryExecutionId")
    if not isinstance(query_id, str) or not query_id:
        raise AthenaError("Athena did not return a query ID.")
    deadline = time.monotonic() + settings.timeout_seconds
    execution = _wait(client, query_id, deadline)
    scanned = (execution.get("Statistics") or {}).get("DataScannedInBytes")
    if isinstance(scanned, int) and not isinstance(scanned, bool) and scanned > scan_cap:
        raise AthenaError("Athena query exceeded the enforced bytes-scanned cutoff.")
    column_info = []
    next_token = None
    records = []
    header_skipped = False
    while len(records) < cap + 1:
        if time.monotonic() >= deadline:
            _stop(client, query_id)
            raise AthenaTimeout("Athena results exceeded the configured time limit and were cancelled.")
        request = {"QueryExecutionId": query_id, "MaxResults": 1000}
        if next_token:
            request["NextToken"] = next_token
        try:
            page = client.get_query_results(**request)
        except Exception as exc:
            raise AthenaError(f"Athena results could not be read: {str(exc).splitlines()[0][:250]}") from exc
        result_set = page.get("ResultSet", {})
        if not column_info:
            column_info = result_set.get("ResultSetMetadata", {}).get("ColumnInfo", [])
        for row in result_set.get("Rows") or []:
            if not header_skipped:
                header_skipped = True
                continue
            values = row.get("Data") or []
            records.append([_decode((values[i] or {}).get("VarCharValue") if i < len(values) else None,
                                    column_info[i].get("Type", "string"))
                            for i in range(len(column_info))])
            if len(records) >= cap + 1:
                break
        next_token = page.get("NextToken")
        complete = len(records) >= cap + 1 or not next_token
        if complete:
            break
        if time.monotonic() >= deadline:
            _stop(client, query_id)
            raise AthenaTimeout("Athena results exceeded the configured time limit.")
    names = [column.get("Name") or f"column_{index + 1}"
             for index, column in enumerate(column_info)]
    if not names or len(names) > 200:
        raise ValueError("Athena table must return between 1 and 200 columns.")
    if len(set(names)) != len(names):
        raise ValueError("Athena table columns must have unique names.")
    columns = {}
    integer_types = {"tinyint", "smallint", "integer", "int", "bigint"}
    for index, column in enumerate(column_info):
        name = names[index]
        values = [record[index] for record in records]
        type_name = column.get("Type", "string").casefold().split("(", 1)[0].strip()
        columns[name] = (pd.array(values, dtype="Int64")
                         if type_name in integer_types else values)
    return pd.DataFrame(columns)


@disk_data._bounded_materialization
def open_athena(ref: dict) -> tuple[pd.DataFrame, dict]:
    import pyarrow as pa
    import disk_data

    settings = _settings(ref["resource_id"])
    database = _allowed_database(settings, ref.get("schema", "public"))
    table = ref["table"]
    if not _table_exists(settings, database, table):
        raise ValueError("Athena table is not available in the configured Glue database.")
    client = _client(settings, "athena")
    output, scan_cap = _workgroup(settings, client)
    if scan_cap > disk_data.MAX_OPERATION_BYTES:
        raise ValueError("Athena workgroup scan cutoff must not exceed the 1 TB operation limit.")
    started = client.start_query_execution(
        QueryString=f"SELECT * FROM {_quote(settings.catalog)}.{_quote(database)}.{_quote(table)}",
        QueryExecutionContext={"Catalog": settings.catalog, "Database": database},
        ResultConfiguration={"OutputLocation": output}, WorkGroup=settings.workgroup)
    query_id = started["QueryExecutionId"]
    deadline = time.monotonic() + settings.timeout_seconds
    execution = _wait(client, query_id, deadline)
    scanned = (execution.get("Statistics") or {}).get("DataScannedInBytes", 0)
    if scanned > scan_cap:
        raise AthenaError("Athena query exceeded the enforced bytes-scanned cutoff.")
    disk_data._actual_budget(scanned)
    path = disk_data._new_path()
    connection = disk_data._connect(path)
    total_bytes = rows = 0
    token = None
    first_page = True
    arrow_schema = None
    try:
        while True:
            if time.monotonic() >= deadline:
                raise AthenaTimeout("Athena results exceeded the configured time limit.")
            request = {"QueryExecutionId": query_id, "MaxResults": 1000}
            if token:
                request["NextToken"] = token
            page = client.get_query_results(**request)
            result = page.get("ResultSet", {})
            if arrow_schema is None:
                info = result.get("ResultSetMetadata", {}).get("ColumnInfo", [])
                names = [item["Name"] for item in info]
                if not names or len(names) > 200 or len(set(names)) != len(names):
                    raise ValueError("Athena requires 1 to 200 unique columns.")
                types = {"tinyint": pa.int64(), "smallint": pa.int64(), "integer": pa.int64(),
                         "int": pa.int64(), "bigint": pa.int64(), "real": pa.float64(),
                         "float": pa.float64(), "double": pa.float64(), "decimal": pa.float64(),
                         "boolean": pa.bool_(), "date": pa.date32(), "timestamp": pa.timestamp("us")}
                def arrow_type(item):
                    declared = item.get("Type", "string").lower()
                    kind = declared.split("(")[0].strip()
                    if kind == "decimal":
                        match = re.fullmatch(r"decimal\((\d+),\s*(\d+)\)", declared)
                        precision = int(match[1]) if match else item.get("Precision", 38)
                        scale = int(match[2]) if match else item.get("Scale", 0)
                        return pa.decimal128(precision, scale)
                    return types.get(kind, pa.string())
                arrow_schema = pa.schema([(item["Name"], arrow_type(item)) for item in info])
                connection.register("_athena_batch", arrow_schema.empty_table())
                connection.execute('CREATE TABLE data AS SELECT * FROM _athena_batch')
                connection.unregister("_athena_batch")
            values = result.get("Rows") or []
            if first_page:
                values = values[1:]
                first_page = False
            records = []
            for row in values:
                cells = row.get("Data") or []
                records.append({item["Name"]: _decode(
                    (cells[index] or {}).get("VarCharValue") if index < len(cells) else None,
                    item.get("Type", "string")) for index, item in enumerate(info)})
            batch = pa.Table.from_pylist(records, schema=arrow_schema)
            total_bytes += batch.nbytes
            disk_data._actual_budget(scanned + total_bytes)
            connection.register("_athena_batch", batch)
            connection.execute('INSERT INTO data SELECT * FROM _athena_batch')
            connection.unregister("_athena_batch")
            rows += batch.num_rows
            token = page.get("NextToken")
            if not token:
                break
        connection.close()
        source = {"path": path, "table": "data", "columns": names,
                  "rows": rows, "estimated_bytes": scanned + total_bytes,
                  "materialized_bytes": total_bytes, "scan_bytes": os.path.getsize(path),
                  "large_warning": scanned + total_bytes >= disk_data.LARGE_OPERATION_BYTES}
        return disk_data._preview(path), source
    except Exception:
        _stop(client, query_id)
        connection.close()
        disk_data.remove({"path": path})
        raise
