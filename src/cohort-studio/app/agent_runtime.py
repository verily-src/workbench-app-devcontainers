import json
import time
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph, add_messages
from pydantic import ConfigDict, Field, ValidationError, create_model
from langsmith.run_helpers import tracing_context

MAX_TURNS = 8
MAX_RUNTIME_SECONDS = 600
MAX_TOOL_CALLS_PER_RESPONSE = 16
MAX_TOTAL_TOOL_CALLS = 64
MAX_TOOL_OUTPUT_BYTES = 64 * 1024
_LIMIT_REPLY = ("I wasn't able to finish that in a reasonable number of "
                "steps — try narrowing the request.")


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    turns: int
    usage: dict[str, int]
    tool_calls: list[str]
    reply: str


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
        on_step=None) -> dict:
    validators = _validators(tool_schemas)
    empty_args = _schema_type({"type": "object"}, "UndeclaredToolArguments")
    deadline = time.monotonic() + MAX_RUNTIME_SECONDS
    initial_messages: list[BaseMessage] = [SystemMessage(content=system)]
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role == "user" and content:
            initial_messages.append(HumanMessage(content=content))
        elif role == "assistant" and content:
            initial_messages.append(AIMessage(content=content))

    def emit(event: dict):
        if on_step:
            on_step({"provider": provider, "model": model, **event})

    def call_model(state: AgentState) -> dict:
        if time.monotonic() >= deadline:
            emit({"type": "runtime_limit", "turn": state["turns"]})
            return {"reply": _LIMIT_REPLY}
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
                "reply": reply}

    def execute_tools(state: AgentState) -> dict:
        assistant = state["messages"][-1]
        results = []
        calls = list(state["tool_calls"])
        for call in assistant.tool_calls:
            name = call.get("name", "")
            call_id = call.get("id") or f"tool-{state['turns']}-{len(calls)}"
            calls.append(name)
            emit({"type": "tool_start", "turn": state["turns"], "tool_name": name})
            try:
                if time.monotonic() >= deadline:
                    result = json.dumps({"error": "Execution time budget exceeded."})
                    error = "Execution time budget exceeded."
                elif name not in tool_impls:
                    result = json.dumps({"error": "Unknown tool."})
                    error = "Unknown tool."
                else:
                    validator = validators.get(name, empty_args)
                    args = validator.model_validate(call.get("args") or {}).model_dump(
                        exclude_none=True)
                    result = tool_impls[name](**args)
                    if not isinstance(result, str):
                        result = json.dumps(result, default=str)
                    if len(result.encode("utf-8", errors="replace")) > MAX_TOOL_OUTPUT_BYTES:
                        result = json.dumps({"error": "Tool result exceeded the 64 KiB limit; no result was returned."})
                        error = "Tool result exceeded the 64 KiB limit."
                    else:
                        try:
                            parsed = json.loads(result)
                        except (TypeError, json.JSONDecodeError):
                            parsed = None
                        if isinstance(parsed, dict) and parsed.get("error"):
                            result = json.dumps({"error": "Tool validation or execution failed."})
                            error = "Tool validation or execution failed."
                        else:
                            error = None
            except Exception as exc:
                result = _safe_validation_error(name, exc) if isinstance(exc, ValidationError) else json.dumps(
                    {"error": "Tool execution failed."})
                error = "Tool execution failed."
            results.append(ToolMessage(content=result, tool_call_id=call_id, name=name))
            event = {"type": "tool_end", "turn": state["turns"], "tool_name": name}
            if error:
                event["error"] = error
            emit(event)
        return {"messages": results, "tool_calls": calls}

    def route_after_model(state: AgentState) -> str:
        if state["reply"] == _LIMIT_REPLY:
            return END
        if not state["messages"][-1].tool_calls:
            return END
        if time.monotonic() >= deadline:
            emit({"type": "runtime_limit", "turn": state["turns"]})
            return "limit"
        return "tools"

    def route_after_tools(state: AgentState) -> str:
        if state["turns"] >= MAX_TURNS or time.monotonic() >= deadline:
            if state["turns"] < MAX_TURNS:
                emit({"type": "runtime_limit", "turn": state["turns"]})
            return "limit"
        return "model"

    graph = StateGraph(AgentState)
    graph.add_node("model", call_model)
    graph.add_node("tools", execute_tools)
    graph.add_node("limit", lambda _state: {"reply": _LIMIT_REPLY})
    graph.add_edge(START, "model")
    graph.add_conditional_edges("model", route_after_model,
                                {"tools": "tools", "limit": "limit", END: END})
    graph.add_conditional_edges("tools", route_after_tools,
                                {"model": "model", "limit": "limit"})
    graph.add_edge("limit", END)
    with tracing_context(enabled=False):
        result = graph.compile().invoke({
            "messages": initial_messages,
            "turns": 0,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "tool_calls": [],
            "reply": "",
        }, {"recursion_limit": MAX_TURNS * 3 + 2})
    return {"reply": result["reply"] or "(done)", "usage": result["usage"],
            "tool_calls": result["tool_calls"], "turns": result["turns"]}
