import knowledge
import agent_sessions
import functools
import json
from datetime import date, datetime

import agent
import agent_instructions
import config
import database as db
import llm
import omop
import providers
import vertexai_auth
import workbench_apps
import workflows

COHORT_TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "search_concepts",
        "description": "Search OMOP concepts for this selected CDM. "
                       "Use search results to ground concept IDs before "
                       "counting or proposing criteria.",
        "parameters": {"type": "object", "properties": {
            "q": {"type": "string"},
            "domain": {"type": "string", "description":
                       "Optional OMOP domain such as condition or drug."},
            "vocabulary": {"type": "string", "description":
                           "Optional OMOP vocabulary ID."},
            "standard_only": {"type": "boolean"}},
            "required": ["q"]}}},
    {"type": "function", "function": {
        "name": "count_cohort",
        "description": "Count people and show cumulative attrition for a "
                       "validated cohort spec. Returns aggregates only.",
        "parameters": {"type": "object", "properties": {
            "spec_json": {"type": "string", "description":
                          "JSON OMOP cohort specification."}},
            "required": ["spec_json"]}}},
    {"type": "function", "function": {
        "name": "propose_cohort",
        "description": "Propose a complete validated OMOP cohort spec for "
                       "the user to review and count/open in the UI.",
        "parameters": {"type": "object", "properties": {
            "spec_json": {"type": "string"},
            "reason": {"type": "string", "description":
                       "Short summary of the proposed criteria."}},
            "required": ["spec_json", "reason"]}}},
    {"type": "function", "function": {
        "name": "list_workflow_jobs",
        "description": "Read current and recent Workbench workflow job "
                       "statuses in this workspace.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "list_workbench_apps",
        "description": "Read the Workbench apps visible in this workspace.",
        "parameters": {"type": "object", "properties": {}}}},
]

def _jsonable(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value

def _parse_spec_json(raw: str) -> dict:
    try:
        return omop.parse_spec(json.loads(raw))
    except (json.JSONDecodeError, TypeError) as e:
        raise ValueError("spec_json must contain a JSON object.") from e

def _check_grounded(spec: dict, known_concepts: set[int]):
    requested = {concept_id for criterion in spec["criteria"]
                 for concept_id in criterion["concept_ids"]}
    unknown = requested - known_concepts
    if unknown:
        sample = ", ".join(str(i) for i in sorted(unknown)[:5])
        raise ValueError("Search for concept IDs before using them. "
                         f"Not found in current spec or search results: {sample}.")

def build_tools(resource_id: str, info: dict, current_spec: dict | None,
                state: dict):

    engine = db.get_engine_for_resource(resource_id)
    normalized_current = omop.parse_spec(_jsonable(current_spec))
    grounded = {concept_id for criterion in normalized_current["criteria"]
                for concept_id in criterion["concept_ids"]}
    concept_names = state.setdefault("concept_names", {})

    def search_concepts(q: str, domain: str = "", vocabulary: str = "",
                        standard_only: bool = True) -> str:
        """Search this CDM for concept names/IDs before building criteria."""
        try:
            results = omop.search_concepts(
                engine, info, q=q, domain=domain or None,
                vocabulary=vocabulary or None,
                standard_only=standard_only, limit=30, persons=False)
            grounded.update(int(r["concept_id"]) for r in results)
            concept_names.update({str(r["concept_id"]): r["concept_name"]
                                  for r in results if r.get("concept_name")})
            return json.dumps({"resource_id": resource_id,
                               "concepts": results}, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)[:300]})

    def count_cohort(spec_json: str) -> str:
        """Count persons and cumulative attrition for a JSON OMOP spec."""
        try:
            spec = _parse_spec_json(spec_json)
            _check_grounded(spec, grounded)
            result = omop.count(engine, info, _jsonable(spec))
            state["count"] = result
            state["count_spec"] = _jsonable(spec)
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"error": str(e)[:300]})

    def propose_cohort(spec_json: str, reason: str) -> str:
        """Propose a complete JSON cohort spec for the user to review and apply."""
        try:
            spec = _parse_spec_json(spec_json)
            _check_grounded(spec, grounded)
            normalized = _jsonable(spec)
            reason = str(reason).strip()[:240]
            state["spec"] = normalized
            state["reason"] = reason
            if state.get("count_spec") != normalized:
                state.pop("count", None)
                state.pop("count_spec", None)
            return json.dumps({"proposed": True, "spec": normalized,
                               "reason": reason, "concept_names": {
                                   str(concept_id): concept_names[str(concept_id)]
                                   for criterion in normalized["criteria"]
                                   for concept_id in criterion["concept_ids"]
                                   if str(concept_id) in concept_names},
                               "counted": state.get("count_spec") == normalized})
        except Exception as e:
            return json.dumps({"error": str(e)[:300]})

    def list_workflow_jobs() -> str:
        """Read recent workflow job status; cannot submit or cancel jobs."""
        result = workflows.list_jobs()
        if not result.get("available"):
            return json.dumps({"available": False, "jobs": []})
        fields = ("run_id", "name", "status", "workflow_type", "engine_type",
                  "created_by", "created_date", "end_time",
                  "output_bucket_name", "output_bucket_path")
        jobs = [{key: job.get(key) for key in fields}
                for job in result.get("jobs", [])[:30]]
        return json.dumps({"available": True,
                           "running_count": result.get("running_count", 0),
                           "jobs": jobs}, default=str)

    def list_workbench_apps() -> str:
        """Read workspace app status; cannot start, stop, or update apps."""
        return json.dumps(workbench_apps.list_apps(limit=20), default=str)

    return [search_concepts, count_cohort, propose_cohort,
            list_workflow_jobs, list_workbench_apps]

def _system_prompt(resource_id: str, info: dict, spec: dict) -> str:
    return (
        agent_instructions.system_guidance(
            "bioinformatics and OMOP cohort data science",
            tool_schemas=COHORT_TOOL_SCHEMAS,
        ) + "\n\n"
        "You are the cohort-building assistant inside Workbench Cohort "
        "Studio. You help the user build a person-level OMOP cohort and "
        "inspect running Workbench workflows and apps.\n\n"
        f"Selected OMOP resource: {resource_id}\n"
        f"CDM version: {info.get('version') or 'unknown'}; "
        f"CDM schema: {info.get('cdm_schema')}\n"
        f"Current cohort spec: {json.dumps(_jsonable(spec))}\n\n"
        "Cohort spec contract: top-level keys are criteria, demographics, "
        "require_observation. Criteria are AND-ed, in order. Each criterion "
        "has domain (condition, drug, procedure, measurement, observation, "
        "visit, device, or death), concept_ids (integer list; death may be "
        "empty), descendants (boolean), exclude (boolean), min_count "
        "(integer >= 1), value_min/value_max (measurement only), start/end "
        "(ISO dates YYYY-MM-DD), and index_relation (before/after/null). "
        "The first included criterion defines index date as its first event; "
        "without an included criterion, index date is first observation "
        "start. index_relation compares later criteria with that index and "
        "cannot be set on the first included criterion. demographics accepts "
        "gender_concept_ids (integer list), age_min/age_max, and "
        "year_of_birth_min/year_of_birth_max. require_observation is boolean. "
        "Do not add other keys. Keep dates as ISO strings.\n\n"
        "The selected resource is fixed. Search concepts before using new "
        "concept IDs. Count returns aggregate person counts and attrition, "
        "never person rows. Propose a complete validated spec when the user "
        "asks to build or change a cohort; the UI will let them review and "
        "count/open it. Do not claim the cohort was opened. Workflow and app "
        "tools are read-only: you may list status, but cannot submit/cancel "
        "jobs or start/stop/update apps. Mention of a resource or a status "
        "question is never authorization to change it. Ground status claims "
        "in tool results, explain when a list is unavailable, and keep the "
        "reply concise."
    )

def chat(resource_id: str, info: dict, message: str,
         history: list[dict] | None = None,
         current_spec: dict | None = None, on_step=None) -> dict:

    cfg = config.get_llm_config()
    provider = cfg["provider"]
    llm.validate_config(cfg)

    spec = omop.parse_spec(current_spec)
    state: dict = {}
    raw_tools = build_tools(resource_id, info, spec, state)
    tool_calls: list[str] = []

    def track(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            tool_calls.append(fn.__name__)
            return fn(*args, **kwargs)
        return inner

    wrapped = [track(fn) for fn in raw_tools]
    impls = {fn.__name__: wrapped_fn
             for fn, wrapped_fn in zip(raw_tools, wrapped)}
    messages = [
        {"role": item["role"], "content": item["content"]}
        for item in (history or [])[-agent.MAX_HISTORY:]
        if item.get("role") in ("user", "assistant") and item.get("content")
    ]
    messages.append({"role": "user", "content": message})
    system = _system_prompt(resource_id, info, spec) + knowledge.context(message)
    stored_history = agent_sessions.start(system, cfg, message)
    if stored_history is not None:
        messages = [
            {"role": item["role"], "content": item["content"]}
            for item in stored_history[-agent.MAX_HISTORY:]
            if item.get("role") in ("user", "assistant") and item.get("content")
        ]
        messages.append({"role": "user", "content": message})

    step = None
    if stored_history is not None or on_step is not None:
        def step(event):
            agent_sessions.event(event)
            if on_step:
                on_step(event)

    if provider == "bedrock":
        out = agent.run_bedrock(
            cfg, system, messages, impls, COHORT_TOOL_SCHEMAS, on_step=step)
    else:
        try:
            out = providers.run(
                provider, cfg["model"], cfg["api_key"], cfg.get("base_url"),
                system, messages, impls, tool_schemas=COHORT_TOOL_SCHEMAS,
                vertex_config=(cfg if provider == "vertexai" else None),
                **({"on_step": step} if step else {}))
        except vertexai_auth.VertexAuthUnavailable as exc:
            raise llm.LLMNotConfigured(str(exc)) from exc
        reply, usage = out["reply"], out["usage"]

    final_spec = state.get("spec")
    expected_count_spec = final_spec if final_spec is not None else _jsonable(spec)
    final_count = (state.get("count")
                   if state.get("count_spec") == expected_count_spec else None)
    final_names = state.get("concept_names", {})
    if final_spec is not None:
        final_names = {str(concept_id): final_names[str(concept_id)]
                       for criterion in final_spec["criteria"]
                       for concept_id in criterion["concept_ids"]
                       if str(concept_id) in final_names}
    else:
        final_names = {}
    return {"reply": out["reply"], "spec": final_spec,
            "count": final_count, "concept_names": final_names,
            "reason": state.get("reason"),
            "tool_calls": out.get("tool_calls", tool_calls), "provider": provider,
            "model": cfg["model"], "usage": out["usage"]}
