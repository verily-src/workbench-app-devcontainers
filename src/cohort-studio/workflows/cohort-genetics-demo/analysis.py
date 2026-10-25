from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

VARIANT_ID = "SYN_VAR_0021"
SYNTHETIC_NOTICE = (
    "Synthetic genotype values and annotations are for workflow demonstration "
    "only; no clinical or causal interpretation."
)
INPUT_COLUMNS = (
    "person_id", "sample_id", "variant_id", "dosage",
    "gender_concept_id", "year_of_birth",
)
DICTIONARY_COLUMNS = ("variant_id", "gene_symbol", "consequence", "synthetic_notice")
OUTPUT_COLUMNS = (
    "variant_id", "carrier_status", "gender_concept_id", "birth_year_band",
    "people", "share_within_status", "synthetic_notice",
)
NULL_VALUES = {"", "none", "null", "na", "nan"}


class InputRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_id: Annotated[int, Field(gt=0)]
    sample_id: Annotated[str, Field(min_length=1)]
    variant_id: Annotated[str, Field(min_length=1)]
    dosage: Annotated[float, Field(ge=0, le=2)]
    gender_concept_id: Annotated[int, Field(ge=0)] | None
    year_of_birth: int | None

    @field_validator("sample_id", "variant_id", mode="before")
    @classmethod
    def strip_required_text(cls, value):
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("gender_concept_id", "year_of_birth", mode="before")
    @classmethod
    def normalize_missing_integer(cls, value):
        if value is None or value == 0 or (
                isinstance(value, str) and value.strip().casefold() in NULL_VALUES):
            return None
        if isinstance(value, str) and value.strip() == "0":
            return None
        return value

    @field_validator("dosage")
    @classmethod
    def finite_dosage(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("dosage must be finite")
        return value

    @field_validator("year_of_birth")
    @classmethod
    def valid_birth_year(cls, value: int | None) -> int | None:
        if value is not None and not 1800 <= value <= 2100:
            raise ValueError("year_of_birth must be between 1800 and 2100")
        return value


class DictionaryRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variant_id: Annotated[str, Field(min_length=1)]
    gene_symbol: Annotated[str, Field(min_length=1)]
    consequence: Annotated[str, Field(min_length=1)]
    synthetic_notice: Annotated[str, Field(min_length=1)]

    @field_validator(*DICTIONARY_COLUMNS, mode="before")
    @classmethod
    def strip_dictionary_text(cls, value):
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("synthetic_notice")
    @classmethod
    def synthetic_label(cls, value: str) -> str:
        if value != SYNTHETIC_NOTICE:
            raise ValueError("synthetic_notice must match the demo notice")
        return value

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _gender(value: int | None) -> str:
    return "unknown" if value is None else str(value)


def _birth_band(value: int | None) -> str:
    return "unknown" if value is None else f"{value // 10 * 10}s"


def _read_and_summarize(path: Path, variant_id: str):
    people: set[int] = set()
    samples: set[str] = set()
    counts: Counter[tuple[str, str, str]] = Counter()
    status_counts: Counter[str] = Counter()
    row_count = 0
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != INPUT_COLUMNS:
            raise ValueError("Input header must contain exactly: " + ", ".join(INPUT_COLUMNS))
        for line_number, raw in enumerate(reader, start=2):
            try:
                row = InputRow.model_validate(raw)
            except Exception as exc:
                raise ValueError(f"Invalid input row at line {line_number}: {exc}") from exc
            if row.variant_id != variant_id:
                raise ValueError(
                    f"Input row at line {line_number} has variant {row.variant_id!r}; "
                    f"expected {variant_id!r}.")
            if row.person_id in people:
                raise ValueError(f"Duplicate person_id at line {line_number}: {row.person_id}")
            if row.sample_id in samples:
                raise ValueError(f"Duplicate sample_id at line {line_number}: {row.sample_id}")
            people.add(row.person_id)
            samples.add(row.sample_id)
            status = "carrier" if row.dosage > 0 else "noncarrier"
            status_counts[status] += 1
            counts[(status, _gender(row.gender_concept_id),
                    _birth_band(row.year_of_birth))] += 1
            row_count += 1
    return row_count, people, status_counts, counts


def _validate_dictionary(path: Path, variant_id: str) -> int:
    seen: set[str] = set()
    row_count = 0
    contains_variant = False
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != DICTIONARY_COLUMNS:
            raise ValueError("Variant dictionary header must contain exactly: " +
                             ", ".join(DICTIONARY_COLUMNS))
        for line_number, raw in enumerate(reader, start=2):
            try:
                row = DictionaryRow.model_validate(raw)
            except Exception as exc:
                raise ValueError(
                    f"Invalid variant dictionary row at line {line_number}: {exc}") from exc
            if row.variant_id in seen:
                raise ValueError(
                    f"Duplicate variant_id in dictionary at line {line_number}: "
                    f"{row.variant_id}")
            seen.add(row.variant_id)
            contains_variant |= row.variant_id == variant_id
            row_count += 1
    if not contains_variant:
        raise ValueError(f"Variant dictionary does not contain {variant_id!r}.")
    return row_count


def _sort_group(value: str):
    number = value.removesuffix("s")
    return (value == "unknown", int(number) if number.isdigit() else 0)


def analyze(
    input_path: Path,
    output_dir: Path,
    *,
    variant_dictionary_path: Path | None = None,
    variant_id: str = VARIANT_ID,
    cohort_size: int | None = None,
    input_uri: str | None = None,
    dictionary_uri: str | None = None,
    output_uri_prefix: str | None = None,
    source_resource: str | None = None,
    source_tables: list[str] | None = None,
    workflow_id: str | None = None,
    run_id: str | None = None,
) -> dict:
    input_path = input_path.expanduser().resolve()
    variant_dictionary_path = (
        variant_dictionary_path or Path(__file__).with_name("variant_dictionary.csv")
    ).expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if not input_path.is_file():
        raise ValueError(f"Input CSV does not exist: {input_path}")
    if not variant_dictionary_path.is_file():
        raise ValueError(f"Variant dictionary does not exist: {variant_dictionary_path}")
    if not variant_id.strip():
        raise ValueError("variant_id must not be empty")
    if cohort_size is not None and cohort_size < 0:
        raise ValueError("cohort_size must be zero or greater")

    row_count, people, status_counts, grouped = _read_and_summarize(input_path, variant_id)
    dictionary_rows = _validate_dictionary(variant_dictionary_path, variant_id)
    matched = len(people)
    if cohort_size is not None and matched > cohort_size:
        raise ValueError("Matched people cannot exceed cohort_size")

    summary_path = output_dir / "carrier_summary.csv"
    manifest_path = output_dir / "run_manifest.json"
    dictionary_output = output_dir / "variant_dictionary.csv"
    if summary_path.exists() or manifest_path.exists() or dictionary_output.exists():
        raise ValueError("Output files already exist; choose a new output directory.")

    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = output_uri_prefix.rstrip("/") if output_uri_prefix else str(output_dir)
    summary_uri = f"{prefix}/carrier_summary.csv"
    dictionary_output_uri = f"{prefix}/variant_dictionary.csv"
    manifest_uri = f"{prefix}/run_manifest.json"
    strata = []
    for status, gender, birth_band in sorted(
            grouped, key=lambda item: (item[0] != "carrier",
                                      _sort_group(item[1]),
                                      _sort_group(item[2]))):
        total = status_counts[status]
        strata.append({
            "variant_id": variant_id,
            "carrier_status": status,
            "gender_concept_id": gender,
            "birth_year_band": birth_band,
            "people": grouped[(status, gender, birth_band)],
            "share_within_status": grouped[(status, gender, birth_band)] / total,
            "synthetic_notice": SYNTHETIC_NOTICE,
        })

    with summary_path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(strata)
    shutil.copyfile(variant_dictionary_path, dictionary_output)

    manifest = {
        "input": {
            "uri": input_uri or str(input_path),
            "sha256": _sha256(input_path),
            "row_count": row_count,
        },
        "variant_dictionary": {
            "uri": dictionary_uri or str(variant_dictionary_path),
            "sha256": _sha256(variant_dictionary_path),
            "row_count": dictionary_rows,
            "key": "variant_id",
            "annotations_used_for_carrier_status": False,
        },
        "cohort": {
            "cohort_size": cohort_size,
            "matched_people": matched,
            "unmatched_cohort_members": (
                cohort_size - matched if cohort_size is not None else None),
        },
        "source": {
            "resource": source_resource,
            "tables": source_tables or [],
        },
        "analysis": {
            "variant_id": variant_id,
            "carrier_definition": "dosage > 0",
            "noncarrier_definition": "dosage = 0",
            "grouping": ["carrier_status", "gender_concept_id", "birth_year_band"],
            "birth_year_band": "decade containing year_of_birth; missing values are unknown",
            "share_within_status": "stratum people / matched people for that status",
            "status_counts": {
                "carrier": status_counts["carrier"],
                "noncarrier": status_counts["noncarrier"],
            },
            "summary_people_total": sum(row["people"] for row in strata),
        },
        "outputs": {
            "carrier_summary_csv": summary_uri,
            "variant_dictionary_csv": dictionary_output_uri,
            "manifest_json": manifest_uri,
        },
        "execution": {
            "workflow_id": workflow_id,
            "run_id": run_id,
            "time_utc": datetime.now(timezone.utc).isoformat(),
            "python_version": sys.version.split()[0],
            "command": sys.argv,
        },
        "synthetic_notice": SYNTHETIC_NOTICE,
    }
    with manifest_path.open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize one synthetic variant by carrier status.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--variant-dictionary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--variant-id", default=VARIANT_ID)
    parser.add_argument("--cohort-size", type=int)
    parser.add_argument("--input-uri")
    parser.add_argument("--variant-dictionary-uri")
    parser.add_argument("--output-uri-prefix")
    parser.add_argument("--source-resource")
    parser.add_argument("--source-table", action="append", dest="source_tables")
    parser.add_argument("--workflow-id")
    parser.add_argument("--run-id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        manifest = analyze(
            args.input, args.output_dir,
            variant_dictionary_path=args.variant_dictionary,
            variant_id=args.variant_id,
            cohort_size=args.cohort_size, input_uri=args.input_uri,
            dictionary_uri=args.variant_dictionary_uri,
            output_uri_prefix=args.output_uri_prefix,
            source_resource=args.source_resource, source_tables=args.source_tables,
            workflow_id=args.workflow_id, run_id=args.run_id)
    except (OSError, ValueError) as exc:
        print(f"analysis failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"carrier_summary_csv": manifest["outputs"]["carrier_summary_csv"],
                      "variant_dictionary_csv": manifest["outputs"]["variant_dictionary_csv"],
                      "run_manifest_json": manifest["outputs"]["manifest_json"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
