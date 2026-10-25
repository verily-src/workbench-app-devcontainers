"""Resolve the explicitly configured Aurora resource for agent storage."""

import json
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class AgentStoreConfigError(RuntimeError):
    pass


class AgentStoreConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    resource_id: str = Field(min_length=1, max_length=128,
                             pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def config_path() -> Path:
    config_file = Path(os.environ.get(
        "STUDIO_CONFIG", str(Path(__file__).parent / "studio_config.json")))
    return config_file.with_name("agent_store_config.json")


def resource_id(explicit: str | None = None) -> str:
    configured = explicit or os.environ.get("STUDIO_AGENT_RESOURCE_ID", "").strip()
    if configured:
        raw = {"resource_id": configured}
        source = "explicit resource ID" if explicit else "STUDIO_AGENT_RESOURCE_ID"
    else:
        path = config_path()
        try:
            raw = json.loads(path.read_text())
        except FileNotFoundError:
            raise AgentStoreConfigError(
                "Set STUDIO_AGENT_RESOURCE_ID or configure resource_id in "
                f"{path}.") from None
        except (OSError, json.JSONDecodeError):
            raise AgentStoreConfigError(
                f"Agent store configuration could not be read from {path}.") from None
        source = str(path)
    try:
        return AgentStoreConfig.model_validate(raw).resource_id
    except ValidationError:
        raise AgentStoreConfigError(
            f"Agent store resource_id in {source} must contain 1 to 128 letters, "
            "numbers, periods, underscores, or hyphens, and start with a letter "
            "or number.") from None
