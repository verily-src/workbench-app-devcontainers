import json
import os
import threading

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, make_url


class Connection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    label: str | None = Field(default=None, max_length=128)
    url_env: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    secret_id: str | None = Field(default=None, min_length=1)
    region: str = "us-east-1"
    sslrootcert: str | None = None
    local_test: bool = False
    allow_write: bool = False

    @model_validator(mode="after")
    def credential_source(self):
        if bool(self.url_env) == bool(self.secret_id):
            raise ValueError("Set exactly one of url_env or secret_id.")
        return self


_lock = threading.Lock()
_engines = {}


def connections():
    try:
        values = TypeAdapter(list[Connection]).validate_json(
            os.environ.get("STUDIO_POSTGRES_SOURCES", "[]"))
    except ValueError:
        raise ValueError("Invalid server PostgreSQL source configuration.") from None
    if len({c.id for c in values}) != len(values):
        raise ValueError("Duplicate PostgreSQL source ID.")
    result = {"postgres:" + c.id: c for c in values}
    import source_registry
    for item in source_registry.entries("postgres"):
        resource_id = "postgres:" + item["id"]
        if resource_id in result:
            continue
        result[resource_id] = Connection.model_validate({
            "id": item["id"], "label": item["label"],
            "secret_id": item["secret_id"], "region": item["region"],
        })
    return result


def resources():
    return [{"id": rid, "kind": "postgres", "label": c.label or f"{c.id} · PostgreSQL",
             "read_only": not c.allow_write} for rid, c in connections().items()]


def _url(config):
    if config.url_env:
        raw = os.environ.get(config.url_env)
        if not raw:
            raise ValueError("PostgreSQL connection secret is not configured.")
    else:
        import boto3
        try:
            raw = boto3.client("secretsmanager", region_name=config.region).get_secret_value(
                SecretId=config.secret_id)["SecretString"]
        except Exception:
            raise ValueError("Cannot read PostgreSQL connection secret.") from None
        if raw.lstrip().startswith("{"):
            try:
                secret = json.loads(raw)
                raw = URL.create("postgresql+psycopg", username=secret["username"],
                                 password=secret["password"], host=secret["host"],
                                 port=int(secret.get("port", 5432)), database=secret["dbname"])
            except (KeyError, ValueError, TypeError):
                raise ValueError("Invalid PostgreSQL connection secret.") from None
    try:
        url = make_url(raw)
        if url.drivername not in {"postgresql", "postgresql+psycopg", "postgres"}:
            raise ValueError()
        if not url.host or not url.database or url.query:
            raise ValueError()
        if config.local_test and url.host not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError()
        return url.set(drivername="postgresql+psycopg")
    except Exception:
        raise ValueError("Invalid PostgreSQL URL; use a host and database without URL options.") from None


def engine(resource_id):
    config = connections().get(resource_id)
    if config is None:
        raise ValueError("Unknown PostgreSQL source.")
    return configured_engine(resource_id, config)


def configured_engine(resource_id, config):
    key = (resource_id, config.model_dump_json())
    with _lock:
        if key not in _engines:
            def creator():
                import psycopg
                url = _url(config)
                args = dict(url.translate_connect_args(username="user"))
                args.update(connect_timeout=10, sslmode="disable" if config.local_test else "verify-full",
                            options="-c statement_timeout=15000 -c default_transaction_read_only="
                                    + ("off" if config.allow_write else "on"))
                args["dbname"] = args.pop("database")
                if not config.local_test:
                    args["sslrootcert"] = (config.sslrootcert
                                           or os.environ.get("STUDIO_POSTGRES_SSLROOTCERT")
                                           or "system")
                return psycopg.connect(**args)
            _engines[key] = create_engine("postgresql+psycopg://", creator=creator,
                                         pool_pre_ping=True, pool_size=3, max_overflow=2,
                                         pool_recycle=300, hide_parameters=True)
        return _engines[key]
