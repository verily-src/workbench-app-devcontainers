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
from db import are_tables_ready, get_active_resource_id, get_cached_tables, get_db, get_sqlite_engine, list_aurora_resources, list_s3_folders, set_active_resource, warm_resource_cache
from dynamic_model import DynamicBase, clear_schema, get_active_mapping, get_active_model, get_all_columns, get_categorical_filters, get_pk_name, get_range_filters, get_visible_columns, load_schema_from_disk, set_active_mapping
from models import Base, Sample
from schema import infer_from_aurora, infer_from_csv, load_mapping_csv, mappings_to_dicts, save_mapping_csv, ColumnMapping
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


def _get_workspace_uuid_from_ec2_tags():
    """Fetch the WorkspaceId tag from the EC2 instance via IMDSv2."""
    import urllib.request
    try:
        token_req = urllib.request.Request(
            "http://169.254.169.254/latest/api/token",
            method="PUT",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "600"},
        )
        with urllib.request.urlopen(token_req, timeout=5) as r:
            token = r.read().decode()

        def _get(path):
            req = urllib.request.Request(
                f"http://169.254.169.254/latest/meta-data/{path}",
                headers={"X-aws-ec2-metadata-token": token},
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.read().decode()

        instance_id = _get("instance-id")
        region = _get("placement/region")

        result = subprocess.run(
            ["aws", "ec2", "describe-tags",
             "--region", region,
             "--filters", f"Name=resource-id,Values={instance_id}",
                          "Name=key,Values=WorkspaceId",
             "--query", "Tags[0].Value", "--output", "text"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            uuid = result.stdout.strip()
            if uuid and uuid != "None":
                return uuid
        logger.warning("aws ec2 describe-tags failed: %s", result.stderr)
    except Exception as e:
        logger.warning("Failed to fetch workspace UUID from EC2 metadata: %s", e)
    return None


def _ensure_workspace():
    """Ensure wb has a workspace set. The container's /root is a named Docker
    volume, isolated from the host, so `wb workspace set` on the host doesn't
    persist here. Try env vars first, then fall back to EC2 instance tags."""
    try:
        result = subprocess.run(
            ["wb", "workspace", "describe", "--format", "json"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            if data.get("id"):
                logger.info("Workspace already set: %s", data["id"])
                return
    except Exception:
        pass

    for env_var, flag in [
        ("WORKBENCH_WORKSPACE_UUID", "--uuid"),
        ("TERRA_WORKSPACE", "--id"),
        ("WORKBENCH_WORKSPACE_ID", "--id"),
        ("WORKSPACE_ID", "--id"),
    ]:
        value = os.environ.get(env_var)
        if not value:
            continue
        try:
            subprocess.run(
                ["wb", "workspace", "set", f"{flag}={value}"],
                capture_output=True, text=True, check=True, timeout=60,
            )
            logger.info("Set workspace from %s=%s", env_var, value)
            return
        except Exception as e:
            logger.warning("Failed to set workspace from %s: %s", env_var, e)

    uuid = _get_workspace_uuid_from_ec2_tags()
    if uuid:
        try:
            subprocess.run(
                ["wb", "workspace", "set", f"--uuid={uuid}"],
                capture_output=True, text=True, check=True, timeout=60,
            )
            logger.info("Set workspace from EC2 tag WorkspaceId=%s", uuid)
            return
        except Exception as e:
            logger.warning("Failed to set workspace from EC2 tag: %s", e)

    logger.error("Could not determine workspace — no env var and EC2 tag lookup failed")


def _ensure_aws_config():
    if os.environ.get("AWS_CONFIG_FILE"):
        return
    try:
        subprocess.run(
            ["wb", "workspace", "configure-aws"],
            capture_output=True, text=True, check=True, timeout=120,
        )
        logger.info("Configured AWS profiles via wb workspace configure-aws")
    except Exception as e:
        logger.warning("Failed to configure AWS profiles: %s", e)
    import glob
    matches = glob.glob(os.path.expanduser("~/.workbench/aws/*.conf"))
    if matches:
        os.environ["AWS_CONFIG_FILE"] = matches[0]
        logger.info("Set AWS_CONFIG_FILE to %s", matches[0])


def _warm_s3_files():
    from db import _resource_cache_ready, list_s3_folders
    _resource_cache_ready.wait(timeout=180)
    folders = list_s3_folders()
    for folder in folders:
        try:
            _fetch_s3_files(folder["id"])
        except Exception as e:
            logger.warning("Failed to warm S3 files for %s: %s", folder["id"], e)


@app.on_event("startup")
def startup():
    _ensure_workspace()
    _ensure_aws_config()
    engine = get_sqlite_engine()
    Base.metadata.create_all(engine)
    logger.info("SQLite tables ensured")
    load_schema_from_disk()
    warm_resource_cache()
    threading.Thread(target=_warm_s3_files, daemon=True).start()
    cohort_folder = os.environ.get("COHORT_STORAGE_FOLDER_ID", "GTEx_demo_folder")
    init_cohorts(cohort_folder)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/datasources")
def get_datasources() -> dict:
    aurora = list_aurora_resources(wait=True)
    for r in aurora:
        r["tables"] = get_cached_tables(r["id"])
    s3_folders = list_s3_folders()
    active = get_active_resource_id()
    return {
        "resources": aurora,
        "s3_folders": s3_folders,
        "active": active,
        "has_local": True,
        "ready": are_tables_ready(),
    }


@app.post("/api/datasources/refresh")
def refresh_datasources() -> dict:
    warm_resource_cache()
    aurora = list_aurora_resources(wait=True)
    for r in aurora:
        r["tables"] = get_cached_tables(r["id"])
    s3_folders = list_s3_folders()
    active = get_active_resource_id()
    return {
        "resources": aurora,
        "s3_folders": s3_folders,
        "active": active,
        "has_local": True,
        "ready": are_tables_ready(),
    }


_s3_files_cache: dict[str, list[dict]] = {}


def _fetch_s3_files(folder_id: str) -> list[dict]:
    bucket_path = subprocess.run(
        ["wb", "resource", "resolve", "--id", folder_id],
        capture_output=True, text=True, check=True, timeout=120,
    ).stdout.strip().rstrip("/")

    result = subprocess.run(
        ["aws", "s3", "ls", "--profile", folder_id, f"{bucket_path}/"],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        logger.warning("aws s3 ls failed for %s: %s", folder_id, result.stderr)
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
    _s3_files_cache[folder_id] = files
    logger.info("Cached %d S3 files for %s", len(files), folder_id)
    return files


@app.get("/api/s3/files")
def list_s3_files(folder_id: str = Query(...)) -> list[dict]:
    if folder_id in _s3_files_cache:
        threading.Thread(target=_fetch_s3_files, args=(folder_id,), daemon=True).start()
        return _s3_files_cache[folder_id]
    try:
        return _fetch_s3_files(folder_id)
    except Exception as e:
        logger.error("Failed to list S3 files: %s", e)
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
        DynamicBase.metadata.drop_all(engine)
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
    try:
        model = _get_model()
        columns = get_visible_columns() or get_all_columns()
        filters = _extract_filter_params(request)
        limit = int(request.query_params.get("limit", "1000"))
        stmt = select(model)
        stmt = _apply_filters(stmt, filters)
        first_col = columns[0] if columns else "id"
        stmt = stmt.order_by(getattr(model, first_col)).limit(limit)
        rows = db.execute(stmt).scalars().all()
        pk = get_pk_name()
        return [
            {pk: getattr(s, pk), **{col: getattr(s, col) for col in columns}}
            for s in rows
        ]
    except Exception as e:
        logger.error("Failed to fetch samples: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/filters")
def get_filters(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    try:
        model = _get_model()
        filters = _extract_filter_params(request)
        result: dict = {}

        pk = _get_pk(model)
        has_filters = bool(filters)
        max_cat = int(request.query_params.get("max_filters", "20"))

        for col_name in get_categorical_filters()[:max_cat]:
            col = getattr(model, col_name)
            if has_filters:
                cross_stmt = select(model)
                cross_stmt = _apply_filters(cross_stmt, filters, exclude=col_name)
                cross_ids = cross_stmt.with_only_columns(pk).subquery()
                values_stmt = (
                    select(col, func.count(pk))
                    .where(pk.in_(select(cross_ids.c[get_pk_name()])))
                    .group_by(col)
                    .order_by(col)
                )
            else:
                values_stmt = (
                    select(col, func.count(pk))
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

        for col_name in get_range_filters():
            col = getattr(model, col_name)
            if has_filters:
                all_stmt = select(model)
                all_stmt = _apply_filters(all_stmt, filters)
                filtered_ids = all_stmt.with_only_columns(pk).subquery()
                range_stmt = (
                    select(func.min(col), func.max(col))
                    .where(pk.in_(select(filtered_ids.c[get_pk_name()])))
                    .where(col.isnot(None))
                )
            else:
                range_stmt = (
                    select(func.min(col), func.max(col))
                    .where(col.isnot(None))
                )
            row = db.execute(range_stmt).one()
            result[col_name] = {
                "min": float(row[0]) if row[0] is not None else None,
                "max": float(row[1]) if row[1] is not None else None,
            }

        return result
    except Exception as e:
        logger.error("Failed to fetch filters: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


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
def api_list_cohorts(datasource: str = Query("")) -> list[dict]:
    return list_cohorts(datasource=datasource)


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
        datasource=body.get("datasource", ""),
    )


@app.delete("/api/cohorts/{name}")
def api_delete_cohort(name: str) -> dict:
    if not delete_cohort(name):
        raise HTTPException(status_code=404, detail=f"Cohort not found: {name}")
    return {"deleted": name}


@app.get("/api/cohorts/{name}/exists")
def api_cohort_exists(name: str) -> dict:
    return {"exists": cohort_exists(name)}


_wdl_inputs_cache: dict[str, list[dict]] = {}
_workflows_cache: list[dict] | None = None
_workflow_jobs: dict[str, dict] = {}


def _fetch_wdl_inputs(workflow_id: str) -> list[dict]:
    if workflow_id in _wdl_inputs_cache:
        return _wdl_inputs_cache[workflow_id]
    try:
        result = subprocess.run(
            ["wb", "workflow", "describe", f"--workflow={workflow_id}", "--format", "json"],
            capture_output=True, text=True, check=True, timeout=120,
        )
        wf = json.loads(result.stdout)
        inputs = wf.get("inputs") or []
        for inp in inputs:
            inp["short_name"] = inp["name"].split(".")[-1]
        _wdl_inputs_cache[workflow_id] = inputs
        return inputs
    except Exception as e:
        logger.warning("Failed to fetch WDL inputs for %s: %s", workflow_id, e)
        return []


@app.get("/api/workflows")
def list_workflows() -> dict:
    global _workflows_cache
    if _workflows_cache is None:
        try:
            result = subprocess.run(
                ["wb", "workflow", "list", "--format", "json"],
                capture_output=True, text=True, check=True, timeout=120,
            )
            _workflows_cache = json.loads(result.stdout)
        except Exception as e:
            logger.error("Failed to list workflows: %s", e)
            raise HTTPException(status_code=500, detail=str(e)) from e
    workflows = [
        {"id": w["id"], "name": w.get("displayName") or w["id"], "description": w.get("description")}
        for w in (_workflows_cache or [])
    ]
    return {"workflows": workflows, "s3_folders": list_s3_folders()}


@app.get("/api/workflows/{name}/inputs")
def get_workflow_inputs(name: str) -> dict:
    return {"inputs": _fetch_wdl_inputs(name)}


def _build_workflow_rows(
    samples: list, inputs: list[dict], bindings: dict[str, dict],
) -> tuple[list[dict], list[str]]:
    """Return (rows, csv_columns) for the batch CSV.

    Every bound input becomes a CSV column. Static values are written
    same-valued to every row (gotcha #1: --inputs is inert for batch runs).
    """
    csv_columns: list[str] = []
    static_values: dict[str, str] = {}
    cohort_columns: dict[str, str] = {}

    for inp in inputs:
        short = inp["short_name"]
        binding = bindings.get(short)
        if not binding:
            continue
        mode = binding.get("mode")
        value = binding.get("value", "")
        if mode == "cohort" and value:
            csv_columns.append(short)
            cohort_columns[short] = value
        elif mode == "static" and value != "":
            csv_columns.append(short)
            static_values[short] = value

    rows: list[dict] = []
    for s in samples:
        row: dict = {}
        skip = False
        for csv_col, model_col in cohort_columns.items():
            val = getattr(s, model_col, None)
            if val is None or val == "":
                skip = True
                break
            row[csv_col] = str(val)
        if skip:
            continue
        for csv_col, static_val in static_values.items():
            row[csv_col] = static_val
        rows.append(row)
    return rows, csv_columns


@app.post("/api/workflows/{name}/prepare")
def prepare_workflow(
    name: str,
    body: dict,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    try:
        bindings = body.get("bindings") or {}
        inputs = _fetch_wdl_inputs(name)

        model = _get_model()
        filters = _extract_filter_params(request)
        stmt = select(model)
        stmt = _apply_filters(stmt, filters)
        samples = db.execute(stmt).scalars().all()

        rows, csv_columns = _build_workflow_rows(samples, inputs, bindings)
        return {
            "sample_count": len(samples),
            "row_count": len(rows),
            "skipped": len(samples) - len(rows),
            "csv_columns": csv_columns,
            "preview": rows[:5],
        }
    except Exception as e:
        logger.error("prepare_workflow failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


def _run_workflow_in_background(
    job_id: str, workflow_id: str, rows: list[dict], csv_columns: list[str],
    csv_filename: str, mapping_filename: str, timestamp: str,
    input_bucket_id: str, output_bucket_id: str, output_path: str,
    full_name_by_short: dict[str, str],
):
    local_csv = None
    local_mapping = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            writer = csv.DictWriter(f, fieldnames=csv_columns)
            writer.writeheader()
            writer.writerows(rows)
            local_csv = f.name

        mapping = {full_name_by_short[c]: c for c in csv_columns}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(mapping, f)
            local_mapping = f.name

        bucket_path = subprocess.run(
            ["wb", "resource", "resolve", "--id", input_bucket_id],
            capture_output=True, text=True, check=True,
        ).stdout.strip().rstrip("/")

        for src, dst in [(local_csv, csv_filename), (local_mapping, mapping_filename)]:
            subprocess.run(
                ["aws", "s3", "cp", "--profile", input_bucket_id,
                 src, f"{bucket_path}/{dst}"],
                capture_output=True, text=True, check=True,
            )

        mapping_uri = f"{bucket_path}/{mapping_filename}"
        cmd = [
            "wb", "workflow", "job", "run",
            f"--workflow={workflow_id}",
            f"--batch-input-bucket-id={input_bucket_id}",
            f"--batch-input-csv-path={csv_filename}",
            f"--column-mapping-uri={mapping_uri}",
            f"--output-bucket-id={output_bucket_id}",
            f"--output-path={output_path}",
            f"--job-id={job_id}",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)

        _workflow_jobs[job_id] = {"status": "submitted", "output": result.stdout.strip()}
        logger.info("Workflow job %s submitted successfully", job_id)

    except subprocess.CalledProcessError as e:
        _workflow_jobs[job_id] = {"status": "failed", "error": e.stderr or e.stdout}
        logger.error("Workflow job %s failed: %s", job_id, e.stderr or e.stdout)
    except Exception as e:
        _workflow_jobs[job_id] = {"status": "failed", "error": str(e)}
        logger.error("Workflow job %s error: %s", job_id, e)
    finally:
        for p in (local_csv, local_mapping):
            if p:
                Path(p).unlink(missing_ok=True)


@app.post("/api/workflows/{name}/submit")
def submit_workflow(
    name: str,
    body: dict,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    try:
        bindings = body.get("bindings") or {}
        input_bucket_id = body.get("input_bucket_id")
        output_bucket_id = body.get("output_bucket_id")
        if not input_bucket_id or not output_bucket_id:
            raise HTTPException(status_code=400, detail="input_bucket_id and output_bucket_id are required")

        inputs = _fetch_wdl_inputs(name)
        full_name_by_short = {inp["short_name"]: inp["name"] for inp in inputs}

        missing_required = [
            inp["short_name"] for inp in inputs
            if inp.get("isRequired") and not (bindings.get(inp["short_name"]) or {}).get("value")
        ]
        if missing_required:
            raise HTTPException(
                status_code=400,
                detail=f"Missing bindings for required inputs: {', '.join(missing_required)}",
            )

        model = _get_model()
        filters = _extract_filter_params(request)
        stmt = select(model)
        stmt = _apply_filters(stmt, filters)
        samples = db.execute(stmt).scalars().all()

        rows, csv_columns = _build_workflow_rows(samples, inputs, bindings)
        if not rows:
            raise HTTPException(status_code=400, detail="No rows to submit — check that bound cohort columns have values")

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        job_id = f"cohort-{name}-{timestamp}"
        csv_filename = f"workflow_inputs/batch_{timestamp}.csv"
        mapping_filename = f"workflow_inputs/mapping_{timestamp}.json"
        output_path = body.get("output_path", f"workflow_outputs/{name}/{timestamp}")

        _workflow_jobs[job_id] = {"status": "submitting"}

        thread = threading.Thread(
            target=_run_workflow_in_background,
            args=(job_id, name, rows, csv_columns, csv_filename, mapping_filename, timestamp,
                  input_bucket_id, output_bucket_id, output_path, full_name_by_short),
            daemon=True,
        )
        thread.start()

        return {
            "job_id": job_id,
            "rows_submitted": len(rows),
            "status": "submitting",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("submit_workflow failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/workflows/jobs/{job_id}")
def workflow_job_status(job_id: str) -> dict:
    if job_id not in _workflow_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job_id": job_id, **_workflow_jobs[job_id]}


if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str) -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")
