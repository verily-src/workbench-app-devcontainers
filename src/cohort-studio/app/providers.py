import json
import logging

import vertexai_auth
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

import agent_runtime

logger = logging.getLogger(__name__)

MAX_TURNS = agent_runtime.MAX_TURNS
# Per-request timeout. Retries are handled by agent_runtime (bounded
# exponential backoff), so the SDK's own retries stay off.
REQUEST_TIMEOUT_SECONDS = 180.0
_CACHE = {"type": "ephemeral"}

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
    kwargs = {"api_key": api_key, "timeout": REQUEST_TIMEOUT_SECONDS, "max_retries": 0}
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
                                 "arguments": json.dumps(call["args"])},
                } for call in message.tool_calls]
            result.append(item)
    return result


def _openai_message(content: str, raw_calls: list[tuple[str | None, str, str]], usage,
                    finish_reason) -> AIMessage:
    calls = []
    for call_id, name, arguments in raw_calls:
        try:
            args = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            args = {"__invalid_arguments__": True}
        if not isinstance(args, dict):
            args = {"__invalid_arguments__": True}
        calls.append({"name": name, "args": args, "id": call_id})
    prompt = (getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
    completion = (getattr(usage, "completion_tokens", 0) or 0) if usage else 0
    metadata = ({"input_tokens": prompt, "output_tokens": completion,
                 "total_tokens": (getattr(usage, "total_tokens", 0) or prompt + completion)}
                if usage else {})
    cached = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", None) \
        if usage else None
    if metadata and isinstance(cached, int):
        metadata["input_token_details"] = {"cache_read": cached}
    return AIMessage(content=content or "", tool_calls=calls,
                     usage_metadata=metadata or None,
                     response_metadata={"finish_reason": finish_reason})


def _openai_call(client, model: str, messages: list[BaseMessage], schemas: list[dict],
                 tool_choice: str | None = None, on_text=None, stream_usage: bool = True):
    """Chat Completions call. With ``on_text`` the response is streamed and
    text deltas are passed to it as they arrive; tool calls are assembled
    from their streamed fragments."""
    kwargs = {"model": model, "messages": _openai_messages(messages), "tools": schemas,
              "tool_choice": tool_choice or "auto"}
    if on_text is None:
        response = client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        raw = choice.message
        return _openai_message(
            raw.content or "",
            [(item.id, item.function.name, item.function.arguments)
             for item in raw.tool_calls or []],
            response.usage, getattr(choice, "finish_reason", None))
    if stream_usage:
        kwargs["stream_options"] = {"include_usage": True}
    stream = client.chat.completions.create(stream=True, **kwargs)
    text: list[str] = []
    calls: dict[int, dict] = {}
    usage = None
    finish_reason = None
    try:
        for chunk in stream:
            if getattr(chunk, "usage", None):
                usage = chunk.usage
            for choice in getattr(chunk, "choices", None) or []:
                delta = getattr(choice, "delta", None)
                finish_reason = getattr(choice, "finish_reason", None) or finish_reason
                if delta is None:
                    continue
                if getattr(delta, "content", None):
                    text.append(delta.content)
                    on_text(delta.content)
                for item in getattr(delta, "tool_calls", None) or []:
                    index = getattr(item, "index", None)
                    slot = calls.setdefault(index if isinstance(index, int) else len(calls),
                                            {"id": None, "name": "", "arguments": []})
                    if getattr(item, "id", None):
                        slot["id"] = item.id
                    function = getattr(item, "function", None)
                    if function is not None:
                        if getattr(function, "name", None) and not slot["name"]:
                            slot["name"] = function.name
                        if getattr(function, "arguments", None):
                            slot["arguments"].append(function.arguments)
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            close()
    return _openai_message(
        "".join(text),
        [(slot["id"], slot["name"], "".join(slot["arguments"]))
         for _, slot in sorted(calls.items())],
        usage, finish_reason)


def _blocks(content) -> list[dict]:
    if isinstance(content, list):
        return list(content)
    return [{"type": "text", "text": content}] if content else []


def _append(convo: list[dict], role: str, content):
    """Append a turn, merging consecutive same-role turns into one."""
    if convo and convo[-1]["role"] == role:
        convo[-1]["content"] = _blocks(convo[-1]["content"]) + _blocks(content)
    else:
        convo.append({"role": role, "content": content})


def _anthropic_messages(messages: list[BaseMessage]):
    system = ""
    convo = []
    for message in messages:
        if isinstance(message, SystemMessage):
            system = message.content
        elif isinstance(message, HumanMessage):
            _append(convo, "user", message.content)
        elif isinstance(message, AIMessage):
            content = []
            if message.content:
                content.append({"type": "text", "text": message.content})
            for call in message.tool_calls:
                content.append({"type": "tool_use", "id": call["id"],
                                "name": call["name"], "input": call["args"]})
            _append(convo, "assistant", content or "")
        elif isinstance(message, ToolMessage):
            _append(convo, "user", [{"type": "tool_result", "tool_use_id": message.tool_call_id,
                                     "content": message.content}])
    return system, convo


def _cache_last_message(convo: list[dict]):
    """Mark the end of the conversation so the growing prefix is cached."""
    if not convo:
        return
    blocks = _blocks(convo[-1]["content"])
    if not blocks:
        return
    blocks[-1] = {**blocks[-1], "cache_control": _CACHE}
    convo[-1]["content"] = blocks


def _anthropic_request(messages: list[BaseMessage], schemas: list[dict],
                       tool_choice: str | None = None) -> dict:
    system, convo = _anthropic_messages(messages)
    _cache_last_message(convo)
    tools = [{"name": item["function"]["name"],
              "description": item["function"].get("description", ""),
              "input_schema": item["function"].get("parameters", {"type": "object"})}
             for item in schemas]
    if tools:
        tools[-1] = {**tools[-1], "cache_control": _CACHE}
    kwargs = {"tool_choice": {"type": tool_choice}} if tool_choice and tools else {}
    return {"max_tokens": 8192,
            "system": [{"type": "text", "text": system, "cache_control": _CACHE}] if system else [],
            "messages": convo, "tools": tools, **kwargs}


def _anthropic_call(client, model: str, messages: list[BaseMessage], schemas: list[dict],
                    tool_choice: str | None = None, on_text=None):
    """Messages API call. With ``on_text`` (and a client that supports it) the
    response is streamed; the SDK assembles tool_use inputs and final usage,
    so the result is mapped exactly like a blocking response."""
    request = _anthropic_request(messages, schemas, tool_choice)
    stream = getattr(client.messages, "stream", None) if on_text is not None else None
    if stream is None:
        response = client.messages.create(model=model, **request)
    else:
        with stream(model=model, **request) as events:
            for event in events:
                if getattr(event, "type", "") == "text" and getattr(event, "text", ""):
                    on_text(event.text)
            response = events.get_final_message()
    return _anthropic_response(response)


def _anthropic_response(response) -> AIMessage:
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
    cache_read = getattr(usage, "cache_read_input_tokens", None) if usage else None
    cache_write = getattr(usage, "cache_creation_input_tokens", None) if usage else None
    if metadata and (isinstance(cache_read, int) or isinstance(cache_write, int)):
        metadata["input_token_details"] = {"cache_read": cache_read or 0,
                                           "cache_creation": cache_write or 0}
    if response.stop_reason == "refusal":
        content = ["I can't help with that request."]
    return AIMessage(content="\n".join(content), tool_calls=calls,
                     usage_metadata=metadata or None,
                     response_metadata={"stop_reason": response.stop_reason})


def _is_stream_rejection(exc: Exception) -> bool:
    return agent_runtime.error_status(exc) in (400, 404, 415, 422) \
        and "stream" in str(exc).lower()


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
        client.timeout = REQUEST_TIMEOUT_SECONDS
        client.max_retries = 0
        vertex_auth = (credentials, request)
    elif provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS,
                                     max_retries=0)
    else:
        client = _client(api_key, base_url)

    # Some OpenAI-compatible servers reject stream_options or streaming
    # itself; the first rejection turns that feature off for this run.
    streaming = {"enabled": True, "usage": True}

    def invoke(model_messages, tool_defs, tool_choice=None, on_text=None):
        if vertex_auth:
            vertexai_auth.refresh_client(client, *vertex_auth)
        if provider == "anthropic":
            return _anthropic_call(client, model, model_messages, tool_defs,
                                   tool_choice=tool_choice, on_text=on_text)
        while True:
            live = on_text if streaming["enabled"] else None
            try:
                return _openai_call(client, model, model_messages, tool_defs,
                                    tool_choice=tool_choice, on_text=live,
                                    stream_usage=streaming["usage"])
            except Exception as exc:
                if live is None or not _is_stream_rejection(exc):
                    raise
                key = "usage" if streaming["usage"] and "stream_options" in str(exc) else "enabled"
                logger.info("Provider rejected %s; continuing without it.",
                            "stream_options" if key == "usage" else "streaming")
                streaming[key] = False

    try:
        return agent_runtime.run(provider, model, system, messages, tool_impls,
                                 schemas, invoke, on_step=on_step,
                                 max_turns=max_turns)
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
