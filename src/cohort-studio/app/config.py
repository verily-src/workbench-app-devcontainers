"""Persistent app configuration (Settings UI backend).

Stored as JSON next to the app code so it survives server restarts and
self-updates within a container's lifetime (wiped on VM recreate, which
is acceptable for a dev workspace — the API key can be re-entered).
The ANTHROPIC_API_KEY environment variable, when set, takes precedence
over the stored key.
"""

import json
import os
import threading
from pathlib import Path

CONFIG_PATH = Path(os.environ.get(
    "STUDIO_CONFIG", str(Path(__file__).parent / "studio_config.json")))

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_PALETTE = "verily"
PALETTES = ("verily", "indigo", "amber", "crimson", "slate")

# The chat agent and Ask AI can run on any of these providers. Anthropic
# is the default and uses the native SDK; OpenAI and Gemini share one
# OpenAI-compatible code path (Gemini exposes an OpenAI-shaped endpoint).
DEFAULT_PROVIDER = "anthropic"
PROVIDERS = ("anthropic", "openai", "gemini")

# Per-provider default model. Only Anthropic is pinned — OpenAI/Gemini
# model IDs move fast, so we leave them blank and let the user set one in
# Settings rather than hardcode an ID that may be retired.
PROVIDER_DEFAULT_MODEL = {
    "anthropic": DEFAULT_MODEL,
    "openai": "",
    "gemini": "",
}

# Where the OpenAI-compatible client points per provider. Anthropic uses
# its own SDK (no base_url). Gemini's OpenAI-compatible endpoint is
# stable and documented; OpenAI uses the SDK default.
PROVIDER_BASE_URL = {
    "openai": None,
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
}

# Environment variables consulted (in order) for each provider's key.
PROVIDER_ENV_KEYS = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
}


def _env_key(provider: str) -> str | None:
    for var in PROVIDER_ENV_KEYS.get(provider, ()):
        if os.environ.get(var):
            return os.environ[var]
    return None


def _llm_section(cfg: dict) -> dict:
    """Read the llm config, migrating the old single-provider shape
    ({api_key, model}) into the per-provider shape on the fly."""
    llm = dict(cfg.get("llm", {}))
    keys = dict(llm.get("keys", {}))
    models = dict(llm.get("models", {}))
    # Back-compat: an older config stored one Anthropic key/model flat.
    if "api_key" in llm and "anthropic" not in keys:
        keys["anthropic"] = llm["api_key"]
    if "model" in llm and "anthropic" not in models:
        models["anthropic"] = llm["model"]
    provider = llm.get("provider") or DEFAULT_PROVIDER
    if provider not in PROVIDERS:
        provider = DEFAULT_PROVIDER
    return {"provider": provider, "keys": keys, "models": models}

# Seeded MCP client connections, editable in Settings. URLs are left for
# the user to fill in: the Verily Workbench MCP endpoint has not shipped
# in this wb CLI build, and community research servers (bioRxiv, PubMed)
# are deployment-specific — we do not guess endpoints.
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
    """Full LLM config for the active provider, including the secret key
    and base URL — internal use only. Env key wins over the stored key."""
    sec = _llm_section(_load())
    provider = sec["provider"]
    api_key = _env_key(provider) or sec["keys"].get(provider)
    model = (sec["models"].get(provider)
             or PROVIDER_DEFAULT_MODEL.get(provider) or "")
    return {
        "provider": provider,
        "api_key": api_key,
        "model": model,
        "base_url": PROVIDER_BASE_URL.get(provider),
    }


def get_mcp_connections() -> list[dict]:
    """Stored MCP client connections, seeded with defaults on first read."""
    stored = _load().get("mcp_connections")
    if stored is None:
        return [dict(c) for c in DEFAULT_MCP_CONNECTIONS]
    return stored


def public_config() -> dict:
    """Config safe to return to the browser — secrets are never echoed."""
    sec = _llm_section(_load())
    provider = sec["provider"]

    providers = {}
    for p in PROVIDERS:
        env_key = _env_key(p)
        stored_key = sec["keys"].get(p)
        key = env_key or stored_key
        providers[p] = {
            "model": sec["models"].get(p) or PROVIDER_DEFAULT_MODEL.get(p) or "",
            "api_key_set": bool(key),
            "api_key_hint": f"…{key[-4:]}" if key else None,
            "api_key_source": ("environment" if env_key
                               else "settings" if stored_key else None),
        }

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
            # Flattened active-provider fields (kept for compatibility
            # with callers that just want the current model/key state).
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
    """Update LLM settings. `model` and `api_key` apply to `provider`
    when given, otherwise to the currently-active provider."""
    with _lock:
        cfg = _load()
        sec = _llm_section(cfg)
        target = provider if provider in PROVIDERS else sec["provider"]
        keys = sec["keys"]
        models = sec["models"]
        if model is not None:
            models[target] = model
        if api_key is not None:
            if api_key:
                keys[target] = api_key
            else:
                keys.pop(target, None)  # empty string clears the key
        # Switching the active provider is an explicit provider= arg.
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
    """Replace the MCP connection list. A connection without an
    authorization_token keeps any token already stored under its name."""
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
