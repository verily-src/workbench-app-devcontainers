import execution
import group_summary
import grain
import operational_store
import logging
import time
import uuid
from typing import Literal
from contextlib import asynccontextmanager, nullcontext
from pathlib import Path

import pandas as pd
from fastapi import Body, FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask
from fastapi.staticfiles import StaticFiles
from pydantic import (BaseModel, ConfigDict, Field, RootModel,
                      field_validator, model_validator)

import agent
import agent_sessions
import agent_store
import knowledge
import knowledge_vectors
import secret_store
import cohort_agent
import bq
import catalog
import config
import datasets
import database as db
import postgres_sources
import external_sources
import source_registry
import duck
import disk_data
import joins
import lineage
import llm
import compare
import derive
import mcp_server
import omop
import queries
import views
import materialized_sources
import saved_snapshots
import view_jobs
import data_jobs
import workflows
import column_settings
import live_query
import query_cache
import export_jobs
import join_discovery
import sql_source
from source_models import ColumnSetting, DerivedSpec, SourceRef, source_dict

logging.basicConfig(level=logging.INFO, force=True)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.warm_resource_cache()
    if knowledge.store.path.exists():
        knowledge_vectors.schedule(knowledge.store)
    try:
        if mcp_server.AVAILABLE:
            async with mcp_server.mcp.session_manager.run():
                yield
        else:
            yield
    finally:
        knowledge_vectors.shutdown()
        data_jobs.shutdown()
        export_jobs.shutdown()
        view_jobs.shutdown()
        datasets.clear()
        operational_store.shutdown()

app = FastAPI(title="Cohort Studio", lifespan=lifespan)
app.middleware("http")(execution.trace_request)
app.include_router(knowledge.router)
app.middleware("http")(agent_sessions.preserve_owner_cookie)

@app.exception_handler(agent_store.AgentStoreError)
async def agent_store_error(_request: Request, exc: agent_store.AgentStoreError):
    status = (409 if isinstance(exc, agent_store.AgentStoreBusy) else
              404 if isinstance(exc, (agent_store.AgentStoreNotFound,
                                     agent_store.AgentStoreOwnershipError)) else 503)
    detail = ("This conversation already has a running turn." if status == 409 else
              "Conversation not found." if status == 404 else
              "Conversation storage is unavailable. Contact the app administrator.")
    return JSONResponse(status_code=status, content={"detail": detail})

@app.exception_handler(secret_store.SecretStoreError)
async def secret_store_error(_request: Request, exc: secret_store.SecretStoreError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})

@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request,
                                     exc: RequestValidationError):
    details = [{"loc": error["loc"], "msg": error["msg"],
                "type": error["type"]} for error in exc.errors()]
    status = 400 if request.url.path.startswith("/api/omop/") else 422
    return JSONResponse(status_code=status, content={"detail": details})

if mcp_server.AVAILABLE:
    app.mount("/mcp", mcp_server.http_app())

class OpenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: str | None = None
    resource_id: str | None = None
    table: str | None = None
    source_ref: SourceRef | None = None

    @model_validator(mode="after")
    def validate_source(self):
        if self.source_ref is not None:
            if any(v is not None for v in (self.kind, self.resource_id, self.table)):
                raise ValueError("Use source_ref or kind/resource_id/table, not both.")
            source_dict(self.source_ref)
        elif not all((self.kind, self.resource_id, self.table)):
            raise ValueError("Provide kind, resource_id and table.")
        return self

class SQLPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    resource_id: str = Field(min_length=1, max_length=256)
    sql: str = Field(min_length=1, max_length=sql_source.MAX_SQL_LENGTH)
    name: str | None = Field(default=None, max_length=128)

    @field_validator("sql")
    @classmethod
    def validate_sql(cls, value: str) -> str:
        return sql_source.normalize(value)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("SQL source name cannot be blank.")
        return value

class Filter(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    column: str
    kind: str
    values: list[str] | None = None
    min: float | None = None
    max: float | None = None

class AxisSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    label: str | None = Field(default=None, max_length=120)
    scale: Literal["linear", "log"] = "linear"
    min: float | None = None
    max: float | None = None

    @model_validator(mode="after")
    def valid_bounds(self):
        if self.min is not None and self.max is not None and self.min >= self.max:
            raise ValueError("Axis minimum must be less than maximum.")
        if self.scale == "log" and ((self.min is not None and self.min <= 0) or
                                    (self.max is not None and self.max <= 0)):
            raise ValueError("Logarithmic axis bounds must be positive.")
        return self


class ChartSpec(BaseModel):
    kind: str
    x: str
    y: str | None = None
    title: str | None = Field(default=None, max_length=120)
    wide: bool | None = None
    x_axis: AxisSettings | None = None
    y_axis: AxisSettings | None = None

    @model_validator(mode="after")
    def valid_map(self):
        if self.kind == "map" and (not self.y or self.y == self.x):
            raise ValueError("Map requires distinct longitude and latitude columns.")
        return self

class QueryRequest(BaseModel):
    filters: list[Filter] = Field(default_factory=list)
    charts: list[ChartSpec] = Field(default_factory=list)
    page: int = Field(default=0, ge=0, le=10_000_000)
    page_size: int = Field(default=50, ge=1, le=1000)
    entity_column: str | None = None
    refresh: bool = Field(default=False, strict=True)

class ColumnsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    columns: list[ColumnSetting] = Field(max_length=200)

class JoinCondition(BaseModel):
    left: str
    op: str = "="
    right: str

class JoinStep(BaseModel):
    right_id: str
    how: str = "left"
    conditions: list[JoinCondition] = Field(default_factory=list)
    columns: list[str] | None = None
    alias: str = ""

class JoinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    allow_loaded: bool = Field(default=False, strict=True)
    base_id: str = ""
    steps: list[JoinStep] = Field(default_factory=list)
    left_id: str = ""
    right_id: str = ""
    left_on: str = ""
    right_on: str = ""
    how: str = "inner"


class CompareRequest(BaseModel):
    filters_a: list[Filter] = Field(default_factory=list)
    filters_b: list[Filter] = Field(default_factory=list)
    b_is_rest: bool = False

class ExportCohortRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    resource_id: str
    path: str
    filters: list[Filter] = Field(default_factory=list)
    workflow: str = ""
    column_mapping: dict[str, str] = Field(default_factory=dict, max_length=6)

class SubmitJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    workflow: str
    output_bucket_id: str
    job_id: str = ""
    batch_input_bucket_id: str = ""
    batch_input_csv_path: str = ""
    column_mapping: str = ""
    row_selection: str = ""
    profile: str = ""
    output_path: str = ""
    params_file_bucket_id: str = ""
    params_file_path: str = ""
    demo_input_resource_id: str = ""
    demo_input_csv_path: str = ""
    demo_output_path: str = ""

    @model_validator(mode="after")
    def validate_workflow_inputs(self):
        workflows._validate_job_inputs(
            self.batch_input_bucket_id, self.batch_input_csv_path,
            self.params_file_bucket_id, self.params_file_path)
        demo_values = (self.demo_input_resource_id, self.demo_input_csv_path,
                       self.demo_output_path)
        if self.workflow == "cohort-genetics-demo":
            if not all(demo_values):
                raise ValueError("Demo input resource, CSV path, and output path are required.")
            workflows._safe_path_segment(self.job_id)
            if self.params_file_bucket_id != self.demo_input_resource_id:
                raise ValueError("Demo params and input CSV must use the same S3 resource.")
            if self.batch_input_bucket_id:
                raise ValueError("The Nextflow demo uses a params file, not batch CSV input.")
        elif any(demo_values):
            raise ValueError("Demo input fields are only valid for cohort-genetics-demo.")
        return self

class CatalogView(BaseModel):
    name: str
    sql: str

class BuildCatalogRequest(BaseModel):
    resource_id: str
    name: str
    views: list[CatalogView] = Field(default_factory=list)
    include_files: bool = True

class OmopCohortOpenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    spec: dict = Field(default_factory=dict)
    name: str = ""

    @model_validator(mode="after")
    def validate_spec(self):
        omop.parse_spec(self.spec)
        return self

class OmopDomainOpenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    table: str
    spec: dict | None = None
    concept_names: bool = True

    @model_validator(mode="after")
    def validate_spec(self):
        if self.spec is not None:
            omop.parse_spec(self.spec)
        return self

DeriveRequest = DerivedSpec

def _lineage_engine():
    return lineage.sqlite_fallback_engine()

def _load_frame(kind: str, resource_id: str, table: str) -> pd.DataFrame:
    if kind == "aurora":
        return db.fetch_aurora_table(resource_id, table, queries.ROW_CAP)
    if kind == "s3":
        return duck.fetch_s3_file(resource_id, table, queries.ROW_CAP)
    if kind == "bq":
        for d in db.list_bq_datasets():
            if d["id"] == resource_id:
                return bq.fetch_table(d["project"], d["dataset"], table,
                                      queries.ROW_CAP)
        raise HTTPException(404, f"Unknown BigQuery dataset: {resource_id}")
    if kind == "catalog":
        try:
            return catalog.fetch_catalog_view(resource_id, table,
                                              queries.ROW_CAP)
        except catalog.UnknownView as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))
    raise HTTPException(400, f"Unknown datasource kind: {kind}")

@app.get("/api/health")
def health():
    return {"ok": True}

@app.get("/api/version")
def version():
    sha_file = Path("/app/APP_SHA")
    local = Path(__file__).parent / "APP_SHA"
    for candidate in (sha_file, local):
        if candidate.exists():
            return {"sha": candidate.read_text().strip()}
    return {"sha": "dev"}

@app.post("/api/admin/update")
def self_update():

    script = Path(__file__).parent / "self_update.sh"
    if not script.exists():
        raise HTTPException(501, "self_update.sh not present in this build")
    import subprocess
    subprocess.Popen(["bash", str(script)],
                     stdout=open("/tmp/self-update.log", "ab"),
                     stderr=subprocess.STDOUT)
    return {"started": True, "log": "/tmp/self-update.log"}

@app.get("/api/datasources")
def datasources():
    ready = db.resources_ready()
    sources = (postgres_sources.resources() + external_sources.athena_resources()
               + [item for item in source_registry.public_sources() if item["kind"] == "s3"])
    folders = []
    if ready:
        db.retry_if_empty()
        for r in db.list_aurora_resources():
            if r.get("kind") == "postgres":
                continue
            source = {"kind": "aurora", "id": r["id"],
                      "label": f"{r['id']} · Aurora"}
            hint = omop.hint(r["id"])
            if hint:
                source["omop"] = hint
            sources.append(source)
        folders = db.list_s3_folders()
        for r in folders:
            sources.append({"kind": "s3", "id": r["id"], "uuid": r.get("uuid"),
                            "label": f"{r['id']} · S3"})
        for r in db.list_bq_datasets():
            sources.append({"kind": "bq", "id": r["id"],
                            "label": f"{r['id']} · BigQuery"})
    catalogs, pending = catalog.discover([r["id"] for r in folders])
    sources.extend(catalogs)
    return {"ready": ready or bool(sources), "sources": sources, "catalogs_pending": pending}

@app.post("/api/sources")
def add_source(req: source_registry.Registration):
    try:
        payload = req.model_dump()
        source_registry.validate_connection(payload)
        return source_registry.add(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/workflows")
def workflow_jobs(refresh: bool = False):

    return workflows.list_jobs(force=refresh)

@app.get("/api/workflows/registry")
def workflow_registry():
    return workflows.list_workflows()

@app.post("/api/datasets/{dataset_id}/export-cohort")
def export_cohort(dataset_id: str, req: ExportCohortRequest):
    try:
        ds = datasets.get(dataset_id)
    except datasets.DatasetNotFound:
        raise HTTPException(404, "Dataset expired or unknown — reload it.")
    if req.workflow == "cohort-genetics-demo" and ds.get("capped"):
        raise HTTPException(
            413, "Genetics demo requires a complete, uncapped cohort dataset.")
    if req.workflow == "cohort-genetics-demo":
        try:
            export_path = workflows._safe_object_path(req.path)
        except ValueError as e:
            raise HTTPException(400, str(e))
    filt = _export_frame(ds, [f.model_dump() for f in req.filters])
    if req.workflow == "cohort-genetics-demo":
        required = ["person_id", "sample_id", "variant_id", "dosage",
                    "gender_concept_id", "year_of_birth"]
        if set(req.column_mapping) - set(required):
            raise HTTPException(400, "Unknown workflow output column.")
        selected = [req.column_mapping.get(column, column) for column in required]
        if len(set(selected)) != len(selected):
            raise HTTPException(400, "Workflow columns must map to distinct source fields.")
        missing = [column for column in selected if column not in filt.columns]
        if missing:
            raise HTTPException(
                400, "Genetics demo export is missing required columns: "
                + ", ".join(missing))
        if len(filt) >= queries.ROW_CAP:
            raise HTTPException(
                413, "Genetics demo export reached the synchronous row limit; "
                "reduce the cohort before exporting.")
        filt = filt[selected].copy()
        filt.columns = required
    try:
        out = workflows.export_cohort_csv(
            filt, req.resource_id,
            export_path if req.workflow == "cohort-genetics-demo" else req.path)
    except Exception as e:
        raise HTTPException(502, str(e).split("\n")[0][:300])
    lineage_engine = _lineage_engine()
    cohort_event_id = lineage.latest_cohort_event_id(lineage_engine, dataset_id)
    artifact_parents = [("dataset", dataset_id)]
    if cohort_event_id is not None:
        cohort_parent = lineage.event_parent(cohort_event_id)
        if cohort_parent:
            artifact_parents.append(cohort_parent)
    artifact_event_id = lineage.record(
        lineage_engine, "artifact_exported", "artifact", out["s3_uri"],
        payload={"dataset_id": dataset_id,
                 "resource_id": out.get("resource_id", req.resource_id),
                 "path": out.get("path", req.path),
                 "rows": out["rows"],
                 "source_ref": lineage.safe_source_ref(
                     ds.get("source_ref") or ds.get("origin"))},
        parents=artifact_parents)
    artifact_parent = lineage.event_parent(artifact_event_id)
    lineage.record(
        lineage_engine, "cohort_exported", "dataset", ds["source"],
        payload={"to": out["s3_uri"], "rows": out["rows"],
                 "dataset_id": dataset_id},
        parents=[artifact_parent] if artifact_parent else [])
    return out

@app.post("/api/workflows/submit")
def submit_workflow(req: SubmitJobRequest):
    try:
        params_uri = None
        input_uri = None
        params_event_type = "workflow_params_used"
        if req.workflow == "cohort-genetics-demo":
            input_path = workflows._safe_object_path(req.demo_input_csv_path)
            output_path = workflows._safe_object_path(req.demo_output_path)
            job_segment = workflows._safe_path_segment(req.job_id)
            workflows.validate_healthomics_output(
                db.resolve_s3_uri(req.output_bucket_id), output_path, job_segment)
            input_uri = f"{db.resolve_s3_uri(req.demo_input_resource_id)}/{input_path}"
            output_bucket, output_key = workflows.s3_bucket_key(
                db.resolve_s3_uri(req.output_bucket_id), output_path, job_segment)
            params = {
                "input": input_uri,
                "input_uri": input_uri,
                "variant_id": "SYN_VAR_0021",
                "output_bucket": output_bucket,
                "output_key": output_key,
                "workflow_id": req.workflow,
            }
            written = workflows.write_params_json(
                req.params_file_bucket_id, req.params_file_path, params)
            params_uri = written["s3_uri"]
            params_event_type = "workflow_params_written"
            job = workflows.submit_job(
                workflow=req.workflow, output_bucket_id=req.output_bucket_id,
                job_id=req.job_id, profile="healthomics",
                output_path=output_path,
                params_file_bucket_id=req.params_file_bucket_id,
                params_file_path=req.params_file_path)
        else:
            if req.batch_input_bucket_id and req.batch_input_csv_path:
                input_uri = (f"{db.resolve_s3_uri(req.batch_input_bucket_id)}/"
                             f"{req.batch_input_csv_path.lstrip('/')}" )
            if req.params_file_bucket_id and req.params_file_path:
                params_uri = (f"{db.resolve_s3_uri(req.params_file_bucket_id)}/"
                              f"{req.params_file_path.lstrip('/')}" )
            job = workflows.submit_job(**req.model_dump(exclude={
                "demo_input_resource_id", "demo_input_csv_path",
                "demo_output_path",
            }))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, str(e).split("\n")[0][:300])
    lineage_engine = _lineage_engine()
    input_event_id = None
    if input_uri:
        input_event_id = lineage.latest_event_id(
            lineage_engine, "artifact_exported", "artifact", input_uri)
        if input_event_id is None:
            input_event_id = lineage.record(
                lineage_engine, "workflow_input_used", "artifact", input_uri,
                payload={"workflow": req.workflow,
                         "resource_id": (req.demo_input_resource_id
                                         or req.batch_input_bucket_id
                                         or req.params_file_bucket_id),
                         "path": (req.demo_input_csv_path
                                  or req.batch_input_csv_path)},
            )

    params_event_id = None
    if params_uri:
        params_event_id = lineage.record(
            lineage_engine, params_event_type, "artifact", params_uri,
            payload={"workflow": req.workflow,
                     "resource_id": (req.params_file_bucket_id
                                     or req.batch_input_bucket_id),
                     "path": req.params_file_path or req.batch_input_csv_path},
            parents=[parent for parent in [lineage.event_parent(input_event_id)]
                     if parent])

    run_payload = workflows.lineage_submission_metadata(
        req.workflow, job, input_uri=input_uri, params_uri=params_uri)
    lineage.record(
        lineage_engine, "workflow_submitted", "workflow",
        job.get("name") or req.workflow,
        payload=run_payload,
        parents=[parent for parent in [lineage.event_parent(input_event_id),
                                       lineage.event_parent(params_event_id)]
                 if parent])
    return job

@app.get("/api/tables")
def tables(kind: str, resource_id: str):
    try:
        if kind in {"aurora", "postgres"}:
            return [{"name": t["name"], "table": t["table"],
                     "schema": t["schema"], "detail": t["kind"]}
                    for t in db.list_aurora_tables(resource_id)]
        if kind == "athena":
            return external_sources.list_athena_tables(resource_id)
        if kind == "s3":
            return [{"name": f, "detail": "file"}
                    for f in duck.list_s3_files(resource_id)]
        if kind == "bq":
            for d in db.list_bq_datasets():
                if d["id"] == resource_id:
                    return [{"name": t, "detail": "table"}
                            for t in bq.list_tables(d["project"], d["dataset"])]
            raise HTTPException(404, f"Unknown dataset: {resource_id}")
        if kind == "catalog":
            try:
                objects = catalog.list_catalog(resource_id)
            except ValueError as e:
                raise HTTPException(400, str(e))
            return [{"name": o["name"], "detail": o["kind"], "sql": o["sql"]}
                    for o in objects]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, str(e).split("\n")[0][:300])
    raise HTTPException(400, f"Unknown kind: {kind}")

@app.post("/api/catalogs/build")
def build_catalog(req: BuildCatalogRequest):

    try:
        out = catalog.publish(req.resource_id, req.name,
                              [(v.name, v.sql) for v in req.views],
                              include_files=req.include_files)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, str(e).split("\n")[0][:300])
    lineage.record(_lineage_engine(), "catalog_published", "catalog",
                   out["uri"], payload={"resource_id": req.resource_id,
                                        "views": out["views"],
                                        "skipped": len(out["skipped"]),
                                        "bytes": out["bytes"]})
    return out

@app.post("/api/datasets/open")
def open_dataset(req: OpenRequest):
    try:
        ref = source_dict(req.source_ref or {
            "kind": req.kind, "resource_id": req.resource_id, "table": req.table})
        result = _open_source(ref)
    except HTTPException:
        raise
    except (sql_source.SQLTimeout, external_sources.AthenaTimeout) as e:
        raise HTTPException(504, str(e))
    except disk_data.OperationTooLarge as e:
        raise HTTPException(413, str(e))
    except disk_data.SourceSizeUnknown as e:
        raise HTTPException(422, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(504 if isinstance(e, joins.JoinTimeout) or "statement timeout" in str(e) else 502,
                            str(e).split("\n")[0][:300])
    lineage.record(_lineage_engine(), "table_loaded", "table", ref.get("table", result["source"]),
                   payload={"source_kind": ref["kind"], "resource_id": ref.get("resource_id"),
                            "rows": result["rows"]})
    return result


@app.post("/api/sql/preview")
def preview_sql_source(req: SQLPreviewRequest):
    try:
        return sql_source.preview(req.resource_id, req.sql, req.name)
    except (sql_source.SQLTimeout, external_sources.AthenaTimeout) as e:
        raise HTTPException(504, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, str(e).split("\n")[0][:300])

def _stored_ref(dataset_id):
    ds = datasets.get(dataset_id)
    if ds.get("source_ref"):
        return ds["source_ref"]
    origin = ds.get("origin") or {}
    if origin.get("kind") == "aurora":
        return {"kind": "aurora", "resource_id": origin["resource_id"],
                "table": origin["table"], "schema": origin.get("schema") or "public"}
    return None

def _join_ref(base_id, steps):
    base = _stored_ref(base_id)
    refs = [_stored_ref(step["right_id"]) for step in steps]
    if base is None or any(ref is None for ref in refs):
        return None
    return source_dict({"kind": "join", "base": base,
                        "steps": [{"source": ref, **{k: step[k] for k in
                                   ("how", "conditions", "columns", "alias") if k in step}}
                                  for step, ref in zip(steps, refs)]})

def _open_source(ref, temporary=False):
    ref = source_dict(ref)
    guard = materialized_sources.operation_lock if any(saved_snapshots._walk_refs(ref)) else nullcontext()
    with guard:
        return _open_source_impl(ref, temporary)


def _open_source_impl(ref, temporary=False):
    ref = source_dict(ref)
    children = []
    out = None
    origin = None
    live = None
    disk = None
    capped = None
    try:
        if ref["kind"] == "derived":
            base = _open_source(ref["base"], temporary=True)
            children.append(base["dataset_id"])
            derive.derive(base["dataset_id"], ref["spec"])
            ds = datasets.get(base["dataset_id"])
            df, label = ds["df"], ds["source"]
            live, capped = ds.get("live_source"), ds.get("capped")
        elif ref["kind"] == "join":
            base = _open_source(ref["base"], temporary=True)
            children.append(base["dataset_id"])
            steps = []
            labels = [base["source"]]
            for step in ref["steps"]:
                right = _open_source(step["source"], temporary=True)
                children.append(right["dataset_id"])
                labels.append(right["source"])
                steps.append({"right_id": right["dataset_id"], **{
                    k: step[k] for k in ("how", "conditions", "columns", "alias") if k in step}})
            out = joins.run(base["dataset_id"], steps, allow_loaded=ref.get("allow_loaded", False))
            df, label = out["df"], " + ".join(labels)
            live, capped = out.get("live_source"), out["stats"]["truncated"]
            disk = out.get("disk_source")
        elif ref["kind"] == "omop_cohort":
            engine, info = _omop_cdm(ref["resource_id"])
            df, live = omop.open_cohort_source(
                engine, info, ref["resource_id"], ref["spec"])
            capped = False
            label = f"{ref['resource_id']} / {ref.get('name') or 'OMOP cohort'}"
        elif ref["kind"] == "materialized":
            with db.get_engine_for_resource(ref["resource_id"]).begin() as conn:
                conn.exec_driver_sql("SET TRANSACTION READ ONLY")
                conn.exec_driver_sql("SET LOCAL statement_timeout = 15000")
                snapshot = materialized_sources.resolve(conn, ref["resource_id"], ref["materialized_id"])
                live = snapshot["live_source"]
                df = pd.read_sql_query(live["sql"] + f" LIMIT {queries.ROW_CAP}", conn)
                df = df.rename(columns={value: key for key, value in live["columns"].items()})
                capped = snapshot["rows"] > queries.ROW_CAP
                label = f"{ref['resource_id']} / Saved join"
        elif ref["kind"] == "sql":
            df, normalized, capped = sql_source.fetch(
                ref["resource_id"], ref["sql"], queries.ROW_CAP)
            ref["sql"] = normalized
            name = ref.get("name") or "SQL query"
            label = f"{ref['resource_id']} / {name}"
            live = {"resource_id": ref["resource_id"], "sql": normalized,
                    "params": {}, "columns": {column: column for column in df.columns}}
        else:
            kind, rid, table = ref["kind"], ref["resource_id"], ref["table"]
            schema = ref.get("schema", "public")
            if kind == "athena":
                df, disk = external_sources.open_athena(ref)
            elif kind in {"aurora", "postgres"}:
                sql = (f"SELECT * FROM {column_settings._q(schema)}."
                       f"{column_settings._q(table)}")
                df, normalized, capped = sql_source.fetch(
                    rid, sql, queries.ROW_CAP)
                live = {"resource_id": rid, "sql": normalized, "params": {},
                        "columns": {column: column for column in df.columns}}
            elif kind == "s3":
                df, disk = disk_data.open_s3(ref)
            elif kind == "catalog":
                try:
                    df, disk = disk_data.open_catalog(ref)
                except catalog.UnknownView as e:
                    raise HTTPException(404, str(e))
            elif kind == "bq":
                df = _load_frame(kind, rid, table)
                capped = len(df) >= queries.ROW_CAP
            else:
                df = _load_frame(kind, rid, table)
            label_table = (table if kind not in {"aurora", "postgres", "athena"} or schema == "public"
                           else f"{schema}.{table}")
            label = f"{rid} / {label_table}"
            if kind in {"aurora", "postgres"}:
                origin = {"kind": "aurora", "resource_id": rid, "table": table, "schema": schema}
        if live is not None:
            live = disk_data.estimate_live_source(live)
    finally:
        for child in children:
            datasets.close_dataset(child)
    result = datasets.open_dataset(
        df, label, origin=origin, temporary=temporary,
        capped=capped, live_source=live, disk_source=disk)
    dataset_id = result["dataset_id"]
    datasets.get(dataset_id)["source_ref"] = ref
    try:
        if ref.get("settings"):
            result.update(column_settings.apply(dataset_id, ref["settings"]))
    except Exception:
        datasets.close_dataset(dataset_id)
        raise
    result["source_ref"] = datasets.get(dataset_id)["source_ref"]
    if out:
        result["join"] = out["stats"]
    return result


@app.patch("/api/datasets/{dataset_id}/columns")
def configure_columns(dataset_id: str, req: ColumnsRequest):
    try:
        return column_settings.apply(dataset_id, [s.model_dump(exclude_none=True) for s in req.columns])
    except datasets.DatasetNotFound:
        raise HTTPException(404, "Dataset expired or unknown — reload it.")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(504 if isinstance(e, joins.JoinTimeout) or "statement timeout" in str(e) else 502,
                            str(e).split("\n")[0][:300])

UPLOAD_SUFFIXES = (".csv", ".tsv", ".txt")

@app.post("/api/datasets/upload")
def upload_dataset(file: UploadFile):
    name = file.filename or "upload.csv"
    if not name.lower().endswith(UPLOAD_SUFFIXES):
        raise HTTPException(
            400, f"Unsupported file type: {name}. Cohort Studio reads "
            "tabular data — upload CSV, TSV, or TXT. Formats like BAM, "
            "VCF, FASTQ, or BED are not row/column tables and can't be "
            "loaded here.")
    sep = "\t" if name.lower().endswith((".tsv", ".txt")) else ","
    try:
        df = pd.read_csv(file.file, sep=sep)
    except Exception as e:
        raise HTTPException(
            400, f"Could not parse {name} as a {sep!r}-delimited table: "
            f"{str(e).splitlines()[0][:200]}")
    result = datasets.open_dataset(df, name, capped=False)
    lineage.record(_lineage_engine(), "csv_uploaded", "file", name,
                   payload={"rows": len(df), "columns": list(df.columns)})
    return result

def _join_pipeline(req: JoinRequest) -> tuple[str, list[dict], list[str]]:

    if req.steps:
        base_id, steps = req.base_id, [s.model_dump() for s in req.steps]
    else:
        base_id, steps = req.left_id, [{
            "right_id": req.right_id, "how": req.how, "columns": None,
            "conditions": [{"left": req.left_on, "op": "=",
                            "right": req.right_on}]}]
    try:
        sources = [datasets.get(base_id)["source"]] + [
            datasets.get(s["right_id"])["source"] for s in steps]
    except datasets.DatasetNotFound:
        raise HTTPException(404, {
            "code": "DATASET_EXPIRED",
            "message": "A dataset expired or is unknown — reload it.",
        })
    for step, source in zip(steps, sources[1:]):
        step["alias"] = (step.get("alias") or "").strip() \
            or joins.default_alias(source)
    return base_id, steps, sources

@app.post("/api/datasets/join")
def join_datasets(req: JoinRequest):
    base_id, steps, sources = _join_pipeline(req)
    try:
        ref = _join_ref(base_id, steps)
        if ref and req.allow_loaded:
            ref["allow_loaded"] = True
        out = joins.run(base_id, steps, allow_loaded=req.allow_loaded)
        label = " + ".join(sources)
        result = datasets.open_dataset(out["df"], label,
                                       capped=out["stats"]["truncated"],
                                       live_source=out.get("live_source"),
                                       disk_source=out.get("disk_source"))
        datasets.get(result["dataset_id"])["source_ref"] = ref
        result["source_ref"] = ref
    except disk_data.OperationTooLarge as e:
        raise HTTPException(413, str(e))
    except disk_data.SourceSizeUnknown as e:
        raise HTTPException(422, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except joins.JoinTimeout as e:
        raise HTTPException(504, str(e))
    except Exception as e:
        raise HTTPException(504 if "statement timeout" in str(e) else 502,
                            str(e).split("\n")[0][:300])
    lineage.record(_lineage_engine(), "joined", "dataset", label,
                   payload={"steps": [{k: s[k] for k in
                                       ("how", "conditions", "alias")}
                                      for s in steps],
                            "rows": result["rows"],
                            "engine": out["stats"]["engine"],
                            "truncated": out["stats"]["truncated"]},
                   parents=[("dataset", s) for s in sources])
    return {**result, "join": out["stats"]}


class DataJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str
    kind: Literal["open", "join"]
    status: Literal["queued", "running", "cancelling", "cancelled", "complete", "failed", "interrupted"]
    result: dict | None = None
    error: str | dict | list | None = None
    status_code: int | None = None


def _submit_data_job(kind, req, request, response):
    owner = agent_sessions.owner(request, response)
    work = lambda: open_dataset(req) if kind == "open" else join_datasets(req)
    try:
        return data_jobs.manager().submit(kind, owner, work,
            lambda result: datasets.close_dataset(result["dataset_id"]))
    except data_jobs.Busy as exc:
        raise HTTPException(429, str(exc)) from exc


@app.post("/api/data-jobs/open", status_code=202, response_model=DataJobResponse, response_model_exclude_none=True)
def start_open_job(req: OpenRequest, request: Request, response: Response):
    return _submit_data_job("open", req, request, response)


@app.post("/api/data-jobs/join", status_code=202, response_model=DataJobResponse, response_model_exclude_none=True)
def start_join_job(req: JoinRequest, request: Request, response: Response):
    return _submit_data_job("join", req, request, response)


@app.get("/api/data-jobs/{job_id}", response_model=DataJobResponse, response_model_exclude_none=True)
def get_data_job(job_id: str, request: Request, response: Response):
    job = data_jobs.manager().get(job_id, agent_sessions.owner(request, response))
    if job is None:
        raise HTTPException(404, "Data job not found")
    return job


@app.post("/api/data-jobs/{job_id}/cancel", response_model=DataJobResponse, response_model_exclude_none=True)
def cancel_data_job(job_id: str, request: Request, response: Response):
    job = data_jobs.manager().cancel(job_id, agent_sessions.owner(request, response))
    if job is None:
        raise HTTPException(404, "Data job not found")
    return job


@app.post("/api/datasets/join/preview")
def preview_join(req: JoinRequest):
    base_id, steps, _ = _join_pipeline(req)
    try:
        return joins.preview(base_id, steps, allow_loaded=req.allow_loaded)
    except disk_data.OperationTooLarge as e:
        raise HTTPException(413, str(e))
    except disk_data.SourceSizeUnknown as e:
        raise HTTPException(422, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except joins.JoinTimeout as e:
        raise HTTPException(504, str(e))
    except joins.JoinEngineError as e:
        raise HTTPException(502, str(e))


@app.post("/api/datasets/join/validate")
def validate_join(req: JoinRequest):

    base_id, steps, _ = _join_pipeline(req)
    return joins.validate(base_id, steps)

@app.post("/api/joins/recommend")
def recommend_join(req: join_discovery.RecommendRequest):
    try:
        result = join_discovery.recommend(req)
        if not result.candidates:
            result.warnings.append("No compatible join-key candidate was found.")
        return result.model_dump(mode="json")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        original = getattr(e, "orig", None) or e
        if getattr(original, "sqlstate", None) == "57014":
            raise HTTPException(504, "Join discovery timed out.")
        raise HTTPException(502, str(e).split("\n")[0][:300])

@app.get("/api/datasets/join/suggest")
def suggest_join_keys(left_id: str, right_id: str):
    try:
        return joins.suggest(left_id, right_id)
    except datasets.DatasetNotFound:
        raise HTTPException(404, "A dataset expired or is unknown — reload it.")

@app.post("/api/datasets/{dataset_id}/compare")
def compare_cohorts(dataset_id: str, req: CompareRequest):
    try:
        result = compare.compare(
            dataset_id,
            [f.model_dump() for f in req.filters_a],
            [f.model_dump() for f in req.filters_b],
            b_is_rest=req.b_is_rest)
    except datasets.DatasetNotFound:
        raise HTTPException(404, "Dataset expired or unknown — reload it.")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, str(e).split("\n")[0][:300])
    lineage.record(_lineage_engine(), "compared", "dataset",
                   datasets.get(dataset_id)["source"],
                   payload={"a_n": result["a_n"], "b_n": result["b_n"],
                            "b_is_rest": req.b_is_rest})
    return result

@app.post("/api/datasets/{dataset_id}/derive")
def derive_column(dataset_id: str, req: DeriveRequest):
    try:
        result = derive.derive(dataset_id, req.model_dump())
    except datasets.DatasetNotFound:
        raise HTTPException(404, "Dataset expired or unknown — reload it.")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, str(e).split("\n")[0][:300])
    lineage.record(_lineage_engine(), "derived_column", "dataset",
                   datasets.get(dataset_id)["source"],
                   payload={"op": req.op, "name": result["name"]})
    return result

@app.post("/api/datasets/{dataset_id}/summary")
def summarize_dataset(dataset_id: str, req: group_summary.SummaryRequest):
    try:
        return group_summary.summarize(dataset_id, req)
    except execution.Busy as e:
        raise HTTPException(429, str(e), headers={"Retry-After": "1"})
    except datasets.DatasetNotFound:
        raise HTTPException(404, "Dataset expired or unknown — reload it.")
    except disk_data.OperationTooLarge as e:
        raise HTTPException(413, str(e))
    except disk_data.SourceSizeUnknown as e:
        raise HTTPException(422, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(504 if "statement timeout" in str(e) else 502,
                            str(e).split("\n")[0][:300])


@app.post("/api/datasets/{dataset_id}/query")
def query_dataset(dataset_id: str, req: QueryRequest):
    try:
        result = datasets.query(
            dataset_id,
            [f.model_dump() for f in req.filters],
            [c.model_dump() for c in req.charts],
            page=req.page, page_size=req.page_size, entity_column=req.entity_column,
            refresh=req.refresh)
        if req.refresh and datasets.get(dataset_id).get("live_source"):
            result["columns"] = column_settings.profiles(datasets.get(dataset_id))
        return result
    except execution.Busy as e:
        raise HTTPException(429, str(e), headers={"Retry-After": "1"})
    except datasets.DatasetNotFound:
        raise HTTPException(404, "Dataset expired or unknown — reload it.")

    except disk_data.OperationTooLarge as e:
        raise HTTPException(413, str(e))
    except disk_data.SourceSizeUnknown as e:
        raise HTTPException(422, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(504 if "statement timeout" in str(e) else 502,
                            str(e).split("\n")[0][:300])


def _require_loaded(dataset_id, operation):
    try:
        ds = datasets.get(dataset_id)
    except datasets.DatasetNotFound:
        raise HTTPException(404, "Dataset expired or unknown — reload it.")
    if ds.get("live_source"):
        raise HTTPException(400, f"{operation} is not available for database-scoped datasets.")

def _export_frame(ds, filters=None):
    try:
        if ds.get("disk_source"):
            return disk_data.export_frame(ds["disk_source"], filters or [],
                                          queries.ROW_CAP)
        if ds.get("live_source"):
            return live_query.fetch_frame(ds["live_source"], filters, max_rows=queries.ROW_CAP)
        return datasets.apply_filters(ds["df"], filters or [])
    except disk_data.OperationTooLarge as e:
        raise HTTPException(413, str(e))
    except disk_data.SourceSizeUnknown as e:
        raise HTTPException(422, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(504 if "statement timeout" in str(e) else 502,
                            str(e).split("\n")[0][:300])


class StartExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filters: list[Filter] = Field(default_factory=list, max_length=200)

@app.post("/api/datasets/{dataset_id}/exports", status_code=202)
def start_export(dataset_id: str, req: StartExportRequest):
    try:
        ds = datasets.get(dataset_id)
        if not ds.get("live_source"):
            raise HTTPException(400, "Background export requires a full Aurora source.")
        return export_jobs.start(ds["live_source"], [f.model_dump() for f in req.filters])
    except datasets.DatasetNotFound:
        raise HTTPException(404, "Dataset expired or unknown — reload it.")
    except export_jobs.ExportBusy as e:
        raise HTTPException(429, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))

@app.get("/api/exports/{job_id}")
def export_status(job_id: str):
    try:
        return export_jobs.status(job_id)
    except KeyError:
        raise HTTPException(404, "Export expired or unknown.")

@app.delete("/api/exports/{job_id}")
def cancel_export(job_id: str):
    try:
        return export_jobs.cancel(job_id)
    except KeyError:
        raise HTTPException(404, "Export expired or unknown.")

@app.get("/api/exports/{job_id}/download")
def download_export(job_id: str):
    try:
        path = export_jobs.download(job_id)
    except KeyError:
        raise HTTPException(404, "Export expired or unknown.")
    except ValueError as e:
        raise HTTPException(409, str(e))
    return FileResponse(path, media_type="text/tab-separated-values", filename="cohort.tsv")

@app.post("/api/datasets/{dataset_id}/export")
def export_dataset(dataset_id: str, req: QueryRequest):
    try:
        ds = datasets.get(dataset_id)
    except datasets.DatasetNotFound:
        raise HTTPException(404, "Dataset expired or unknown — reload it.")
    if ds.get("disk_source"):
        try:
            path = disk_data.export_tsv(ds["disk_source"],
                [f.model_dump() for f in req.filters], queries.ROW_CAP)
        except disk_data.OperationTooLarge as e:
            raise HTTPException(413, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))
        lineage.record(_lineage_engine(), "export", "export", ds["source"],
                       payload={"row_limit": queries.ROW_CAP})
        return FileResponse(path, media_type="text/tab-separated-values",
                            filename="cohort.tsv",
                            background=BackgroundTask(disk_data.remove_file, path))
    df = _export_frame(ds, [f.model_dump() for f in req.filters])
    lineage.record(_lineage_engine(), "export", "export", ds["source"],
                   payload={"rows": len(df)})
    return Response(df.to_csv(sep="\t", index=False),
                    media_type="text/tab-separated-values",
                    headers={"Content-Disposition":
                             "attachment; filename=cohort.tsv"})


@app.delete("/api/datasets/{dataset_id}")
def delete_dataset(dataset_id: str):
    datasets.close_dataset(dataset_id)
    return {"ok": True}

class MCPConnection(config.MCPConnectionSettings):
    pass

class ConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    provider: config.StoredProvider | None = None
    model: str | None = Field(default=None, max_length=256)
    api_key: str | None = Field(default=None, max_length=8192)
    jev_api_key: str | None = Field(default=None, max_length=8192)
    jev_model: str | None = Field(default=None, max_length=256)
    ncbi_api_key: str | None = Field(default=None, max_length=128,
                                     pattern=r"^[A-Za-z0-9_-]*$")
    mcp_connections: list[MCPConnection] | None = Field(default=None, max_length=128)
    chart_palette: str | None = None

class AskRequest(BaseModel):
    question: str
    filters: list[Filter] = Field(default_factory=list)

class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=24000)

class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    session_id: str | None = Field(default=None, pattern=r"^[0-9a-fA-F-]{36}$")
    message: str = Field(min_length=1, max_length=8000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=30)
    filters: list[Filter] = Field(default_factory=list)
    charts: list[ChartSpec] = Field(default_factory=list)

class MaterializeRequest(BaseModel):
    resource_id: str
    table: str

class Cohort(BaseModel):
    name: str
    filters: list[Filter] = Field(default_factory=list)

class FilterAskEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    question: str = Field(min_length=1, max_length=2000)
    answer: str | None = Field(default=None, max_length=4000)
    error: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def has_result(self):
        if bool(self.answer) == bool(self.error):
            raise ValueError("A filter question needs exactly one answer or error.")
        return self

class SavedGroupSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    group_by: list[str] = Field(min_length=1, max_length=5)
    measure: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def distinct_groups(self):
        if any(not name or len(name) > 512 for name in self.group_by) or len(set(self.group_by)) != len(self.group_by):
            raise ValueError("Choose distinct grouping columns.")
        return self


class ViewDataset(BaseModel):
    source: SourceRef
    entity_column: str | None = None

    @field_validator("source")
    @classmethod
    def validate_source(cls, value):
        source_dict(value)
        return value

    group_summary: SavedGroupSummary | None = None
    title: str = ""
    filters: list[Filter] = Field(default_factory=list)
    charts: list[ChartSpec] = Field(default_factory=list)
    cohorts: list[Cohort] = Field(default_factory=list)
    filter_ask_history: list[FilterAskEntry] = Field(default_factory=list, max_length=25)

class SaveViewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["aurora", "s3"]
    resource_id: str = Field(min_length=1, max_length=256)
    name: str = Field(pattern=r"^[A-Za-z0-9 ._-]{1,80}$")
    datasets: list[ViewDataset] = Field(default_factory=list, max_length=16)
    active: int = Field(default=0, ge=0)


@app.get("/api/config")
def get_config():
    cfg = config.public_config()
    cfg["mcp"] = {"available": mcp_server.AVAILABLE, "path": "/mcp"}
    return cfg

@app.put("/api/config")
def put_config(req: ConfigUpdate):
    if (req.model is not None or req.api_key is not None
            or req.provider is not None):
        config.update_llm_config(model=req.model, api_key=req.api_key,
                                 provider=req.provider)
    if req.jev_model is not None or req.jev_api_key is not None:
        config.update_jev_config(model=req.jev_model, api_key=req.jev_api_key)
    if req.ncbi_api_key is not None:
        config.update_literature_config(ncbi_api_key=req.ncbi_api_key)
    if req.mcp_connections is not None:
        config.update_mcp_connections(
            [c.model_dump() for c in req.mcp_connections])
    if req.chart_palette is not None:
        config.update_chart_palette(req.chart_palette)
    cfg = config.public_config()
    cfg["mcp"] = {"available": mcp_server.AVAILABLE, "path": "/mcp"}
    return cfg

@app.post("/api/config/keys/migrate")
def migrate_model_keys():
    return config.migrate_legacy_keys()

@app.post("/api/config/llm/test")
def test_llm():
    try:
        return llm.test_connection()
    except llm.LLMNotConfigured as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, str(e).split("\n")[0][:300])

@app.post("/api/datasets/{dataset_id}/ask")
def ask_dataset(dataset_id: str, req: AskRequest):
    try:
        ds = datasets.get(dataset_id)
    except datasets.DatasetNotFound:
        raise HTTPException(404, "Dataset expired or unknown — reload it.")
    try:
        result = llm.suggest_filters(
            req.question,
            column_settings.profiles(ds),
            [f.model_dump() for f in req.filters])
    except llm.LLMNotConfigured as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, str(e).split("\n")[0][:300])
    lineage.record(_lineage_engine(), "ask_ai", "dataset", ds["source"],
                   payload={"question": req.question,
                            "filters": result["filters"]})
    return result


@app.post("/api/datasets/{dataset_id}/materialize")
def materialize_dataset(dataset_id: str, req: MaterializeRequest):

    try:
        ds = datasets.get(dataset_id)
    except datasets.DatasetNotFound:
        raise HTTPException(404, "Dataset expired or unknown — reload it.")
    frame = _export_frame(ds)
    engine = db.get_engine_for_resource(req.resource_id)
    try:
        rows = queries.ingest_dataframe(engine, frame, req.table)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, str(e).split("\n")[0][:300])
    db.list_aurora_tables.invalidate()
    db.fetch_aurora_table.invalidate()
    query_cache.invalidate_resource(req.resource_id)
    views.invalidate_listing("aurora", req.resource_id)
    join_discovery.invalidate_resource(req.resource_id)
    lineage.record(engine, "materialized", "table", req.table,
                   payload={"resource_id": req.resource_id, "rows": rows,
                            "from": ds["source"]})
    return {"table": req.table, "resource_id": req.resource_id, "rows": rows}

@app.post("/api/datasets/{dataset_id}/chat")
def chat_dataset(dataset_id: str, req: ChatRequest, request: Request, response: Response):
    trace_id = uuid.uuid4().hex
    started = time.monotonic()
    try:
        dataset = datasets.get(dataset_id)
        source = dataset["source"]
    except datasets.DatasetNotFound:
        raise HTTPException(404, "Dataset expired or unknown — reload it.")
    if dataset.get("live_source"):
        raise HTTPException(400,
            "Chat is not available for database-scoped datasets. "
            "Use the full-source filters and charts to explore this result.")
    try:
        llm.validate_config(config.get_llm_config())
        with agent_sessions.bind(agent_sessions.owner(request, response),
                                 agent_sessions.dataset_scope(dataset_id), req.session_id):
            result = agent.chat(
                dataset_id, req.message,
                [m.model_dump() for m in req.history],
                [f.model_dump() for f in req.filters],
                [{k: v for k, v in c.model_dump().items() if v is not None}
                 for c in req.charts])
            agent_sessions.finish(result)
    except datasets.DatasetNotFound:
        raise HTTPException(404, "Dataset expired or unknown — reload it.")
    except llm.LLMNotConfigured as e:
        _record_turn(trace_id, source, req.message, started,
                     status="unconfigured", error=str(e))
        raise HTTPException(400, str(e))
    except agent_store.AgentStoreError:
        raise
    except Exception as e:
        _record_turn(trace_id, source, req.message, started,
                     status="error", error=str(e).split("\n")[0][:300])
        raise HTTPException(502, str(e).split("\n")[0][:300])
    _record_turn(trace_id, source, req.message, started, result=result)
    result.setdefault("trace_id", trace_id)
    return result


@app.get("/api/datasets/{dataset_id}/chat/history")
def dataset_chat_history(dataset_id: str, request: Request, response: Response,
                         session_id: uuid.UUID | None = None, before: int | None = None):
    return agent_sessions.history(agent_sessions.owner(request, response),
                                  agent_sessions.dataset_scope(dataset_id), session_id, before)

@app.get("/api/omop/{resource_id}/cohort/agent/history")
def cohort_chat_history(resource_id: str, request: Request, response: Response,
                        session_id: uuid.UUID | None = None, before: int | None = None):
    return agent_sessions.history(agent_sessions.owner(request, response),
                                  "omop:" + resource_id, session_id, before)

def _record_turn(trace_id: str, source: str, message: str, started: float,
                 result: dict | None = None, status: str = "ok",
                 error: str | None = None):
    return None

@app.get("/api/agent/turns")
def agent_turns():
    return {"turns": []}

@app.get("/api/views/all")
def list_all_saved_views():
    stores = []
    discovery_errors = []
    try:
        for resource in db.list_aurora_resources():
            if resource.get("kind") == "postgres" or not resource.get("id"):
                continue
            resource_id = resource["id"]
            stores.append({"kind": "aurora", "resource_id": resource_id,
                           "label": f"{resource_id} · Aurora"})
    except Exception as exc:
        discovery_errors.append({
            "kind": "aurora", "resource_id": "", "label": "Aurora",
            "error": str(exc).split("\n")[0][:300]
                    or "Aurora resources could not be listed.",
        })
    try:
        for resource in db.list_s3_folders():
            if not resource.get("id"):
                continue
            resource_id = resource["id"]
            stores.append({"kind": "s3", "resource_id": resource_id,
                           "label": f"{resource_id} · S3"})
    except Exception as exc:
        discovery_errors.append({
            "kind": "s3", "resource_id": "", "label": "S3 resources",
            "error": str(exc).split("\n")[0][:300]
                    or "S3 resources could not be listed.",
        })
    unique = {}
    for store in stores:
        unique[(store["kind"], store["resource_id"])] = store
    result = views.list_all_views(list(unique.values()))
    result["unavailable"] = discovery_errors + result["unavailable"]
    return result


@app.get("/api/views")
def list_views(kind: str, resource_id: str):
    try:
        return views.list_views(kind, resource_id)
    except Exception as e:
        raise HTTPException(502, str(e).split("\n")[0][:300])

@app.get("/api/views/one")
def get_view(kind: str, resource_id: str, name: str):
    try:
        state = views.get_view(kind, resource_id, name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, str(e).split("\n")[0][:300])
    if state is None:
        raise HTTPException(404, f"View {name!r} not found.")
    return state

class RefreshViewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["aurora"]
    resource_id: str = Field(min_length=1, max_length=256)
    name: str = Field(pattern=r"^[A-Za-z0-9 ._-]{1,80}$")


def _managed_snapshot_store(resource_id: str):
    if resource_id.startswith(("postgres:", "s3:", "athena:")):
        raise HTTPException(400, "Saved snapshots require a managed Aurora store.")


def _compile_snapshot(resource_id, source):
    import copy
    normalized = source_dict(source)
    for ds in list(datasets._store.values()):
        live = ds.get("live_source")
        if ds.get("source_ref") == normalized and live and live["resource_id"] == resource_id:
            return copy.deepcopy(live)
    opened = _open_source(source, temporary=True)
    try:
        live = datasets.get(opened["dataset_id"]).get("live_source")
        if live and live["resource_id"] == resource_id:
            return copy.deepcopy(live)
        return None
    finally:
        datasets.close_dataset(opened["dataset_id"])


@app.get("/api/views/jobs/{job_id}")
def saved_view_job(job_id: str, request: Request, response: Response):
    job = view_jobs.get(job_id, owner=agent_sessions.owner(request, response))
    if job is None:
        raise HTTPException(404, "Saved-view job expired or unknown.")
    return job


@app.post("/api/views/refresh")
def refresh_saved_view(req: RefreshViewRequest, request: Request, response: Response):
    owner = agent_sessions.owner(request, response)
    _managed_snapshot_store(req.resource_id)
    try:
        total = saved_snapshots.materialized_count(req.resource_id, req.name)
        if not total:
            raise ValueError("This view has no snapshots to refresh.")
        def work(progress):
            result = saved_snapshots.refresh(req.resource_id, req.name, progress)
            query_cache.invalidate_resource(req.resource_id)
            views.invalidate_listing("aurora", req.resource_id)
            return result
        return view_jobs.submit(req.name, total, work, key=f"{req.resource_id}:{req.name}", owner=owner)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, str(exc).split("\n")[0][:300])


@app.post("/api/views")
def save_view(req: SaveViewRequest, request: Request, response: Response):
    owner = agent_sessions.owner(request, response)
    if not req.datasets:
        raise HTTPException(400, "Nothing to save — open a datasource-backed "
                            "table first.")
    state = {
        "version": 2,
        "active": req.active,
        "datasets": [{
            "source": source_dict(d.source),
            "entity_column": d.entity_column,
            "group_summary": d.group_summary.model_dump() if d.group_summary else None,
            "title": d.title,
            "filters": [{k: v for k, v in f.model_dump().items()
                         if v is not None} for f in d.filters],
            "charts": [{k: v for k, v in c.model_dump().items()
                        if v is not None} for c in d.charts],
            "cohorts": [{
                "name": ch.name,
                "filters": [{k: v for k, v in f.model_dump().items()
                             if v is not None} for f in ch.filters],
            } for ch in d.cohorts],
            "filter_ask_history": [entry.model_dump()
                                   for entry in d.filter_ask_history],
        } for d in req.datasets],
    }
    try:
        if req.kind == "aurora" and (saved_snapshots.has_join_source(state, req.resource_id)
                                     or saved_snapshots.has_materialized_source(state, req.resource_id)):
            _managed_snapshot_store(req.resource_id)
            def work(progress):
                result = saved_snapshots.save(req.resource_id, req.name, state,
                                              _compile_snapshot, progress)
                query_cache.invalidate_resource(req.resource_id)
                views.invalidate_listing("aurora", req.resource_id)
                lineage.record(_lineage_engine(), "view_saved", "view", req.name,
                               payload={"store": f"{req.kind}:{req.resource_id}",
                                        "datasets": len(req.datasets), **result})
                return result
            return view_jobs.submit(req.name, len(state["datasets"]), work,
                                    key=f"{req.resource_id}:{req.name}", owner=owner)
        result = views.save_view(req.kind, req.resource_id, req.name, state)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, str(e).split("\n")[0][:300])
    lineage.record(_lineage_engine(), "view_saved", "view", req.name,
                   payload={"store": f"{req.kind}:{req.resource_id}",
                            "datasets": len(req.datasets)})
    return result

@app.delete("/api/views")
def delete_view(kind: str, resource_id: str, name: str):
    try:
        views.delete_view(kind, resource_id, name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}

@app.get("/api/lineage")
def lineage_events():
    df = lineage.recent_events(_lineage_engine())
    return {"columns": list(df.columns),
            "data": df.astype(object).where(df.notna(), None).values.tolist()}

@app.post("/api/seed/gtex")
def seed_gtex(resource_id: str):
    engine = db.get_engine_for_resource(resource_id)
    try:
        rows = queries.load_gtex_samples(engine)
    except Exception as e:
        raise HTTPException(502, str(e).split("\n")[0][:300])
    db.list_aurora_tables.invalidate()
    db.fetch_aurora_table.invalidate()
    lineage.record(engine, "gtex_loaded", "table", "gtex_samples",
                   payload={"rows": rows})
    return {"rows": rows}

def _omop_error(e: Exception) -> HTTPException:
    if isinstance(e, ValueError):
        return HTTPException(400, str(e))
    if isinstance(e, omop.OmopTimeout):
        return HTTPException(504, str(e))
    return HTTPException(502, str(e).split("\n")[0][:300])

def _omop_info(resource_id: str, refresh: bool = False) -> dict | None:
    known = {r["id"] for r in db.list_aurora_resources()}
    if resource_id not in known:
        if not known and not db.resources_ready():
            raise HTTPException(503, "Workspace resources are not ready; retry shortly.")
        raise HTTPException(404, f"Unknown Aurora resource: {resource_id}")
    if refresh:
        omop.invalidate(resource_id)
    try:
        return omop.detect_resource(resource_id)
    except Exception as e:
        raise _omop_error(e)

def _omop_cdm(resource_id: str):
    info = _omop_info(resource_id)
    if info is None:
        raise HTTPException(404, f"No OMOP CDM found in {resource_id}.")
    return db.get_engine_for_resource(resource_id), info

@app.get("/api/omop/{resource_id}")
def omop_detect(resource_id: str, refresh: bool = False):
    return omop.public(_omop_info(resource_id, refresh))

@app.get("/api/omop/{resource_id}/concepts")
def omop_concepts(resource_id: str, q: str = "", domain: str = "",
                  vocabulary: str = "", standard_only: bool = True,
                  limit: int = 50):
    engine, info = _omop_cdm(resource_id)
    try:
        return {"concepts": omop.search_concepts(
            engine, info, q, domain or None, vocabulary or None,
            standard_only=standard_only, limit=limit)}
    except Exception as e:
        raise _omop_error(e)

class CohortAgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    session_id: str | None = Field(default=None, pattern=r"^[0-9a-fA-F-]{36}$")
    message: str = Field(min_length=1, max_length=8000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=30)
    spec: dict = Field(default_factory=dict)

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must contain non-whitespace text.")
        return value

    @model_validator(mode="after")
    def validate_spec(self):
        omop.parse_spec(self.spec)
        return self

class OmopSpecRequest(RootModel[dict]):

    model_config = ConfigDict(strict=True)

    @model_validator(mode="after")
    def validate_spec(self):
        omop.parse_spec(self.root)
        return self

class OmopSummaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    spec: dict

    @model_validator(mode="after")
    def validate_spec(self):
        omop.parse_spec(self.spec)
        return self

@app.post("/api/omop/{resource_id}/cohort/agent")
def omop_agent(resource_id: str, req: CohortAgentRequest, request: Request, response: Response):
    _, info = _omop_cdm(resource_id)
    trace_id = uuid.uuid4().hex
    started = time.monotonic()
    source = f"{resource_id} / OMOP cohort assistant"
    try:
        llm.validate_config(config.get_llm_config())
        with agent_sessions.bind(agent_sessions.owner(request, response),
                                 "omop:" + resource_id, req.session_id):
            result = cohort_agent.chat(resource_id, info, req.message,
                                       [m.model_dump() for m in req.history], req.spec)
            agent_sessions.finish(result)
    except llm.LLMNotConfigured as e:
        _record_turn(trace_id, source, req.message, started,
                     status="unconfigured", error=str(e))
        raise HTTPException(400, str(e))
    except agent_store.AgentStoreError:
        raise
    except Exception as e:
        _record_turn(trace_id, source, req.message, started,
                     status="error", error=str(e).split("\n")[0][:300])
        raise _omop_error(e)
    _record_turn(trace_id, source, req.message, started, result=result)
    result.setdefault("trace_id", trace_id)
    return result

@app.post("/api/omop/{resource_id}/cohort/count")
def omop_count(resource_id: str,
               req: OmopSpecRequest = Body(default_factory=lambda: OmopSpecRequest({}))):
    engine, info = _omop_cdm(resource_id)
    try:
        return omop.count(engine, info, req.root)
    except Exception as e:
        raise _omop_error(e)

@app.post("/api/omop/{resource_id}/cohort/summary")
def omop_cohort_summary(resource_id: str, req: OmopSummaryRequest):
    engine, info = _omop_cdm(resource_id)
    try:
        return omop.cohort_summary(engine, info, req.spec)
    except Exception as e:
        raise _omop_error(e)

@app.post("/api/omop/{resource_id}/cohort/open")
def omop_open_cohort(resource_id: str, req: OmopCohortOpenRequest):
    try:
        _, info = _omop_cdm(resource_id)
        parents = omop.tables_used(info, req.spec)
        name = req.name.strip() or "OMOP cohort"
        ref = source_dict({"kind": "omop_cohort", "resource_id": resource_id,
                           "spec": req.spec, "membership_mode": "live",
                           "name": name})
        result = _open_source(ref)
    except HTTPException:
        raise
    except disk_data.OperationTooLarge as e:
        raise HTTPException(413, str(e))
    except disk_data.SourceSizeUnknown as e:
        raise HTTPException(422, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except omop.OmopTimeout as e:
        raise HTTPException(504, str(e))
    except Exception as e:
        raise _omop_error(e)
    source = result["source"]
    lineage.record(_lineage_engine(), "omop_cohort_opened", "cohort", source,
                   payload={"resource_id": resource_id,
                            "spec": result["source_ref"]["spec"],
                            "membership_mode": "live",
                            "rows": result["rows"],
                            "dataset_id": result["dataset_id"],
                            "source_ref": result["source_ref"]},
                   parents=[("dataset", result["dataset_id"]),
                            *(("table", t) for t in parents)])
    return result

@app.post("/api/omop/{resource_id}/domain/open")
def omop_open_domain(resource_id: str, req: OmopDomainOpenRequest):
    engine, info = _omop_cdm(resource_id)
    try:
        df, origin = omop.open_domain(engine, info, req.table, req.spec,
                                      concept_names=req.concept_names,
                                      resource_id=resource_id)
    except Exception as e:
        raise _omop_error(e)
    table = f"{info['cdm_schema']}.{req.table}"
    source = f"{resource_id} / {table}" + (" (cohort)" if req.spec is not None else "")
    result = datasets.open_dataset(df, source, origin=origin)
    lineage.record(_lineage_engine(), "table_loaded", "table", table,
                   payload={"resource_id": resource_id, "source_kind": "omop",
                            "rows": len(df), "cohort": req.spec,
                            "concept_names": req.concept_names})
    return result

from agent_mode_api import router as agent_mode_router
app.include_router(agent_mode_router)


@app.get("/api/performance")
def performance(request: Request, response: Response):
    return operational_store.store().summary(agent_sessions.owner(request, response))


@app.get("/api/datasets/{dataset_id}/grain")
def get_grain(dataset_id: str):
    try:
        return grain.get(dataset_id)
    except datasets.DatasetNotFound:
        raise HTTPException(404, "Dataset expired or unknown — reload it.")


@app.put("/api/datasets/{dataset_id}/grain")
def save_grain(dataset_id: str, req: grain.Definition):
    try:
        return grain.save(dataset_id, req.model_dump())
    except datasets.DatasetNotFound:
        raise HTTPException(404, "Dataset expired or unknown — reload it.")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/datasets/{dataset_id}/grain/check")
def check_grain(dataset_id: str):
    try:
        return grain.check(dataset_id)
    except datasets.DatasetNotFound:
        raise HTTPException(404, "Dataset expired or unknown — reload it.")
    except execution.Busy as exc:
        raise HTTPException(429, str(exc), headers={"Retry-After": "1"})
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception:
        raise HTTPException(502, "Could not check the key. Retry or narrow the source.")


STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"),
              name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        target = STATIC_DIR / path
        if path and target.is_file():
            return FileResponse(target)
        return FileResponse(STATIC_DIR / "index.html")
