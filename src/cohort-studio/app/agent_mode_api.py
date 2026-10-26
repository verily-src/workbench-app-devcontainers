import hashlib
import json
import threading
import time
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

import agent_guardrails
import agent_sessions
import datasets
import column_settings
import db
import join_discovery
import llm
import omop
import workflows
from source_models import source_dict

router = APIRouter(prefix="/api/agent")
_lock = threading.RLock()
_dashboards: dict[str, dict] = {}
_SCOPE = "workspace:agent-mode"


class AgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message: str = Field(min_length=1, max_length=8000)
    session_id: uuid.UUID | None = Field(default=None, strict=False)
    new_session: bool = False

    @field_validator("message")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Enter a request.")
        return value.strip()

    @model_validator(mode="after")
    def session_choice(self):
        if self.new_session and self.session_id is not None:
            raise ValueError("Choose an existing conversation or start a new one.")
        return self


class AgentFilter(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    column: str = Field(min_length=1, max_length=512)
    kind: Literal["categorical", "range"]
    values: list[str] | None = Field(default=None, max_length=1000)
    min: float | None = None
    max: float | None = None


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AgentSessionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: uuid.UUID
    title: str = Field(max_length=80)
    updated_at: datetime


class AgentSessionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sessions: list[AgentSessionSummary] = Field(max_length=50)


def _main():
    import main
    return main


def _owned(owner, dataset_id):
    with _lock:
        entry = _dashboards.get(dataset_id)
        if not entry or entry["owner"] != owner:
            raise ValueError("This dashboard is not available in your Agent session.")
        datasets.get(dataset_id)
        return entry


def _inspect_dataset(owner, dataset_id, filters):
    _owned(owner, dataset_id)
    ds = datasets.get(dataset_id)
    query = datasets.query(dataset_id, filters, [], 0, 1)
    columns = column_settings.profiles(ds)
    names = [c["name"] for c in columns]
    required = ("person_id", "sample_id", "variant_id", "dosage", "gender_concept_id", "year_of_birth")
    mapping = {}
    for name in required:
        matches = [c for c in names if c.endswith(" → " + name)]
        if name in names:
            mapping[name] = name
        elif len(matches) == 1:
            mapping[name] = matches[0]
    identity = {"source": ds.get("source_ref"), "columns": columns}
    return {"rows": query["filtered"], "columns": [c["name"] for c in columns],
            "column_mapping": mapping, "capped": query.get("sampled", False), "source_ref": ds.get("source_ref"),
            "fingerprint": hashlib.sha256(json.dumps(identity, sort_keys=True,
                                                       default=str).encode()).hexdigest()}


class Operations:
    def __init__(self, owner, user_message=""):
        self.user_message = user_message
        self.owner = owner
        self.actions = []
        self.workflow_plans = []
        self.inspected = set()
        self.concepts = {}
        self.available = {(s["kind"], s["id"]) for s in _main().datasources()["sources"]
                          if s["kind"] in {"aurora", "s3"}}

    def _resource(self, kind, resource_id):
        if (kind, resource_id) not in self.available:
            raise ValueError("Select a datasource exposed by this workspace.")

    def _table(self, value):
        ref = source_dict(value)
        if ref["kind"] not in {"aurora", "s3"}:
            raise ValueError("Inspect an Aurora table or S3 file.")
        self._resource(ref["kind"], ref["resource_id"])
        schema = ref.get("schema") or "public"
        if schema.startswith("_") or ref["table"].split(".")[-1].startswith("_"):
            raise ValueError("Internal application tables are not available to Agent mode.")
        entries = _main().tables(ref["kind"], ref["resource_id"])
        if not any((item.get("table") == ref["table"] and item.get("schema", "public") == schema)
                   or (ref["kind"] == "s3" and item["name"] == ref["table"]) for item in entries):
            raise ValueError("Table or file was not found in the datasource.")
        return ref

    @staticmethod
    def _identity(ref):
        return json.dumps({k: ref[k] for k in ("kind", "resource_id", "schema", "table")
                           if k in ref}, sort_keys=True)

    def list_sources(self):
        with _lock:
            dashboards = [{"dataset_id": key, "title": value["title"],
                           "source_ref": value["source_ref"], "filters": value["filters"],
                           "verification": value.get("verification")}
                          for key, value in _dashboards.items() if value["owner"] == self.owner]
        return {"sources": [{"kind": kind, "id": rid} for kind, rid in sorted(self.available)],
                "dashboards": dashboards[-20:]}

    def list_tables(self, resource_id, kind="aurora", query=""):
        self._resource(kind, resource_id)
        entries = [item for item in _main().tables(kind, resource_id)
                   if not item.get("table", item["name"]).split(".")[-1].startswith("_")
                   and query.casefold() in item["name"].casefold()]
        return {"tables": entries[:100], "total": len(entries), "truncated": len(entries) > 100}

    def inspect_table(self, source_json):
        ref = self._table(json.loads(source_json))
        if ref["kind"] == "aurora":
            metadata = join_discovery._metadata(join_discovery.AuroraTableRef.model_validate(ref), False)
        else:
            opened = _main()._open_source(ref, temporary=True)
            try:
                metadata = {"columns": opened["columns"], "rows": opened["rows"],
                            "scope": opened.get("query_scope")}
            finally:
                datasets.close_dataset(opened["dataset_id"])
        self.inspected.add(self._identity(ref))
        return {"source_ref": ref, "metadata": metadata}

    def search_concepts(self, resource_id, q, domain=""):
        self._resource("aurora", resource_id)
        engine, info = _main()._omop_cdm(resource_id)
        concepts = omop.search_concepts(engine, info, q=q, domain=domain or None, limit=20)
        self.concepts.setdefault(resource_id, set()).update(c["concept_id"] for c in concepts)
        return {"concepts": concepts, "cdm_schema": info["cdm_schema"]}

    def _spec(self, resource_id, spec):
        parsed = omop.parse_spec(spec)
        for criterion in parsed["criteria"]:
            if not set(criterion.get("concept_ids", [])) <= self.concepts.get(resource_id, set()):
                raise ValueError("Search concepts in this turn before using their IDs.")
        return spec

    def count_cohort(self, resource_id, spec_json):
        self._resource("aurora", resource_id)
        engine, info = _main()._omop_cdm(resource_id)
        return omop.count(engine, info, self._spec(resource_id, json.loads(spec_json)))

    def recommend_join(self, left_json, right_json):
        left, right = self._table(json.loads(left_json)), self._table(json.loads(right_json))
        if left["kind"] != "aurora" or right["kind"] != "aurora":
            raise ValueError("Jev schema recommendations currently require Aurora tables.")
        self.inspected.update((self._identity(left), self._identity(right)))
        return join_discovery.recommend(join_discovery.RecommendRequest.model_validate(
            {"left": left, "right": right})).model_dump(mode="json")

    def _source(self, ref):
        kind = ref["kind"]
        if kind == "omop_cohort":
            self._resource("aurora", ref["resource_id"])
            self._spec(ref["resource_id"], ref["spec"])
        elif kind == "join":
            if ref.get("allow_loaded"):
                raise ValueError("Cross-source preview consent must be given in the visual join builder.")
            self._source(ref["base"])
            for step in ref["steps"]:
                self._source(step["source"])
        elif kind in {"aurora", "s3"}:
            canonical = self._table(ref)
            if self._identity(canonical) not in self.inspected:
                raise ValueError("Inspect this table before building its dashboard.")
        else:
            raise ValueError("Agent mode uses table, file, OMOP and join recipes; raw SQL is not enabled.")

    def _view_options(self, dataset_id, charts_json, filters_json):
        charts, filters = json.loads(charts_json), json.loads(filters_json)
        if not isinstance(charts, list) or len(charts) > 8 or not isinstance(filters, list) or len(filters) > 30:
            raise ValueError("Use at most eight charts and thirty filters.")
        main = _main()
        charts = [main.ChartSpec.model_validate(c).model_dump(exclude_none=True) for c in charts]
        filters = [AgentFilter.model_validate(f).model_dump(exclude_none=True) for f in filters]
        columns = {c["name"] for c in column_settings.profiles(datasets.get(dataset_id))}
        for f in filters:
            if f["column"] not in columns:
                raise ValueError("Unknown filter column. Use the dashboard column metadata; no filters were applied.")
            if f["kind"] == "categorical" and not f.get("values"):
                raise ValueError("Categorical filters require at least one value.")
            if f["kind"] == "range" and (f.get("min") is None or f.get("max") is None or f["min"] > f["max"]):
                raise ValueError("Range filters require min and max with min <= max.")
        return charts, filters

    def build_dashboard(self, source_json, title, charts_json="[]", filters_json="[]"):
        if len(self.actions) >= 4:
            raise ValueError("At most four dashboards can be created in one turn.")
        ref = source_dict(json.loads(source_json))
        self._source(ref)
        opened = _main()._open_source(ref)
        dataset_id = opened["dataset_id"]
        try:
            charts, filters = self._view_options(dataset_id, charts_json, filters_json)
            if not charts:
                charts = [{"kind": "histogram" if c["filter_kind"] == "range" else "bar", "x": c["name"]}
                          for c in opened["columns"] if c["filter_kind"] in {"range", "categorical"}][:4]
            result = datasets.query(dataset_id, filters, charts, 0, 5)
        except Exception:
            datasets.close_dataset(dataset_id)
            raise
        action = {"dataset": opened, "title": title[:128], "charts": charts, "filters": filters}
        self.actions.append(action)
        with _lock:
            expired = [key for key, value in _dashboards.items() if time.monotonic() - value["created"] > 43200]
            for key in expired:
                _dashboards.pop(key, None)
            if len(_dashboards) >= 256:
                _dashboards.pop(next(iter(_dashboards)))
            _dashboards[dataset_id] = {"owner": self.owner, "title": title[:128],
                                       "source_ref": ref, "filters": filters, "created": time.monotonic()}
        return {"dataset_id": dataset_id, "title": title[:128], "source_ref": ref,
                "total": result["total"], "filtered": result["filtered"],
                "scope": result.get("scope"), "columns": opened["columns"], "charts": result["charts"]}

    def query_dashboard(self, dataset_id, filters_json="[]", charts_json="[]", entity_column=""):
        entry = _owned(self.owner, dataset_id)
        charts, filters = self._view_options(dataset_id, charts_json, filters_json)
        return datasets.query(dataset_id, entry["filters"] + filters, charts, 0, 5,
                              entity_column=entity_column or None)

    def check_grain(self, dataset_id):
        _owned(self.owner, dataset_id)
        import grain
        return grain.check(dataset_id)

    def list_workflows(self):
        import agent_workflows
        return {"registry": workflows.list_workflows(), "jobs": workflows.list_jobs(),
                "plans": agent_workflows.list_plans(self.owner)}

    def prepare_workflow(self, dataset_id, input_resource_id, output_resource_id, filters_json="[]"):
        import agent_workflows
        entry = _owned(self.owner, dataset_id)
        _, filters = self._view_options(dataset_id, "[]", filters_json)
        self._resource("s3", input_resource_id)
        self._resource("s3", output_resource_id)
        plan = agent_workflows.prepare(dataset_id, input_resource_id, output_resource_id,
            entry["filters"] + filters, self.owner,
            inspect_dataset=lambda did, f: _inspect_dataset(self.owner, did, f),
            list_workflows=workflows.list_workflows, resolve_s3_resource=db.resolve_s3_uri)
        self.workflow_plans.append(plan)
        return plan

    def workflow_status(self, plan_id):
        import agent_workflows
        return agent_workflows.status(plan_id, self.owner, list_jobs=workflows.list_jobs)

    def open_workflow_results(self, plan_id):
        if len(self.actions) >= 4:
            raise ValueError("At most four dashboards can be opened in one turn.")
        result = _open_workflow_result(self.owner, plan_id)
        self.actions.append(result["action"])
        did = result["action"]["dataset"]["dataset_id"]
        return {"dataset_id": did, "verification": result["verification"],
                "preview": datasets.query(did, [], [], 0, 20)}

    def search_knowledge(self, query, limit=5):
        import knowledge
        return knowledge.search(knowledge.Search(query=query, limit=limit))

    def search_pubmed(self, query, limit=5):
        import config
        import literature
        agent_guardrails.validate_literature_query(self.user_message, query)
        return literature.search_pubmed(query, limit=limit, api_key=config.get_ncbi_api_key() or "")

    def search_biorxiv(self, query, start_date, end_date, limit=5):
        import literature
        agent_guardrails.validate_literature_query(self.user_message, query)
        return literature.search_biorxiv(query, start_date, end_date, limit=limit)

    def callbacks(self):
        names = ("search_knowledge", "search_pubmed", "search_biorxiv", "list_sources", "list_tables", "inspect_table", "search_concepts", "count_cohort",
                 "recommend_join", "build_dashboard", "query_dashboard", "check_grain", "list_workflows", "prepare_workflow",
                 "workflow_status", "open_workflow_results")
        return {name: getattr(self, name) for name in names}


@router.post("/chat")
def chat(req: AgentRequest, request: Request, response: Response):
    import studio_agent
    owner = agent_sessions.owner(request, response)
    operations = Operations(owner, user_message=req.message)
    try:
        with agent_sessions.bind(owner, _SCOPE,
                                 str(req.session_id) if req.session_id else None,
                                 new_session=req.new_session):
            result = studio_agent.chat(req.message, operations.callbacks())
            agent_sessions.finish(result)
        return {**result, "actions": operations.actions, "workflow_plans": operations.workflow_plans}
    except llm.LLMNotConfigured as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/chat/history")
def history(request: Request, response: Response, session_id: uuid.UUID | None = None,
            before: int | None = None):
    return agent_sessions.history(agent_sessions.owner(request, response), _SCOPE, session_id, before)


@router.get("/chat/sessions", response_model=AgentSessionsResponse,
             description="Lists up to 50 recent sessions for this owner and workspace. Older sessions remain available by explicit session ID.")
def list_sessions(request: Request, response: Response):
    from agent_store import AgentStore
    sessions = AgentStore().list_sessions(
        owner=agent_sessions.owner(request, response), scope=_SCOPE, limit=50)
    return AgentSessionsResponse(sessions=sessions)



def _restore_workflow_source(owner, plan):
    ref = source_dict(plan.get("source_ref") or {})
    available = {(s["kind"], s["id"]) for s in _main().datasources()["sources"]}
    def check(source):
        kind = source["kind"]
        if kind == "join":
            if source.get("allow_loaded"):
                raise ValueError("Rebuild this preview join before approving the workflow.")
            check(source["base"])
            for step in source["steps"]:
                check(step["source"])
        elif kind in {"aurora", "s3", "omop_cohort"}:
            resource_kind = "aurora" if kind == "omop_cohort" else kind
            if (resource_kind, source["resource_id"]) not in available:
                raise ValueError("The saved workflow source is no longer available.")
        else:
            raise ValueError("Rebuild the dataset before approving this workflow.")
    check(ref)
    opened = _main()._open_source(ref, temporary=True)
    did = opened["dataset_id"]
    with _lock:
        _dashboards[did] = {"owner": owner, "title": "Workflow input", "source_ref": ref,
                            "filters": plan.get("filters", []), "created": time.monotonic()}
    return did


@router.post("/workflows/{plan_id}/approve")
def approve(plan_id: str, req: ApprovalRequest, request: Request, response: Response):
    import agent_workflows
    main = _main()
    owner = agent_sessions.owner(request, response)
    restored = {}
    def inspect_dataset(dataset_id, filters):
        if dataset_id not in restored:
            try:
                _owned(owner, dataset_id)
            except (ValueError, datasets.DatasetNotFound):
                plan = agent_workflows.get_plan(plan_id, owner)
                restored[dataset_id] = _restore_workflow_source(owner, plan)
        return _inspect_dataset(owner, restored.get(dataset_id, dataset_id), filters)
    def export_cohort(dataset_id, resource_id, path, filters, column_mapping):
        return main.export_cohort(restored.get(dataset_id, dataset_id), main.ExportCohortRequest(
            resource_id=resource_id, path=path, filters=filters, workflow="cohort-genetics-demo",
            column_mapping=column_mapping))
    def submit_workflow(workflow, input_resource_id, input_path, output_resource_id,
                        output_path, params_resource_id, params_path, job_id):
        return main.submit_workflow(main.SubmitJobRequest(
            workflow=workflow, demo_input_resource_id=input_resource_id,
            demo_input_csv_path=input_path, output_bucket_id=output_resource_id,
            demo_output_path=output_path, params_file_bucket_id=params_resource_id,
            params_file_path=params_path, job_id=job_id))
    try:
        return agent_workflows.approve(plan_id, owner,
            inspect_dataset=inspect_dataset,
            export_cohort=export_cohort, submit_workflow=submit_workflow)
    except (agent_workflows.PlanNotFound, agent_workflows.PlanOwnerMismatch) as exc:
        raise HTTPException(404, "Workflow plan expired or unknown.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        for did in restored.values():
            with _lock:
                _dashboards.pop(did, None)
            datasets.close_dataset(did)


@router.get("/workflows/{plan_id}/status")
def status(plan_id: str, request: Request, response: Response):
    import agent_workflows
    try:
        return agent_workflows.status(plan_id, agent_sessions.owner(request, response),
                                      list_jobs=workflows.list_jobs)
    except (agent_workflows.PlanNotFound, agent_workflows.PlanOwnerMismatch, ValueError) as exc:
        raise HTTPException(404, "Workflow plan expired or unknown.") from exc


def _open_workflow_result(owner, plan_id):
    import io
    import pandas as pd
    import agent_results
    import agent_workflows
    import lineage
    plan = agent_workflows.status(plan_id, owner, list_jobs=workflows.list_jobs)
    if plan["status"] != "completed":
        raise ValueError("Workflow results are available after the run completes.")
    available = {(s["kind"], s["id"]) for s in _main().datasources()["sources"]}
    if ("s3", plan["output_resource_id"]) not in available:
        raise ValueError("The workflow output resource is not available in this workspace.")
    checked = agent_results.verify(plan["run"], plan["output_resource_id"], plan["rows"],
                                   expected_input_uri=plan["input_uri"])
    verification = {key: value for key, value in checked.items()
                    if key not in {"summary_csv", "source_ref"}}
    frame = pd.read_csv(io.BytesIO(checked["summary_csv"]))
    ref = source_dict(checked["source_ref"])
    title = "Carrier summary"
    opened = datasets.open_dataset(frame, f"{plan['output_resource_id']} / {title}", capped=False)
    did = opened["dataset_id"]
    datasets.get(did)["source_ref"] = ref
    datasets.get(did)["workflow_verification"] = verification
    opened["source_ref"] = ref
    charts = [{"kind": "scatter", "x": "people", "y": "share_within_status"}]
    try:
        datasets.query(did, [], charts, 0, 5)
    except Exception:
        datasets.close_dataset(did)
        raise
    with _lock:
        if len(_dashboards) >= 256:
            _dashboards.pop(next(iter(_dashboards)))
        _dashboards[did] = {"owner": owner, "title": title, "source_ref": ref,
                            "filters": [], "created": time.monotonic(),
                            "verification": verification}
    run_id = plan["run"]["run_id"]
    lineage.record(_main()._lineage_engine(), "workflow_results_verified", "dataset", did,
                   payload={"dataset_id": did, "run_id": run_id,
                            "source_ref": ref, "verification": verification})
    return {"action": {"dataset": opened, "title": title, "charts": charts, "filters": []},
            "verification": verification}


@router.get("/workflows")
def workflow_plans(request: Request, response: Response):
    import agent_workflows
    return {"plans": agent_workflows.list_plans(agent_sessions.owner(request, response))}


@router.post("/workflows/{plan_id}/results/open")
def open_workflow_result(plan_id: str, req: ApprovalRequest, request: Request, response: Response):
    import agent_workflows
    try:
        return _open_workflow_result(agent_sessions.owner(request, response), plan_id)
    except (agent_workflows.PlanNotFound, agent_workflows.PlanOwnerMismatch) as exc:
        raise HTTPException(404, "Workflow plan expired or unknown.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


import agent_stream
router.include_router(agent_stream.router)
