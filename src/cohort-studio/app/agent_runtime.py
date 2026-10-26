import agent_guardrails
import json
import hashlib
import time
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


def _safe_validation_error(name: str, exc: Exception) -> str:
    details = []
    for issue in getattr(exc, "errors", lambda: [])():
        loc = ".".join(str(part) for part in issue.get("loc", ()))
        details.append({"field": loc, "message": issue.get("msg", "invalid value")})
    return json.dumps({"error": f"Invalid arguments for tool {name}.",
                       "details": details[:8]})


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
    initial_messages: list[BaseMessage] = [SystemMessage(content=system + "\n" + agent_guardrails.POLICY)]
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

    def call_model(state: AgentState) -> dict:
        if time.monotonic() >= deadline:
            emit({"type": "runtime_limit", "turn": state["turns"]})
            return {"reply": _LIMIT_REPLY, "limit_reached": True,
                    "limit_reason": "wall_clock"}
        turn = state["turns"] + 1
        emit({"type": "model_start", "turn": turn})
        response = model_call(state["messages"], tool_schemas)
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
            emit({"type": "runtime_limit", "turn": turn})
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
            emit({"type": "tool_start", "turn": state["turns"], "tool_name": name})
            signature = _signature(name, call.get("args") or {})
            error = None
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
                    result = json.dumps({"error": "Unknown tool.", "code": "unknown_tool"})
                    error = "unknown_tool"
                    failure_text = "Unknown tool."
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
                            result = json.dumps({"error": "Tool validation or execution failed.",
                                                 "code": "tool_error"})
                            error = "tool_error"
                            failure_text = "Tool validation or execution failed."
                        else:
                            error = None
            except Exception as exc:
                if isinstance(exc, ValidationError):
                    result = _safe_validation_error(name, exc)
                    error = "invalid_arguments"
                    failure_text = "The tool arguments did not match the required schema. Correct the listed fields."
                else:
                    result = json.dumps({"error": "Tool execution failed.", "code": "tool_error"})
                    error = "tool_error"
                    failure_text = "Tool execution failed. Check the inputs and service availability."
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
            results.append(ToolMessage(content=agent_guardrails.tool_evidence(result), tool_call_id=call_id, name=name))
            event = {"type": "tool_end", "turn": state["turns"], "tool_name": name}
            if error:
                event["error_code"] = error
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

    def limit(state: AgentState) -> dict:
        reason = state.get("limit_reason") or (
            "turn_budget" if state["turns"] >= max_turns else "wall_clock")
        emit({"type": "runtime_limit", "turn": state["turns"], "reason": reason})
        return {"reply": _LIMIT_REPLY, "limit_reached": True,
                "limit_reason": reason}

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
    with tracing_context(enabled=False):
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
