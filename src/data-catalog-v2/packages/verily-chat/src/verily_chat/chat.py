"""
Metadata Q&A chat mode.

Stateless per-call: builds a system prompt from profiling context,
appends conversation history, and calls Gemini.
"""

from __future__ import annotations

import re
from typing import Optional

from verily_chat.context import build_catalog_system_prompt
from verily_chat.models import ChatContext, ChatMessage


def chat(
    message: str,
    context: ChatContext,
    history: list[ChatMessage] | None = None,
    model: str = "gemini-3-flash-preview",
    project_id: str | None = None,
) -> ChatMessage:
    """
    Send a message in metadata Q&A mode.

    Args:
        message: The user's question.
        context: Profiling metadata context.
        history: Prior conversation messages for multi-turn.
        model: Gemini model name.
        project_id: GCP project for Vertex AI billing.

    Returns:
        ChatMessage with the assistant's response.
    """
    from verily_profiler.llm import call_gemini

    system_prompt = build_catalog_system_prompt(context, mode="metadata")
    user_content = _build_user_content(message, history)

    response_text = call_gemini(
        system_prompt=system_prompt,
        user_message=user_content,
        model_name=model,
        project_id=project_id,
        temperature=0.3,
        max_output_tokens=8192,
    )

    sql = _extract_sql(response_text)

    return ChatMessage(
        role="assistant",
        content=response_text,
        sql=sql,
        mode="metadata",
    )


def _build_user_content(message: str, history: list[ChatMessage] | None) -> str:
    """Fold conversation history into the user message for context."""
    if not history:
        return message

    turns: list[str] = []
    for msg in history[-10:]:
        prefix = "User" if msg.role == "user" else "Assistant"
        turns.append(f"{prefix}: {msg.content}")
    turns.append(f"User: {message}")

    return "Conversation so far:\n\n" + "\n\n".join(turns) + "\n\nPlease respond to the latest User message."


def _extract_sql(text: str) -> str | None:
    match = re.search(r"```sql\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None
