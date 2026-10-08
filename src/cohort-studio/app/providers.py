"""OpenAI-compatible chat-agent loop for the OpenAI and Gemini providers.

Anthropic keeps its native SDK tool runner (see agent.py). OpenAI and
Gemini share this one manual loop: the official `openai` SDK talks to
OpenAI directly and to Gemini through its documented OpenAI-compatible
endpoint (a base_url switch). The tool schemas below mirror, by hand, the
five callables agent.build_tools() produces — the Anthropic path derives
them from docstrings, which does not carry over to this wire format.
"""

import json
import logging

logger = logging.getLogger(__name__)

MAX_TURNS = 8

# OpenAI function-tool schemas mirroring agent.build_tools(). Keep arg
# names in sync with the callables there.
TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "run_query",
        "description": "Count rows matching a filter set and preview the "
                       "first rows.",
        "parameters": {"type": "object", "properties": {
            "filters_json": {"type": "string", "description":
                "JSON array of filters, each {\"column\", \"kind\": "
                "\"categorical\"|\"range\", \"values\"?, \"min\"?, "
                "\"max\"?}. Pass \"[]\" for the full dataset."}},
            "required": ["filters_json"]}}},
    {"type": "function", "function": {
        "name": "aggregate",
        "description": "Compute a statistic, optionally grouped and filtered.",
        "parameters": {"type": "object", "properties": {
            "agg": {"type": "string", "enum":
                ["count", "mean", "median", "min", "max", "sum", "nunique"]},
            "column": {"type": "string", "description":
                "Numeric column the statistic applies to."},
            "group_by": {"type": "string", "description":
                "Optional categorical column to group by."},
            "filters_json": {"type": "string", "description":
                "JSON array of filters to apply first. \"[]\" for none."}},
            "required": ["agg"]}}},
    {"type": "function", "function": {
        "name": "set_filters",
        "description": "Replace the filters shown in the UI; the user sees "
                       "the grid, counts and charts update immediately.",
        "parameters": {"type": "object", "properties": {
            "filters_json": {"type": "string", "description":
                "The COMPLETE new filter set as a JSON array. \"[]\" clears."},
            "reason": {"type": "string", "description":
                "Short phrase shown to the user, e.g. \"liver, RIN ≥ 7\"."}},
            "required": ["filters_json", "reason"]}}},
    {"type": "function", "function": {
        "name": "add_chart",
        "description": "Add a chart card to the user's dashboard.",
        "parameters": {"type": "object", "properties": {
            "kind": {"type": "string",
                     "enum": ["bar", "histogram", "scatter", "heatmap"]},
            "x": {"type": "string", "description": "Column for the main axis."},
            "y": {"type": "string", "description":
                  "Second column — required for scatter and heatmap."}},
            "required": ["kind", "x"]}}},
    {"type": "function", "function": {
        "name": "remove_chart",
        "description": "Remove a chart from the dashboard by zero-based index.",
        "parameters": {"type": "object", "properties": {
            "index": {"type": "integer",
                      "description": "Zero-based position in the chart list."}},
            "required": ["index"]}}},
]


def _client(api_key: str, base_url: str | None):
    from openai import OpenAI
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def run(provider: str, model: str, api_key: str, base_url: str | None,
        system: str, messages: list[dict], tool_impls: dict) -> dict:
    """Drive the OpenAI-compatible tool loop to completion.

    tool_impls maps a tool name to the plain callable from
    agent.build_tools(). Returns {reply, usage, tool_calls, turns}.
    """
    client = _client(api_key, base_url)
    convo = [{"role": "system", "content": system}] + messages
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    tool_calls: list[str] = []

    for _turn in range(MAX_TURNS):
        # No explicit max_tokens: the OpenAI reasoning-model line rejects
        # it (wants max_completion_tokens) and the model field is free
        # text, so we let the provider default apply.
        resp = client.chat.completions.create(
            model=model, messages=convo,
            tools=TOOL_SCHEMAS, tool_choice="auto")
        if resp.usage:
            usage["prompt_tokens"] += resp.usage.prompt_tokens or 0
            usage["completion_tokens"] += resp.usage.completion_tokens or 0
            usage["total_tokens"] += resp.usage.total_tokens or 0
        choice = resp.choices[0]
        msg = choice.message
        # Append the assistant turn verbatim so tool_call_ids line up.
        convo.append(msg.model_dump(exclude_none=True))
        if not msg.tool_calls:
            return {"reply": (msg.content or "(done)").strip(), "usage": usage,
                    "tool_calls": tool_calls, "turns": _turn + 1}
        for call in msg.tool_calls:
            name = call.function.name
            tool_calls.append(name)
            try:
                kwargs = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                kwargs = {}
            impl = tool_impls.get(name)
            if impl is None:
                result = json.dumps({"error": f"unknown tool {name}"})
            else:
                try:
                    result = impl(**kwargs)
                except Exception as e:  # tool errors feed back to the model
                    result = json.dumps({"error": str(e)})
            convo.append({"role": "tool", "tool_call_id": call.id,
                          "content": result})

    return {"reply": "I wasn't able to finish that in a reasonable number of "
            "steps — try narrowing the request.", "usage": usage,
            "tool_calls": tool_calls, "turns": MAX_TURNS}
