import json

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

import agent_runtime

MAX_TURNS = agent_runtime.MAX_TURNS

def _client(region: str):
    import boto3
    from botocore.config import Config
    return boto3.client(
        "bedrock-runtime", region_name=region,
        config=Config(connect_timeout=5, read_timeout=60,
                      retries={"total_max_attempts": 1, "mode": "standard"}))

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

def _messages(messages: list[BaseMessage]) -> list[dict]:
    convo = []
    for message in messages:
        if isinstance(message, SystemMessage):
            continue
        if isinstance(message, HumanMessage):
            convo.append({"role": "user", "content": [{"text": message.content}]})
        elif isinstance(message, AIMessage):
            content = ([{"text": message.content}] if message.content else [])
            content.extend({"toolUse": {"toolUseId": call["id"],
                                         "name": call["name"],
                                         "input": call["args"]}}
                           for call in message.tool_calls)
            convo.append({"role": "assistant", "content": content})
        elif isinstance(message, ToolMessage):
            try:
                parsed = json.loads(message.content)
            except (TypeError, json.JSONDecodeError):
                parsed = None
            block = {"toolResult": {"toolUseId": message.tool_call_id,
                                    "content": ([{"json": parsed}]
                                                if isinstance(parsed, dict)
                                                else [{"text": str(message.content)}])}}
            if convo and convo[-1]["role"] == "user":
                convo[-1]["content"].append(block)
            else:
                convo.append({"role": "user", "content": [block]})
    return convo

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
    tool_config = {"tools": _tools(tool_schemas), "toolChoice": {"auto": {}}}
    def invoke(model_messages, _schemas):
        response = client.converse(
            modelId=model,
            system=[{"text": system}],
            messages=_messages(model_messages),
            toolConfig=tool_config,
        )
        used = response.get("usage", {})
        output = response.get("output", {}).get("message", {})
        content = output.get("content", [])
        tool_uses = [block["toolUse"] for block in content
                     if "toolUse" in block]
        calls = [{"name": use["name"], "args": use.get("input") or {},
                  "id": use["toolUseId"]} for use in tool_uses]
        usage = {"input_tokens": used.get("inputTokens", 0) or 0,
                 "output_tokens": used.get("outputTokens", 0) or 0,
                 "total_tokens": used.get("totalTokens", 0) or 0}
        return AIMessage(content="\n".join(block["text"] for block in content
                                            if "text" in block),
                         tool_calls=calls, usage_metadata=usage)

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
