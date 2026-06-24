import csv
import logging
import subprocess
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Base, Sample

logger = logging.getLogger(__name__)

TSV_COLUMN_MAP = {
    "subjects.submitter_id": "subject_id",
    "gtex_sample_id": "gtex_sample_id",
    "specimen_id": "specimen_id",
    "dbgap_sample_id": "dbgap_sample_id",
    "submitter_id": "submitter_id",
    "SRR_id": "srr_id",
    "tissue_type": "tissue_type",
    "tissue_type_detail": "tissue_type_detail",
    "autolysis_score": "autolysis_score",
    "current_material_type": "current_material_type",
    "sample_collection_kit": "sample_collection_kit",
    "rin_number": "rin_number",
    "total_ischemic_time": "total_ischemic_time",
    "paxgene_time": "paxgene_time",
    "tissue_location": "tissue_location",
    "bss_collection_site": "bss_collection_site",
    "original_material_type": "original_material_type",
    "pathology_notes_prc": "pathology_notes",
    "prosector_comments": "prosector_comments",
    "fastq1_path": "fastq1_path",
    "fastq2_path": "fastq2_path",
}

SENTINEL_VALUES = {"n/a", "N/A", "NA", "na", ""}


def _clean_text(value: str) -> str | None:
    if value.strip() in SENTINEL_VALUES:
        return None
    return value.strip()


def _clean_float(value: str) -> float | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_date(value: str):
    from datetime import date, datetime
    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    try:
        return date.fromisoformat(cleaned[:10])
    except ValueError:
        pass
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def _clean_rin(value: str) -> float | None:
    f = _clean_float(value)
    if f is None:
        return None
    return round(f, 1)


def _parse_row(row: dict[str, str]) -> dict:
    result: dict = {}
    for tsv_col, model_col in TSV_COLUMN_MAP.items():
        raw = row.get(tsv_col, "")
        if model_col == "rin_number":
            result[model_col] = _clean_rin(raw)
        elif model_col in ("total_ischemic_time", "paxgene_time"):
            result[model_col] = _clean_float(raw)
        else:
            result[model_col] = _clean_text(raw)
    return result


def _resolve_path(tsv_path: str | Path) -> Path:
    path_str = str(tsv_path)
    if path_str.startswith("s3://"):
        logger.info("Downloading from S3: %s", path_str)
        local = Path(tempfile.gettempdir()) / Path(path_str).name
        subprocess.run(
            ["aws", "s3", "cp", path_str, str(local)],
            check=True,
            capture_output=True,
            text=True,
        )
        return local
    local = Path(path_str)
    if not local.exists():
        raise FileNotFoundError(f"TSV not found: {local}")
    return local


def seed_from_tsv(db: Session, tsv_path: str | Path) -> int:
    tsv_path = _resolve_path(tsv_path)

    existing = db.scalar(select(Sample.id).limit(1))
    if existing is not None:
        logger.info("Samples table already has data, skipping seed")
        return 0

    Base.metadata.create_all(db.get_bind())

    logger.info("Seeding from %s", tsv_path)
    batch: list[dict] = []
    count = 0
    batch_size = 1000

    with open(tsv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            parsed = _parse_row(row)
            if parsed.get("gtex_sample_id") is None:
                continue
            batch.append(parsed)
            if len(batch) >= batch_size:
                db.bulk_insert_mappings(Sample, batch)
                count += len(batch)
                batch.clear()

        if batch:
            db.bulk_insert_mappings(Sample, batch)
            count += len(batch)

    db.commit()
    logger.info("Seeded %d samples", count)
    return count


def seed_dynamic(db: Session, tsv_path: str | Path, model: type, mappings: list[dict]) -> int:
    tsv_path = _resolve_path(tsv_path)

    existing = db.scalar(select(model.id).limit(1))
    if existing is not None:
        logger.info("Table already has data, skipping seed")
        return 0

    col_types = {m["column"]: m["type"] for m in mappings}
    col_names = list(col_types.keys())

    path = Path(tsv_path)
    with open(path, newline="", encoding="utf-8") as f:
        sample = f.read(8192)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t")
        except csv.Error:
            dialect = None
    delimiter = dialect.delimiter if dialect else ("\t" if path.suffix.lower() != ".csv" else ",")

    logger.info("Seeding dynamic table from %s (%d columns)", tsv_path, len(col_names))
    batch: list[dict] = []
    count = 0
    batch_size = 1000

    with open(tsv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        for row in reader:
            parsed: dict = {}
            for col in col_names:
                raw = row.get(col, "").strip()
                if raw in SENTINEL_VALUES:
                    parsed[col] = None
                elif col_types[col] == "float":
                    parsed[col] = _clean_float(raw)
                elif col_types[col] == "integer":
                    v = _clean_float(raw)
                    parsed[col] = int(v) if v is not None else None
                elif col_types[col] == "boolean":
                    parsed[col] = raw.lower() in ("true", "yes", "1", "t", "y")
                elif col_types[col] == "date":
                    parsed[col] = _parse_date(raw)
                else:
                    parsed[col] = raw or None
            batch.append(parsed)
            if len(batch) >= batch_size:
                db.bulk_insert_mappings(model, batch)
                count += len(batch)
                batch.clear()

        if batch:
            db.bulk_insert_mappings(model, batch)
            count += len(batch)

    db.commit()
    logger.info("Seeded %d rows into dynamic table", count)
    return count
