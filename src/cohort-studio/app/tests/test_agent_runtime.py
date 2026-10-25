import json

import pandas as pd
from langchain_core.messages import AIMessage
from langchain_core.messages import ToolMessage
from langsmith.run_helpers import get_tracing_context

import agent
import agent_runtime
import datasets
import providers


def schema():
    return [{"type": "function", "function": {
        "name": "count_rows", "description": "Count rows.",
        "parameters": {"type": "object", "properties": {
            "limit": {"type": "integer", "minimum": 0}},
            "required": ["limit"], "additionalProperties": False}}}]


def test_graph_runs_validated_tool_then_returns_final_and_reports_steps():
    calls = []
    events = []
    replies = iter([
        AIMessage(content="", tool_calls=[{"name": "count_rows", "args": {"limit": 3},
                                           "id": "tool-1"}],
                  usage_metadata={"input_tokens": 7, "output_tokens": 2,
                                  "total_tokens": 9}),
        AIMessage(content="There are 3 rows.",
                  usage_metadata={"input_tokens": 5, "output_tokens": 4,
                                  "total_tokens": 9}),
    ])

    def count_rows(limit):
        calls.append(limit)
        return json.dumps({"count": limit})

    result = agent_runtime.run(
        "openai", "test-model", "system",
        [{"role": "user", "content": "count rows"}],
        {"count_rows": count_rows}, schema(), lambda *_: next(replies), events.append)

    assert calls == [3]
    assert result == {"reply": "There are 3 rows.",
                      "usage": {"prompt_tokens": 12, "completion_tokens": 6,
                                "total_tokens": 18},
                      "tool_calls": ["count_rows"], "turns": 2}
    assert [event["type"] for event in events] == [
        "model_start", "model_end", "tool_start", "tool_end",
        "model_start", "model_end"]
    assert events[5]["usage"] == result["usage"]
    assert "args" not in events[2]


def test_fake_provider_runs_real_dataset_tool_and_returns_grounded_answer():
    df = pd.DataFrame({"sample": ["a", "b", "c"], "score": [1, 2, 3]})
    columns = datasets.profile_columns(df)
    ui = {"filters": [], "charts": []}
    actions = []
    impls = {tool.__name__: tool for tool in agent.build_tools(
        df, columns, ui, actions)}
    seen_tool_result = []
    replies = iter([
        AIMessage(content="", tool_calls=[{"name": "run_query",
                                           "args": {"filters_json": "[]"},
                                           "id": "query-1"}]),
        AIMessage(content="The full dataset has 3 rows."),
    ])

    def fake_provider(messages, _schemas):
        for message in messages:
            if isinstance(message, ToolMessage):
                seen_tool_result.append(json.loads(message.content))
        return next(replies)

    result = agent_runtime.run(
        "openrouter", "fake-model", "system",
        [{"role": "user", "content": "How many rows are present?"}],
        impls, providers.TOOL_SCHEMAS, fake_provider)

    assert seen_tool_result[0]["matching_rows"] == 3
    assert seen_tool_result[0]["total_rows"] == 3
    assert result["reply"] == "The full dataset has 3 rows."
    assert result["tool_calls"] == ["run_query"]


def test_graph_rejects_bad_arguments_before_tool_execution():
    calls = []
    responses = iter([
        AIMessage(content="", tool_calls=[{"name": "count_rows",
                                           "args": {"limit": "bad", "extra": 1},
                                           "id": "tool-1"}]),
        AIMessage(content="The arguments were invalid."),
    ])

    def count_rows(limit):
        calls.append(limit)
        return "{}"

    result = agent_runtime.run("openrouter", "test", "system", [],
                               {"count_rows": count_rows}, schema(),
                               lambda *_: next(responses))
    assert calls == []
    assert result["reply"] == "The arguments were invalid."
    assert result["tool_calls"] == ["count_rows"]


def test_graph_stops_after_bounded_tool_calls():
    calls = []
    events = []

    def repeat(*_):
        calls.append(True)
        return AIMessage(content="", tool_calls=[{"name": "count_rows",
                                                   "args": {"limit": 1},
                                                   "id": f"tool-{len(calls)}"}])

    result = agent_runtime.run("anthropic", "test", "system", [],
                               {"count_rows": lambda limit: "{}"}, schema(),
                               repeat, events.append)
    assert len(calls) == agent_runtime.MAX_TURNS
    assert result["turns"] == agent_runtime.MAX_TURNS
    assert result["reply"] == agent_runtime._LIMIT_REPLY
    assert result["tool_calls"] == ["count_rows"] * agent_runtime.MAX_TURNS


def test_graph_enforces_wall_time_budget(monkeypatch):
    clock = iter([10.0, 10.0 + agent_runtime.MAX_RUNTIME_SECONDS + 1])
    monkeypatch.setattr(agent_runtime.time, "monotonic", lambda: next(clock))
    calls = []
    result = agent_runtime.run("openai", "test", "system", [], {}, [],
                               lambda *_: calls.append(True))
    assert calls == []
    assert result["reply"] == agent_runtime._LIMIT_REPLY


def test_graph_disables_ambient_langsmith_tracing(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    tracing_states = []

    def fake_provider(*_):
        tracing_states.append(get_tracing_context()["enabled"])
        return AIMessage(content="done")

    agent_runtime.run("openai", "test", "system", [], {}, [], fake_provider)
    assert tracing_states == [False]


def test_graph_caps_tool_calls_and_tool_output():
    calls = []
    too_many = AIMessage(content="", tool_calls=[
        {"name": "count_rows", "args": {"limit": 1}, "id": f"call-{i}"}
        for i in range(agent_runtime.MAX_TOOL_CALLS_PER_RESPONSE + 1)])
    result = agent_runtime.run(
        "openai", "test", "system", [], {"count_rows": lambda limit: calls.append(limit)},
        schema(), lambda *_: too_many)
    assert calls == []
    assert result["reply"] == agent_runtime._LIMIT_REPLY

    seen = []
    responses = iter([
        AIMessage(content="", tool_calls=[{"name": "count_rows", "args": {"limit": 1},
                                           "id": "large-result"}]),
        AIMessage(content="The tool result was unavailable."),
    ])

    def next_response(messages, _schemas):
        seen.extend(message.content for message in messages
                    if isinstance(message, ToolMessage))
        return next(responses)

    agent_runtime.run("openai", "test", "system", [],
                      {"count_rows": lambda limit: "x" * (agent_runtime.MAX_TOOL_OUTPUT_BYTES + 1)},
                      schema(), next_response)
    assert len(seen) == 1
    assert "no result was returned" in seen[0]


def test_graph_caps_total_tool_calls_across_turns():
    executed = []
    turns = []

    def fake_provider(*_):
        turn = len(turns) + 1
        turns.append(turn)
        return AIMessage(content="", tool_calls=[
            {"name": "count_rows", "args": {"limit": 1},
             "id": f"turn-{turn}-{index}"}
            for index in range(agent_runtime.MAX_TOOL_CALLS_PER_RESPONSE)])

    result = agent_runtime.run(
        "openai", "test", "system", [],
        {"count_rows": lambda limit: executed.append(limit) or "{}"},
        schema(), fake_provider)
    assert len(executed) == agent_runtime.MAX_TOTAL_TOOL_CALLS
    assert result["reply"] == agent_runtime._LIMIT_REPLY
