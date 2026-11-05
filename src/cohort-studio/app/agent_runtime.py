import agent_guardrails
import contextlib
import contextvars
import inspect
import json
import hashlib
import random
import re
import time
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph, add_messages
from pydantic import ConfigDict, Field, ValidationError, create_model
from langsmith.run_helpers import tracing_context

MAX_TURNS = 8
MAX_ALLOWED_TURNS = 16
MAX_RUNTIME_SECONDS = 600
MAX_TOOL_CALLS_PER_RESPONSE = 16
MAX_TOTAL_TOOL_CALLS = 64
MAX_FAILED_CALLS_PER_TOOL = 3
MAX_TOOL_OUTPUT_BYTES = 64 * 1024
_LIMIT_REPLY = ("I wasn't able to finish that in a reasonable number of "
                "steps — try narrowing the request.")
# Total bytes of earlier tool results kept verbatim in the model context
# within one run. Older large results beyond this are replaced by a marker.
MAX_CONTEXT_TOOL_BYTES = 256 * 1024
_CONTEXT_PRUNE_MIN_BYTES = 2048
_PRUNED_TOOL_RESULT = json.dumps({"trust": "untrusted_tool_data", "content": {
    "truncated": True,
    "note": "Earlier tool result removed to keep the context within budget. "
            "Re-run the tool if you need these details again."}})
# Provider retries: bounded exponential backoff with jitter.
MODEL_MAX_RETRIES = 3
MODEL_RETRY_BASE_SECONDS = 2.0
MODEL_RETRY_MAX_DELAY_SECONDS = 20.0
MODEL_RETRY_TOTAL_SECONDS = 45.0
_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}
_RETRYABLE_AWS_CODES = {"ThrottlingException", "ServiceUnavailableException",
                        "InternalServerException", "ModelNotReadyException",
                        "TooManyRequestsException", "ServiceQuotaExceededException"}
_RETRYABLE_ERROR_NAMES = {"APITimeoutError", "APIConnectionError", "ReadTimeoutError",
                          "ConnectTimeoutError", "EndpointConnectionError",
                          "ConnectionClosedError", "ReadTimeout", "ConnectTimeout",
                          "ConnectError", "RemoteProtocolError", "OverloadedError",
                          "InternalServerError", "RateLimitError"}
# Final narration call when the step budget is reached.
_FINAL_CALL_MIN_SECONDS = 20.0
_FINAL_SUMMARY_PROMPT = (
    "The step budget for this request has been reached, so no more tools can run. "
    "Without calling any tools, briefly summarise for the user what the completed "
    "tool results above showed (only facts those results support), and list what "
    "is still left to do so they can ask you to continue.")
_BUDGET_NOTE = ("\n\n_Step budget reached: this summary covers the steps completed "
                "so far. Ask me to continue for the remaining work._")

# Live text: model text deltas are coalesced before they reach the sink so a
# fast token stream cannot flood the bounded NDJSON queue.
TEXT_FLUSH_CHARS = 64
TEXT_FLUSH_SECONDS = 0.08
# Tool event summaries shown in the UI step timeline and the eval harness.
MAX_EVENT_SUMMARY_BYTES = 800
_SUMMARY_STRING_CHARS = 120

_cancel_event: contextvars.ContextVar = contextvars.ContextVar("agent_cancel_event", default=None)
_cancel_error: contextvars.ContextVar = contextvars.ContextVar("agent_cancel_error", default=None)
_text_sink: contextvars.ContextVar = contextvars.ContextVar("agent_text_sink", default=None)


@contextlib.contextmanager
def cancellation(event, raise_with: type[BaseException] | None = None):
    """Let retry backoff wake early when ``event`` (a threading.Event) is set.
    With ``raise_with``, a wake-up caused by the event raises that exception
    instead of starting the next attempt."""
    token = _cancel_event.set(event)
    error_token = _cancel_error.set(raise_with)
    try:
        yield
    finally:
        _cancel_error.reset(error_token)
        _cancel_event.reset(token)


@contextlib.contextmanager
def text_stream(sink):
    """Receive live model text as ``{"type": "text_delta", "turn", "text"}``.

    Deltas use this side channel rather than ``on_step`` because step events
    are persisted one row each; text deltas are display-only. Adapters stream
    only while a sink is set. The sink may raise to cancel the run."""
    token = _text_sink.set(sink)
    try:
        yield
    finally:
        _text_sink.reset(token)


def _cancelled() -> bool:
    event = _cancel_event.get()
    return bool(event is not None and event.is_set())


def _sleep(seconds: float):
    event = _cancel_event.get()
    if event is not None:
        event.wait(seconds)
        error = _cancel_error.get()
        if error is not None and event.is_set():
            raise error()
    else:
        time.sleep(seconds)


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def error_status(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if isinstance(code, int):
            return code
    return None


def error_code(exc: BaseException) -> str:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        return str(response.get("Error", {}).get("Code") or "")
    return ""


def error_names(exc: BaseException) -> set[str]:
    return {cls.__name__ for cls in type(exc).__mro__}


def is_timeout(exc: BaseException) -> bool:
    return isinstance(exc, TimeoutError) or bool(
        error_names(exc) & {"APITimeoutError", "ReadTimeoutError", "ConnectTimeoutError",
                            "ReadTimeout", "ConnectTimeout", "Timeout"})


def is_overloaded(exc: BaseException) -> bool:
    return error_status(exc) == 529 or "OverloadedError" in error_names(exc) \
        or "overloaded" in str(exc).lower()


def is_retryable(exc: BaseException) -> bool:
    status = error_status(exc)
    if error_code(exc) in _RETRYABLE_AWS_CODES:
        return True
    if status is not None:
        return status in _RETRYABLE_STATUS or status >= 500
    return (isinstance(exc, (TimeoutError, ConnectionError))
            or bool(error_names(exc) & _RETRYABLE_ERROR_NAMES)
            or is_overloaded(exc))


def _retry_after(exc: BaseException) -> float | None:
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if not headers:
        return None
    try:
        value = headers.get("retry-after-ms")
        if value is not None:
            return max(0.0, float(value) / 1000)
        value = headers.get("retry-after")
        if value is not None:
            return max(0.0, float(value))
    except (TypeError, ValueError):
        return None
    return None


def _retry_delay(exc: BaseException, attempt: int) -> float:
    hinted = _retry_after(exc)
    if hinted is not None:
        return min(MODEL_RETRY_MAX_DELAY_SECONDS, hinted + random.uniform(0, 0.5))
    base = min(MODEL_RETRY_MAX_DELAY_SECONDS, MODEL_RETRY_BASE_SECONDS * (2 ** attempt))
    return base * random.uniform(0.5, 1.0)


def retry_reason(exc: BaseException) -> str:
    status = error_status(exc)
    code = error_code(exc)
    if is_overloaded(exc):
        return "overloaded"
    if status == 429 or code in ("ThrottlingException", "TooManyRequestsException",
                                 "ServiceQuotaExceededException") \
            or "RateLimitError" in error_names(exc):
        return "rate_limit"
    if status in (408, 504) or is_timeout(exc):
        return "timeout"
    if (status is not None and status >= 500) or code in (
            "ServiceUnavailableException", "InternalServerException", "ModelNotReadyException"):
        return "server_error"
    return "connection"


def _accepts(model_call, name: str) -> bool:
    try:
        parameters = inspect.signature(model_call).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(p.name == name or p.kind is inspect.Parameter.VAR_KEYWORD
               for p in parameters)


def _accepts_tool_choice(model_call) -> bool:
    return _accepts(model_call, "tool_choice")


class _TextRelay:
    """Coalesces one model call's text deltas and records whether any arrived."""

    def __init__(self, sink, turn: int):
        self.sink = sink
        self.turn = turn
        self.parts: list[str] = []
        self.size = 0
        self.emitted = False
        self.last_flush = time.monotonic()

    def __call__(self, text):
        if not isinstance(text, str) or not text:
            return
        self.emitted = True
        self.parts.append(text)
        self.size += len(text)
        if self.size >= TEXT_FLUSH_CHARS \
                or time.monotonic() - self.last_flush >= TEXT_FLUSH_SECONDS:
            self.flush()

    def flush(self):
        if not self.parts:
            return
        text = "".join(self.parts)
        self.parts, self.size = [], 0
        self.last_flush = time.monotonic()
        self.sink({"type": "text_delta", "turn": self.turn, "text": text})


# --- Event summaries (bounded, redacted) ------------------------------------

_SECRET_KEY = re.compile(r"(?i)(secret|password|passwd|token|credential|api[_-]?key|"
                         r"authorization|cookie|private[_-]?key|access[_-]?key)")
_SECRET_VALUE = re.compile(
    r"(?i)(\bbearer\s+[A-Za-z0-9._~+/-]+=*|\b(?:sk|pk|rk)-[A-Za-z0-9_-]{12,}|"
    r"\bAKIA[A-Z0-9]{16}\b|\bASIA[A-Z0-9]{16}\b|\bgh[pousr]_[A-Za-z0-9_]{12,}|"
    r"\bgithub_pat_[A-Za-z0-9_]{20,}|\bxox[abprs]-[A-Za-z0-9-]{10,}|"
    r"://[^/\s:@]+:[^@\s]+@|"
    r"\b(?:api[_ -]?key|password|passwd|secret|access[_ -]?token|refresh[_ -]?token|"
    r"authorization)\b\s*[:=]\s*[^\s,;]+)")
# Markers of internal detail (stack traces, file paths, SQL, SDK internals,
# addresses) that must not be relayed from raw tool errors.
_INTERNAL_DETAIL = re.compile(
    r"(?i)(traceback|\bfile \"|site-packages|\.py\b|(?:^|[\s'\"(])/(?:home|users|opt|usr|var|tmp|"
    r"app|etc|srv|root|private)/|\bselect\b.+\bfrom\b|\binsert\s+into\b|\bupdate\s+\w+\s+set\b|"
    r"\bsqlalchemy\b|psycopg|\bbotocore\b|\bboto3\b|arn:aws|://|\b0x[0-9a-f]{6,}|"
    r"\b\d{1,3}(?:\.\d{1,3}){3}\b|\bline \d+\b|\bat 0x)")
_RESULT_TEXT_KEYS = re.compile(
    r"(?i)^(id|name|title|table|schema|source|dataset|status|kind|format|workflow|column|"
    r"agg|entity_column|grain|stage|mode|database|catalog|resource|scope|query_scope|"
    r"source_kind|run_status|plan_status|domain|vocabulary_id|concept_name)$|_id$")
_GENERIC_TOOL_ERROR = ("The tool reported an error without a shareable detail. Check source, "
                       "table, column and dataset names against earlier tool results, then "
                       "retry with corrected arguments.")
_GENERIC_TOOL_EXCEPTION = ("Tool execution failed. Check the inputs against earlier tool "
                           "results and the source's availability.")


def _redact(value: str, limit: int = _SUMMARY_STRING_CHARS) -> str:
    text = _SECRET_VALUE.sub("[REDACTED]", value[:2000])
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _compact(value: Any, depth: int = 0) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _redact(value)
    if isinstance(value, (list, tuple)):
        items = [_compact(item, depth + 1) for item in list(value)[:5]]
        if len(value) > 5:
            items.append(f"… +{len(value) - 5} more")
        return items
    if isinstance(value, dict):
        if depth >= 2:
            return f"{{{len(value)} fields}}"
        return {str(key)[:40]: ("[REDACTED]" if _SECRET_KEY.search(str(key))
                                else _compact(item, depth + 1))
                for key, item in list(value.items())[:12]}
    return _redact(str(value), 60)


def _bounded(summary: dict) -> dict:
    if len(json.dumps(summary, default=str).encode()) <= MAX_EVENT_SUMMARY_BYTES:
        return summary
    shorter = {key: (_redact(value, 40) if isinstance(value, str) else
                     value if isinstance(value, (bool, int, float)) or value is None
                     else _redact(json.dumps(value, default=str), 40))
               for key, value in summary.items()}
    if len(json.dumps(shorter, default=str).encode()) <= MAX_EVENT_SUMMARY_BYTES:
        return shorter
    return {"truncated": True, "fields": [str(key)[:40] for key in list(summary)[:12]]}


def summarize_args(args: Any) -> dict:
    """Compact, redacted view of model-supplied tool arguments for events."""
    if not isinstance(args, dict):
        return {}
    if args.get("__invalid_arguments__") is True:
        return {"invalid_json": True}
    return _bounded(_compact(args))


def summarize_result(result: Any) -> dict:
    """Key facts from a successful tool result: scalar counts and flags, short
    identifier-like strings, list sizes and OMOP concept ids. Free text, rows
    and previews are never copied."""
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except (TypeError, json.JSONDecodeError):
            return {}
    if isinstance(result, list):
        return {"items": len(result)}
    if not isinstance(result, dict):
        return {}
    summary: dict[str, Any] = {}
    concept_ids: list[int] = []

    def collect_ids(items):
        for item in items[:50]:
            if isinstance(item, dict) and isinstance(item.get("concept_id"), int) \
                    and not isinstance(item.get("concept_id"), bool):
                concept_ids.append(item["concept_id"])

    for key, value in result.items():
        if len(summary) >= 10:
            break
        key = str(key)
        if _SECRET_KEY.search(key) or key == "trust":
            continue
        if isinstance(value, bool) or isinstance(value, (int, float)):
            summary[key[:40]] = value
        elif isinstance(value, str):
            if _RESULT_TEXT_KEYS.search(key) and len(value) <= 200:
                summary[key[:40]] = _redact(value, 80)
        elif isinstance(value, list):
            summary[key[:36] + "_count"] = len(value)
            collect_ids(value)
        elif isinstance(value, dict):
            nested = {str(k)[:30]: v for k, v in value.items()
                      if (isinstance(v, (int, float)) and not isinstance(v, bool))
                      or (isinstance(v, str) and _RESULT_TEXT_KEYS.search(str(k))
                          and len(v) <= 80)}
            if nested:
                summary[key[:40]] = {k: (_redact(v, 60) if isinstance(v, str) else v)
                                     for k, v in list(nested.items())[:5]}
            for item in value.values():
                if isinstance(item, list):
                    collect_ids(item)
    if concept_ids:
        summary["concept_ids"] = list(dict.fromkeys(concept_ids))[:8]
    return _bounded(summary)


def safe_tool_message(value: Any, limit: int = 240) -> str:
    """A tool's own error text when it is short and carries no secrets or
    internal detail; otherwise an empty string."""
    if not isinstance(value, str):
        return ""
    lines = [line.strip() for line in value.strip().splitlines() if line.strip()]
    if not lines:
        return ""
    message = lines[0]
    if len(message) > limit or _SECRET_VALUE.search(message) \
            or _SECRET_KEY.search(message) or _INTERNAL_DETAIL.search(message):
        return ""
    return message


def _cap_tool_context(messages: list[BaseMessage],
                      limit: int | None = None) -> list[BaseMessage]:
    """Replace the oldest large tool results with a marker once the total
    tool-result bytes exceed ``limit``. Results answering the latest assistant
    turn are always kept. Oldest-first pruning keeps the pruned prefix stable
    across later calls, so prompt caching still applies to it."""
    limit = MAX_CONTEXT_TOOL_BYTES if limit is None else limit
    last_ai = max((i for i, m in enumerate(messages) if isinstance(m, AIMessage)), default=-1)
    sizes = [(i, len(m.content.encode("utf-8", errors="replace")))
             for i, m in enumerate(messages)
             if isinstance(m, ToolMessage) and isinstance(m.content, str)]
    total = sum(size for _, size in sizes)
    if total <= limit:
        return messages
    pruned = list(messages)
    marker = len(_PRUNED_TOOL_RESULT)
    for index, size in sizes:
        if total <= limit:
            break
        if index > last_ai or size < _CONTEXT_PRUNE_MIN_BYTES:
            continue
        pruned[index] = messages[index].model_copy(update={"content": _PRUNED_TOOL_RESULT})
        total -= size - marker
    return pruned


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    turns: int
    usage: dict[str, int]
    tool_calls: list[str]
    tool_results: list[dict[str, str]]
    failed_signatures: dict[str, str]
    failure_counts: dict[str, int]
    stop_reply: str
    completion_reply: str
    limit_reached: bool
    limit_reason: str
    reply: str


class AgentToolResult(str):
    def __new__(cls, value: str, failure: dict[str, str] | None = None,
                completion_reply: str = ""):
        result = super().__new__(cls, value)
        result.failure = failure
        result.completion_reply = completion_reply
        return result


def _signature(name: str, args: Any) -> str:
    encoded = json.dumps({"name": name, "args": args}, sort_keys=True,
                         separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _schema_type(schema: dict[str, Any], name: str = "Arguments") -> Any:
    kind = schema.get("type", "object")
    if "enum" in schema:
        return Literal.__getitem__(tuple(schema["enum"]))
    if kind == "string":
        typ = str
        constraints = {key: schema[value] for key, value in (
            ("min_length", "minLength"), ("max_length", "maxLength"),
            ("pattern", "pattern")) if value in schema}
    elif kind == "integer":
        typ = int
        constraints = {key: schema[value] for key, value in (
            ("ge", "minimum"), ("gt", "exclusiveMinimum"),
            ("le", "maximum"), ("lt", "exclusiveMaximum")) if value in schema}
    elif kind == "number":
        typ = float
        constraints = {key: schema[value] for key, value in (
            ("ge", "minimum"), ("gt", "exclusiveMinimum"),
            ("le", "maximum"), ("lt", "exclusiveMaximum")) if value in schema}
    elif kind == "boolean":
        return bool
    else:
        constraints = {}
    if kind in ("string", "integer", "number") and constraints:
        typ = Annotated[typ, Field(**constraints)]
    if kind == "array":
        item_type = _schema_type(schema.get("items", {}), name + "Item")
        min_items = schema.get("minItems")
        max_items = schema.get("maxItems")
        if min_items is not None or max_items is not None:
            item_type = Annotated[list[item_type], Field(min_length=min_items,
                                                         max_length=max_items)]
        else:
            item_type = list[item_type]
        return item_type
    if kind == "object":
        required = set(schema.get("required", []))
        fields = {}
        for prop, spec in schema.get("properties", {}).items():
            typ = _schema_type(spec, name + prop.title())
            default = ... if prop in required else spec.get("default", None)
            fields[prop] = (typ, Field(default))
        return create_model(name, __config__=ConfigDict(extra="forbid", strict=True), **fields)
    if kind in ("string", "integer", "number"):
        return typ
    return Any


def _validators(tool_schemas: list[dict]) -> dict[str, Any]:
    models = {}
    for item in tool_schemas:
        function = item.get("function", item)
        name = function.get("name")
        if name:
            models[name] = _schema_type(
                function.get("parameters", {"type": "object"}),
                "Tool" + name.title().replace("_", ""))
    return models


def _validation_details(exc: Exception) -> list[dict[str, str]]:
    try:
        issues = exc.errors(include_input=False)
    except TypeError:
        issues = getattr(exc, "errors", lambda: [])()
    details = []
    for issue in issues[:8]:
        loc = ".".join(str(part) for part in issue.get("loc", ())) or "arguments"
        kind = issue.get("type", "")
        if loc == "__invalid_arguments__":
            details.append({"field": "arguments", "message":
                            "were not valid JSON; send one JSON object matching the tool schema"})
            continue
        if kind == "extra_forbidden":
            message = "is not a parameter of this tool"
        elif kind == "missing":
            message = "is required"
        else:
            message = str(issue.get("msg", "invalid value"))[:160]
        details.append({"field": loc[:80], "message": message})
    return details


def _safe_validation_error(name: str, exc: Exception,
                           allowed: list[str] | None = None) -> tuple[str, str]:
    """Tool-result JSON and a one-line failure text naming each bad field."""
    details = _validation_details(exc)
    payload = {"error": f"Invalid arguments for tool {name}.", "details": details}
    if allowed is not None:
        payload["allowed_fields"] = allowed[:30]
    text = "; ".join(f"{item['field']} {item['message']}" if item["message"].startswith(
        ("is ", "were ")) else f"{item['field']}: {item['message']}" for item in details)
    failure = (f"Invalid arguments for {name}: {text}." if text else
               f"Invalid arguments for {name}. Correct them to match the tool schema.")
    return json.dumps(payload), failure[:300]


def _usage(message: AIMessage) -> dict[str, int]:
    metadata = message.usage_metadata or {}
    usage = message.response_metadata.get("token_usage", {})
    prompt = metadata.get("input_tokens", usage.get("prompt_tokens", 0)) or 0
    completion = metadata.get("output_tokens", usage.get("completion_tokens", 0)) or 0
    total = (metadata.get("total_tokens") or usage.get("total_tokens")
             or prompt + completion)
    return {"prompt_tokens": int(prompt), "completion_tokens": int(completion),
            "total_tokens": int(total)}


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "\n".join(block.get("text", "") for block in content
                          if isinstance(block, dict) and isinstance(block.get("text"), str)).strip()
    return ""


def run(provider: str, model: str, system: str, messages: list[dict],
        tool_impls: dict, tool_schemas: list[dict], model_call,
        on_step=None, max_turns: int = MAX_TURNS) -> dict:
    if isinstance(max_turns, bool) or not isinstance(max_turns, int) \
            or not 1 <= max_turns <= MAX_ALLOWED_TURNS:
        raise ValueError(f"max_turns must be between 1 and {MAX_ALLOWED_TURNS}.")
    validators = _validators(tool_schemas)
    empty_args = _schema_type({"type": "object"}, "UndeclaredToolArguments")
    deadline = time.monotonic() + MAX_RUNTIME_SECONDS
    # The date goes last so the large static system prefix stays cacheable;
    # it changes once per day.
    initial_messages: list[BaseMessage] = [SystemMessage(
        content=system + "\n" + agent_guardrails.POLICY
        + f"\nToday's date (UTC) is {_today()}. Use it to interpret relative "
          "dates such as \"recent\" or \"last year\".")]
    conversation_text = [message.get("content") for message in messages
                         if message.get("role") in ("user", "assistant")
                         and isinstance(message.get("content"), str)]
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role == "reference" and content:
            initial_messages.append(HumanMessage(content="UNTRUSTED REFERENCE DATA\n" + content))
        elif role == "user" and content:
            initial_messages.append(HumanMessage(content=content))
        elif role == "assistant" and content:
            initial_messages.append(AIMessage(content=content))

    def emit(event: dict):
        if on_step:
            on_step({"provider": provider, "model": model, **event})

    streams_text = _accepts(model_call, "on_text")

    def relay_for(turn: int):
        sink = _text_sink.get()
        return _TextRelay(sink, turn) if sink is not None and streams_text else None

    def invoke_model(view, turn: int, relay, **kwargs):
        if relay is not None:
            kwargs["on_text"] = relay
        try:
            return model_call(view, tool_schemas, **kwargs)
        finally:
            if relay is not None:
                relay.flush()

    def call_with_retries(call, turn: int, relay=None):
        attempt = 0
        waited = 0.0
        while True:
            try:
                return call()
            except Exception as exc:
                # Text already shown to the user cannot be taken back, so a
                # call that streamed any text is never retried.
                if relay is not None and relay.emitted:
                    raise
                if attempt >= MODEL_MAX_RETRIES or not is_retryable(exc):
                    raise
                delay = _retry_delay(exc, attempt)
                if waited + delay > MODEL_RETRY_TOTAL_SECONDS \
                        or deadline - time.monotonic() <= delay:
                    raise
                attempt += 1
                # One event per attempt, before the wait so the UI can show
                # it; the step hook raises if the run was already cancelled
                # and _sleep raises if it is cancelled while backing off.
                emit({"type": "model_retry_start", "turn": turn, "attempt": attempt,
                      "wait_seconds": round(delay, 1), "reason": retry_reason(exc)})
                _sleep(delay)
                waited += delay

    def call_model(state: AgentState) -> dict:
        if time.monotonic() >= deadline:
            emit({"type": "runtime_limit", "turn": state["turns"], "reason": "wall_clock"})
            return {"reply": _LIMIT_REPLY, "limit_reached": True,
                    "limit_reason": "wall_clock"}
        turn = state["turns"] + 1
        emit({"type": "model_start", "turn": turn})
        view = _cap_tool_context(state["messages"])
        relay = relay_for(turn)
        response = call_with_retries(lambda: invoke_model(view, turn, relay), turn, relay)
        if not isinstance(response, AIMessage):
            raise TypeError("Model adapter must return a LangChain AIMessage.")
        step_usage = _usage(response)
        usage = {key: state["usage"][key] + step_usage[key]
                 for key in state["usage"]}
        tool_names = [call.get("name", "") for call in response.tool_calls]
        reply = _content_text(response.content)
        over_tool_budget = (
            len(response.tool_calls) > MAX_TOOL_CALLS_PER_RESPONSE
            or len(state["tool_calls"]) + len(response.tool_calls) > MAX_TOTAL_TOOL_CALLS)
        if over_tool_budget:
            reply = _LIMIT_REPLY
        emit({"type": "model_end", "turn": turn, "usage": usage,
              "step_usage": step_usage, "tool_calls": tool_names})
        if over_tool_budget:
            emit({"type": "runtime_limit", "turn": turn, "reason": "tool_calls"})
        return {"messages": [response], "turns": turn, "usage": usage,
                "reply": reply, **({"limit_reached": True,
                                    "limit_reason": "tool_calls"} if over_tool_budget else {})}

    def execute_tools(state: AgentState) -> dict:
        assistant = state["messages"][-1]
        results = []
        calls = list(state["tool_calls"])
        tool_results = list(state["tool_results"])
        failed_signatures = dict(state["failed_signatures"])
        failure_counts = dict(state["failure_counts"])
        stop_reply = state["stop_reply"]
        limit_reached = state["limit_reached"]
        limit_reason = ""
        completion_reply = ""
        for call in assistant.tool_calls:
            name = call.get("name", "")
            call_id = call.get("id") or f"tool-{state['turns']}-{len(calls)}"
            calls.append(name)
            arg_summary = summarize_args(call.get("args") or {})
            emit({"type": "tool_start", "turn": state["turns"], "tool_name": name,
                  "args": arg_summary})
            signature = _signature(name, call.get("args") or {})
            error = None
            result_summary: dict = {}
            failure_text = "The tool call failed."
            tool_value = None
            try:
                if stop_reply:
                    result = json.dumps({"error": "Execution stopped after repeated tool failures.",
                                         "code": "no_progress"})
                    error = "no_progress"
                    failure_text = "Execution stopped after repeated tool failures."
                elif signature in failed_signatures:
                    previous = failed_signatures[signature]
                    result = json.dumps({"error": "This exact tool call already failed. Correct its inputs instead of repeating it.",
                                         "code": "no_progress"})
                    error = "no_progress"
                    failure_text = previous
                    stop_reply = (f"I stopped after the same {name} call failed twice. "
                                  f"The tool reported: {previous} Please correct the inputs and try again.")
                elif failure_counts.get(name, 0) >= MAX_FAILED_CALLS_PER_TOOL:
                    previous = failed_signatures.get(f"tool:{name}", "The tool did not return a result.")
                    result = json.dumps({"error": "Further calls to this tool were stopped after repeated failures.",
                                         "code": "no_progress"})
                    error = "no_progress"
                    failure_text = previous
                    stop_reply = (f"I stopped after {MAX_FAILED_CALLS_PER_TOOL} failed calls to {name}. "
                                  f"The last issue was: {previous}")
                elif time.monotonic() >= deadline:
                    result = json.dumps({"error": "Execution time budget exceeded.",
                                         "code": "runtime_limit"})
                    error = "runtime_limit"
                    limit_reached = True
                    limit_reason = "wall_clock"
                elif name not in tool_impls:
                    available = sorted(tool_impls)[:40]
                    failure_text = (f"Unknown tool {_redact(str(name), 60)!r}. Use one of: "
                                    + ", ".join(available) + ".")[:400]
                    result = json.dumps({"error": failure_text, "code": "unknown_tool",
                                         "available_tools": available})
                    error = "unknown_tool"
                else:
                    validator = validators.get(name, empty_args)
                    args = validator.model_validate(call.get("args") or {}).model_dump(
                        exclude_none=True)
                    tool_value = tool_impls[name](**args)
                    safe_failure = getattr(tool_value, "failure", None)
                    result = tool_value
                    if not isinstance(result, str):
                        result = json.dumps(result, default=str)
                    if len(result.encode("utf-8", errors="replace")) > MAX_TOOL_OUTPUT_BYTES:
                        result = json.dumps({"error": "Tool result exceeded the 64 KiB limit; no result was returned.",
                                             "code": "tool_result_too_large"})
                        error = "tool_result_too_large"
                        failure_text = "Tool result exceeded the 64 KiB limit. Narrow the request."
                    else:
                        try:
                            parsed = json.loads(result)
                        except (TypeError, json.JSONDecodeError):
                            parsed = None
                        if safe_failure and isinstance(parsed, dict) and parsed.get("error"):
                            code = str(safe_failure.get("code", "tool_error"))[:60]
                            failure_text = str(safe_failure.get("message", "Tool call failed."))[:300]
                            result = json.dumps({"error": failure_text, "code": code})
                            error = code
                        elif isinstance(parsed, dict) and parsed.get("error"):
                            # Unclassified tool errors are relayed only when
                            # they are short and free of internal detail.
                            failure_text = (safe_tool_message(parsed.get("error"))
                                            or _GENERIC_TOOL_ERROR)
                            result = json.dumps({"error": failure_text, "code": "tool_error"})
                            error = "tool_error"
                        else:
                            error = None
                            result_summary = summarize_result(parsed)
            except Exception as exc:
                if isinstance(exc, ValidationError):
                    fields = getattr(validators.get(name, empty_args), "model_fields", None)
                    result, failure_text = _safe_validation_error(
                        name, exc, list(fields) if isinstance(fields, dict) else None)
                    error = "invalid_arguments"
                elif isinstance(exc, TimeoutError):
                    failure_text = ("The tool timed out. Narrow the request (fewer rows or "
                                    "columns, a smaller date range) and retry once.")
                    result = json.dumps({"error": failure_text, "code": "tool_error"})
                    error = "tool_error"
                elif isinstance(exc, ValueError) and safe_tool_message(str(exc)):
                    failure_text = safe_tool_message(str(exc))
                    result = json.dumps({"error": failure_text, "code": "invalid_tool_input"})
                    error = "invalid_tool_input"
                else:
                    failure_text = _GENERIC_TOOL_EXCEPTION
                    result = json.dumps({"error": failure_text, "code": "tool_error"})
                    error = "tool_error"
            if error:
                tool_results.append({"name": name, "status": "failed"})
                if error not in {"runtime_limit", "no_progress"}:
                    failure_counts[name] = failure_counts.get(name, 0) + 1
                    failed_signatures[signature] = failure_text
                    failed_signatures[f"tool:{name}"] = failure_text
                    if failure_counts[name] >= MAX_FAILED_CALLS_PER_TOOL and not stop_reply:
                        stop_reply = (f"I stopped after {MAX_FAILED_CALLS_PER_TOOL} failed calls to {name}. "
                                      f"The last issue was: {failure_text}")
            else:
                tool_results.append({"name": name, "status": "completed"})
                failed_signatures.clear()
                failure_counts.clear()
                if name in agent_guardrails.LITERATURE_TOOLS:
                    agent_guardrails.note_literature_result(result)
            results.append(ToolMessage(content=agent_guardrails.tool_evidence(result), tool_call_id=call_id, name=name))
            event = {"type": "tool_end", "turn": state["turns"], "tool_name": name,
                     "args": arg_summary}
            if error:
                event["error_code"] = error
                event["summary"] = {"error": _redact(failure_text, 300)}
            else:
                event["summary"] = result_summary
            emit(event)
            if not error and isinstance(tool_value, AgentToolResult) and tool_value.completion_reply:
                completion_reply = tool_value.completion_reply
                emit({"type": "approval_required", "turn": state["turns"], "tool_name": name})
                break
        return {"messages": results, "tool_calls": calls, "tool_results": tool_results,
                "failed_signatures": failed_signatures, "failure_counts": failure_counts,
                "stop_reply": stop_reply, "completion_reply": completion_reply,
                "limit_reached": limit_reached,
                **({"limit_reason": limit_reason} if limit_reason else {})}

    def route_after_model(state: AgentState) -> str:
        if state["reply"] == _LIMIT_REPLY:
            return END
        if not state["messages"][-1].tool_calls:
            return END
        if time.monotonic() >= deadline:
            return "limit"
        return "tools"

    def route_after_tools(state: AgentState) -> str:
        if state["completion_reply"]:
            return "complete"
        if state["stop_reply"]:
            return "stop"
        if state["limit_reached"] or state["turns"] >= max_turns or time.monotonic() >= deadline:
            return "limit"
        return "model"

    def final_summary(state: AgentState, reason: str):
        """One tool-free call that narrates the completed tool results."""
        last = state["messages"][-1] if state["messages"] else None
        if reason == "wall_clock" or (isinstance(last, AIMessage) and last.tool_calls):
            return "", state["usage"]
        if deadline - time.monotonic() < _FINAL_CALL_MIN_SECONDS:
            return "", state["usage"]
        turn = state["turns"] + 1
        view = _cap_tool_context(state["messages"]) + [HumanMessage(content=_FINAL_SUMMARY_PROMPT)]
        emit({"type": "model_start", "turn": turn, "final_summary": True})
        relay = relay_for(turn)
        try:
            kwargs = {"tool_choice": "none"} if _accepts_tool_choice(model_call) else {}
            response = invoke_model(view, turn, relay, **kwargs)
        except Exception:
            # A cancelled run must stop, not fall back to the limit reply.
            if _cancelled():
                raise
            response = None
        if not isinstance(response, AIMessage):
            emit({"type": "model_end", "turn": turn, "usage": state["usage"],
                  "step_usage": {}, "tool_calls": []})
            return "", state["usage"]
        step_usage = _usage(response)
        usage = {key: state["usage"][key] + step_usage[key] for key in state["usage"]}
        # Tool calls in this response are ignored: no tools may run now.
        emit({"type": "model_end", "turn": turn, "usage": usage,
              "step_usage": step_usage, "tool_calls": []})
        return _content_text(response.content), usage

    def limit(state: AgentState) -> dict:
        reason = state.get("limit_reason") or (
            "turn_budget" if state["turns"] >= max_turns else "wall_clock")
        emit({"type": "runtime_limit", "turn": state["turns"], "reason": reason})
        summary, usage = final_summary(state, reason)
        return {"reply": summary + _BUDGET_NOTE if summary else _LIMIT_REPLY,
                "usage": usage, "limit_reached": True, "limit_reason": reason}

    def stop(state: AgentState) -> dict:
        return {"reply": state["stop_reply"]}

    graph = StateGraph(AgentState)
    graph.add_node("model", call_model)
    graph.add_node("tools", execute_tools)
    graph.add_node("limit", limit)
    graph.add_node("stop", stop)
    graph.add_node("complete", lambda state: {"reply": state["completion_reply"]})
    graph.add_edge(START, "model")
    graph.add_conditional_edges("model", route_after_model,
                                {"tools": "tools", "limit": "limit", END: END})
    graph.add_conditional_edges("tools", route_after_tools,
                                {"model": "model", "limit": "limit", "stop": "stop", "complete": "complete"})
    graph.add_edge("limit", END)
    graph.add_edge("stop", END)
    graph.add_edge("complete", END)
    with tracing_context(enabled=False), \
            agent_guardrails.literature_context(conversation_text):
        result = graph.compile().invoke({
            "messages": initial_messages,
            "turns": 0,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "tool_calls": [],
            "tool_results": [],
            "failed_signatures": {},
            "failure_counts": {},
            "stop_reply": "",
            "completion_reply": "",
            "limit_reached": False,
            "limit_reason": "",
            "reply": "",
        }, {"recursion_limit": max_turns * 3 + 2})
    return {"reply": result["reply"] or "(done)", "usage": result["usage"],
            "tool_calls": result["tool_calls"], "tool_results": result["tool_results"],
            "turns": result["turns"],
            "limit_reached": result.get("limit_reached", False),
            **({"limit_reason": result["limit_reason"]}
               if result.get("limit_reason") else {}),
            **({"completion_reason": "approval_required"} if result.get("completion_reply") else {}),
            **({"stop_reason": "tool_failures"} if result.get("stop_reply") else {})}
