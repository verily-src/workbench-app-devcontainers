"""
verily-profiler — BigQuery table profiling: technical stats + LLM-driven semantic metadata.

Public API
----------
Discovery:
    discover_datasets(project_id, billing_project?) -> list[str]
    discover_tables(project_id, dataset_id, billing_project?) -> list[BQTableInfo]
    get_table_api_metadata(project_id, dataset_id, table_id, billing_project?, log_failures?) -> (rows, bytes)

Profiling:
    profile_technical(table_info, billing_project?) -> TechTableProfile
    profile_semantic(tech_profile, model, project_id?, context_text?) -> SemanticTableProfile

Storage (GCS):
    write_tech_profile(bucket, fq_table, profile, project_id?) -> str
    write_sem_profile(bucket, fq_table, profile, project_id?) -> str
    read_tech_profile(bucket, fq_table, project_id?) -> dict | None
    read_sem_profile(bucket, fq_table, project_id?) -> dict | None
    scan_profile_availability(bucket, data_project, billing_project?) -> dict

Models:
    BQTableInfo, BQColumnInfo
    TechTableProfile, TechColumnProfile
    SemanticTableProfile, SemanticColumnProfile
    PrimaryKeyInfo, SemanticDomain
"""

from verily_profiler.discovery import discover_datasets, discover_tables, get_table_api_metadata
from verily_profiler.technical import profile_technical
from verily_profiler.semantic import profile_semantic
from verily_profiler.storage import (
    write_tech_profile,
    write_sem_profile,
    read_tech_profile,
    read_sem_profile,
    read_registry,
    write_registry,
    scan_profile_availability,
)
from verily_profiler.models import (
    BQTableInfo,
    BQColumnInfo,
    TechTableProfile,
    TechColumnProfile,
    SemanticTableProfile,
    SemanticColumnProfile,
    PrimaryKeyInfo,
    SemanticDomain,
    CombinedProfile,
    ValidationResult,
    SemanticValidationResult,
    TerminologyBinding,
    TermEntry,
    TerminologyRegistry,
)
from verily_profiler.reconcile import reconcile, apply_reconciliation

__all__ = [
    "discover_datasets",
    "discover_tables",
    "get_table_api_metadata",
    "profile_technical",
    "profile_semantic",
    "write_tech_profile",
    "write_sem_profile",
    "read_tech_profile",
    "read_sem_profile",
    "read_registry",
    "write_registry",
    "scan_profile_availability",
    "reconcile",
    "apply_reconciliation",
    "BQTableInfo",
    "BQColumnInfo",
    "TechTableProfile",
    "TechColumnProfile",
    "SemanticTableProfile",
    "SemanticColumnProfile",
    "PrimaryKeyInfo",
    "SemanticDomain",
    "CombinedProfile",
    "ValidationResult",
    "SemanticValidationResult",
    "TerminologyBinding",
    "TermEntry",
    "TerminologyRegistry",
]
