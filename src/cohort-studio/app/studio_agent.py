import json
from datetime import date, datetime

import agent
import agent_instructions
import agent_sessions
import config
import knowledge
import llm
import providers
import vertexai_auth
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message: str = Field(min_length=1, max_length=8000)

    @field_validator("message")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must contain non-whitespace text.")
        return value.strip()


_TOOLS = [
    ("list_sources", "List sources visible in the current workspace.", {}),
    ("list_tables", "List table metadata for a selected datasource, optionally filtering names.", {
        "resource_id": {"type": "string", "minLength": 1, "maxLength": 256},
        "kind": {"type": "string", "enum": ["aurora", "s3"],
                 "default": "aurora"},
        "query": {"type": "string", "maxLength": 256, "default": ""},
    }, ["resource_id"]),
    ("inspect_table", "Inspect a validated source reference and its metadata.", {
        "source_json": {"type": "string", "minLength": 2, "maxLength": 16000},
    }, ["source_json"]),
    ("search_concepts", "Search the selected OMOP CDM for concept names and IDs.", {
        "resource_id": {"type": "string", "minLength": 1, "maxLength": 256},
        "q": {"type": "string", "minLength": 1, "maxLength": 1000},
        "domain": {"type": "string", "maxLength": 64, "default": ""},
    }, ["resource_id", "q"]),
    ("count_cohort", "Count people and attrition for a validated OMOP cohort spec.", {
        "resource_id": {"type": "string", "minLength": 1, "maxLength": 256},
        "spec_json": {"type": "string", "minLength": 2, "maxLength": 20000},
    }, ["resource_id", "spec_json"]),
    ("recommend_join", "Return deterministic and Jev join-key evidence. Jev scores are probabilities, not proof.", {
        "left_json": {"type": "string", "minLength": 2, "maxLength": 16000},
        "right_json": {"type": "string", "minLength": 2, "maxLength": 16000},
    }, ["left_json", "right_json"]),
    ("build_dashboard", "Propose a dashboard title, charts and filters for review.", {
        "source_json": {"type": "string", "minLength": 2, "maxLength": 16000},
        "title": {"type": "string", "minLength": 1, "maxLength": 128},
        "charts_json": {"type": "string", "maxLength": 8000, "default": "[]"},
        "filters_json": {"type": "string", "maxLength": 8000, "default": "[]"},
    }, ["source_json", "title"]),
    ("query_dashboard", "Query an owned dashboard using its saved filters plus requested filters; return full-scope counts and at most five preview rows.", {
        "dataset_id": {"type": "string", "minLength": 1, "maxLength": 64},
        "filters_json": {"type": "string", "maxLength": 8000, "default": "[]"},
        "charts_json": {"type": "string", "maxLength": 8000, "default": "[]"},
    }, ["dataset_id"]),
    ("list_workflows", "List available workflow metadata. This does not submit a run.", {}),
    ("prepare_workflow", "Prepare a workflow proposal for user review. This never submits a run.", {
        "dataset_id": {"type": "string", "minLength": 1, "maxLength": 64},
        "input_resource_id": {"type": "string", "minLength": 1, "maxLength": 256},
        "output_resource_id": {"type": "string", "minLength": 1, "maxLength": 256},
        "filters_json": {"type": "string", "maxLength": 8000, "default": "[]"},
    }, ["dataset_id", "input_resource_id", "output_resource_id"]),
]


def _tool_schemas() -> list[dict]:
    return [{"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties,
                        "required": required[0] if required else []},
    }} for name, description, properties, *required in _TOOLS]


TOOL_SCHEMAS = _tool_schemas()
_JSON_FIELDS = {
    "inspect_table": {"source_json": dict},
    "count_cohort": {"spec_json": dict},
    "recommend_join": {"left_json": dict, "right_json": dict},
    "build_dashboard": {"source_json": dict, "charts_json": list,
                         "filters_json": list},
    "query_dashboard": {"filters_json": list, "charts_json": list},
    "prepare_workflow": {"filters_json": list},
}
_MAX_TOOL_OUTPUT_BYTES = 60 * 1024


def _json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return str(value)


def _tool_result(name: str, callback, args: dict) -> str:
    for field, expected in _JSON_FIELDS.get(name, {}).items():
        try:
            value = json.loads(args[field])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"{field} must contain valid JSON.") from exc
        if not isinstance(value, expected):
            shape = "object" if expected is dict else "array"
            raise ValueError(f"{field} must contain a JSON {shape}.")
    result = callback(**args)
    encoded = json.dumps(result, ensure_ascii=False, default=_json_default)
    if len(encoded.encode("utf-8")) > _MAX_TOOL_OUTPUT_BYTES:
        raise ValueError("Tool result is too large. Narrow the request.")
    return encoded


def build_tools(operations: dict) -> list:
    allowed = {name for name, *_ in _TOOLS}
    unknown = set(operations) - allowed
    if unknown:
        raise ValueError("Unsupported agent operation.")
    tools = []
    for name, *_ in _TOOLS:
        callback = operations.get(name)

        def invoke(_callback=callback, _name=name, **args):
            if _callback is None:
                return json.dumps({"error": f"{_name} is unavailable."})
            try:
                return _tool_result(_name, _callback, args)
            except Exception as exc:
                return json.dumps({"error": str(exc).split("\n")[0][:300]})

        invoke.__name__ = name
        tools.append(invoke)
    return tools


def _system_prompt() -> str:
    return (
        agent_instructions.system_guidance(
            "bioinformatics, cohort data science, and data engineering",
            tool_schemas=TOOL_SCHEMAS,
        ) + "\n\n"
        "You are the data engineer assistant in Cohort Studio. First inspect "
        "available sources and metadata. Ground OMOP concept IDs in real "
        "concept search results before counting a cohort. Distinguish persons "
        "from event rows and report the data scope and evidence for claims. "
        "Treat Jev recommendations as probabilistic evidence only; metadata, "
        "key names, entity levels and row-level checks remain important. "
        "Dashboard and workflow tools return proposals for the user to review. "
        "Never submit a workflow or make an external change. Do not write or "
        "execute raw SQL. Do not invent table metadata, concepts, counts, "
        "join evidence or workflow capabilities.\n"
        "Source recipes are JSON objects. Aurora tables use "
        "{\"kind\":\"aurora\",\"resource_id\":\"...\","
        "\"schema\":\"cdm\",\"table\":\"person\"}. OMOP cohorts use "
        "{\"kind\":\"omop_cohort\",\"resource_id\":\"...\","
        "\"membership_mode\":\"live\",\"spec\":{\"criteria\":[]}}. "
        "A join recipe has the form {\"kind\":\"join\",\"base\":<source>,"
        "\"steps\":[{\"source\":<source>,\"how\":\"inner\","
        "\"conditions\":[{\"left\":\"person_id\",\"op\":\"=\","
        "\"right\":\"person_id\"}],\"alias\":\"genetics\"}]}. "
        "Use exact recipes and IDs returned by tools. Chart specs are objects "
        "such as {\"kind\":\"bar\",\"x\":\"gender\"}; filters are "
        "arrays of validated categorical or numeric range filters. "
        "`list_sources` may return dashboard dataset IDs for later workflow "
        "proposals or dashboard queries. Do not invent IDs or resource paths.\n"
    )


def chat(message: str, operations: dict, on_step=None) -> dict:
    request = ChatInput.model_validate({"message": message})
    cfg = config.get_llm_config()
    provider = cfg["provider"]
    llm.validate_config(cfg)
    system = _system_prompt() + knowledge.context(request.message)
    stored_history = agent_sessions.start(system, cfg, request.message)
    messages = []
    if stored_history is not None:
        messages = [{"role": item["role"], "content": item["content"]}
                    for item in stored_history[-agent.MAX_HISTORY:]
                    if item.get("role") in ("user", "assistant")
                    and item.get("content")]
    messages.append({"role": "user", "content": request.message})
    impls = {tool.__name__: tool for tool in build_tools(operations)}
    step = None
    if stored_history is not None or on_step is not None:
        def step(event):
            agent_sessions.event(event)
            if on_step:
                on_step(event)
    if provider == "bedrock":
        out = agent.run_bedrock(cfg, system, messages, impls, TOOL_SCHEMAS,
                                on_step=step)
    else:
        try:
            out = providers.run(
                provider, cfg["model"], cfg["api_key"], cfg.get("base_url"),
                system, messages, impls, tool_schemas=TOOL_SCHEMAS,
                vertex_config=(cfg if provider == "vertexai" else None),
                **({"on_step": step} if step else {}))
        except vertexai_auth.VertexAuthUnavailable as exc:
            raise llm.LLMNotConfigured(str(exc)) from exc
    return {"reply": out["reply"], "usage": out["usage"],
            "tool_calls": out.get("tool_calls", []),
            "provider": provider, "model": cfg["model"]}
