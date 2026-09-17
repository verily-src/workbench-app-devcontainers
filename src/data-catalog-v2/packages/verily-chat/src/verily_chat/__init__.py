"""
verily-chat — Chat over BigQuery metadata.

Public API
----------
Chat:
    chat(message, context, history?, model?, project_id?) -> ChatMessage

Context:
    build_catalog_system_prompt(context, mode?) -> str
    format_table_for_prompt(fq_table, tech?, sem?) -> str

Models:
    ChatMessage, ChatContext, ChatSession

Agent (requires optional deps):
    create_chat_agent(context, model?, project_id?) -> (graph, prompt)
    chat_agent(message, graph, history?) -> (ChatMessage, history)
"""

from verily_chat.models import ChatMessage, ChatContext, ChatSession
from verily_chat.chat import chat
from verily_chat.context import build_catalog_system_prompt, format_table_for_prompt

try:
    from verily_chat.agent import create_chat_agent, chat_agent
except ImportError:
    pass

__all__ = [
    "chat",
    "build_catalog_system_prompt",
    "format_table_for_prompt",
    "ChatMessage",
    "ChatContext",
    "ChatSession",
    "create_chat_agent",
    "chat_agent",
]
