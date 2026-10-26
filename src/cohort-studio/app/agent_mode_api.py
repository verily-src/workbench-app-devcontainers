import hashlib
import json
import threading
import time
import uuid

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

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

    @field_validator("message")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Enter a request.")
        return value.strip()


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


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
    def __init__(self, owner):
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
                           "source_ref": value["source_ref"], "filters": value["filters"]}
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
        return parsed

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
        filters = llm.validate_filters(filters, column_settings.profiles(datasets.get(dataset_id)))
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

    def query_dashboard(self, dataset_id, filters_json="[]", charts_json="[]"):
        entry = _owned(self.owner, dataset_id)
        charts, filters = self._view_options(dataset_id, charts_json, filters_json)
        return datasets.query(dataset_id, entry["filters"] + filters, charts, 0, 5)

    def list_workflows(self):
        return {"registry": workflows.list_workflows(), "jobs": workflows.list_jobs()}

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

    def callbacks(self):
        names = ("list_sources", "list_tables", "inspect_table", "search_concepts", "count_cohort",
                 "recommend_join", "build_dashboard", "query_dashboard", "list_workflows", "prepare_workflow")
        return {name: getattr(self, name) for name in names}


@router.post("/chat")
def chat(req: AgentRequest, request: Request, response: Response):
    import studio_agent
    owner = agent_sessions.owner(request, response)
    operations = Operations(owner)
    try:
        with agent_sessions.bind(owner, _SCOPE, str(req.session_id) if req.session_id else None):
            result = studio_agent.chat(req.message, operations.callbacks())
            agent_sessions.finish(result)
        return {**result, "actions": operations.actions, "workflow_plans": operations.workflow_plans}
    except llm.LLMNotConfigured as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/chat/history")
def history(request: Request, response: Response, session_id: uuid.UUID | None = None,
            before: int | None = None):
    return agent_sessions.history(agent_sessions.owner(request, response), _SCOPE, session_id, before)


@router.post("/workflows/{plan_id}/approve")
def approve(plan_id: str, req: ApprovalRequest, request: Request, response: Response):
    import agent_workflows
    main = _main()
    owner = agent_sessions.owner(request, response)
    def export_cohort(dataset_id, resource_id, path, filters, column_mapping):
        return main.export_cohort(dataset_id, main.ExportCohortRequest(
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
            inspect_dataset=lambda did, f: _inspect_dataset(owner, did, f),
            export_cohort=export_cohort, submit_workflow=submit_workflow)
    except (agent_workflows.PlanNotFound, agent_workflows.PlanOwnerMismatch) as exc:
        raise HTTPException(404, "Workflow plan expired or unknown.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/workflows/{plan_id}/status")
def status(plan_id: str, request: Request, response: Response):
    import agent_workflows
    try:
        return agent_workflows.status(plan_id, agent_sessions.owner(request, response),
                                      list_jobs=workflows.list_jobs)
    except (agent_workflows.PlanNotFound, agent_workflows.PlanOwnerMismatch, ValueError) as exc:
        raise HTTPException(404, "Workflow plan expired or unknown.") from exc
