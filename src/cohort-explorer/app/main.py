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

from db import get_active_resource_id, get_db, get_sqlite_engine, list_aurora_resources, set_active_resource, warm_aurora_cache
from models import Base, Sample
from seed import seed_from_tsv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Cohort Explorer")

STATIC_DIR = Path(__file__).parent / "static"

FILTERABLE_CATEGORICAL = [
    "tissue_type",
    "tissue_type_detail",
    "autolysis_score",
    "current_material_type",
    "sample_collection_kit",
]
FILTERABLE_RANGE = ["rin_number", "total_ischemic_time", "paxgene_time"]


def _apply_filters(stmt, params: dict):
    for col_name in FILTERABLE_CATEGORICAL:
        values = params.get(col_name)
        if values:
            col = getattr(Sample, col_name)
            value_list = values if isinstance(values, list) else [values]
            has_null = "__null__" in value_list
            non_null_values = [v for v in value_list if v != "__null__"]
            if has_null and non_null_values:
                stmt = stmt.where(col.in_(non_null_values) | col.is_(None))
            elif has_null:
                stmt = stmt.where(col.is_(None))
            elif non_null_values:
                stmt = stmt.where(col.in_(non_null_values))

    for col_name in FILTERABLE_RANGE:
        col = getattr(Sample, col_name)
        min_val = params.get(f"{col_name}_min")
        max_val = params.get(f"{col_name}_max")
        if min_val is not None:
            stmt = stmt.where(col >= float(min_val))
        if max_val is not None:
            stmt = stmt.where(col <= float(max_val))

    return stmt


def _extract_filter_params(
    tissue_type: list[str] | None = Query(None),
    tissue_type_detail: list[str] | None = Query(None),
    autolysis_score: list[str] | None = Query(None),
    current_material_type: list[str] | None = Query(None),
    sample_collection_kit: list[str] | None = Query(None),
    rin_number_min: float | None = Query(None),
    rin_number_max: float | None = Query(None),
    total_ischemic_time_min: float | None = Query(None),
    total_ischemic_time_max: float | None = Query(None),
    paxgene_time_min: float | None = Query(None),
    paxgene_time_max: float | None = Query(None),
) -> dict:
    return {
        "tissue_type": tissue_type,
        "tissue_type_detail": tissue_type_detail,
        "autolysis_score": autolysis_score,
        "current_material_type": current_material_type,
        "sample_collection_kit": sample_collection_kit,
        "rin_number_min": rin_number_min,
        "rin_number_max": rin_number_max,
        "total_ischemic_time_min": total_ischemic_time_min,
        "total_ischemic_time_max": total_ischemic_time_max,
        "paxgene_time_min": paxgene_time_min,
        "paxgene_time_max": paxgene_time_max,
    }


@app.on_event("startup")
def startup():
    engine = get_sqlite_engine()
    Base.metadata.create_all(engine)
    logger.info("SQLite tables ensured")
    warm_aurora_cache()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/datasources")
def get_datasources() -> dict:
    aurora = list_aurora_resources(wait=True)
    active = get_active_resource_id()
    return {
        "resources": aurora,
        "active": active,
        "has_local": True,
    }


@app.post("/api/datasources/refresh")
def refresh_datasources() -> dict:
    warm_aurora_cache()
    active = get_active_resource_id()
    return {
        "resources": list_aurora_resources(),
        "active": active,
        "has_local": True,
    }


@app.post("/api/connect")
def connect_resource(resource_id: str = Query(...)) -> dict:
    if resource_id == "__local__":
        set_active_resource(None)
        return {"connected": "local (SQLite)"}

    try:
        set_active_resource(resource_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Connection failed: {e}") from e

    return {"connected": resource_id}


@app.get("/api/samples")
def get_samples(
    filters: dict = Depends(_extract_filter_params),
    db: Session = Depends(get_db),
) -> list[dict]:
    stmt = select(Sample)
    stmt = _apply_filters(stmt, filters)
    stmt = stmt.order_by(Sample.tissue_type, Sample.gtex_sample_id)
    rows = db.execute(stmt).scalars().all()
    return [
        {
            "id": s.id,
            "subject_id": s.subject_id,
            "gtex_sample_id": s.gtex_sample_id,
            "specimen_id": s.specimen_id,
            "tissue_type": s.tissue_type,
            "tissue_type_detail": s.tissue_type_detail,
            "autolysis_score": s.autolysis_score,
            "current_material_type": s.current_material_type,
            "sample_collection_kit": s.sample_collection_kit,
            "rin_number": float(s.rin_number) if s.rin_number is not None else None,
            "total_ischemic_time": s.total_ischemic_time,
            "paxgene_time": s.paxgene_time,
            "tissue_location": s.tissue_location,
            "bss_collection_site": s.bss_collection_site,
            "original_material_type": s.original_material_type,
            "srr_id": s.srr_id,
            "fastq1_path": s.fastq1_path,
            "fastq2_path": s.fastq2_path,
        }
        for s in rows
    ]


@app.get("/api/filters")
def get_filters(
    filters: dict = Depends(_extract_filter_params),
    db: Session = Depends(get_db),
) -> dict:
    base_stmt = select(Sample)
    base_stmt = _apply_filters(base_stmt, filters)
    filtered_ids = base_stmt.with_only_columns(Sample.id).subquery()

    result: dict = {}
    for col_name in FILTERABLE_CATEGORICAL:
        col = getattr(Sample, col_name)
        values_stmt = (
            select(col, func.count(Sample.id))
            .where(Sample.id.in_(select(filtered_ids.c.id)))
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

    for col_name in FILTERABLE_RANGE:
        col = getattr(Sample, col_name)
        range_stmt = (
            select(func.min(col), func.max(col))
            .where(Sample.id.in_(select(filtered_ids.c.id)))
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
    filters: dict = Depends(_extract_filter_params),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(Sample)
    stmt = _apply_filters(stmt, filters)
    filtered = stmt.subquery()

    counts = db.execute(
        select(
            func.count(filtered.c.id).label("samples"),
            func.count(distinct(filtered.c.subject_id)).label("subjects"),
            func.count(filtered.c.fastq1_path).label("fastq_pairs"),
        )
    ).one()

    return {
        "samples": counts.samples,
        "subjects": counts.subjects,
        "fastq_pairs": counts.fastq_pairs,
    }


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
    filters: dict = Depends(_extract_filter_params),
    db: Session = Depends(get_db),
):
    stmt = select(Sample)
    stmt = _apply_filters(stmt, filters)
    stmt = stmt.order_by(Sample.tissue_type, Sample.gtex_sample_id)
    rows = db.execute(stmt).scalars().all()

    output = io.StringIO()
    header = ["subject_id", "gtex_sample_id", "tissue_type", "tissue_type_detail", "fastq1_path", "fastq2_path", "srr_id"]
    output.write("\t".join(header) + "\n")
    for s in rows:
        vals = [
            s.subject_id or "",
            s.gtex_sample_id or "",
            s.tissue_type or "",
            s.tissue_type_detail or "",
            s.fastq1_path or "",
            s.fastq2_path or "",
            s.srr_id or "",
        ]
        output.write("\t".join(vals) + "\n")

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/tab-separated-values",
        headers={"Content-Disposition": "attachment; filename=cohort_export.tsv"},
    )


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
    filters: dict = Depends(_extract_filter_params),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(Sample)
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

        creds_json = subprocess.run(
            ["wb", "resource", "credentials", "--id", SALMON_INPUT_BUCKET_ID,
             "--scope", "WRITE_READ", "--format", "JSON"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        creds = json.loads(creds_json)

        upload_env = {
            **os.environ,
            "AWS_ACCESS_KEY_ID": creds["AccessKeyId"],
            "AWS_SECRET_ACCESS_KEY": creds["SecretAccessKey"],
            "AWS_SESSION_TOKEN": creds["SessionToken"],
        }

        subprocess.run(
            ["aws", "s3", "cp", local_csv, f"{bucket_path.rstrip('/')}/{csv_filename}"],
            capture_output=True, text=True, check=True, env=upload_env,
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
    filters: dict = Depends(_extract_filter_params),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(Sample)
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
