import json
import os
import threading
from pathlib import Path

CONFIG_PATH = Path(os.environ.get(
    "STUDIO_CONFIG", str(Path(__file__).parent / "studio_config.json")))

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_PALETTE = "verily"
PALETTES = ("verily", "indigo", "amber", "crimson", "slate")

DEFAULT_PROVIDER = "anthropic"
PROVIDERS = ("anthropic", "openai", "gemini", "openrouter", "bedrock",
             "vertexai")

PROVIDER_DEFAULT_MODEL = {
    "anthropic": DEFAULT_MODEL,
    "openai": "",
    "gemini": "",
    "openrouter": "",
    "bedrock": "",
    "vertexai": "",
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
}

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

_lock = threading.Lock()

def _load() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def get_llm_config() -> dict:

    sec = _llm_section(_load())
    provider = sec["provider"]
    api_key = (None if provider in ("bedrock", "vertexai")
               else _env_key(provider) or sec["keys"].get(provider))
    model = (sec["models"].get(provider)
             or PROVIDER_DEFAULT_MODEL.get(provider) or "")
    out = {
        "provider": provider,
        "api_key": api_key,
        "model": model,
        "base_url": PROVIDER_BASE_URL.get(provider),
        "region": _aws_region() if provider == "bedrock" else None,
    }
    if provider == "vertexai":
        out.update(project=_vertex_project(), location=_vertex_location())
    return out

def get_mcp_connections() -> list[dict]:

    stored = _load().get("mcp_connections")
    if stored is None:
        return [dict(c) for c in DEFAULT_MCP_CONNECTIONS]
    return stored

def public_config() -> dict:

    sec = _llm_section(_load())
    provider = sec["provider"]

    providers = {}
    for p in PROVIDERS:
        env_key = None if p in ("bedrock", "vertexai") else _env_key(p)
        stored_key = None if p in ("bedrock", "vertexai") else sec["keys"].get(p)
        key = env_key or stored_key
        project = _vertex_project() if p == "vertexai" else None
        location = _vertex_location() if p == "vertexai" else None
        state = {
            "model": sec["models"].get(p) or PROVIDER_DEFAULT_MODEL.get(p) or "",
            "api_key_set": bool(key),
            "api_key_hint": f"…{key[-4:]}" if key else None,
            "api_key_source": ("environment" if env_key
                               else "settings" if stored_key else None),
            "auth_method": ("iam" if p == "bedrock" else
                            "adc" if p == "vertexai" else "api_key"),
            "region": _aws_region() if p == "bedrock" else None,
        }
        if p == "vertexai":
            state.update(project=project, location=location,
                         configured=bool(project and location))
        providers[p] = state

    connections = []
    for c in get_mcp_connections():
        pub = {k: v for k, v in c.items() if k != "authorization_token"}
        pub["token_set"] = bool(c.get("authorization_token"))
        connections.append(pub)

    active = providers[provider]
    return {
        "llm": {
            "provider": provider,
            "providers": providers,

            "model": active["model"],
            "api_key_set": active["api_key_set"],
            "api_key_hint": active["api_key_hint"],
            "api_key_source": active["api_key_source"],
        },
        "mcp_connections": connections,
        "chart_palette": _load().get("chart_palette") or DEFAULT_PALETTE,
    }

def update_llm_config(model: str | None = None,
                      api_key: str | None = None,
                      provider: str | None = None) -> dict:

    with _lock:
        cfg = _load()
        sec = _llm_section(cfg)
        target = provider if provider in PROVIDERS else sec["provider"]
        keys = sec["keys"]
        models = sec["models"]
        if model is not None:
            models[target] = model
        if target in ("bedrock", "vertexai"):
            keys.pop(target, None)
        elif api_key is not None:
            if api_key:
                keys[target] = api_key
            else:
                keys.pop(target, None)

        new_provider = target if provider in PROVIDERS else sec["provider"]
        cfg["llm"] = {"provider": new_provider, "keys": keys, "models": models}
        _write(cfg)
    return public_config()

def update_chart_palette(palette: str) -> dict:
    with _lock:
        cfg = _load()
        cfg["chart_palette"] = palette if palette in PALETTES else DEFAULT_PALETTE
        _write(cfg)
    return public_config()

def update_mcp_connections(connections: list[dict]) -> dict:

    with _lock:
        cfg = _load()
        existing = {c.get("name"): c for c in cfg.get("mcp_connections", [])}
        cleaned = []
        for c in connections:
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
                entry["authorization_token"] = token
            elif existing.get(entry["name"], {}).get("authorization_token"):
                entry["authorization_token"] =                     existing[entry["name"]]["authorization_token"]
            cleaned.append(entry)
        cfg["mcp_connections"] = cleaned
        _write(cfg)
    return public_config()

def _write(cfg: dict):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    try:
        CONFIG_PATH.chmod(0o600)
    except OSError:
        pass
