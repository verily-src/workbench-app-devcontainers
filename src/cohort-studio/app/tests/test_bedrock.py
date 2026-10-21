import pytest

import bedrock


def test_converse_tool_loop_runs_closures_and_tracks_usage():
    first = {
        "output": {"message": {"role": "assistant", "content": [
            {"toolUse": {"toolUseId": "use-1", "name": "fail_tool",
                          "input": {"value": "bad"}}}]}},
        "stopReason": "tool_use",
        "usage": {"inputTokens": 11, "outputTokens": 3, "totalTokens": 14},
    }
    second = {
        "output": {"message": {"role": "assistant",
                                "content": [{"text": "Recovered."}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 7, "outputTokens": 2, "totalTokens": 9},
    }

    class FakeClient:
        def __init__(self):
            self.requests = []
            self.responses = [first, second]

        def converse(self, **request):
            self.requests.append(request)
            return self.responses.pop(0)

    client = FakeClient()
    schema = [{"type": "function", "function": {
        "name": "fail_tool", "description": "Test tool.",
        "parameters": {"type": "object", "properties": {
            "value": {"type": "string"}}, "required": ["value"]}}}]
    result = bedrock.run(
        "model-id", "us-east-1", "system prompt",
        [{"role": "user", "content": "Run tool."}], schema,
        {"fail_tool": lambda value: (_ for _ in ()).throw(
            ValueError(f"bad value: {value}"))}, client=client)

    assert result["reply"] == "Recovered."
    assert result["tool_calls"] == ["fail_tool"]
    assert result["usage"] == {"prompt_tokens": 18,
                                "completion_tokens": 5,
                                "total_tokens": 23}
    assert client.requests[0]["modelId"] == "model-id"
    assert client.requests[0]["system"] == [{"text": "system prompt"}]
    assert client.requests[0]["toolConfig"]["tools"][0]["toolSpec"]["name"] == "fail_tool"
    tool_result = client.requests[1]["messages"][-1]["content"][0]["toolResult"]
    assert tool_result["toolUseId"] == "use-1"
    assert tool_result["status"] == "error"
    assert "bad value: bad" in tool_result["content"][0]["text"]


def test_botocore_stubber_validates_multiturn_converse_shapes():
    import boto3
    from botocore.stub import Stubber

    client = boto3.client(
        "bedrock-runtime", region_name="us-east-1",
        aws_access_key_id="test-access-key",
        aws_secret_access_key="test-secret-key")
    schema = [{"type": "function", "function": {
        "name": "count_rows", "description": "Count rows.",
        "parameters": {"type": "object", "properties": {
            "column": {"type": "string"}}, "required": ["column"]}}}]
    tool_config = {
        "tools": [{"toolSpec": {
            "name": "count_rows", "description": "Count rows.",
            "inputSchema": {"json": {
                "type": "object", "properties": {
                    "column": {"type": "string"}},
                "required": ["column"]}}}}],
        "toolChoice": {"auto": {}},
    }
    first_messages = [{"role": "user", "content": [{"text": "Count rows."}]}]
    assistant_tool_message = {"role": "assistant", "content": [{
        "toolUse": {"toolUseId": "tooluse_0123456789abcdefghijk",
                    "name": "count_rows", "input": {"column": "person_id"}}}]}
    followup_messages = first_messages + [assistant_tool_message, {
        "role": "user", "content": [{"toolResult": {
            "toolUseId": "tooluse_0123456789abcdefghijk",
            "content": [{"json": {"count": 3}}]}}]}]
    with Stubber(client) as stubber:
        stubber.add_response("converse", {
            "output": {"message": assistant_tool_message},
            "stopReason": "tool_use",
            "usage": {"inputTokens": 10, "outputTokens": 4,
                       "totalTokens": 14},
            "metrics": {"latencyMs": 1},
        }, {
            "modelId": "test-model",
            "system": [{"text": "Use tools."}],
            "messages": first_messages,
            "toolConfig": tool_config,
        })
        stubber.add_response("converse", {
            "output": {"message": {"role": "assistant",
                                    "content": [{"text": "Three rows."}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 7, "outputTokens": 2,
                       "totalTokens": 9},
            "metrics": {"latencyMs": 1},
        }, {
            "modelId": "test-model",
            "system": [{"text": "Use tools."}],
            "messages": followup_messages,
            "toolConfig": tool_config,
        })
        result = bedrock.run(
            "test-model", "us-east-1", "Use tools.",
            [{"role": "user", "content": "Count rows."}], schema,
            {"count_rows": lambda column: '{"count": 3}'}, client=client)
        stubber.assert_no_pending_responses()

    assert result["reply"] == "Three rows."
    assert result["tool_calls"] == ["count_rows"]
    assert result["usage"] == {"prompt_tokens": 17,
                                "completion_tokens": 6,
                                "total_tokens": 23}


def test_structured_call_returns_tool_input():
    class FakeClient:
        def converse(self, **request):
            assert request["toolConfig"]["toolChoice"] == {"auto": {}}
            return {"output": {"message": {"content": [
                {"toolUse": {"name": "result", "input": {"ok": True}}}]}}}

    result = bedrock.structured_call(
        "model-id", "us-east-1", "system", "prompt", "result", "Return data.",
        {"type": "object", "properties": {"ok": {"type": "boolean"}}},
        client=FakeClient())
    assert result == {"ok": True}


def test_bedrock_requires_region_and_model_before_client_creation(monkeypatch):
    monkeypatch.setattr(bedrock, "_client",
                        lambda region: pytest.fail("unexpected AWS client"))
    with pytest.raises(ValueError, match="AWS region"):
        bedrock.run("model-id", "", "system", [], [], {})
    with pytest.raises(ValueError, match="model ID"):
        bedrock.run("", "us-east-1", "system", [], [], {})


def test_converse_api_errors_are_not_hidden():
    class FailingClient:
        def converse(self, **_request):
            raise RuntimeError("bedrock unavailable")

    with pytest.raises(RuntimeError, match="bedrock unavailable"):
        bedrock.run("model-id", "us-east-1", "system", [], [], {},
                    client=FailingClient())


def test_test_connection_uses_configured_region_and_model(monkeypatch):
    seen = {}

    class FakeClient:
        def converse(self, **request):
            seen.update(request)
            return {"usage": {}}

    monkeypatch.setattr(bedrock, "_client", lambda region: (
        seen.update(region=region) or FakeClient()))
    result = bedrock.test_connection("model-id", "us-east-1")
    assert result == {"ok": True, "provider": "bedrock", "model": "model-id",
                      "display_name": "model-id"}
    assert seen["region"] == "us-east-1"
    assert seen["modelId"] == "model-id"


def test_ask_ai_uses_bedrock_tool_schema_and_validates_filters(monkeypatch):
    import config
    import llm

    monkeypatch.setattr(config, "get_llm_config", lambda: {
        "provider": "bedrock", "api_key": None, "model": "model-id",
        "region": "us-east-1"})
    seen = {}

    def fake_structured_call(model, region, system, prompt, name,
                             description, schema):
        seen.update(model=model, region=region, name=name,
                    schema=schema, prompt=prompt)
        return {"filters": [{"column": "tissue", "kind": "categorical",
                              "values": ["liver", "invalid"]}],
                "explanation": "Selected liver."}

    monkeypatch.setattr(bedrock, "structured_call", fake_structured_call)
    out = llm.suggest_filters("liver", [{"name": "tissue",
        "filter_kind": "categorical", "values": ["liver", "lung"]}], [])
    assert seen["region"] == "us-east-1"
    assert seen["model"] == "model-id"
    assert seen["name"] == "submit_filter_suggestion"
    assert out["filters"] == [{"column": "tissue", "kind": "categorical",
                               "values": ["liver"]}]


def test_ask_ai_flags_bedrock_model_without_tool_result(monkeypatch):
    import config
    import llm

    monkeypatch.setattr(config, "get_llm_config", lambda: {
        "provider": "bedrock", "api_key": None, "model": "model-id",
        "region": "us-east-1"})
    monkeypatch.setattr(bedrock, "structured_call", lambda *a, **k: None)
    out = llm.suggest_filters("liver", [], [{"column": "x"}])
    assert out["filters"] == [{"column": "x"}]
    assert "supports Converse tool use" in out["explanation"]
