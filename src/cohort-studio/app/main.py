import io
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pandas as pd
from fastapi import Body, FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.exception_handlers import (
    request_validation_exception_handler as default_request_validation_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import (BaseModel, ConfigDict, Field, RootModel,
                      field_validator, model_validator)

import agent
import cohort_agent
import bq
import catalog
import config
import datasets
import db
import duck
import joins
import lineage
import llm
import compare
import derive
import mcp_server
import omop
import queries
import views
import workflows
import column_settings
import live_query
import query_cache
import export_jobs
import join_discovery
from source_models import ColumnSetting, DerivedSpec, SourceRef, source_dict

logging.basicConfig(level=logging.INFO, force=True)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.warm_resource_cache()
    try:
        if mcp_server.AVAILABLE:
            async with mcp_server.mcp.session_manager.run():
                yield
        else:
            yield
    finally:
        export_jobs.shutdown()

app = FastAPI(title="Cohort Studio", lifespan=lifespan)

@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request,
                                     exc: RequestValidationError):
    if request.url.path.startswith("/api/omop/"):

        details = [{"loc": error["loc"], "msg": error["msg"],
                    "type": error["type"]} for error in exc.errors()]
        return JSONResponse(status_code=400, content={"detail": details})
    return await default_request_validation_handler(request, exc)

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

class Filter(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    column: str
    kind: str
    values: list[str] | None = None
    min: float | None = None
    max: float | None = None

class ChartSpec(BaseModel):
    kind: str
    x: str
    y: str | None = None

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
    resource_id: str
    path: str
    filters: list[Filter] = Field(default_factory=list)

class SubmitJobRequest(BaseModel):
    workflow: str
    output_bucket_id: str
    job_id: str = ""
    batch_input_bucket_id: str = ""
    batch_input_csv_path: str = ""
    column_mapping: str = ""
    row_selection: str = ""
    profile: str = ""

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
    sources = []
    folders = []
    if ready:
        db.retry_if_empty()
        for r in db.list_aurora_resources():
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
    return {"ready": ready, "sources": sources, "catalogs_pending": pending}

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
    filt = _export_frame(ds, [f.model_dump() for f in req.filters])
    try:
        out = workflows.export_cohort_csv(filt, req.resource_id, req.path)
    except Exception as e:
        raise HTTPException(502, str(e).split("\n")[0][:300])
    lineage.record(_lineage_engine(), "cohort_exported", "dataset",
                   ds["source"], payload={"to": out["s3_uri"],
                                          "rows": out["rows"]})
    return out

@app.post("/api/workflows/submit")
def submit_workflow(req: SubmitJobRequest):
    try:
        job = workflows.submit_job(**req.model_dump())
    except Exception as e:
        raise HTTPException(502, str(e).split("\n")[0][:300])
    lineage.record(_lineage_engine(), "workflow_submitted", "workflow",
                   job.get("name") or req.workflow,
                   payload={"run_id": job.get("run_id"),
                            "workflow": req.workflow})
    return job

@app.get("/api/tables")
def tables(kind: str, resource_id: str):
    try:
        if kind == "aurora":
            return [{"name": t["name"], "table": t["table"],
                     "schema": t["schema"], "detail": t["kind"]}
                    for t in db.list_aurora_tables(resource_id)]
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
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(504 if isinstance(e, joins.JoinTimeout) or "statement timeout" in str(e) else 502,
                            str(e).split("\n")[0][:300])
    lineage.record(_lineage_engine(), "table_loaded", "table", ref.get("table", result["source"]),
                   payload={"source_kind": ref["kind"], "resource_id": ref.get("resource_id"),
                            "rows": result["rows"]})
    return result

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
    children = []
    out = None
    origin = None
    live = None
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
            out = joins.run(base["dataset_id"], steps)
            df, label = out["df"], " + ".join(labels)
            live, capped = out.get("live_source"), out["stats"]["truncated"]
        else:
            kind, rid, table = ref["kind"], ref["resource_id"], ref["table"]
            schema = ref.get("schema", "public")
            if kind == "aurora" and schema != "public":
                sql = f"SELECT * FROM {column_settings._q(schema)}.{column_settings._q(table)} LIMIT {queries.ROW_CAP}"
                from sql_utils import statement as text
                with db.get_engine_for_resource(rid).begin() as conn:
                    if conn.dialect.name == "postgresql":
                        conn.execute(text("SET LOCAL statement_timeout = 15000"))
                    df = pd.read_sql_query(text(sql), conn)
            else:
                df = _load_frame(kind, rid, table)
            label_table = (table if kind != "aurora" or schema == "public"
                           else f"{schema}.{table}")
            label = f"{rid} / {label_table}"
            if kind == "aurora":
                origin = {"kind": "aurora", "resource_id": rid, "table": table, "schema": schema}
    finally:
        for child in children:
            datasets.close_dataset(child)
    result = datasets.open_dataset(
        df, label, origin=origin, temporary=temporary,
        capped=capped, live_source=live)
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
async def upload_dataset(file: UploadFile):
    name = file.filename or "upload.csv"
    if not name.lower().endswith(UPLOAD_SUFFIXES):
        raise HTTPException(
            400, f"Unsupported file type: {name}. Cohort Studio reads "
            "tabular data — upload CSV, TSV, or TXT. Formats like BAM, "
            "VCF, FASTQ, or BED are not row/column tables and can't be "
            "loaded here.")
    sep = "\t" if name.lower().endswith((".tsv", ".txt")) else ","
    try:
        df = pd.read_csv(io.BytesIO(await file.read()), sep=sep)
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
        out = joins.run(base_id, steps)
        label = " + ".join(sources)
        result = datasets.open_dataset(out["df"], label,
                                       capped=out["stats"]["truncated"],
                                       live_source=out.get("live_source"))
        datasets.get(result["dataset_id"])["source_ref"] = ref
        result["source_ref"] = ref
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

@app.post("/api/datasets/join/preview")
def preview_join(req: JoinRequest):
    base_id, steps, _ = _join_pipeline(req)
    try:
        return joins.preview(base_id, steps)
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
    except datasets.DatasetNotFound:
        raise HTTPException(404, "Dataset expired or unknown — reload it.")

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
        if ds.get("live_source"):
            return live_query.fetch_frame(ds["live_source"], filters, max_rows=queries.ROW_CAP)
        return datasets.apply_filters(ds["df"], filters or [])
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

class MCPConnection(BaseModel):
    name: str
    label: str = ""
    url: str = ""
    enabled: bool = False
    note: str = ""
    authorization_token: str | None = None

class ConfigUpdate(BaseModel):
    provider: str | None = None
    model: str | None = None
    api_key: str | None = None
    mcp_connections: list[MCPConnection] | None = None
    chart_palette: str | None = None

class AskRequest(BaseModel):
    question: str
    filters: list[Filter] = Field(default_factory=list)

class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = Field(default_factory=list)
    filters: list[Filter] = Field(default_factory=list)
    charts: list[ChartSpec] = Field(default_factory=list)

class MaterializeRequest(BaseModel):
    resource_id: str
    table: str

class Cohort(BaseModel):
    name: str
    filters: list[Filter] = Field(default_factory=list)

class ViewDataset(BaseModel):
    source: SourceRef
    entity_column: str | None = None

    @field_validator("source")
    @classmethod
    def validate_source(cls, value):
        source_dict(value)
        return value

    title: str = ""
    filters: list[Filter] = Field(default_factory=list)
    charts: list[ChartSpec] = Field(default_factory=list)
    cohorts: list[Cohort] = Field(default_factory=list)

class SaveViewRequest(BaseModel):
    kind: str
    resource_id: str
    name: str
    datasets: list[ViewDataset] = Field(default_factory=list)
    active: int = 0

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
    if req.mcp_connections is not None:
        config.update_mcp_connections(
            [c.model_dump() for c in req.mcp_connections])
    if req.chart_palette is not None:
        config.update_chart_palette(req.chart_palette)
    cfg = config.public_config()
    cfg["mcp"] = {"available": mcp_server.AVAILABLE, "path": "/mcp"}
    return cfg

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
            datasets.profile_columns(ds["df"]),
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
    join_discovery.invalidate_resource(req.resource_id)
    lineage.record(engine, "materialized", "table", req.table,
                   payload={"resource_id": req.resource_id, "rows": rows,
                            "from": ds["source"]})
    return {"table": req.table, "resource_id": req.resource_id, "rows": rows}

@app.post("/api/datasets/{dataset_id}/chat")
def chat_dataset(dataset_id: str, req: ChatRequest):
    _require_loaded(dataset_id, "Chat")
    trace_id = uuid.uuid4().hex
    started = time.monotonic()
    try:
        source = datasets.get(dataset_id)["source"]
    except datasets.DatasetNotFound:
        raise HTTPException(404, "Dataset expired or unknown — reload it.")
    try:
        result = agent.chat(
            dataset_id, req.message,
            [m.model_dump() for m in req.history],
            [f.model_dump() for f in req.filters],
            [{k: v for k, v in c.model_dump().items() if v is not None}
             for c in req.charts])
    except datasets.DatasetNotFound:
        raise HTTPException(404, "Dataset expired or unknown — reload it.")
    except llm.LLMNotConfigured as e:
        _record_turn(trace_id, source, req.message, started,
                     status="unconfigured", error=str(e))
        raise HTTPException(400, str(e))
    except Exception as e:
        _record_turn(trace_id, source, req.message, started,
                     status="error", error=str(e).split("\n")[0][:300])
        raise HTTPException(502, str(e).split("\n")[0][:300])
    _record_turn(trace_id, source, req.message, started, result=result)
    lineage.record(_lineage_engine(), "chat", "dataset", source,
                   payload={"message": req.message,
                            "actions": result["actions"]})
    result["trace_id"] = trace_id
    return result

def _record_turn(trace_id: str, source: str, message: str, started: float,
                 result: dict | None = None, status: str = "ok",
                 error: str | None = None):

    latency_ms = (time.monotonic() - started) * 1000
    cfg = config.get_llm_config()
    lineage.record_turn(
        _lineage_engine(), trace_id=trace_id,
        provider=(result or {}).get("provider") or cfg["provider"],
        model=(result or {}).get("model") or cfg["model"],
        dataset=source, prompt=message, latency_ms=latency_ms,
        usage=(result or {}).get("usage"),
        tool_calls=(result or {}).get("tool_calls"),
        status=status, error=error)

@app.get("/api/agent/turns")
def agent_turns():
    df = lineage.recent_turns(_lineage_engine())
    return {"turns": df.to_dict(orient="records")}

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

@app.post("/api/views")
def save_view(req: SaveViewRequest):
    if not req.datasets:
        raise HTTPException(400, "Nothing to save — open a datasource-backed "
                            "table first.")
    state = {
        "version": 2,
        "active": req.active,
        "datasets": [{
            "source": source_dict(d.source),
            "entity_column": d.entity_column,
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
        } for d in req.datasets],
    }
    try:
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

@app.post("/api/omop/{resource_id}/cohort/agent")
def omop_agent(resource_id: str, req: CohortAgentRequest):
    _, info = _omop_cdm(resource_id)
    trace_id = uuid.uuid4().hex
    started = time.monotonic()
    source = f"{resource_id} / OMOP cohort assistant"
    try:
        result = cohort_agent.chat(resource_id, info, req.message,
                                   [m.model_dump() for m in req.history], req.spec)
    except llm.LLMNotConfigured as e:
        _record_turn(trace_id, source, req.message, started,
                     status="unconfigured", error=str(e))
        raise HTTPException(400, str(e))
    except Exception as e:
        _record_turn(trace_id, source, req.message, started,
                     status="error", error=str(e).split("\n")[0][:300])
        raise _omop_error(e)
    _record_turn(trace_id, source, req.message, started, result=result)
    result["trace_id"] = trace_id
    return result

@app.post("/api/omop/{resource_id}/cohort/count")
def omop_count(resource_id: str,
               req: OmopSpecRequest = Body(default_factory=lambda: OmopSpecRequest({}))):
    engine, info = _omop_cdm(resource_id)
    try:
        return omop.count(engine, info, req.root)
    except Exception as e:
        raise _omop_error(e)

@app.post("/api/omop/{resource_id}/cohort/open")
def omop_open_cohort(resource_id: str, req: OmopCohortOpenRequest):
    engine, info = _omop_cdm(resource_id)
    try:
        df = omop.open_cohort(engine, info, req.spec)
        parents = omop.tables_used(info, req.spec)
    except Exception as e:
        raise _omop_error(e)
    name = req.name.strip() or "OMOP cohort"
    source = f"{resource_id} / {name}"
    result = datasets.open_dataset(df, source)
    lineage.record(_lineage_engine(), "omop_cohort_opened", "cohort", source,
                   payload={"resource_id": resource_id, "spec": req.spec,
                            "rows": len(df)},
                   parents=[("table", t) for t in parents])
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
