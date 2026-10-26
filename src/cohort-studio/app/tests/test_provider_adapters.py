from types import SimpleNamespace

import bedrock
import providers
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage


def test_provider_wrappers_forward_optional_turn_budget(monkeypatch):
    forwarded = []
    monkeypatch.setattr(providers, "_client", lambda *_args: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(providers.agent_runtime, "run",
                        lambda *args, **kwargs: forwarded.append(kwargs) or {})
    providers.run("openai", "model", "key", None, "system", [], {},
                  max_turns=13)
    assert forwarded[-1]["max_turns"] == 13

    monkeypatch.setattr(bedrock.agent_runtime, "run",
                        lambda *args, **kwargs: forwarded.append(kwargs) or {})
    bedrock.run("model", "us-east-1", "system", [], [], {}, client=object(),
                max_turns=14)
    assert forwarded[-1]["max_turns"] == 14


def test_openai_compatible_response_maps_calls_and_usage():
    response = SimpleNamespace(
        choices=[SimpleNamespace(
            finish_reason="tool_calls",
            message=SimpleNamespace(content=None, tool_calls=[SimpleNamespace(
                id="call-1", function=SimpleNamespace(name="count_rows",
                                                       arguments='{"limit":2}'))]))],
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=3, total_tokens=14))
    client = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=lambda **_: response)))
    message = providers._openai_call(client, "model", [HumanMessage(content="count")], [])
    assert message.tool_calls == [{"name": "count_rows", "args": {"limit": 2},
                                   "id": "call-1", "type": "tool_call"}]
    assert message.usage_metadata == {"input_tokens": 11, "output_tokens": 3,
                                      "total_tokens": 14}


def test_anthropic_response_maps_tool_use_and_usage():
    response = SimpleNamespace(
        stop_reason="tool_use",
        content=[SimpleNamespace(type="tool_use", id="use-1", name="count_rows",
                                 input={"limit": 2})],
        usage=SimpleNamespace(input_tokens=8, output_tokens=4))
    captured = {}

    class Messages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return response

    client = SimpleNamespace(messages=Messages())
    message = providers._anthropic_call(
        client, "claude-test", [SystemMessage(content="system"),
                                 HumanMessage(content="count")], providers.TOOL_SCHEMAS)
    assert message.tool_calls == [{"name": "count_rows", "args": {"limit": 2},
                                   "id": "use-1", "type": "tool_call"}]
    assert message.usage_metadata == {"input_tokens": 8, "output_tokens": 4,
                                      "total_tokens": 12}
    assert captured["system"] == "system"
    assert captured["tools"][0]["name"] == "run_query"


def test_bedrock_uses_graph_and_reconstructs_tool_messages():
    responses = iter([
        {"output": {"message": {"role": "assistant", "content": [
            {"toolUse": {"toolUseId": "use-1", "name": "count_rows",
                          "input": {"limit": 2}}}]}},
         "usage": {"inputTokens": 10, "outputTokens": 2, "totalTokens": 12}},
        {"output": {"message": {"role": "assistant", "content": [
            {"text": "There are 2 rows."}]}},
         "usage": {"inputTokens": 7, "outputTokens": 4, "totalTokens": 11}},
    ])
    requests = []

    class Client:
        def converse(self, **kwargs):
            requests.append(kwargs)
            return next(responses)

    schemas = [{"type": "function", "function": {
        "name": "count_rows", "parameters": {"type": "object", "properties": {
            "limit": {"type": "integer"}}, "required": ["limit"]}}}]
    result = bedrock.run("model", "us-east-1", "system",
                         [{"role": "user", "content": "count"}], schemas,
                         {"count_rows": lambda limit: '{"count":2}'},
                         client=Client())
    assert result["reply"] == "There are 2 rows."
    assert result["usage"] == {"prompt_tokens": 17, "completion_tokens": 6,
                                "total_tokens": 23}
    assert result["tool_calls"] == ["count_rows"]
    followup = requests[1]["messages"]
    assert followup[-2]["role"] == "assistant"
    assert followup[-2]["content"][0]["toolUse"]["toolUseId"] == "use-1"
    assert followup[-1]["content"][0]["toolResult"]["toolUseId"] == "use-1"

