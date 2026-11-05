"""Live text streaming, enriched step events and actionable tool errors.

All provider clients are fakes; nothing calls a live API.
"""
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage

import agent_runtime
import agent_stream
import bedrock
import providers
from tests.test_agent_reliability import ClientError, StatusError, schema
from tests.test_agent_store import agent_store  # noqa: F401  (fixture)


@pytest.fixture
def sleeps(monkeypatch):
    waited = []
    monkeypatch.setattr(agent_runtime, "_sleep", waited.append)
    return waited


def run_streaming(model_call, tools=None, schemas=None, max_turns=8, steps=None):
    deltas = []
    with agent_runtime.text_stream(deltas.append):
        result = agent_runtime.run("anthropic", "m", "system",
                                   [{"role": "user", "content": "count"}],
                                   tools or {}, schemas if schemas is not None else schema(),
                                   model_call, (steps.append if steps is not None else None),
                                   max_turns=max_turns)
    return result, deltas


# 1. Anthropic ----------------------------------------------------------------

def text(value):
    return SimpleNamespace(type="text", text=value, snapshot=value)


class FakeStream:
    def __init__(self, events, final=None, fail_on_enter=None):
        self.events, self.final, self.fail_on_enter = events, final, fail_on_enter
        self.closed = False

    def __enter__(self):
        if self.fail_on_enter:
            raise self.fail_on_enter
        return self

    def __exit__(self, *_):
        self.closed = True
        return False

    def __iter__(self):
        for event in self.events:
            if isinstance(event, Exception):
                raise event
            yield event

    def get_final_message(self):
        return self.final


class FakeMessages:
    def __init__(self, streams):
        self.streams = list(streams)
        self.requests = []
        self.opened = []

    def stream(self, **kwargs):
        self.requests.append(kwargs)
        stream = self.streams.pop(0)
        self.opened.append(stream)
        return stream

    def create(self, **_kwargs):
        raise AssertionError("streaming client must not fall back to create")


def anthropic_message(content, stop_reason="end_turn", **usage):
    return SimpleNamespace(stop_reason=stop_reason, content=content, usage=SimpleNamespace(
        input_tokens=usage.get("input", 10), output_tokens=usage.get("output", 5),
        cache_read_input_tokens=usage.get("cache_read", 0),
        cache_creation_input_tokens=usage.get("cache_write", 0)))


def anthropic_run(monkeypatch, streams, tools, schemas, steps, max_turns=8):
    import anthropic
    messages = FakeMessages(streams)
    monkeypatch.setattr(anthropic, "Anthropic", lambda **_: SimpleNamespace(
        messages=messages, close=lambda: None))
    deltas = []
    with agent_runtime.text_stream(deltas.append):
        result = providers.run("anthropic", "claude-test", "key", None, "system",
                               [{"role": "user", "content": "count"}], tools,
                               tool_schemas=schemas, on_step=steps.append,
                               max_turns=max_turns)
    return result, deltas, messages


def test_anthropic_streams_text_assembles_tool_use_and_keeps_cache_usage(monkeypatch):
    tool_use = SimpleNamespace(type="tool_use", id="use-1", name="count_rows",
                               input={"limit": 2})
    streams = [
        FakeStream([text("Let me "), text("count.")],
                   anthropic_message([SimpleNamespace(type="text", text="Let me count."),
                                      tool_use], "tool_use", cache_write=900)),
        FakeStream([text("There are "), text("2 rows.")],
                   anthropic_message([SimpleNamespace(type="text", text="There are 2 rows.")],
                                     input=12, output=6, cache_read=900)),
    ]
    steps = []
    result, deltas, messages = anthropic_run(
        monkeypatch, streams, {"count_rows": lambda limit: json.dumps({"count": limit})},
        schema(), steps)
    assert result["reply"] == "There are 2 rows."
    assert result["tool_calls"] == ["count_rows"]
    assert result["usage"] == {"prompt_tokens": 22, "completion_tokens": 11,
                               "total_tokens": 33}
    # Deltas are coalesced per call and tagged with the model step.
    assert [(d["turn"], d["text"]) for d in deltas] == [(1, "Let me count."),
                                                       (2, "There are 2 rows.")]
    assert all(d["type"] == "text_delta" for d in deltas)
    # Prompt caching kwargs are unchanged on the streaming path.
    first = messages.requests[0]
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert first["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "tool_choice" not in first
    followup = messages.requests[1]["messages"]
    assert followup[-1]["content"][-1]["type"] == "tool_result"
    assert followup[-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    model_end = [s for s in steps if s["type"] == "model_end"]
    assert model_end[0]["step_usage"] == {"prompt_tokens": 10, "completion_tokens": 5,
                                          "total_tokens": 15}
    assert all(stream.closed for stream in messages.opened)


def test_anthropic_final_summary_streams_with_tool_choice_none(monkeypatch):
    tool_use = SimpleNamespace(type="tool_use", id="use-1", name="count_rows",
                               input={"limit": 1})
    streams = [
        FakeStream([], anthropic_message([tool_use], "tool_use")),
        FakeStream([text("Counted 1 row so far.")],
                   anthropic_message([SimpleNamespace(type="text", text="Counted 1 row so far.")])),
    ]
    steps = []
    result, deltas, messages = anthropic_run(
        monkeypatch, streams, {"count_rows": lambda limit: "{}"}, schema(), steps, max_turns=1)
    assert messages.requests[1]["tool_choice"] == {"type": "none"}
    assert result["reply"].startswith("Counted 1 row so far.")
    assert deltas == [{"type": "text_delta", "turn": 2, "text": "Counted 1 row so far."}]
    limit = next(s for s in steps if s["type"] == "runtime_limit")
    assert limit["reason"] == "turn_budget"
    summary_start = [s for s in steps if s["type"] == "model_start"][-1]
    assert summary_start["final_summary"] is True


def test_anthropic_without_stream_support_uses_blocking_create():
    captured = {}

    class Messages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return anthropic_message([SimpleNamespace(type="text", text="done")])

    seen = []
    message = providers._anthropic_call(SimpleNamespace(messages=Messages()), "claude",
                                        [], [], on_text=seen.append)
    assert message.content == "done" and seen == [] and captured


# 2. Retries and streaming ---------------------------------------------------

def test_retry_happens_only_before_the_first_delta(sleeps):
    calls = []

    def model(_messages, _schemas, on_text=None):
        calls.append(True)
        if len(calls) == 1:
            raise StatusError(529, "overloaded_error")
        on_text("Recovered.")
        return AIMessage(content="Recovered.")

    steps = []
    result, deltas = run_streaming(model, steps=steps)
    assert result["reply"] == "Recovered." and len(calls) == 2
    retry = next(s for s in steps if s["type"] == "model_retry_start")
    assert retry["attempt"] == 1 and retry["reason"] == "overloaded"
    assert retry["wait_seconds"] == round(sleeps[0], 1)
    assert [d["text"] for d in deltas] == ["Recovered."]


def test_error_after_streamed_text_is_surfaced_not_retried(sleeps):
    calls = []

    def model(_messages, _schemas, on_text=None):
        calls.append(True)
        on_text("Partial ans")
        raise StatusError(529, "overloaded_error")

    deltas = []
    with agent_runtime.text_stream(deltas.append), pytest.raises(StatusError):
        agent_runtime.run("anthropic", "m", "system", [], {}, [], model)
    assert calls == [True] and sleeps == []
    # Buffered text is flushed before the error propagates.
    assert [d["text"] for d in deltas] == ["Partial ans"]


def test_anthropic_midstream_error_after_text_is_not_retried(monkeypatch, sleeps):
    streams = [FakeStream([text("Half"), StatusError(529, "overloaded_error")])]
    with pytest.raises(StatusError):
        anthropic_run(monkeypatch, streams, {}, [], [])
    assert sleeps == []


def test_anthropic_connect_error_before_text_is_retried(monkeypatch, sleeps):
    streams = [FakeStream([], fail_on_enter=StatusError(503)),
               FakeStream([text("ok")], anthropic_message([SimpleNamespace(type="text", text="ok")]))]
    steps = []
    result, deltas, _ = anthropic_run(monkeypatch, streams, {}, [], steps)
    assert result["reply"] == "ok" and len(sleeps) == 1
    assert [s["reason"] for s in steps if s["type"] == "model_retry_start"] == ["server_error"]


def test_text_sink_cancellation_stops_the_stream(monkeypatch):
    class Cancelled(Exception):
        pass

    def sink(_event):
        raise Cancelled()

    import anthropic
    stream = FakeStream([text("x" * 100), text("never")],
                        anthropic_message([SimpleNamespace(type="text", text="x")]))
    monkeypatch.setattr(anthropic, "Anthropic", lambda **_: SimpleNamespace(
        messages=FakeMessages([stream]), close=lambda: None))
    with agent_runtime.text_stream(sink), pytest.raises(Cancelled):
        providers.run("anthropic", "claude", "key", None, "system", [], {}, tool_schemas=[])
    assert stream.closed


def test_no_text_sink_means_no_streaming_argument():
    seen = []

    def model(_messages, _schemas, on_text=None):
        seen.append(on_text)
        return AIMessage(content="done")

    agent_runtime.run("anthropic", "m", "system", [], {}, [], model)
    assert seen == [None]


def test_deltas_are_coalesced(monkeypatch):
    def model(_messages, _schemas, on_text=None):
        for _ in range(200):
            on_text("ab")
        return AIMessage(content="ab" * 200)

    monkeypatch.setattr(agent_runtime, "TEXT_FLUSH_SECONDS", 3600)
    _, deltas = run_streaming(model, schemas=[])
    assert "".join(d["text"] for d in deltas) == "ab" * 200
    assert len(deltas) <= 400 // agent_runtime.TEXT_FLUSH_CHARS + 1


# 3. OpenAI-compatible -------------------------------------------------------

def chunk(content=None, calls=None, finish=None, usage=None, choices=True):
    delta = SimpleNamespace(content=content, tool_calls=calls)
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=delta, finish_reason=finish)] if choices else [],
        usage=usage)


def call_fragment(index, id=None, name=None, arguments=None):
    return SimpleNamespace(index=index, id=id, function=SimpleNamespace(
        name=name, arguments=arguments))


def test_openai_stream_assembles_text_tool_calls_and_usage():
    chunks = [
        chunk("Checking"), chunk(" now."),
        chunk(calls=[call_fragment(0, "c1", "count_rows", '{"lim')]),
        chunk(calls=[call_fragment(0, arguments='it": 2}')]),
        chunk(calls=[call_fragment(1, "c2", "count_rows", '{"limit": 3}')], finish="tool_calls"),
        chunk(choices=False, usage=SimpleNamespace(
            prompt_tokens=11, completion_tokens=4, total_tokens=15,
            prompt_tokens_details=SimpleNamespace(cached_tokens=8))),
    ]
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return iter(chunks)

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    seen = []
    message = providers._openai_call(client, "m", [], providers.TOOL_SCHEMAS,
                                     tool_choice="none", on_text=seen.append)
    assert captured["stream"] is True and captured["tool_choice"] == "none"
    assert captured["stream_options"] == {"include_usage": True}
    assert seen == ["Checking", " now."] and message.content == "Checking now."
    assert [(c["id"], c["args"]) for c in message.tool_calls] == [("c1", {"limit": 2}),
                                                                   ("c2", {"limit": 3})]
    assert message.usage_metadata["total_tokens"] == 15
    assert message.usage_metadata["input_token_details"] == {"cache_read": 8}


def test_openai_compatible_server_rejecting_stream_options_falls_back(monkeypatch):
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        if "stream_options" in kwargs:
            raise StatusError(400, "Unrecognized request argument: stream_options")
        if kwargs.get("stream"):
            return iter([chunk("Hello")])
        raise AssertionError("expected a streaming call")

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
                             close=lambda: None)
    monkeypatch.setattr(providers, "_client", lambda *_: client)
    deltas = []
    with agent_runtime.text_stream(deltas.append):
        result = providers.run("openai", "m", "key", None, "system",
                               [{"role": "user", "content": "hi"}], {}, tool_schemas=[])
    assert result["reply"] == "Hello" and [d["text"] for d in deltas] == ["Hello"]
    assert "stream_options" in requests[0] and "stream_options" not in requests[1]


# 4. Bedrock ConverseStream --------------------------------------------------

def bedrock_events(*events):
    return {"stream": list(events)}


def test_bedrock_converse_stream_assembles_text_tool_use_and_cache_usage():
    calls = []

    class Client:
        def converse_stream(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return bedrock_events(
                    {"messageStart": {"role": "assistant"}},
                    {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "Let me "}}},
                    {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "count."}}},
                    {"contentBlockStart": {"contentBlockIndex": 1, "start": {"toolUse": {
                        "toolUseId": "use-1", "name": "count_rows"}}}},
                    {"contentBlockDelta": {"contentBlockIndex": 1, "delta": {"toolUse": {"input": '{"limit"'}}}},
                    {"contentBlockDelta": {"contentBlockIndex": 1, "delta": {"toolUse": {"input": ": 2}"}}}},
                    {"messageStop": {"stopReason": "tool_use"}},
                    {"metadata": {"usage": {"inputTokens": 10, "outputTokens": 3, "totalTokens": 13,
                                            "cacheWriteInputTokens": 700}}})
            return bedrock_events(
                {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "2 rows."}}},
                {"metadata": {"usage": {"inputTokens": 5, "outputTokens": 2, "totalTokens": 7,
                                        "cacheReadInputTokens": 700}}})

        def converse(self, **_):
            raise AssertionError("streaming client must not call converse")

    deltas, executed = [], []
    with agent_runtime.text_stream(deltas.append):
        result = bedrock.run("anthropic.claude-sonnet-4-5", "us-east-1", "system",
                             [{"role": "user", "content": "count"}], schema(),
                             {"count_rows": lambda limit: executed.append(limit) or '{"count": 2}'},
                             client=Client())
    assert executed == [2] and result["reply"] == "2 rows."
    assert result["usage"] == {"prompt_tokens": 15, "completion_tokens": 5, "total_tokens": 20}
    assert [d["text"] for d in deltas] == ["Let me count.", "2 rows."]
    assert calls[1]["messages"][-2]["content"][1]["toolUse"]["input"] == {"limit": 2}
    assert calls[0]["system"][-1] == {"cachePoint": {"type": "default"}}


def test_bedrock_stream_permission_denied_falls_back_to_converse():
    attempts = []

    class Client:
        def converse_stream(self, **_):
            attempts.append("stream")
            raise ClientError("AccessDeniedException", 403,
                              "not authorized to perform bedrock:InvokeModelWithResponseStream")

        def converse(self, **_):
            attempts.append("converse")
            return {"output": {"message": {"content": [{"text": "Fine."}]}}, "usage": {}}

    with agent_runtime.text_stream(lambda _event: None):
        result = bedrock.run("model", "us-east-1", "system", [], [], {}, client=Client())
    assert result["reply"] == "Fine." and attempts == ["stream", "converse"]


def test_bedrock_stream_error_event_is_classified_for_retry(sleeps):
    responses = [bedrock_events({"throttlingException": {"message": "Too many requests"}}),
                 bedrock_events({"contentBlockDelta": {"contentBlockIndex": 0,
                                                       "delta": {"text": "ok"}}})]

    class Client:
        def converse_stream(self, **_):
            return responses.pop(0)

    steps = []
    with agent_runtime.text_stream(lambda _event: None):
        result = bedrock.run("model", "us-east-1", "system", [], [], {}, client=Client(),
                             on_step=steps.append)
    assert result["reply"] == "ok"
    assert [s["reason"] for s in steps if s["type"] == "model_retry_start"] == ["rate_limit"]


# 5. Enriched tool events and actionable tool errors -------------------------

def tool_run(tool, args, schemas=None, name="count_rows"):
    responses = iter([AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "t1"}]),
                      AIMessage(content="done")])
    seen, steps = [], []

    def model(messages, _schemas):
        seen.extend(m.content for m in messages if isinstance(m, ToolMessage))
        return next(responses)

    agent_runtime.run("openai", "m", "system", [], {"count_rows": tool} if tool else {},
                      schemas if schemas is not None else schema(), model, steps.append)
    end = next(s for s in steps if s["type"] == "tool_end")
    start = next(s for s in steps if s["type"] == "tool_start")
    return start, end, seen


def test_tool_events_summarise_args_and_results_with_redaction():
    schemas = [{"type": "function", "function": {"name": "count_rows", "parameters": {
        "type": "object", "properties": {"query": {"type": "string"},
                                         "api_key": {"type": "string"}}}}}]
    result = {"rows": [{"person_id": 1}] * 40, "row_count": 40, "dataset_id": "ds-1",
              "note": "free text that should not be copied",
              "concepts": [{"concept_id": 201826, "concept_name": "Type 2 diabetes"},
                           {"concept_id": 443238}],
              "count_contract": {"total": 40, "filtered": 12}}
    start, end, _ = tool_run(lambda **_: json.dumps(result),
                             {"query": "diabetes sk-abcdefghijklmnopqrstuvwx " + "x" * 300,
                              "api_key": "secret-value"}, schemas)
    assert start["args"]["api_key"] == "[REDACTED]"
    assert "sk-abc" not in start["args"]["query"] and len(start["args"]["query"]) <= 120
    assert end["args"] == start["args"]
    summary = end["summary"]
    assert summary["row_count"] == 40 and summary["rows_count"] == 40
    assert summary["dataset_id"] == "ds-1" and "note" not in summary
    assert summary["concept_ids"] == [201826, 443238]
    assert summary["count_contract"] == {"total": 40, "filtered": 12}
    assert "person_id" not in json.dumps(summary)
    assert len(json.dumps(end).encode()) < 2000


def test_safe_tool_error_text_reaches_the_model_and_timeline():
    _, end, seen = tool_run(lambda limit: json.dumps({"error": "unknown column: tissue_type"}),
                            {"limit": 1})
    assert "unknown column: tissue_type" in seen[0]
    assert end["error_code"] == "tool_error"
    assert end["summary"] == {"error": "unknown column: tissue_type"}


@pytest.mark.parametrize("raw", [
    'psycopg.errors.UndefinedTable: relation "secret_schema.t" does not exist\nLINE 1: SELECT * FROM x',
    "Traceback (most recent call last): File \"/app/x.py\", line 3",
    "connect to postgresql://admin:hunter2@10.0.0.4/db failed",
    "password=hunter2 rejected",
])
def test_unsafe_tool_error_text_is_replaced_by_actionable_generic(raw):
    _, end, seen = tool_run(lambda limit: json.dumps({"error": raw}), {"limit": 1})
    for leaked in ("psycopg", "secret_schema", "Traceback", "hunter2", "10.0.0.4"):
        assert leaked not in seen[0] and leaked not in json.dumps(end)
    assert "Check source, table, column and dataset names" in seen[0]


def test_tool_exceptions_relay_safe_value_errors_only():
    def bad(limit):
        raise ValueError("Unknown dataset 'ds-9'. Call list_sources to see available datasets.")

    _, end, seen = tool_run(bad, {"limit": 1})
    assert "Unknown dataset 'ds-9'" in seen[0] and end["error_code"] == "invalid_tool_input"

    def internal(limit):
        raise RuntimeError("boto3 credentials at /home/app/.aws")

    _, end, seen = tool_run(internal, {"limit": 1})
    assert "boto3" not in seen[0] and end["error_code"] == "tool_error"
    assert "Tool execution failed" in seen[0]


def test_validation_errors_name_each_field_and_allowed_fields():
    _, end, seen = tool_run(lambda limit: "{}", {"limit": "bad", "extra": 1})
    payload = json.loads(seen[0])["content"]
    assert payload["error"] == "Invalid arguments for tool count_rows."
    fields = {item["field"]: item["message"] for item in payload["details"]}
    assert "integer" in fields["limit"] and fields["extra"] == "is not a parameter of this tool"
    assert payload["allowed_fields"] == ["limit"]
    assert "limit" in end["summary"]["error"] and "extra is not a parameter" in end["summary"]["error"]


def test_invalid_json_arguments_are_explained():
    _, end, seen = tool_run(lambda limit: "{}", {"__invalid_arguments__": True})
    assert "were not valid JSON" in seen[0]
    assert end["args"] == {"invalid_json": True}


def test_unknown_tool_lists_available_tools():
    responses = iter([AIMessage(content="", tool_calls=[{"name": "cont_rows", "args": {}, "id": "t"}]),
                      AIMessage(content="done")])
    seen = []

    def model(messages, _schemas):
        seen.extend(m.content for m in messages if isinstance(m, ToolMessage))
        return next(responses)

    agent_runtime.run("openai", "m", "system", [], {"count_rows": lambda limit: "{}"},
                      schema(), model)
    assert "Unknown tool 'cont_rows'. Use one of: count_rows." in seen[0]


# 6. Stream endpoint ------------------------------------------------------------

@pytest.fixture
def workspace(agent_store, monkeypatch):
    from fastapi.testclient import TestClient
    import agent_store as store_module
    import config
    import main

    monkeypatch.setattr(store_module, "AgentStore", lambda: agent_store)
    monkeypatch.setattr(config, "get_llm_config", lambda: {
        "provider": "openai", "model": "test", "api_key": "test", "base_url": None})
    client = TestClient(main.app)
    assert client.get("/api/agent/chat/history").status_code == 200
    return client


def test_stream_endpoint_sends_text_deltas_and_enriched_events(workspace, monkeypatch, sleeps):
    def provider(provider, model, _key, _base, system, messages, tool_impls, *,
                 on_step=None, **_kwargs):
        replies = iter([
            StatusError(503),
            AIMessage(content="Checking.", tool_calls=[{
                "name": "count_rows", "args": {"limit": 2}, "id": "t1"}],
                usage_metadata={"input_tokens": 4, "output_tokens": 2, "total_tokens": 6}),
            AIMessage(content="There are 2 rows.",
                      usage_metadata={"input_tokens": 5, "output_tokens": 3, "total_tokens": 8}),
        ])

        def invoke(_messages, _schemas, tool_choice=None, on_text=None):
            reply = next(replies)
            if isinstance(reply, Exception):
                raise reply
            on_text(reply.content)
            return reply

        return agent_runtime.run(provider, model, system, messages,
                                 {"count_rows": lambda limit: json.dumps({"row_count": limit})},
                                 schema(), invoke, on_step=on_step)

    monkeypatch.setattr(providers, "run", provider)
    response = workspace.post("/api/agent/chat/stream", json={"message": "Count rows"})
    assert response.status_code == 200
    output = [json.loads(line) for line in response.text.splitlines()]
    deltas = [e for e in output if e["type"] == "text_delta"]
    assert [(d["turn"], d["text"]) for d in deltas] == [(1, "Checking."), (2, "There are 2 rows.")]
    progress = [e for e in output if e["type"] == "progress"]
    retry = next(e for e in progress if e["stage"] == "model_retry_start")
    assert retry["attempt"] == 1 and retry["reason"] == "server_error" and "wait_seconds" in retry
    tool_end = next(e for e in progress if e["stage"] == "tool_end")
    assert tool_end["tool_name"] == "count_rows"
    assert tool_end["args"] == {"limit": 2} and tool_end["summary"] == {"row_count": 2}
    model_end = [e for e in progress if e["stage"] == "model_end"]
    assert model_end[-1]["usage"]["total_tokens"] == 14
    assert model_end[0]["step_usage"]["total_tokens"] == 6
    assert model_end[0]["tool_calls"] == ["count_rows"]
    result = next(e["result"] for e in output if e["type"] == "result")
    assert result["reply"] == "There are 2 rows."
    # Deltas are display-only: the persisted history holds the final reply.
    history = workspace.get("/api/agent/chat/history").json()
    assert history["messages"][-1]["content"] == "There are 2 rows."
    assert output[-1] == {"type": "end"}


def test_stream_endpoint_forwards_limit_reason(workspace, monkeypatch):
    def provider(*_args, on_step=None, **_kwargs):
        on_step({"type": "runtime_limit", "turn": 3, "reason": "turn_budget"})
        return {"reply": "Summary.", "usage": {}, "tool_calls": [], "limit_reached": True}

    monkeypatch.setattr(providers, "run", provider)
    output = [json.loads(line) for line in
              workspace.post("/api/agent/chat/stream", json={"message": "Go"}).text.splitlines()]
    limit = next(e for e in output if e.get("stage") == "runtime_limit")
    assert limit["reason"] == "turn_budget"


def test_progress_fields_are_an_explicit_allowlist():
    assert set(agent_stream._PROGRESS_FIELDS) >= {"args", "summary", "usage", "reason",
                                                  "attempt", "wait_seconds"}


def test_cancel_while_backing_off_raises_from_the_real_sleep():
    import threading

    class Cancelled(Exception):
        pass

    stopped = threading.Event()
    attempts = []

    def model(*_):
        attempts.append(True)
        stopped.set()  # Stop pressed while the provider is failing
        raise StatusError(529)

    with agent_runtime.cancellation(stopped, Cancelled), pytest.raises(Cancelled):
        agent_runtime.run("anthropic", "m", "system", [], {}, [], model)
    assert attempts == [True]
