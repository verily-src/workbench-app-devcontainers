"""
Shared data models for WB Data Profiler.

Contains all dataclasses used across modules:
  - BQ schema models (BQColumnInfo, BQTableInfo)
  - Technical profiling models (TechColumnProfile, TechTableProfile)
  - Semantic profiling models (SemanticColumnProfile, SemanticTableProfile)
  - Combined profile for export
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional


# ── BigQuery Schema Models ────────────────────────────────────────────────────

@dataclass
class BQColumnInfo:
    """Column information from BigQuery INFORMATION_SCHEMA."""
    column_name: str
    data_type: str
    is_nullable: str  # "YES" or "NO"
    description: Optional[str] = None
    ordinal_position: int = 0


@dataclass
class BQTableInfo:
    """Table information from BigQuery INFORMATION_SCHEMA."""
    project_id: str
    dataset_id: str
    table_id: str
    columns: list[BQColumnInfo] = field(default_factory=list)
    row_count: Optional[int] = None
    size_bytes: Optional[int] = None
    table_type: str = "BASE TABLE"

    @property
    def fq_name(self) -> str:
        return f"{self.project_id}.{self.dataset_id}.{self.table_id}"


# ── Technical Profiling Models (C2a) ─────────────────────────────────────────

@dataclass
class TechColumnProfile:
    """Technical profiling statistics for a single column."""
    column_name: str
    data_type: str
    nullable: bool = True
    null_count: int = 0
    null_percent: float = 0.0
    distinct_count: int = 0
    top_values: list[str] = field(default_factory=list)
    value_counts: Optional[dict[str, int]] = None
    # String stats
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    avg_length: Optional[float] = None
    # Numeric stats
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    median: Optional[float] = None
    stddev: Optional[float] = None
    # Pattern detection
    detected_pattern: Optional[str] = None  # UUID, EMAIL, URL, DATE, IP, etc.
    # Anomaly flags
    anomalies: list[str] = field(default_factory=list)

    def to_json_dict(self) -> dict:
        """Convert to the plain JSON output format."""
        d: dict = {
            "name": self.column_name,
            "data_type": self.data_type,
            "nullable": self.nullable,
            "null_count": self.null_count,
            "null_percent": self.null_percent,
            "distinct_count": self.distinct_count,
        }
        if self.top_values:
            d["top_values"] = self.top_values[:15]
        if self.value_counts:
            d["value_counts"] = dict(list(self.value_counts.items())[:15])
        if self.min_length is not None:
            d["string_stats"] = {
                "min_length": self.min_length,
                "max_length": self.max_length,
                "avg_length": self.avg_length,
            }
        if self.min_value is not None:
            d["numeric_stats"] = {
                "min": self.min_value,
                "max": self.max_value,
                "median": self.median,
                "stddev": self.stddev,
            }
        if self.detected_pattern:
            d["pattern"] = self.detected_pattern
        if self.anomalies:
            d["anomalies"] = self.anomalies
        return d

    def to_review_row(self) -> dict:
        """Convert to a flat dict for the Gradio review DataFrame."""
        stats = ""
        if self.min_value is not None:
            stats = f"min={self.min_value}, max={self.max_value}, med={self.median}"
        elif self.min_length is not None:
            stats = f"len {self.min_length}-{self.max_length} (avg {self.avg_length})"
        return {
            "Column": self.column_name,
            "Type": self.data_type,
            "Nullable": "Yes" if self.nullable else "No",
            "Nulls": f"{self.null_percent}%",
            "Distinct": self.distinct_count,
            "Top Values": ", ".join(self.top_values[:5]) if self.top_values else "",
            "Stats": stats,
            "Pattern": self.detected_pattern or "",
            "Anomalies": "; ".join(self.anomalies) if self.anomalies else "",
        }


@dataclass
class ValidationResult:
    """Result of a self-validation pass."""
    status: str = "pass"  # "pass" or "fail"
    anomalies: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class TechTableProfile:
    """Complete technical profile for one table (C2a output)."""
    table_name: str
    row_count: int = 0
    size_bytes: Optional[int] = None
    profiled_at: str = ""
    columns: list[TechColumnProfile] = field(default_factory=list)
    validation: ValidationResult = field(default_factory=ValidationResult)

    def __post_init__(self):
        if not self.profiled_at:
            self.profiled_at = datetime.now(timezone.utc).isoformat()

    def to_json_dict(self) -> dict:
        return {
            "table": self.table_name,
            "row_count": self.row_count,
            "size_bytes": self.size_bytes,
            "profiled_at": self.profiled_at,
            "validation": asdict(self.validation),
            "columns": [c.to_json_dict() for c in self.columns],
        }

    def to_json_string(self) -> str:
        return json.dumps(self.to_json_dict(), indent=2)

    def get_column(self, name: str) -> Optional[TechColumnProfile]:
        for c in self.columns:
            if c.column_name == name:
                return c
        return None


# ── Semantic Profiling Models (C2b) ──────────────────────────────────────────

@dataclass
class TerminologyBinding:
    """A suggested terminology binding for a column."""
    system: str      # e.g. "http://loinc.org", "http://hl7.org/fhir/sid/icd-10"
    code: str
    display: str

    def to_json_dict(self) -> dict:
        return {"system": self.system, "code": self.code, "display": self.display}


@dataclass
class SemanticColumnProfile:
    """Semantic profiling output for a single column."""
    column_name: str
    definition: str = ""
    terminology_bindings: list[TerminologyBinding] = field(default_factory=list)
    sensitivity: str = ""       # PHI, PII, UID, or empty
    join_paths: list[str] = field(default_factory=list)
    confidence: str = "medium"  # high, medium, low

    def to_json_dict(self) -> dict:
        d: dict = {
            "name": self.column_name,
            "definition": self.definition,
            "terminology_bindings": [tb.to_json_dict() for tb in self.terminology_bindings],
            "sensitivity": self.sensitivity,
            "join_paths": self.join_paths,
            "confidence": self.confidence,
        }
        return d

    def to_review_row(self) -> dict:
        bindings_str = "; ".join(
            f"{tb.system}|{tb.code} ({tb.display})" for tb in self.terminology_bindings
        ) if self.terminology_bindings else ""
        return {
            "Column": self.column_name,
            "Definition": self.definition,
            "Terminology Bindings": bindings_str,
            "Sensitivity": self.sensitivity,
            "Join Paths": ", ".join(self.join_paths) if self.join_paths else "",
            "Confidence": self.confidence,
        }


@dataclass
class SemanticValidationResult:
    """Result of semantic self-validation (LLM-as-Judge + cross-check)."""
    status: str = "pass"
    issues: list[str] = field(default_factory=list)


@dataclass
class SemanticTableProfile:
    """Complete semantic profile for one table (C2b output)."""
    table_name: str
    model_used: str = ""
    profiled_at: str = ""
    columns: list[SemanticColumnProfile] = field(default_factory=list)
    validation: SemanticValidationResult = field(default_factory=SemanticValidationResult)

    def __post_init__(self):
        if not self.profiled_at:
            self.profiled_at = datetime.now(timezone.utc).isoformat()

    def to_json_dict(self) -> dict:
        return {
            "table": self.table_name,
            "profiled_at": self.profiled_at,
            "model_used": self.model_used,
            "validation": asdict(self.validation),
            "columns": [c.to_json_dict() for c in self.columns],
        }

    def to_json_string(self) -> str:
        return json.dumps(self.to_json_dict(), indent=2)

    def get_column(self, name: str) -> Optional[SemanticColumnProfile]:
        for c in self.columns:
            if c.column_name == name:
                return c
        return None


# ── Combined Profile ─────────────────────────────────────────────────────────

@dataclass
class CombinedProfile:
    """Merges technical + semantic for a single table."""
    table_name: str
    tech: Optional[TechTableProfile] = None
    semantic: Optional[SemanticTableProfile] = None

    def to_json_dict(self) -> dict:
        d: dict = {"table": self.table_name}
        if self.tech:
            d["technical"] = self.tech.to_json_dict()
        if self.semantic:
            d["semantic"] = self.semantic.to_json_dict()
        return d

    def to_json_string(self) -> str:
        return json.dumps(self.to_json_dict(), indent=2)
