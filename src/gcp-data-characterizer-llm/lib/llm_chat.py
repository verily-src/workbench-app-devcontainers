"""LLM-backed 'talk to your data' using OpenAI-compatible API (user provides key)."""
import json
from openai import OpenAI


def chat_with_data(
    api_key: str,
    base_url: str | None,
    model: str,
    data_summary: str,
    schema_and_sample: str,
    question: str,
    conversation: list[dict],
) -> tuple[str, list[dict]]:
    """
    Send user question + data context to LLM. base_url can be None for OpenAI, or set for compatible endpoints.
    Returns (response_text, updated_messages).
    """
    if not api_key or not api_key.strip():
        return "Please set your LLM API key in the sidebar.", conversation

    client = OpenAI(api_key=api_key.strip(), base_url=base_url or "https://api.openai.com/v1")

    system = """You are a helpful data analyst. The user is asking questions about a dataset.
Use the following context about the data to answer accurately. If the question cannot be answered from the context, say so.
You can describe patterns, suggest aggregations, or answer factual questions about the schema and sample.
Be concise. If the user asks for code (e.g. Python/pandas), you may provide it in a markdown code block."""

    user_content = f"## Data summary\n{data_summary}\n\n## Schema and sample\n{schema_and_sample}\n\n## User question\n{question}"

    messages = conversation + [{"role": "user", "content": user_content}]

    try:
        response = client.chat.completions.create(
            model=model.strip() or "gpt-4o-mini",
            messages=[{"role": "system", "content": system}] + messages,
            max_tokens=1024,
        )
        reply = response.choices[0].message.content
        return reply, messages + [{"role": "assistant", "content": reply}]
    except Exception as e:
        return f"LLM error: {e}", conversation
