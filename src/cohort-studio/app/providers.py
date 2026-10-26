import logging

import vertexai_auth
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

import agent_runtime

logger = logging.getLogger(__name__)

MAX_TURNS = agent_runtime.MAX_TURNS

TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "run_query",
        "description": "Count rows matching a filter set and preview the "
                       "first rows.",
        "parameters": {"type": "object", "properties": {
            "filters_json": {"type": "string", "description":
                "JSON array of filters, each {\"column\", \"kind\": "
                "\"categorical\"|\"range\", \"values\"?, \"min\"?, "
                "\"max\"?}. Pass \"[]\" to keep current UI filters."}},
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
                "JSON array of filters in addition to current UI filters. "
                "Pass \"[]\" for current UI filters only."}},
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
    kwargs = {"api_key": api_key, "timeout": 60.0, "max_retries": 0}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)

def _openai_messages(messages: list[BaseMessage]) -> list[dict]:
    result = []
    for message in messages:
        if isinstance(message, SystemMessage):
            result.append({"role": "system", "content": message.content})
        elif isinstance(message, HumanMessage):
            result.append({"role": "user", "content": message.content})
        elif isinstance(message, ToolMessage):
            result.append({"role": "tool", "tool_call_id": message.tool_call_id,
                           "content": message.content})
        elif isinstance(message, AIMessage):
            item = {"role": "assistant", "content": message.content or None}
            if message.tool_calls:
                item["tool_calls"] = [{
                    "id": call.get("id"), "type": "function",
                    "function": {"name": call["name"],
                                 "arguments": __import__("json").dumps(call["args"])},
                } for call in message.tool_calls]
            result.append(item)
    return result


def _openai_call(client, model: str, messages: list[BaseMessage], schemas: list[dict]):
    import json
    response = client.chat.completions.create(
        model=model, messages=_openai_messages(messages), tools=schemas,
        tool_choice="auto")
    choice = response.choices[0]
    raw = choice.message
    calls = []
    for item in raw.tool_calls or []:
        try:
            args = json.loads(item.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {"__invalid_arguments__": True}
        calls.append({"name": item.function.name, "args": args, "id": item.id})
    usage = response.usage
    prompt = (usage.prompt_tokens or 0) if usage else 0
    completion = (usage.completion_tokens or 0) if usage else 0
    metadata = ({"input_tokens": prompt, "output_tokens": completion,
                 "total_tokens": (usage.total_tokens or prompt + completion)}
                if usage else {})
    return AIMessage(content=raw.content or "", tool_calls=calls,
                     usage_metadata=metadata or None,
                     response_metadata={"finish_reason": getattr(choice, "finish_reason", None)})


def _anthropic_messages(messages: list[BaseMessage]):
    system = ""
    convo = []
    for message in messages:
        if isinstance(message, SystemMessage):
            system = message.content
        elif isinstance(message, HumanMessage):
            convo.append({"role": "user", "content": message.content})
        elif isinstance(message, AIMessage):
            content = []
            if message.content:
                content.append({"type": "text", "text": message.content})
            for call in message.tool_calls:
                content.append({"type": "tool_use", "id": call["id"],
                                "name": call["name"], "input": call["args"]})
            convo.append({"role": "assistant", "content": content or ""})
        elif isinstance(message, ToolMessage):
            block = {"type": "tool_result", "tool_use_id": message.tool_call_id,
                     "content": message.content}
            if convo and convo[-1]["role"] == "user" and isinstance(convo[-1]["content"], list):
                convo[-1]["content"].append(block)
            else:
                convo.append({"role": "user", "content": [block]})
    return system, convo


def _anthropic_call(client, model: str, messages: list[BaseMessage], schemas: list[dict]):
    system, convo = _anthropic_messages(messages)
    tools = [{"name": item["function"]["name"],
              "description": item["function"].get("description", ""),
              "input_schema": item["function"].get("parameters", {"type": "object"})}
             for item in schemas]
    response = client.messages.create(model=model, max_tokens=8192,
                                      system=system, messages=convo, tools=tools)
    content = []
    calls = []
    for block in response.content:
        if getattr(block, "type", "") == "text":
            content.append(block.text)
        elif getattr(block, "type", "") == "tool_use":
            calls.append({"name": block.name, "args": block.input,
                          "id": block.id})
    usage = getattr(response, "usage", None)
    metadata = ({"input_tokens": getattr(usage, "input_tokens", 0) or 0,
                 "output_tokens": getattr(usage, "output_tokens", 0) or 0,
                 "total_tokens": ((getattr(usage, "input_tokens", 0) or 0)
                                  + (getattr(usage, "output_tokens", 0) or 0))}
                if usage else {})
    if response.stop_reason == "refusal":
        content = ["I can't help with that request."]
    return AIMessage(content="\n".join(content), tool_calls=calls,
                     usage_metadata=metadata or None,
                     response_metadata={"stop_reason": response.stop_reason})


def run(provider: str, model: str, api_key: str, base_url: str | None,
        system: str, messages: list[dict], tool_impls: dict,
        tool_schemas: list[dict] | None = None,
        vertex_config: dict | None = None, on_step=None,
        max_turns: int = agent_runtime.MAX_TURNS) -> dict:
    schemas = tool_schemas if tool_schemas is not None else TOOL_SCHEMAS
    vertex_auth = None
    if provider == "vertexai":
        if not vertex_config:
            raise vertexai_auth.VertexAuthUnavailable(
                "Vertex AI project and location are required.")
        client, credentials, request = vertexai_auth.new_client(
            vertex_config.get("project"), vertex_config.get("location"))
        client.timeout = 60.0
        client.max_retries = 0
        vertex_auth = (credentials, request)
    elif provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=api_key, timeout=60.0,
                                     max_retries=0)
    else:
        client = _client(api_key, base_url)

    def invoke(model_messages, tool_defs):
        if vertex_auth:
            vertexai_auth.refresh_client(client, *vertex_auth)
        if provider == "anthropic":
            return _anthropic_call(client, model, model_messages, tool_defs)
        return _openai_call(client, model, model_messages, tool_defs)

    try:
        return agent_runtime.run(provider, model, system, messages, tool_impls,
                                 schemas, invoke, on_step=on_step,
                                 max_turns=max_turns)
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
