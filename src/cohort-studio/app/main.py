"""Cohort Studio — FastAPI backend for the TypeScript cohort explorer.

Thin REST layer over the same proven engine modules the Panel app uses
(Aurora via SQLAlchemy, S3 Parquet/CSV via DuckDB, BigQuery), with
server-side cross-filter aggregation (datasets.py) and lineage recording.
The compiled React frontend is served from ./static.
"""

import io
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import bq
import config
import datasets
import db
import duck
import lineage
import llm
import mcp_server
import queries

logging.basicConfig(level=logging.INFO, force=True)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.warm_resource_cache()
    if mcp_server.AVAILABLE:
        async with mcp_server.mcp.session_manager.run():
            yield
    else:
        yield


app = FastAPI(title="Cohort Studio", lifespan=lifespan)

if mcp_server.AVAILABLE:
    app.mount("/mcp", mcp_server.http_app())


# ------------------------------------------------------------------ models

class OpenRequest(BaseModel):
    kind: str
    resource_id: str
    table: str


class Filter(BaseModel):
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
    page: int = 0
    page_size: int = 50


# ----------------------------------------------------------------- helpers

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
    raise HTTPException(400, f"Unknown datasource kind: {kind}")


# --------------------------------------------------------------- endpoints

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
    """Redeploy the branch in place — see self_update.sh.

    Reachable only through the workspace proxy (workspace members), and
    only ever installs code from this app's pinned GitHub repo/branch.
    The server restarts itself when an update lands, so the caller should
    poll /api/version until the sha changes.
    """
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
    if ready:
        db.retry_if_empty()
        for r in db.list_aurora_resources():
            sources.append({"kind": "aurora", "id": r["id"],
                            "label": f"{r['id']} · Aurora"})
        for r in db.list_s3_folders():
            sources.append({"kind": "s3", "id": r["id"],
                            "label": f"{r['id']} · S3"})
        for r in db.list_bq_datasets():
            sources.append({"kind": "bq", "id": r["id"],
                            "label": f"{r['id']} · BigQuery"})
    return {"ready": ready, "sources": sources}


@app.get("/api/tables")
def tables(kind: str, resource_id: str):
    try:
        if kind == "aurora":
            return [{"name": t["name"], "detail": t["kind"]}
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, str(e).split("\n")[0][:300])
    raise HTTPException(400, f"Unknown kind: {kind}")


@app.post("/api/datasets/open")
def open_dataset(req: OpenRequest):
    try:
        df = _load_frame(req.kind, req.resource_id, req.table)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, str(e).split("\n")[0][:300])
    result = datasets.open_dataset(df, f"{req.resource_id} / {req.table}")
    lineage.record(_lineage_engine(), "table_loaded", "table", req.table,
                   payload={"resource_id": req.resource_id,
                            "source_kind": req.kind, "rows": len(df)})
    return result


@app.post("/api/datasets/upload")
async def upload_dataset(file: UploadFile):
    name = file.filename or "upload.csv"
    sep = "\t" if name.lower().endswith((".tsv", ".txt")) else ","
    df = pd.read_csv(io.BytesIO(await file.read()), sep=sep)
    result = datasets.open_dataset(df, name)
    lineage.record(_lineage_engine(), "csv_uploaded", "file", name,
                   payload={"rows": len(df), "columns": list(df.columns)})
    return result


@app.post("/api/datasets/{dataset_id}/query")
def query_dataset(dataset_id: str, req: QueryRequest):
    try:
        return datasets.query(
            dataset_id,
            [f.model_dump() for f in req.filters],
            [c.model_dump() for c in req.charts],
            page=req.page, page_size=req.page_size)
    except datasets.DatasetNotFound:
        raise HTTPException(404, "Dataset expired or unknown — reload it.")


@app.post("/api/datasets/{dataset_id}/export")
def export_dataset(dataset_id: str, req: QueryRequest):
    try:
        ds = datasets.get(dataset_id)
    except datasets.DatasetNotFound:
        raise HTTPException(404, "Dataset expired or unknown — reload it.")
    df = datasets.apply_filters(ds["df"], [f.model_dump() for f in req.filters])
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
    model: str | None = None
    api_key: str | None = None
    mcp_connections: list[MCPConnection] | None = None


class AskRequest(BaseModel):
    question: str
    filters: list[Filter] = Field(default_factory=list)


@app.get("/api/config")
def get_config():
    cfg = config.public_config()
    cfg["mcp"] = {"available": mcp_server.AVAILABLE, "path": "/mcp"}
    return cfg


@app.put("/api/config")
def put_config(req: ConfigUpdate):
    if req.model is not None or req.api_key is not None:
        config.update_llm_config(model=req.model, api_key=req.api_key)
    if req.mcp_connections is not None:
        config.update_mcp_connections(
            [c.model_dump() for c in req.mcp_connections])
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


# ------------------------------------------------------------ static files

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
