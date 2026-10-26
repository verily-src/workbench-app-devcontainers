from __future__ import annotations

import json
import os
import re
from typing import Annotated, Literal, Union
from urllib.parse import urlsplit

from pydantic import (BaseModel, ConfigDict, Field, TypeAdapter,
                      field_validator)

import config

_ID = r"^[A-Za-z0-9_-]{1,80}$"
_REGION = r"^[a-z]{2}(-gov)?-[a-z]+-\d+$"
_DB = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_S3_BUCKET = re.compile(r"^(?=.{3,63}$)(?!\d+\.\d+\.\d+\.\d+$)(?!.*\.\.)[a-z0-9][a-z0-9.-]*[a-z0-9]$")
_S3_PATH = re.compile(r"^[A-Za-z0-9._\-/ ()+=]*$")


class RegistrationBase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(pattern=_ID)
    label: str = Field(min_length=1, max_length=128)

    @field_validator("label")
    @classmethod
    def nonblank_label(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Datasource label is required.")
        return value


class PostgresRegistration(RegistrationBase):
    kind: Literal["postgres"]
    secret_id: str = Field(min_length=1, max_length=2048)
    region: str = Field(default="us-east-1", pattern=_REGION, max_length=32)

    @field_validator("secret_id")
    @classmethod
    def validate_secret_id(cls, value: str) -> str:
        if any(char.isspace() or ord(char) < 32 for char in value):
            raise ValueError("PostgreSQL secret_id is invalid.")
        return value


class S3Registration(RegistrationBase):
    kind: Literal["s3"]
    bucket: str = Field(min_length=3, max_length=63)
    prefix: str = Field(default="", max_length=512)
    region: str = Field(default="us-east-1", pattern=_REGION, max_length=32)

    @field_validator("bucket")
    @classmethod
    def validate_bucket(cls, value: str) -> str:
        if not _S3_BUCKET.fullmatch(value) or value.endswith((".", "-")):
            raise ValueError("S3 bucket name is invalid.")
        return value

    @field_validator("prefix")
    @classmethod
    def validate_prefix(cls, value: str) -> str:
        parts = value.split("/")
        if (value.startswith("/") or "\\" in value or "\x00" in value
                or not _S3_PATH.fullmatch(value) or "//" in value
                or any(part in {".", ".."} for part in parts)):
            raise ValueError("S3 prefix must be a relative object path.")
        return value.strip("/")


class AthenaRegistration(RegistrationBase):
    kind: Literal["athena"]
    region: str = Field(pattern=_REGION, max_length=32)
    workgroup: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    output_location: str = Field(min_length=10, max_length=1024)
    databases: list[str] = Field(min_length=1, max_length=500)
    catalog: Literal["AwsDataCatalog"] = "AwsDataCatalog"

    @field_validator("databases")
    @classmethod
    def validate_databases(cls, values: list[str]) -> list[str]:
        if any(not _DB.fullmatch(value) for value in values):
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
                or parsed.username or parsed.password
                or not _S3_BUCKET.fullmatch(parsed.netloc)
                or any(part in {".", ".."} for part in parts)
                or any(char.isspace() for char in value)):
            raise ValueError("Athena output_location must be a safe s3:// URI.")
        return value.rstrip("/") + "/"


Registration = Annotated[
    Union[PostgresRegistration, S3Registration, AthenaRegistration],
    Field(discriminator="kind"),
]


def _validated_entries(raw=None) -> list[dict]:
    if raw is None:
        raw = config._load().get("data_sources", [])
    if not isinstance(raw, list):
        raise ValueError("Registered datasource metadata must be a list.")
    result = []
    seen = set()
    for value in raw:
        try:
            validated = TypeAdapter(Registration).validate_python(value)
        except Exception:
            raise ValueError("Registered datasource metadata is invalid.") from None
        key = (validated.kind, validated.id)
        if key in seen:
            raise ValueError("Duplicate registered datasource ID.")
        seen.add(key)
        result.append(validated.model_dump())
    return result


def _environment_ids(kind: str) -> set[str]:
    if kind == "postgres":
        try:
            raw = json.loads(os.environ.get("STUDIO_POSTGRES_SOURCES", "[]"))
        except json.JSONDecodeError:
            raise ValueError("Invalid server PostgreSQL source configuration.") from None
        if not isinstance(raw, list):
            raise ValueError("Invalid server PostgreSQL source configuration.")
        return {item.get("id") for item in raw
                if isinstance(item, dict) and isinstance(item.get("id"), str)}
    if kind == "athena":
        try:
            raw = json.loads(os.environ.get("STUDIO_ATHENA_RESOURCES", "{}"))
        except json.JSONDecodeError:
            raise ValueError("Invalid server Athena source configuration.") from None
        if not isinstance(raw, dict):
            raise ValueError("Invalid server Athena source configuration.")
        return set(raw)
    return set()


def entries(kind: str | None = None) -> list[dict]:
    values = _validated_entries()
    return [item for item in values if kind is None or item["kind"] == kind]


def get(kind: str, source_id: str) -> dict | None:
    for item in entries(kind):
        if item["id"] == source_id:
            return item
    return None


def add(payload: dict) -> dict:
    try:
        item = TypeAdapter(Registration).validate_python(payload)
    except Exception as exc:
        raise ValueError("Datasource configuration is invalid.") from exc
    with config._lock:
        cfg = config._load()
        values = _validated_entries(cfg.get("data_sources", []))
        key = (item.kind, item.id)
        if any((row["kind"], row["id"]) == key for row in values):
            raise ValueError("A datasource with this kind and ID is already registered.")
        if item.id in _environment_ids(item.kind):
            raise ValueError("This ID is reserved by server datasource configuration.")
        values.append(item.model_dump())
        cfg["data_sources"] = values
        config._write(cfg)
    runtime_id = (f"postgres:{item.id}" if item.kind == "postgres" else
                  f"s3:{item.id}" if item.kind == "s3" else item.id)
    return {"kind": item.kind, "id": runtime_id, "label": item.label}


def public_sources() -> list[dict]:
    result = []
    for item in entries():
        if item["id"] in _environment_ids(item["kind"]):
            continue
        if item["kind"] == "postgres":
            runtime_id = f"postgres:{item['id']}"
            summary = {"kind": "postgres", "id": runtime_id,
                       "label": item["label"], "region": item["region"]}
        elif item["kind"] == "s3":
            runtime_id = f"s3:{item['id']}"
            summary = {"kind": "s3", "id": runtime_id,
                       "label": item["label"], "bucket": item["bucket"],
                       "prefix": item["prefix"], "region": item["region"]}
        else:
            summary = {key: item[key] for key in (
                "kind", "id", "label", "region", "workgroup", "databases",
                "catalog", "output_location")}
        result.append(summary)
    return result


def s3_location(resource_id: str) -> tuple[str, str, str] | None:
    prefix = "s3:"
    if not isinstance(resource_id, str) or not resource_id.startswith(prefix):
        return None
    source_id = resource_id[len(prefix):]
    item = get("s3", source_id)
    if item is None:
        raise ValueError("Registered S3 datasource was not found.")
    uri = f"s3://{item['bucket']}"
    if item["prefix"]:
        uri += f"/{item['prefix']}"
    return uri, item["region"], item["prefix"]


def validate_connection(payload: dict) -> None:
    item = TypeAdapter(Registration).validate_python(payload)
    try:
        if isinstance(item, PostgresRegistration):
            import postgres_sources
            from sqlalchemy import text
            settings = postgres_sources.Connection(
                id=item.id, label=item.label, secret_id=item.secret_id, region=item.region)
            engine = postgres_sources.configured_engine("registration:" + item.id, settings)
            try:
                with engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
            finally:
                engine.dispose()
        elif isinstance(item, S3Registration):
            import boto3
            boto3.client("s3", region_name=item.region).list_objects_v2(
                Bucket=item.bucket, Prefix=item.prefix.rstrip("/") + "/" if item.prefix else "",
                MaxKeys=1)
        else:
            import external_sources
            settings = external_sources.AthenaResource.model_validate({
                key: getattr(item, key) for key in (
                    "region", "catalog", "workgroup", "output_location", "databases")})
            external_sources._workgroup(settings, external_sources._client(settings, "athena"))
            glue = external_sources._client(settings, "glue")
            for database in settings.databases:
                glue.get_tables(DatabaseName=database, MaxResults=1)
    except Exception:
        raise ValueError("Connection test failed. Check source settings, permissions and network access.") from None
