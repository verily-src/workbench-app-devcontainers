"""
verily-profiler data models.

  - BQ schema models (BQColumnInfo, BQTableInfo)
  - Technical profiling models (TechColumnProfile, TechTableProfile)
  - Semantic profiling models (SemanticColumnProfile, SemanticTableProfile,
    PrimaryKeyInfo, SemanticDomain)
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


# ── Technical Profiling Models ────────────────────────────────────────────────

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
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    avg_length: Optional[float] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    median: Optional[float] = None
    stddev: Optional[float] = None
    detected_pattern: Optional[str] = None
    anomalies: list[str] = field(default_factory=list)

    def to_json_dict(self) -> dict:
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
    status: str = "pass"
    anomalies: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class TechTableProfile:
    """Complete technical profile for one table."""
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


# ── Semantic Profiling Models (v2) ────────────────────────────────────────────

@dataclass
class TerminologyBinding:
    """A suggested terminology binding for a column."""
    system: str
    code: str
    display: str

    def to_json_dict(self) -> dict:
        return {"system": self.system, "code": self.code, "display": self.display}


@dataclass
class PrimaryKeyInfo:
    """Identified primary key for a table."""
    columns: list[str] = field(default_factory=list)
    pk_type: str = ""       # "single", "composite", "none"
    confidence: str = "low"  # "high", "medium", "low"

    def to_json_dict(self) -> dict:
        return {
            "columns": self.columns,
            "pk_type": self.pk_type,
            "confidence": self.confidence,
        }


@dataclass
class SemanticDomain:
    """Two-tier domain classification for a table."""
    primary: str = ""      # from fixed taxonomy
    sub_domain: str = ""   # free-text from LLM

    def to_json_dict(self) -> dict:
        return {"primary": self.primary, "sub_domain": self.sub_domain}


@dataclass
class SemanticColumnProfile:
    """Semantic profiling output for a single column."""
    column_name: str
    definition: str = ""
    terminology_bindings: list[TerminologyBinding] = field(default_factory=list)
    sensitivity: str = ""
    join_paths: list[str] = field(default_factory=list)
    confidence: str = "medium"
    unit_of_measure: str = ""
    measurement_method: str = ""

    def to_json_dict(self) -> dict:
        return {
            "name": self.column_name,
            "definition": self.definition,
            "terminology_bindings": [tb.to_json_dict() for tb in self.terminology_bindings],
            "sensitivity": self.sensitivity,
            "join_paths": self.join_paths,
            "confidence": self.confidence,
            "unit_of_measure": self.unit_of_measure,
            "measurement_method": self.measurement_method,
        }

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
            "Unit": self.unit_of_measure,
            "Method": self.measurement_method,
        }


@dataclass
class SemanticValidationResult:
    """Result of semantic self-validation (LLM-as-Judge + cross-check)."""
    status: str = "pass"       # "pass", "warning", "fail"
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class SemanticTableProfile:
    """Complete semantic profile for one table (v2 output)."""
    table_name: str
    model_used: str = ""
    profiled_at: str = ""
    business_name: str = ""
    table_definition: str = ""
    primary_key: PrimaryKeyInfo = field(default_factory=PrimaryKeyInfo)
    granularity: str = ""
    semantic_domain: SemanticDomain = field(default_factory=SemanticDomain)
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
            "business_name": self.business_name,
            "table_definition": self.table_definition,
            "primary_key": self.primary_key.to_json_dict(),
            "granularity": self.granularity,
            "semantic_domain": self.semantic_domain.to_json_dict(),
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


# ── Terminology Registry ─────────────────────────────────────────────────────

STANDARD_SYSTEMS = {
    "loinc": "http://loinc.org",
    "snomed": "http://snomed.info/sct",
    "icd10": "http://hl7.org/fhir/sid/icd-10",
    "icd10cm": "http://hl7.org/fhir/sid/icd-10-cm",
    "ndc": "http://hl7.org/fhir/sid/ndc",
    "rxnorm": "http://www.nlm.nih.gov/research/umls/rxnorm",
    "cpt": "http://www.ama-assn.org/go/cpt",
    "hcpcs": "https://www.cms.gov/Medicare/Coding/HCPCSReleaseCodeSets",
    "custom": "urn:verily:custom",
}


@dataclass
class TermEntry:
    """A single entry in the terminology registry."""
    system: str                    # URI from STANDARD_SYSTEMS or "urn:verily:custom"
    code: str                      # standard code or custom slug
    display: str                   # human-readable display name
    concept_key: str = ""          # normalized key for dedup (lowercase slug of display)
    source_columns: list[str] = field(default_factory=list)  # ["proj.ds.table.col", ...]
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.concept_key:
            self.concept_key = _slugify(self.display)
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def to_json_dict(self) -> dict:
        return {
            "system": self.system,
            "code": self.code,
            "display": self.display,
            "concept_key": self.concept_key,
            "source_columns": self.source_columns,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TermEntry":
        return cls(
            system=d.get("system", ""),
            code=d.get("code", ""),
            display=d.get("display", ""),
            concept_key=d.get("concept_key", ""),
            source_columns=d.get("source_columns", []),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
        )


@dataclass
class TerminologyRegistry:
    """Project-level registry of all terminology bindings across datasets."""
    version: str = "1.0"
    entries: list[TermEntry] = field(default_factory=list)
    updated_at: str = ""

    def __post_init__(self):
        if not self.updated_at:
            self.updated_at = datetime.now(timezone.utc).isoformat()

    def find_by_concept(self, concept_key: str) -> Optional[TermEntry]:
        for e in self.entries:
            if e.concept_key == concept_key:
                return e
        return None

    def find_by_code(self, system: str, code: str) -> Optional[TermEntry]:
        for e in self.entries:
            if e.system == system and e.code == code:
                return e
        return None

    def upsert(self, entry: TermEntry) -> TermEntry:
        """Add or update an entry. Merges source_columns if concept_key matches."""
        existing = self.find_by_concept(entry.concept_key)
        if existing:
            for sc in entry.source_columns:
                if sc not in existing.source_columns:
                    existing.source_columns.append(sc)
            existing.updated_at = datetime.now(timezone.utc).isoformat()
            return existing
        self.entries.append(entry)
        self.updated_at = datetime.now(timezone.utc).isoformat()
        return entry

    def to_json_dict(self) -> dict:
        return {
            "version": self.version,
            "updated_at": self.updated_at,
            "entries": [e.to_json_dict() for e in self.entries],
        }

    def to_json_string(self) -> str:
        return json.dumps(self.to_json_dict(), indent=2)

    @classmethod
    def from_dict(cls, d: dict) -> "TerminologyRegistry":
        entries = [TermEntry.from_dict(e) for e in d.get("entries", [])]
        return cls(
            version=d.get("version", "1.0"),
            entries=entries,
            updated_at=d.get("updated_at", ""),
        )

    def format_for_prompt(self, max_entries: int = 200) -> str:
        """Format registry as context for LLM prompt injection."""
        if not self.entries:
            return ""
        lines = ["EXISTING TERMINOLOGY REGISTRY (reuse these when the concept matches):"]
        for e in self.entries[:max_entries]:
            sources = f" (used by {len(e.source_columns)} columns)" if e.source_columns else ""
            lines.append(f"  - [{e.system}] {e.code}: {e.display}{sources}")
        if len(self.entries) > max_entries:
            lines.append(f"  ... and {len(self.entries) - max_entries} more entries")
        return "\n".join(lines)


def _slugify(text: str) -> str:
    """Normalize text into a stable concept key."""
    import re
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9\s_-]", "", slug)
    slug = re.sub(r"[\s_-]+", "_", slug)
    return slug.strip("_")[:120]


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
