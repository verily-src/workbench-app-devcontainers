"""
verily-chat data models.

  - ChatMessage: a single message in a conversation
  - ChatContext: metadata context for the LLM (profiles, project info)
  - ChatSession: a multi-turn conversation with context
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass
class ChatMessage:
    """A single message in a chat conversation."""

    role: str  # "user", "assistant", "system"
    content: str
    timestamp: str = ""
    sql: Optional[str] = None
    mode: str = "metadata"  # "metadata" or "agent"

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_json_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "mode": self.mode,
        }
        if self.sql:
            d["sql"] = self.sql
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ChatMessage:
        return cls(
            role=d.get("role", "user"),
            content=d.get("content", ""),
            timestamp=d.get("timestamp", ""),
            sql=d.get("sql"),
            mode=d.get("mode", "metadata"),
        )


@dataclass
class ChatContext:
    """Metadata context provided to the LLM."""

    project_id: str = ""
    billing_project: str = ""
    fq_table: Optional[str] = None
    tech_profiles: dict[str, dict[str, Any]] = field(default_factory=dict)
    sem_profiles: dict[str, dict[str, Any]] = field(default_factory=dict)
    table_summaries: list[dict[str, Any]] = field(default_factory=list)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "billing_project": self.billing_project,
            "fq_table": self.fq_table,
            "tech_profile_count": len(self.tech_profiles),
            "sem_profile_count": len(self.sem_profiles),
            "table_count": len(self.table_summaries),
        }


@dataclass
class ChatSession:
    """A multi-turn conversation session."""

    session_id: str = ""
    messages: list[ChatMessage] = field(default_factory=list)
    context: ChatContext = field(default_factory=ChatContext)
    created_at: str = ""
    mode: str = "metadata"

    def __post_init__(self):
        if not self.session_id:
            self.session_id = str(uuid.uuid4())
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def add_message(self, msg: ChatMessage) -> None:
        self.messages.append(msg)

    def clear(self) -> None:
        self.messages.clear()

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "messages": [m.to_json_dict() for m in self.messages],
            "context": self.context.to_json_dict(),
            "created_at": self.created_at,
            "mode": self.mode,
        }

    def to_json_string(self) -> str:
        return json.dumps(self.to_json_dict(), indent=2)
