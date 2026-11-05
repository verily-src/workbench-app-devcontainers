import json
import logging
import re

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

import agent_runtime

MAX_TURNS = agent_runtime.MAX_TURNS
# Retries are handled by agent_runtime, so botocore makes a single attempt.
READ_TIMEOUT_SECONDS = 180
_CACHE_POINT = {"cachePoint": {"type": "default"}}
logger = logging.getLogger(__name__)


class StreamEventError(Exception):
    """An error event inside a ConverseStream response, shaped like a
    botocore ClientError so agent_runtime can classify it."""

    def __init__(self, name: str, detail: dict | None):
        code = name[:1].upper() + name[1:]
        message = str((detail or {}).get("message") or code)[:300]
        super().__init__(message)
        self.response = {"Error": {"Code": code, "Message": message},
                         "ResponseMetadata": {}}

def _client(region: str):
    import boto3
    from botocore.config import Config
    return boto3.client(
        "bedrock-runtime", region_name=region,
        config=Config(connect_timeout=5, read_timeout=READ_TIMEOUT_SECONDS,
                      retries={"total_max_attempts": 1, "mode": "standard"}))


def _supports_cache(model: str) -> bool:
    """Converse prompt caching is available for recent Claude models only;
    older ones reject cachePoint blocks."""
    model = (model or "").lower()
    return "claude" in model and not re.search(
        r"claude-(instant|v2|3-haiku|3-sonnet|3-opus|3-5-sonnet)", model)


def _is_cache_rejection(exc: Exception) -> bool:
    return (agent_runtime.error_code(exc) == "ValidationException"
            and re.search(r"cach", str(exc), re.I) is not None)

def _tools(schemas: list[dict]) -> list[dict]:
    tools = []
    for schema in schemas:
        function = schema["function"]
        tools.append({"toolSpec": {
            "name": function["name"],
            "description": function.get("description", ""),
            "inputSchema": {"json": function.get("parameters", {
                "type": "object", "properties": {}})},
        }})
    return tools

def _append(convo: list[dict], role: str, content: list[dict]):
    """Converse rejects consecutive same-role turns, so merge them."""
    if not content:
        return
    if convo and convo[-1]["role"] == role:
        convo[-1]["content"].extend(content)
    else:
        convo.append({"role": role, "content": list(content)})


def _messages(messages: list[BaseMessage]) -> list[dict]:
    convo = []
    for message in messages:
        if isinstance(message, SystemMessage):
            continue
        if isinstance(message, HumanMessage):
            _append(convo, "user", [{"text": message.content}] if message.content else [])
        elif isinstance(message, AIMessage):
            content = ([{"text": message.content}] if message.content else [])
            content.extend({"toolUse": {"toolUseId": call["id"],
                                         "name": call["name"],
                                         "input": call["args"]}}
                           for call in message.tool_calls)
            _append(convo, "assistant", content)
        elif isinstance(message, ToolMessage):
            try:
                parsed = json.loads(message.content)
            except (TypeError, json.JSONDecodeError):
                parsed = None
            block = {"toolResult": {"toolUseId": message.tool_call_id,
                                    "content": ([{"json": parsed}]
                                                if isinstance(parsed, dict)
                                                else [{"text": str(message.content)}])}}
            _append(convo, "user", [block])
    return convo

def _is_stream_denied(exc: Exception) -> bool:
    """Streaming needs bedrock:InvokeModelWithResponseStream, which a role
    allowed only InvokeModel lacks."""
    return agent_runtime.error_code(exc) in ("AccessDeniedException",
                                             "UnrecognizedClientException") \
        or (agent_runtime.error_code(exc) == "ValidationException"
            and "stream" in str(exc).lower())


def _usage(used: dict) -> dict:
    usage = {"input_tokens": used.get("inputTokens", 0) or 0,
             "output_tokens": used.get("outputTokens", 0) or 0,
             "total_tokens": used.get("totalTokens", 0) or 0}
    read, write = used.get("cacheReadInputTokens"), used.get("cacheWriteInputTokens")
    if isinstance(read, int) or isinstance(write, int):
        usage["input_token_details"] = {"cache_read": read or 0, "cache_creation": write or 0}
    return usage


def _message(content: list[dict], used: dict) -> AIMessage:
    calls = [{"name": block["toolUse"]["name"], "args": block["toolUse"].get("input") or {},
              "id": block["toolUse"]["toolUseId"]} for block in content if "toolUse" in block]
    return AIMessage(content="\n".join(block["text"] for block in content if "text" in block),
                     tool_calls=calls, usage_metadata=_usage(used))


def _read_stream(response: dict, on_text) -> tuple[list[dict], dict]:
    """Assemble ConverseStream events into Converse-shaped content blocks."""
    blocks: dict[int, dict] = {}
    used: dict = {}
    stream = response.get("stream") or []
    try:
        for event in stream:
            if "contentBlockStart" in event:
                start = event["contentBlockStart"]
                tool = (start.get("start") or {}).get("toolUse")
                if tool:
                    blocks[start.get("contentBlockIndex", len(blocks))] = {
                        "tool": {"toolUseId": tool.get("toolUseId"), "name": tool.get("name")},
                        "input": []}
            elif "contentBlockDelta" in event:
                body = event["contentBlockDelta"]
                index = body.get("contentBlockIndex", 0)
                delta = body.get("delta") or {}
                if isinstance(delta.get("text"), str):
                    blocks.setdefault(index, {"text": []}).setdefault("text", []).append(delta["text"])
                    on_text(delta["text"])
                elif "toolUse" in delta:
                    slot = blocks.setdefault(index, {"tool": {}, "input": []})
                    slot.setdefault("input", []).append((delta["toolUse"] or {}).get("input") or "")
            elif "metadata" in event:
                used = (event["metadata"] or {}).get("usage") or {}
            else:
                for name, detail in event.items():
                    if name.endswith("Exception"):
                        raise StreamEventError(name, detail)
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            close()
    content = []
    for _, block in sorted(blocks.items()):
        if "tool" in block:
            raw = "".join(block.get("input") or [])
            try:
                args = json.loads(raw) if raw.strip() else {}
            except json.JSONDecodeError:
                args = {"__invalid_arguments__": True}
            content.append({"toolUse": {**block["tool"], "input": args if isinstance(args, dict)
                                        else {"__invalid_arguments__": True}}})
        elif block.get("text"):
            content.append({"text": "".join(block["text"])})
    return content, used


def run(model: str, region: str, system: str, messages: list[dict],
        tool_schemas: list[dict], tool_impls: dict,
        client=None, on_step=None,
        max_turns: int = agent_runtime.MAX_TURNS) -> dict:

    if not region:
        raise ValueError("AWS region is required; set AWS_REGION or AWS_DEFAULT_REGION.")
    if not model:
        raise ValueError("Bedrock model ID is required; set it in Settings.")
    owns_client = client is None
    client = client or _client(region)
    tools = _tools(tool_schemas)
    cache = {"enabled": _supports_cache(model)}

    def request(model_messages):
        convo = _messages(model_messages)
        # agent_runtime prepares the system message (it appends today's date).
        prepared = [m.content for m in model_messages
                    if isinstance(m, SystemMessage) and isinstance(m.content, str) and m.content]
        system_text = "\n\n".join(prepared) if prepared else system
        if not cache["enabled"]:
            return {"system": [{"text": system_text}], "messages": convo,
                    "toolConfig": {"tools": tools, "toolChoice": {"auto": {}}}}
        if convo:
            convo[-1] = {**convo[-1], "content": convo[-1]["content"] + [_CACHE_POINT]}
        return {"system": [{"text": system_text}, _CACHE_POINT], "messages": convo,
                "toolConfig": {"tools": tools + ([_CACHE_POINT] if tools else []),
                               "toolChoice": {"auto": {}}}}

    # Converse has no "none" tool choice and needs toolConfig while the history
    # holds toolUse blocks, so a tool-free final call keeps toolConfig and any
    # tool calls it returns are ignored by agent_runtime.
    # With a text sink, ConverseStream is used; a role without the streaming
    # permission falls back to Converse for the rest of the run.
    streaming = {"enabled": hasattr(client, "converse_stream")}

    def send(model_messages, on_text):
        if on_text is not None and streaming["enabled"]:
            try:
                response = client.converse_stream(modelId=model, **request(model_messages))
            except Exception as exc:
                if not _is_stream_denied(exc):
                    raise
                logger.info("Bedrock streaming is unavailable (%s); using Converse.",
                            agent_runtime.error_code(exc) or type(exc).__name__)
                streaming["enabled"] = False
            else:
                content, used = _read_stream(response, on_text)
                return _message(content, used)
        response = client.converse(modelId=model, **request(model_messages))
        return _message(response.get("output", {}).get("message", {}).get("content", []),
                        response.get("usage", {}))

    def invoke(model_messages, _schemas, tool_choice=None, on_text=None):
        try:
            return send(model_messages, on_text)
        except Exception as exc:
            if not (cache["enabled"] and _is_cache_rejection(exc)):
                raise
            cache["enabled"] = False
            return send(model_messages, on_text)

    try:
        return agent_runtime.run("bedrock", model, system, messages, tool_impls,
                                 tool_schemas, invoke, on_step=on_step,
                                 max_turns=max_turns)
    finally:
        close = getattr(client, "close", None)
        if owns_client and callable(close):
            close()

def structured_call(model: str, region: str, system: str, prompt: str,
                    name: str, description: str, schema: dict,
                    client=None) -> dict | None:

    if not region:
        raise ValueError("AWS region is required; set AWS_REGION or AWS_DEFAULT_REGION.")
    if not model:
        raise ValueError("Bedrock model ID is required; set it in Settings.")
    client = client or _client(region)
    response = client.converse(
        modelId=model,
        system=[{"text": system}],
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        toolConfig={"tools": [{"toolSpec": {
            "name": name,
            "description": description,
            "inputSchema": {"json": schema},
        }}], "toolChoice": {"auto": {}}},
    )
    for block in response.get("output", {}).get("message", {}).get("content", []):
        if block.get("toolUse", {}).get("name") == name:
            return block["toolUse"].get("input")
    return None

def test_connection(model: str, region: str) -> dict:
    if not region:
        raise ValueError("AWS region is required; set AWS_REGION or AWS_DEFAULT_REGION.")
    if not model:
        raise ValueError("Bedrock model ID is required; set it in Settings.")
    response = _client(region).converse(
        modelId=model,
        system=[{"text": "Reply with OK."}],
        messages=[{"role": "user", "content": [{"text": "Connection test."}]}],
        inferenceConfig={"maxTokens": 8},
    )
    return {"ok": True, "provider": "bedrock", "model": model,
            "display_name": model}
