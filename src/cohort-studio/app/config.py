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
    """Full LLM config including the secret key — internal use only."""
    cfg = _load().get("llm", {})
    return {
        "api_key": os.environ.get("ANTHROPIC_API_KEY") or cfg.get("api_key"),
        "model": cfg.get("model") or DEFAULT_MODEL,
    }


def get_mcp_connections() -> list[dict]:
    """Stored MCP client connections, seeded with defaults on first read."""
    stored = _load().get("mcp_connections")
    if stored is None:
        return [dict(c) for c in DEFAULT_MCP_CONNECTIONS]
    return stored


def public_config() -> dict:
    """Config safe to return to the browser — secrets are never echoed."""
    cfg = _load().get("llm", {})
    stored_key = cfg.get("api_key")
    env_key = os.environ.get("ANTHROPIC_API_KEY")
    key = env_key or stored_key
    connections = []
    for c in get_mcp_connections():
        pub = {k: v for k, v in c.items() if k != "authorization_token"}
        pub["token_set"] = bool(c.get("authorization_token"))
        connections.append(pub)
    return {
        "llm": {
            "model": cfg.get("model") or DEFAULT_MODEL,
            "api_key_set": bool(key),
            "api_key_hint": f"…{key[-4:]}" if key else None,
            "api_key_source": ("environment" if env_key
                               else "settings" if stored_key else None),
        },
        "mcp_connections": connections,
        "chart_palette": _load().get("chart_palette") or DEFAULT_PALETTE,
    }


def update_llm_config(model: str | None = None,
                      api_key: str | None = None) -> dict:
    with _lock:
        cfg = _load()
        llm = cfg.setdefault("llm", {})
        if model is not None:
            llm["model"] = model
        if api_key is not None:
            llm["api_key"] = api_key or None  # empty string clears the key
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
