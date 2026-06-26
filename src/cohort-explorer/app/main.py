import csv
import io
import json
import logging
import os
import subprocess
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from cohorts import cohort_exists, delete_cohort, get_cohort, init_cohorts, list_cohorts, save_cohort
from db import get_active_resource_id, get_db, get_sqlite_engine, list_aurora_resources, list_s3_folders, set_active_resource, warm_connection_string, wait_connection_string, warm_resource_cache
from dynamic_model import DynamicBase, clear_schema, get_active_mapping, get_active_model, get_all_columns, get_categorical_filters, get_pk_name, get_range_filters, get_visible_columns, load_schema_from_disk, set_active_mapping
from models import Base, Sample
from schema import infer_from_aurora, infer_from_csv, list_aurora_tables, load_mapping_csv, mappings_to_dicts, save_mapping_csv, ColumnMapping
from seed import seed_dynamic, seed_from_tsv
from starlette.requests import Request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Cohort Explorer")

STATIC_DIR = Path(__file__).parent / "static"

def _get_model():
    return get_active_model() or Sample


def _get_pk(model):
    return getattr(model, get_pk_name()) if get_active_model() else model.id


def _apply_filters(stmt, params: dict, exclude: str | None = None):
    model = _get_model()
    for col_name in get_categorical_filters():
        if col_name == exclude:
            continue
        values = params.get(col_name)
        if values:
            col = getattr(model, col_name)
            value_list = values if isinstance(values, list) else [values]
            has_null = "__null__" in value_list
            non_null_values = [v for v in value_list if v != "__null__"]
            if has_null and non_null_values:
                stmt = stmt.where(col.in_(non_null_values) | col.is_(None))
            elif has_null:
                stmt = stmt.where(col.is_(None))
            elif non_null_values:
                stmt = stmt.where(col.in_(non_null_values))

    for col_name in get_range_filters():
        col = getattr(model, col_name)
        min_val = params.get(f"{col_name}_min")
        max_val = params.get(f"{col_name}_max")
        if min_val is not None:
            stmt = stmt.where(col >= float(min_val))
        if max_val is not None:
            stmt = stmt.where(col <= float(max_val))

    return stmt


def _extract_filter_params(request: Request) -> dict:
    params: dict = {}
    for col_name in get_categorical_filters():
        values = request.query_params.getlist(col_name)
        if values:
            params[col_name] = values
    for col_name in get_range_filters():
        for suffix in ("_min", "_max"):
            val = request.query_params.get(f"{col_name}{suffix}")
            if val is not None:
                params[f"{col_name}{suffix}"] = float(val)
    return params


def _ensure_aws_config():
    if os.environ.get("AWS_CONFIG_FILE"):
        return
    import glob
    matches = glob.glob(os.path.expanduser("~/.workbench/aws/*.conf"))
    if matches:
        os.environ["AWS_CONFIG_FILE"] = matches[0]
        logger.info("Set AWS_CONFIG_FILE to %s", matches[0])


@app.on_event("startup")
def startup():
    _ensure_aws_config()
    engine = get_sqlite_engine()
    Base.metadata.create_all(engine)
    logger.info("SQLite tables ensured")
    load_schema_from_disk()
    warm_resource_cache()
    cohort_folder = os.environ.get("COHORT_STORAGE_FOLDER_ID", "GTEx_demo_folder")
    init_cohorts(cohort_folder)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/datasources")
def get_datasources() -> dict:
    aurora = list_aurora_resources(wait=True)
    for r in aurora:
        warm_connection_string(r["id"])
    s3_folders = list_s3_folders()
    active = get_active_resource_id()
    return {
        "resources": aurora,
        "s3_folders": s3_folders,
        "active": active,
        "has_local": True,
    }


@app.post("/api/datasources/refresh")
def refresh_datasources() -> dict:
    warm_resource_cache()
    aurora = list_aurora_resources(wait=True)
    s3_folders = list_s3_folders()
    active = get_active_resource_id()
    return {
        "resources": aurora,
        "s3_folders": s3_folders,
        "active": active,
        "has_local": True,
    }


@app.get("/api/s3/files")
def list_s3_files(folder_id: str = Query(...)) -> list[dict]:
    try:
        bucket_path = subprocess.run(
            ["wb", "resource", "resolve", "--id", folder_id],
            capture_output=True, text=True, check=True, timeout=120,
        ).stdout.strip().rstrip("/")

        result = subprocess.run(
            ["aws", "s3", "ls", f"{bucket_path}/", "--recursive"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            return []

        files = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            key = parts[3]
            if key.lower().endswith((".tsv", ".csv", ".txt")):
                size = int(parts[2])
                files.append({
                    "key": key,
                    "name": key.split("/")[-1],
                    "size": size,
                    "s3_path": f"{bucket_path}/{key}",
                })
        return files
    except Exception as e:
        logger.error("Failed to list S3 files: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/schema/tables")
def api_list_tables(resource_id: str = Query(...)) -> list[dict]:
    try:
        wait_connection_string(resource_id)
        return list_aurora_tables(resource_id)
    except Exception as e:
        logger.error("Failed to list tables: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/schema/infer")
def api_infer_schema(body: dict) -> dict:
    source_type = body.get("source_type")
    folder_id = body.get("folder_id")
    try:
        if source_type == "file":
            s3_path = body.get("s3_path", "")
            local_path = Path(tempfile.gettempdir()) / Path(s3_path).name
            profile_args = ["--profile", folder_id] if folder_id else []
            subprocess.run(
                ["aws", "s3", "cp", *profile_args, s3_path, str(local_path)],
                capture_output=True, text=True, check=True, timeout=120,
            )
            mappings = infer_from_csv(str(local_path))
            local_path.unlink(missing_ok=True)
        elif source_type == "aurora":
            resource_id = body.get("resource_id", "")
            table = body.get("table", "")
            mappings = infer_from_aurora(resource_id, table)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown source_type: {source_type}")
        return {"mappings": mappings_to_dicts(mappings)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Schema inference failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/schema/confirm")
def api_confirm_schema(body: dict) -> dict:
    mappings_raw = body.get("mappings", [])
    mappings = [ColumnMapping(**m) for m in mappings_raw]
    folder_id = body.get("folder_id")
    source_name = body.get("source_name", "schema")

    if folder_id:
        try:
            local_csv = Path(tempfile.gettempdir()) / f"{source_name}.columns.csv"
            save_mapping_csv(str(local_csv), mappings)

            bucket_path = subprocess.run(
                ["wb", "resource", "resolve", "--id", folder_id],
                capture_output=True, text=True, check=True, timeout=120,
            ).stdout.strip().rstrip("/")

            subprocess.run(
                ["aws", "s3", "cp", "--profile", folder_id, str(local_csv),
                 f"{bucket_path}/{source_name}.columns.csv"],
                capture_output=True, text=True, check=True, timeout=120,
            )
            local_csv.unlink(missing_ok=True)
            logger.info("Saved mapping CSV to S3 for %s", source_name)
        except Exception as e:
            logger.warning("Failed to save mapping CSV to S3: %s", e)

    table_name = body.get("table_name", "data")
    is_aurora = get_active_resource_id() is not None
    set_active_mapping(mappings_raw, table_name=table_name, needs_pk=not is_aurora)

    seeded = 0
    if not is_aurora:
        engine = get_sqlite_engine()
        DynamicBase.metadata.create_all(engine)
        file_path = body.get("file_path")
        if file_path:
            from sqlalchemy.orm import Session as SaSession
            with SaSession(engine) as db:
                seeded = seed_dynamic(db, file_path, get_active_model(), mappings_raw, profile=folder_id)

    return {"confirmed": True, "columns": len(mappings), "seeded": seeded}


@app.get("/api/schema/active")
def api_active_schema() -> dict:
    mapping = get_active_mapping()
    return {"mappings": mapping or []}


@app.post("/api/connect")
def connect_resource(
    resource_id: str = Query(...),
    cohort_folder: str | None = Query(None),
    seed_from: str | None = Query(None),
) -> dict:
    if resource_id == "__local__":
        set_active_resource(None)
    else:
        try:
            set_active_resource(resource_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Connection failed: {e}") from e

    if cohort_folder:
        init_cohorts(cohort_folder)

    if seed_from:
        engine = get_sqlite_engine()
        Base.metadata.create_all(engine)
        from sqlalchemy.orm import Session as SaSession
        with SaSession(engine) as db:
            count = seed_from_tsv(db, seed_from)
        set_active_resource(None)
        return {"connected": "local (SQLite)", "seeded": count}

    return {"connected": resource_id if resource_id != "__local__" else "local (SQLite)"}


@app.get("/api/samples")
def get_samples(
    request: Request,
    db: Session = Depends(get_db),
) -> list[dict]:
    model = _get_model()
    columns = get_visible_columns() or get_all_columns()
    filters = _extract_filter_params(request)
    stmt = select(model)
    stmt = _apply_filters(stmt, filters)
    first_col = columns[0] if columns else "id"
    stmt = stmt.order_by(getattr(model, first_col))
    rows = db.execute(stmt).scalars().all()
    pk = get_pk_name()
    return [
        {pk: getattr(s, pk), **{col: getattr(s, col) for col in columns}}
        for s in rows
    ]


@app.get("/api/filters")
def get_filters(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    model = _get_model()
    filters = _extract_filter_params(request)
    result: dict = {}

    for col_name in get_categorical_filters():
        cross_stmt = select(model)
        cross_stmt = _apply_filters(cross_stmt, filters, exclude=col_name)
        pk = _get_pk(model)
        cross_ids = cross_stmt.with_only_columns(pk).subquery()

        col = getattr(model, col_name)
        values_stmt = (
            select(col, func.count(pk))
            .where(pk.in_(select(cross_ids.c[get_pk_name()])))
            .group_by(col)
            .order_by(col)
        )
        rows = db.execute(values_stmt).all()
        options = []
        for val, cnt in rows:
            options.append({
                "value": val if val is not None else "__null__",
                "label": val if val is not None else "Unknown",
                "count": cnt,
            })
        result[col_name] = options

    all_stmt = select(model)
    all_stmt = _apply_filters(all_stmt, filters)
    pk = _get_pk(model)
    filtered_ids = all_stmt.with_only_columns(pk).subquery()

    for col_name in get_range_filters():
        col = getattr(model, col_name)
        range_stmt = (
            select(func.min(col), func.max(col))
            .where(pk.in_(select(filtered_ids.c[get_pk_name()])))
            .where(col.isnot(None))
        )
        row = db.execute(range_stmt).one()
        result[col_name] = {
            "min": float(row[0]) if row[0] is not None else None,
            "max": float(row[1]) if row[1] is not None else None,
        }

    return result


@app.get("/api/counts")
def get_counts(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    model = _get_model()
    filters = _extract_filter_params(request)
    stmt = select(model)
    stmt = _apply_filters(stmt, filters)
    filtered = stmt.subquery()

    pk_col = get_pk_name()
    count_exprs = [func.count(filtered.c[pk_col]).label("samples")]
    if hasattr(filtered.c, "subject_id"):
        count_exprs.append(func.count(distinct(filtered.c.subject_id)).label("subjects"))
    if hasattr(filtered.c, "fastq1_path"):
        count_exprs.append(func.count(filtered.c.fastq1_path).label("fastq_pairs"))

    row = db.execute(select(*count_exprs)).one()
    result = {"samples": row.samples}
    if hasattr(row, "subjects"):
        result["subjects"] = row.subjects
    if hasattr(row, "fastq_pairs"):
        result["fastq_pairs"] = row.fastq_pairs
    return result


@app.post("/api/seed")
def seed_data(
    path: str | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    tsv_path = path or os.environ.get("TSV_PATH", "/workspace/GTEx_V8_sample_manifest_metadata.tsv")
    try:
        count = seed_from_tsv(db, tsv_path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=f"Permission denied: {tsv_path}") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Seed error: {e}") from e
    return {"seeded": count}


@app.get("/api/export")
def export_csv(
    request: Request,
    db: Session = Depends(get_db),
):
    model = _get_model()
    columns = get_all_columns()
    filters = _extract_filter_params(request)
    stmt = select(model)
    stmt = _apply_filters(stmt, filters)
    first_col = columns[0] if columns else "id"
    stmt = stmt.order_by(getattr(model, first_col))
    rows = db.execute(stmt).scalars().all()

    output = io.StringIO()
    output.write("\t".join(columns) + "\n")
    for s in rows:
        vals = [str(getattr(s, col) or "") for col in columns]
        output.write("\t".join(vals) + "\n")

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/tab-separated-values",
        headers={"Content-Disposition": "attachment; filename=cohort_export.tsv"},
    )


@app.get("/api/cohorts")
def api_list_cohorts() -> list[dict]:
    return list_cohorts()


@app.get("/api/cohorts/{name}")
def api_get_cohort(name: str) -> dict:
    cohort = get_cohort(name)
    if not cohort:
        raise HTTPException(status_code=404, detail=f"Cohort not found: {name}")
    return cohort


@app.post("/api/cohorts")
def api_save_cohort(body: dict) -> dict:
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Cohort name is required")
    return save_cohort(
        name=name,
        description=body.get("description", ""),
        filters=body.get("filters", {}),
        sample_count=body.get("sampleCount", 0),
    )


@app.delete("/api/cohorts/{name}")
def api_delete_cohort(name: str) -> dict:
    if not delete_cohort(name):
        raise HTTPException(status_code=404, detail=f"Cohort not found: {name}")
    return {"deleted": name}


@app.get("/api/cohorts/{name}/exists")
def api_cohort_exists(name: str) -> dict:
    return {"exists": cohort_exists(name)}


SALMON_WORKFLOW_ID = os.environ.get("SALMON_WORKFLOW_ID", "salmon-workflow")
SALMON_INPUT_BUCKET_ID = os.environ.get("SALMON_INPUT_BUCKET_ID", "GTEx_demo_folder")
SALMON_OUTPUT_BUCKET_ID = os.environ.get("SALMON_OUTPUT_BUCKET_ID", "GTEx_demo_folder")
SALMON_COLUMN_MAPPING_URI = os.environ.get(
    "SALMON_COLUMN_MAPPING_URI",
    "s3://v0-saas-prod-us-west-2-workbench/GTEx_demo_folder-yp-copy-of-gtex-demo-project/salmon-workflow-columns.json",
)
SALMON_TRANSCRIPTOME = os.environ.get("SALMON_TRANSCRIPTOME", "test")
SALMON_TRANSCRIPT_MAP = os.environ.get(
    "SALMON_TRANSCRIPT_MAP",
    json.dumps({
        "test": {
            "transcript_index": "s3://v0-saas-prod-us-west-2-workbench/GTEx_demo_folder-yp-copy-of-gtex-demo-project/data/transcripts.fasta.tar.gz",
            "genomitory_id": "test",
        }
    }),
)


def _build_salmon_row(sample: Sample) -> dict | None:
    if not sample.fastq1_path:
        return None
    files = [sample.fastq1_path]
    if sample.fastq2_path:
        files.append(sample.fastq2_path)
    return {
        "input_files": json.dumps(files),
        "sample_name": sample.gtex_sample_id,
        "transcriptome": SALMON_TRANSCRIPTOME,
        "transcript_map": SALMON_TRANSCRIPT_MAP,
    }


@app.post("/api/salmon/prepare")
def prepare_salmon(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    model = _get_model()
    filters = _extract_filter_params(request)
    stmt = select(model)
    stmt = _apply_filters(stmt, filters)
    rows = db.execute(stmt).scalars().all()

    with_fastq = []
    without_fastq = 0
    for s in rows:
        row = _build_salmon_row(s)
        if row:
            with_fastq.append(row)
        else:
            without_fastq += 1

    return {
        "sample_count": len(rows),
        "samples_with_fastq": len(with_fastq),
        "samples_without_fastq": without_fastq,
        "preview": with_fastq[:5],
    }


_salmon_jobs: dict[str, dict] = {}


def _run_salmon_in_background(job_id: str, salmon_rows: list[dict], csv_filename: str, timestamp: str):
    local_csv = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            writer = csv.DictWriter(f, fieldnames=["input_files", "sample_name", "transcriptome", "transcript_map"])
            writer.writeheader()
            writer.writerows(salmon_rows)
            local_csv = f.name

        bucket_path = subprocess.run(
            ["wb", "resource", "resolve", "--id", SALMON_INPUT_BUCKET_ID],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        subprocess.run(
            ["aws", "s3", "cp", "--profile", SALMON_INPUT_BUCKET_ID,
             local_csv, f"{bucket_path.rstrip('/')}/{csv_filename}"],
            capture_output=True, text=True, check=True,
        )

        result = subprocess.run(
            [
                "wb", "workflow", "job", "run",
                f"--workflow={SALMON_WORKFLOW_ID}",
                f"--batch-input-bucket-id={SALMON_INPUT_BUCKET_ID}",
                f"--batch-input-csv-path={csv_filename}",
                f"--column-mapping-uri={SALMON_COLUMN_MAPPING_URI}",
                f"--output-bucket-id={SALMON_OUTPUT_BUCKET_ID}",
                f"--output-path=salmon_outputs/{timestamp}",
                f"--job-id={job_id}",
            ],
            capture_output=True, text=True, check=True,
        )

        _salmon_jobs[job_id] = {"status": "submitted", "output": result.stdout.strip()}
        logger.info("Salmon job %s submitted successfully", job_id)

    except subprocess.CalledProcessError as e:
        _salmon_jobs[job_id] = {"status": "failed", "error": e.stderr or e.stdout}
        logger.error("Salmon job %s failed: %s", job_id, e.stderr or e.stdout)
    except Exception as e:
        _salmon_jobs[job_id] = {"status": "failed", "error": str(e)}
        logger.error("Salmon job %s error: %s", job_id, e)
    finally:
        if local_csv:
            Path(local_csv).unlink(missing_ok=True)


@app.post("/api/salmon/submit")
def submit_salmon(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    model = _get_model()
    filters = _extract_filter_params(request)
    stmt = select(model)
    stmt = _apply_filters(stmt, filters)
    rows = db.execute(stmt).scalars().all()

    salmon_rows = [r for r in (_build_salmon_row(s) for s in rows) if r]
    if not salmon_rows:
        raise HTTPException(status_code=400, detail="No samples with FASTQ paths in current filter")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    job_id = f"cohort-salmon-{timestamp}"
    csv_filename = f"workflow_inputs/batch_{timestamp}.csv"

    _salmon_jobs[job_id] = {"status": "submitting"}

    thread = threading.Thread(
        target=_run_salmon_in_background,
        args=(job_id, salmon_rows, csv_filename, timestamp),
        daemon=True,
    )
    thread.start()

    return {
        "job_id": job_id,
        "samples_submitted": len(salmon_rows),
        "status": "submitting",
    }


@app.get("/api/salmon/status/{job_id}")
def salmon_job_status(job_id: str) -> dict:
    if job_id not in _salmon_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job_id": job_id, **_salmon_jobs[job_id]}


if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str) -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")
