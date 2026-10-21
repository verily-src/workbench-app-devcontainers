"""Amazon Bedrock Converse adapter using the AWS SDK credential chain."""

import json

MAX_TURNS = 8


def _client(region: str):
    import boto3
    from botocore.config import Config
    return boto3.client(
        "bedrock-runtime", region_name=region,
        config=Config(connect_timeout=10, read_timeout=60,
                      retries={"max_attempts": 2, "mode": "standard"}))


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


def _messages(messages: list[dict]) -> list[dict]:
    return [{"role": m["role"], "content": [{"text": m["content"]}]}
            for m in messages if m.get("role") in ("user", "assistant")
            and m.get("content")]


def run(model: str, region: str, system: str, messages: list[dict],
        tool_schemas: list[dict], tool_impls: dict,
        client=None) -> dict:
    """Run a Converse client-side tool loop and return common agent fields."""
    if not region:
        raise ValueError("AWS region is required; set AWS_REGION or AWS_DEFAULT_REGION.")
    if not model:
        raise ValueError("Bedrock model ID is required; set it in Settings.")
    client = client or _client(region)
    convo = _messages(messages)
    tool_config = {"tools": _tools(tool_schemas), "toolChoice": {"auto": {}}}
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    calls = []

    for turn in range(MAX_TURNS):
        response = client.converse(
            modelId=model,
            system=[{"text": system}],
            messages=convo,
            toolConfig=tool_config,
        )
        used = response.get("usage", {})
        usage["prompt_tokens"] += used.get("inputTokens", 0) or 0
        usage["completion_tokens"] += used.get("outputTokens", 0) or 0
        usage["total_tokens"] += used.get("totalTokens", 0) or 0
        output = response.get("output", {}).get("message", {})
        content = output.get("content", [])
        tool_uses = [block["toolUse"] for block in content
                     if "toolUse" in block]
        if not tool_uses:
            reply = "\n".join(block["text"] for block in content
                               if "text" in block).strip() or "(done)"
            return {"reply": reply, "usage": usage,
                    "tool_calls": calls, "turns": turn + 1}

        # Converse requires the exact assistant message to be included before
        # the user-role message that returns the matching toolUseIds.
        convo.append(output)
        results = []
        for use in tool_uses:
            name = use["name"]
            calls.append(name)
            impl = tool_impls.get(name)
            status = None
            if impl is None:
                result = json.dumps({"error": f"unknown tool {name}"})
                status = "error"
            else:
                try:
                    args = use.get("input") or {}
                    result = impl(**args)
                except Exception as exc:
                    result = str(exc)
                    status = "error"
            try:
                parsed = json.loads(result)
            except (TypeError, json.JSONDecodeError):
                parsed = None
            result_content = ([{"json": parsed}] if isinstance(parsed, dict)
                              else [{"text": str(result)}])
            result_block = {"toolUseId": use["toolUseId"],
                            "content": result_content}
            if status:
                result_block["status"] = status
            results.append({"toolResult": result_block})
        convo.append({"role": "user", "content": results})

    return {"reply": "I wasn't able to finish that in a reasonable number of "
            "steps — try narrowing the request.", "usage": usage,
            "tool_calls": calls, "turns": MAX_TURNS}


def structured_call(model: str, region: str, system: str, prompt: str,
                    name: str, description: str, schema: dict,
                    client=None) -> dict | None:
    """Ask a model for structured output by defining a single Converse tool."""
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
