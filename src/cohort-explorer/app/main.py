import io
import logging
import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from db import get_active_resource_id, get_db, get_sqlite_engine, list_aurora_resources, set_active_resource
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


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/datasources")
def get_datasources() -> dict:
    aurora = list_aurora_resources()
    active = get_active_resource_id()
    return {
        "resources": aurora,
        "active": active,
        "has_local": True,
    }


@app.post("/api/connect")
def connect_resource(resource_id: str = Query(...)) -> dict:
    if resource_id == "__local__":
        set_active_resource(None)
        return {"connected": "local (SQLite)"}

    aurora = list_aurora_resources()
    match = [r for r in aurora if r["id"] == resource_id]
    if not match:
        raise HTTPException(status_code=404, detail=f"Resource not found: {resource_id}")

    try:
        set_active_resource(resource_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Connection failed: {e}") from e

    return {"connected": resource_id, "database": match[0].get("database")}


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


if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str) -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")
