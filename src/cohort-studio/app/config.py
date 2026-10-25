import json
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field

import secret_store

CONFIG_PATH = Path(os.environ.get(
    "STUDIO_CONFIG", str(Path(__file__).parent / "studio_config.json")))

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_PALETTE = "verily"
PALETTES = ("verily", "indigo", "amber", "crimson", "slate")

DEFAULT_PROVIDER = "anthropic"
PROVIDERS = ("anthropic", "openai", "gemini", "openrouter", "bedrock",
             "vertexai", "openweight")
StoredProvider = Literal["anthropic", "openai", "gemini", "openrouter",
                        "bedrock", "vertexai", "openweight"]


class LLMConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    model: str | None = Field(default=None, max_length=256)
    api_key: str | None = Field(default=None, max_length=8192)
    provider: StoredProvider | None = None


class JevConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    api_key: str | None = Field(default=None, max_length=8192)
    model: str | None = Field(default=None, max_length=256)

class MCPConnectionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    label: str = Field(default="", max_length=128)
    url: str = Field(default="", max_length=2048)
    enabled: bool = False
    note: str = Field(default="", max_length=1000)
    authorization_token: str | None = Field(default=None, max_length=8192)


PROVIDER_DEFAULT_MODEL = {
    "anthropic": DEFAULT_MODEL,
    "openai": "",
    "gemini": "",
    "openrouter": "",
    "bedrock": "",
    "vertexai": "",
    "openweight": "",
}

PROVIDER_BASE_URL = {
    "openai": None,
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "openrouter": "https://openrouter.ai/api/v1",
}

PROVIDER_ENV_KEYS = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "openrouter": ("OPENROUTER_API_KEY",),
    "openweight": ("STUDIO_OPENWEIGHT_API_KEY",),
}


def _openweight_endpoint() -> tuple[str | None, str | None]:
    raw = os.environ.get("STUDIO_OPENWEIGHT_BASE_URL", "").strip()
    if not raw:
        return None, None
    try:
        parsed = urlsplit(raw)
        host = parsed.hostname
        if (parsed.scheme not in ("http", "https") or not host
                or parsed.username or parsed.password or parsed.query
                or parsed.fragment or "?" in raw or "#" in raw
                or any(ch.isspace() for ch in raw)):
            return None, None
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            return None, None
        netloc = host if port is None else f"{host}:{port}"
        if ":" in host and not host.startswith("["):
            netloc = f"[{host}]" + (f":{port}" if port is not None else "")
        endpoint = urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/"), "", ""))
        return endpoint, host
    except ValueError:
        return None, None


def _openweight_model() -> str:
    model = os.environ.get("STUDIO_OPENWEIGHT_MODEL", "").strip()
    return model if len(model) <= 256 else ""

def _aws_region() -> str | None:
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")

def _vertex_project() -> str | None:
    return (os.environ.get("GOOGLE_CLOUD_PROJECT")
            or os.environ.get("VERTEXAI_PROJECT"))

def _vertex_location() -> str | None:
    return (os.environ.get("GOOGLE_CLOUD_LOCATION")
            or os.environ.get("VERTEXAI_LOCATION"))

def _env_key(provider: str) -> str | None:
    for var in PROVIDER_ENV_KEYS.get(provider, ()):
        if os.environ.get(var):
            return os.environ[var]
    return None


def _secure_keys_for_read() -> tuple[dict[str, str], bool]:
    try:
        return secret_store.read_keys(), True
    except secret_store.SecretStoreError:
        return {}, False

def _llm_section(cfg: dict) -> dict:

    llm = dict(cfg.get("llm", {}))
    keys = dict(llm.get("keys", {}))
    models = dict(llm.get("models", {}))

    if "api_key" in llm and "anthropic" not in keys:
        keys["anthropic"] = llm["api_key"]
    if "model" in llm and "anthropic" not in models:
        models["anthropic"] = llm["model"]
    provider = llm.get("provider") or DEFAULT_PROVIDER
    if provider not in PROVIDERS:
        provider = DEFAULT_PROVIDER
    return {"provider": provider, "keys": keys, "models": models}

DEFAULT_MCP_CONNECTIONS = [
    {"name": "verily-workbench", "label": "Verily Workbench",
     "url": "", "enabled": False,
     "note": "Workbench MCP endpoint — set the URL when Verily ships it."},
    {"name": "biorxiv", "label": "bioRxiv preprints",
     "url": "", "enabled": False,
     "note": "Community bioRxiv MCP server — set your deployment's URL."},
    {"name": "pubmed", "label": "PubMed / NCBI",
     "url": "", "enabled": False,
     "note": "Community PubMed MCP server — set your deployment's URL."},
]
_MCP_TOKEN_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

_lock = threading.Lock()

def _load() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def get_llm_config() -> dict:

    sec = _llm_section(_load())
    provider = sec["provider"]
    api_key = None
    if provider not in ("bedrock", "vertexai"):
        api_key = _env_key(provider)
        if not api_key:
            secure_keys, _ = _secure_keys_for_read()
            api_key = secure_keys.get(provider)
            if provider != "openweight":
                api_key = api_key or sec["keys"].get(provider)
    model = (sec["models"].get(provider)
             or PROVIDER_DEFAULT_MODEL.get(provider) or "")
    base_url = PROVIDER_BASE_URL.get(provider)
    if provider == "openweight":
        base_url, _ = _openweight_endpoint()
        model = _openweight_model()
        api_key = api_key or "not-required"
    out = {
        "provider": provider,
        "api_key": api_key,
        "model": model,
        "base_url": base_url,
        "region": _aws_region() if provider == "bedrock" else None,
    }
    if provider == "vertexai":
        out.update(project=_vertex_project(), location=_vertex_location())
    return out

def get_mcp_connections() -> list[dict]:

    stored = _load().get("mcp_connections")
    if stored is None:
        stored = [dict(c) for c in DEFAULT_MCP_CONNECTIONS]
    if not isinstance(stored, list):
        return [dict(c) for c in DEFAULT_MCP_CONNECTIONS]
    try:
        secure_keys = secret_store.read_keys()
    except secret_store.SecretStoreError:
        secure_keys = {}
    connections = []
    for value in stored:
        if not isinstance(value, dict):
            continue
        connection = dict(value)
        name = connection.get("name")
        key = f"mcp:{name}" if isinstance(name, str) and _MCP_TOKEN_NAME.fullmatch(name) else None
        token = secure_keys.get(key) if key else None
        if token:
            connection["authorization_token"] = token
        connections.append(connection)
    return connections


def _legacy_mcp_tokens(cfg: dict, strict: bool = False) -> dict[str, str]:
    result = {}
    for item in cfg.get("mcp_connections", []):
        if not isinstance(item, dict):
            continue
        name, token = item.get("name"), item.get("authorization_token")
        if not isinstance(token, str) or not token:
            continue
        if not isinstance(name, str) or not _MCP_TOKEN_NAME.fullmatch(name):
            if strict:
                raise secret_store.SecretStoreError(
                    "A legacy MCP token has an invalid connection name; "
                    "the app left it unchanged.")
            continue
        result[f"mcp:{name}"] = token
    return result


def _has_legacy_mcp_tokens(cfg: dict) -> bool:
    return any(isinstance(item, dict)
               and isinstance(item.get("authorization_token"), str)
               and bool(item.get("authorization_token"))
               for item in cfg.get("mcp_connections", []))


def get_integration_key(integration: str) -> str | None:
    if integration != "jev":
        raise ValueError("Unknown integration key.")
    value = os.environ.get("TYPESAFE_API_KEY")
    if value:
        return value
    secure_keys, _ = _secure_keys_for_read()
    secure_key = secure_keys.get("jev")
    if secure_key:
        return secure_key
    return _load().get("jev", {}).get("api_key")


def update_jev_config(api_key: str | None = None,
                      model: str | None = None) -> dict:
    request = JevConfigUpdate.model_validate({"api_key": api_key, "model": model})
    api_key, model = request.api_key, request.model
    with _lock:
        cfg = _load()
        section = dict(cfg.get("jev", {}))
        if api_key not in (None, ""):
            secure_keys = secret_store.read_keys()
            secure_keys["jev"] = api_key
            secret_store.write_keys(secure_keys)
        elif api_key == "":
            section.pop("api_key", None)
            secret_store.remove_key("jev")
        if model is not None:
            section["model"] = model
        cfg["jev"] = section
        _write(cfg)
    return public_config()

def public_config() -> dict:

    cfg = _load()
    sec = _llm_section(cfg)
    provider = sec["provider"]
    legacy_keys = {p: key for p, key in sec["keys"].items()
                   if p not in ("bedrock", "vertexai") and key}
    has_legacy_mcp_tokens = _has_legacy_mcp_tokens(cfg)
    secure_keys, secure_store_available = _secure_keys_for_read()
    secure_store_available = secret_store.is_available()

    providers = {}
    for p in PROVIDERS:
        env_key = None if p in ("bedrock", "vertexai") else _env_key(p)
        legacy_key = None if p in ("bedrock", "vertexai") else sec["keys"].get(p)
        secure_key = secure_keys.get(p)
        if p == "openweight":
            legacy_key = None
        key = env_key or secure_key or legacy_key
        project = _vertex_project() if p == "vertexai" else None
        location = _vertex_location() if p == "vertexai" else None
        endpoint, endpoint_host = _openweight_endpoint() if p == "openweight" else (None, None)
        model = (_openweight_model() if p == "openweight"
                 else sec["models"].get(p) or PROVIDER_DEFAULT_MODEL.get(p) or "")
        state = {
            "model": model,
            "api_key_set": bool(key),
            "api_key_source": ("environment" if env_key
                               else secret_store.key_source(p) if secure_key
                               else "legacy_settings" if legacy_key else None),
            "auth_method": ("iam" if p == "bedrock" else
                            "adc" if p == "vertexai" else
                            "optional_api_key" if p == "openweight" else "api_key"),
            "region": _aws_region() if p == "bedrock" else None,
        }
        if p == "vertexai":
            state.update(project=project, location=location,
                         configured=bool(project and location))
        elif p == "openweight":
            state.update(endpoint_host=endpoint_host,
                         configured=bool(endpoint and model))
        providers[p] = state

    connections = []
    for c in get_mcp_connections():
        pub = {k: v for k, v in c.items() if k != "authorization_token"}
        pub["token_set"] = bool(c.get("authorization_token"))
        connections.append(pub)

    active = providers[provider]
    legacy_jev_key = cfg.get("jev", {}).get("api_key")
    jev_secure_key = secure_keys.get("jev")
    jev_env_key = os.environ.get("TYPESAFE_API_KEY")
    jev_key = jev_env_key or jev_secure_key or legacy_jev_key
    return {
        "llm": {
            "provider": provider,
            "providers": providers,
            "model": active["model"],
            "api_key_set": active["api_key_set"],
            "api_key_source": active["api_key_source"],
            "secure_key_store_configured": secret_store.is_configured(),
            "secure_key_store_available": secure_store_available,
            "legacy_keys_present": bool(legacy_keys or has_legacy_mcp_tokens),
            "legacy_mcp_tokens_present": has_legacy_mcp_tokens,
        },
        "jev": {
            "api_key_set": bool(jev_key),
            "api_key_source": ("environment" if jev_env_key
                               else secret_store.key_source("jev") if jev_secure_key
                               else "legacy_settings" if legacy_jev_key else None),
            "model": cfg.get("jev", {}).get("model") or "",
            "secure_key_store_configured": secret_store.is_configured(),
            "secure_key_store_available": secure_store_available,
            "legacy_key_present": bool(legacy_jev_key),
        },
        "mcp_connections": connections,
        "chart_palette": _load().get("chart_palette") or DEFAULT_PALETTE,
    }

def update_llm_config(model: str | None = None,
                      api_key: str | None = None,
                      provider: str | None = None) -> dict:
    request = LLMConfigUpdate.model_validate({
        "model": model, "api_key": api_key, "provider": provider})
    model, api_key, provider = request.model, request.api_key, request.provider

    with _lock:
        cfg = _load()
        sec = _llm_section(cfg)
        target = provider if provider in PROVIDERS else sec["provider"]
        keys = sec["keys"]
        models = sec["models"]
        if (target not in ("bedrock", "vertexai")
                and api_key not in (None, "")):
            secure_keys = secret_store.read_keys()
            secure_keys[target] = api_key
            secret_store.write_keys(secure_keys)
            if target == "openweight":
                keys.pop(target, None)
        if model is not None and target != "openweight":
            models[target] = model
        if target in ("bedrock", "vertexai"):
            keys.pop(target, None)
        elif api_key is not None:
            if not api_key:
                keys.pop(target, None)
                secret_store.remove_key(target)

        new_provider = target if provider in PROVIDERS else sec["provider"]
        cfg["llm"] = {"provider": new_provider, "keys": keys, "models": models}
        _write(cfg)
    return public_config()


def migrate_legacy_keys() -> dict:
    with _lock:
        cfg = _load()
        sec = _llm_section(cfg)
        legacy_keys = {provider: value for provider, value in sec["keys"].items()
                       if provider in {"anthropic", "openai", "gemini", "openrouter",
                                       "openweight"}
                       and isinstance(value, str) and value}
        legacy_jev_key = cfg.get("jev", {}).get("api_key")
        if isinstance(legacy_jev_key, str) and legacy_jev_key:
            legacy_keys["jev"] = legacy_jev_key
        legacy_mcp_tokens = _legacy_mcp_tokens(cfg, strict=True)
        legacy_keys.update(legacy_mcp_tokens)
        if not legacy_keys:
            return {"migrated": 0}
        secure_keys = secret_store.read_keys()
        expected = {**legacy_keys, **secure_keys}
        secret_store.write_keys(expected)
        if secret_store.read_keys() != expected:
            raise secret_store.SecretStoreError(
                "Secure model-key migration could not be confirmed. Legacy keys "
                "remain in the local settings file.")
        llm = dict(cfg.get("llm", {}))
        disk_keys = dict(llm.get("keys", {}))
        for provider in legacy_keys:
            disk_keys.pop(provider, None)
        if disk_keys:
            llm["keys"] = disk_keys
        else:
            llm.pop("keys", None)
        raw_keys = llm.get("keys") or {}
        if ("anthropic" in legacy_keys and llm.get("api_key")
                and (not isinstance(raw_keys, dict)
                     or "anthropic" not in raw_keys)):
            llm.pop("api_key", None)
        cfg["llm"] = llm
        if "jev" in legacy_keys:
            integration = dict(cfg.get("jev", {}))
            integration.pop("api_key", None)
            cfg["jev"] = integration
        if legacy_mcp_tokens:
            clean_connections = []
            for connection in cfg.get("mcp_connections", []):
                if isinstance(connection, dict):
                    clean = dict(connection)
                    clean.pop("authorization_token", None)
                    clean_connections.append(clean)
                else:
                    clean_connections.append(connection)
            cfg["mcp_connections"] = clean_connections
        _write(cfg)
        return {"migrated": len(legacy_keys)}

def update_chart_palette(palette: str) -> dict:
    with _lock:
        cfg = _load()
        cfg["chart_palette"] = palette if palette in PALETTES else DEFAULT_PALETTE
        _write(cfg)
    return public_config()

def update_mcp_connections(connections: list[dict]) -> dict:
    connections = [MCPConnectionSettings.model_validate(item).model_dump() for item in connections]
    if len(connections) > 128 or len({item["name"] for item in connections}) != len(connections):
        raise ValueError("MCP connections need unique names and at most 128 entries.")
    with _lock:
        cfg = _load()
        existing = {c.get("name"): c for c in cfg.get("mcp_connections", [])
                    if isinstance(c, dict)}
        cleaned = []
        secure_keys = None
        for c in connections:
            if not isinstance(c, dict):
                raise ValueError("MCP connection configuration is invalid.")
            entry = {
                "name": str(c.get("name", "")).strip(),
                "label": str(c.get("label", "") or c.get("name", "")),
                "url": str(c.get("url", "")).strip(),
                "enabled": bool(c.get("enabled")),
                "note": str(c.get("note", "")),
            }
            if not entry["name"]:
                continue
            token = c.get("authorization_token")
            if token:
                if not isinstance(token, str) or len(token) > 8192:
                    raise ValueError("MCP authorization token is invalid.")
                if not _MCP_TOKEN_NAME.fullmatch(entry["name"]):
                    raise ValueError("MCP connection name cannot store a secure token.")
                if secure_keys is None:
                    secure_keys = secret_store.read_keys()
                secure_keys[f"mcp:{entry['name']}"] = token
            elif existing.get(entry["name"], {}).get("authorization_token"):
                entry["authorization_token"] = existing[entry["name"]]["authorization_token"]
            cleaned.append(entry)
        if secure_keys is not None:
            secret_store.write_keys(secure_keys)
        cfg["mcp_connections"] = cleaned
        _write(cfg)
    return public_config()

def _write(cfg: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = CONFIG_PATH.with_name(f".{CONFIG_PATH.name}.{uuid.uuid4().hex}.tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(json.dumps(cfg, indent=2))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(CONFIG_PATH)
    finally:
        temporary.unlink(missing_ok=True)
