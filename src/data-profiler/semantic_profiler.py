"""
C2b Semantic Profiler — LLM-driven field definitions, terminology bindings,
PHI/PII classification, join paths, and confidence scoring.

Consumes TechTableProfile (C2a output) + optional context signals.
Includes self-validation via LLM-as-Judge and cross-check against C2a.
"""

from __future__ import annotations

import json
from typing import Optional

from models import (
    SemanticColumnProfile,
    SemanticTableProfile,
    SemanticValidationResult,
    TechTableProfile,
    TerminologyBinding,
)
from prompt_engine import call_gemini, extract_json_from_response


# ── System Prompts ────────────────────────────────────────────────────────────

_SEMANTIC_SYSTEM_PROMPT = """\
You are a data governance and metadata specialist. You analyze BigQuery table
schemas and technical profiling data to generate rich semantic metadata.

For each column you MUST return a JSON array of objects with these fields:
- "column_name": exact column name (must match input)
- "definition": plain-language description (2-3 sentences; what the column stores, how it's used)
- "terminology_bindings": array of objects with "system", "code", "display"
    - Use standard systems: http://loinc.org, http://hl7.org/fhir/sid/icd-10,
      http://snomed.info/sct, http://hl7.org/fhir/sid/ndc
    - Only include bindings when a clear clinical/admin concept applies
    - Return empty array [] if no standard terminology applies
- "sensitivity": one of "PHI", "PII", "UID", "" (empty if not sensitive)
    - PHI: Protected Health Information (diagnosis, lab values, medications, dates of service)
    - PII: Personally Identifiable Information (name, SSN, email, phone, address)
    - UID: Unique Identifier (patient ID, encounter ID, MRN — linkable to an individual)
    - "": not sensitive
- "join_paths": array of strings suggesting likely join columns in other tables
    - Format: "likely_table.likely_column" based on naming conventions
    - Return empty array [] if no obvious joins
- "confidence": "high", "medium", or "low"
    - high: definition is unambiguous from column name + type + stats
    - medium: reasonable guess based on context
    - low: speculative, user should review carefully

Return ONLY a JSON array (no markdown, no explanation outside the JSON).
"""

_JUDGE_SYSTEM_PROMPT = """\
You are a metadata quality reviewer. You check AI-generated semantic metadata
for plausibility and correctness.

For each column, assess:
1. Is the definition accurate and specific enough?
2. Are terminology bindings appropriate (correct system, code, display)?
3. Is the sensitivity classification correct?
4. Are join path suggestions reasonable?
5. Is the confidence rating appropriate?

Return a JSON object with:
- "status": "pass" or "fail"
- "issues": array of strings describing problems found (empty if all good)
"""


# ── Main Entry Point ──────────────────────────────────────────────────────────

def profile_table_semantic(
    tech_profile: TechTableProfile,
    model_name: str,
    project_id: Optional[str] = None,
    context_text: Optional[str] = None,
) -> SemanticTableProfile:
    """
    Generate semantic profiles for all columns in a table.

    Args:
        tech_profile: C2a output for the table.
        model_name: Gemini model to use.
        project_id: GCP project for Vertex AI billing.
        context_text: Optional context (data dictionary, schema.yml, etc.).

    Returns:
        SemanticTableProfile with per-column definitions, bindings, sensitivity, etc.
    """
    sem_profile = SemanticTableProfile(
        table_name=tech_profile.table_name,
        model_used=model_name,
    )

    user_msg = _build_profiling_prompt(tech_profile, context_text)

    try:
        response = call_gemini(
            system_prompt=_SEMANTIC_SYSTEM_PROMPT,
            user_message=user_msg,
            model_name=model_name,
            project_id=project_id,
            temperature=0.1,
        )
        raw = extract_json_from_response(response)
    except Exception as e:
        print(f"  Semantic profiling LLM call failed: {e}")
        for cp in tech_profile.columns:
            sem_profile.columns.append(SemanticColumnProfile(
                column_name=cp.column_name,
                definition=f"[LLM error: {e}]",
                confidence="low",
            ))
        sem_profile.validation = SemanticValidationResult(
            status="fail", issues=[f"LLM call failed: {e}"]
        )
        return sem_profile

    col_map = _parse_llm_output(raw, tech_profile)
    tech_col_names = {cp.column_name for cp in tech_profile.columns}

    for cp in tech_profile.columns:
        llm_data = col_map.get(cp.column_name, {})
        sem_col = _build_semantic_column(cp.column_name, llm_data)
        sem_profile.columns.append(sem_col)

    # Cross-check: flag any LLM column names that don't exist in C2a
    cross_issues = []
    for name in col_map:
        if name not in tech_col_names:
            cross_issues.append(f"LLM referenced non-existent column: {name}")

    # LLM-as-Judge validation
    judge_result = _run_judge_validation(sem_profile, tech_profile, model_name, project_id)
    all_issues = cross_issues + judge_result.issues
    sem_profile.validation = SemanticValidationResult(
        status="fail" if all_issues else "pass",
        issues=all_issues,
    )

    return sem_profile


def revalidate_semantic(
    sem_profile: SemanticTableProfile,
    tech_profile: TechTableProfile,
    model_name: str,
    project_id: Optional[str] = None,
) -> SemanticValidationResult:
    """Re-run LLM-as-Judge validation on an edited semantic profile."""
    return _run_judge_validation(sem_profile, tech_profile, model_name, project_id)


# ── Prompt Construction ───────────────────────────────────────────────────────

def _build_profiling_prompt(tech_profile: TechTableProfile, context_text: Optional[str]) -> str:
    """Build the user message for semantic profiling from C2a output."""
    lines = [
        f"Table: {tech_profile.table_name}",
        f"Row count: {tech_profile.row_count:,}",
        "",
        "Column details (from technical profiling):",
    ]

    for cp in tech_profile.columns:
        parts = [f"  - {cp.column_name} ({cp.data_type})"]
        parts.append(f"nulls={cp.null_percent}%")
        parts.append(f"distinct={cp.distinct_count}")
        if cp.top_values:
            preview = ", ".join(cp.top_values[:5])
            parts.append(f"top_values=[{preview}]")
        if cp.detected_pattern:
            parts.append(f"pattern={cp.detected_pattern}")
        if cp.min_value is not None:
            parts.append(f"range=[{cp.min_value}, {cp.max_value}]")
        if cp.min_length is not None:
            parts.append(f"strlen=[{cp.min_length}, {cp.max_length}]")
        if cp.anomalies:
            parts.append(f"anomalies={cp.anomalies}")
        lines.append(" | ".join(parts))

    if context_text:
        lines.append("")
        lines.append("Additional context (data dictionary / schema / protocol):")
        lines.append(context_text[:8000])

    return "\n".join(lines)


# ── LLM Output Parsing ───────────────────────────────────────────────────────

def _parse_llm_output(raw: Optional[dict | list], tech_profile: TechTableProfile) -> dict:
    """Parse LLM JSON response into a column_name -> dict mapping."""
    if raw is None:
        return {}

    items = raw if isinstance(raw, list) else [raw]
    col_map: dict[str, dict] = {}
    for item in items:
        if isinstance(item, dict) and "column_name" in item:
            col_map[item["column_name"]] = item
    return col_map


def _build_semantic_column(column_name: str, llm_data: dict) -> SemanticColumnProfile:
    """Build a SemanticColumnProfile from parsed LLM data."""
    bindings = []
    for tb in llm_data.get("terminology_bindings", []):
        if isinstance(tb, dict) and "system" in tb and "code" in tb:
            bindings.append(TerminologyBinding(
                system=tb["system"],
                code=str(tb["code"]),
                display=tb.get("display", ""),
            ))

    sensitivity = str(llm_data.get("sensitivity", "")).strip().upper()
    if sensitivity not in ("PHI", "PII", "UID"):
        sensitivity = ""

    confidence = str(llm_data.get("confidence", "medium")).strip().lower()
    if confidence not in ("high", "medium", "low"):
        confidence = "medium"

    join_paths = llm_data.get("join_paths", [])
    if not isinstance(join_paths, list):
        join_paths = []

    return SemanticColumnProfile(
        column_name=column_name,
        definition=str(llm_data.get("definition", "")).strip(),
        terminology_bindings=bindings,
        sensitivity=sensitivity,
        join_paths=[str(jp) for jp in join_paths],
        confidence=confidence,
    )


# ── LLM-as-Judge ─────────────────────────────────────────────────────────────

def _run_judge_validation(
    sem_profile: SemanticTableProfile,
    tech_profile: TechTableProfile,
    model_name: str,
    project_id: Optional[str] = None,
) -> SemanticValidationResult:
    """Run LLM-as-Judge to check plausibility of semantic metadata."""
    summary_lines = [f"Table: {sem_profile.table_name}", ""]
    for sc in sem_profile.columns:
        tc = tech_profile.get_column(sc.column_name)
        tc_info = ""
        if tc:
            tc_info = f" (type={tc.data_type}, nulls={tc.null_percent}%, distinct={tc.distinct_count})"
        bindings_str = ", ".join(f"{tb.system}|{tb.code}" for tb in sc.terminology_bindings)
        summary_lines.append(
            f"  {sc.column_name}{tc_info}: "
            f"def=\"{sc.definition}\" | sens={sc.sensitivity} | "
            f"bindings=[{bindings_str}] | conf={sc.confidence}"
        )

    user_msg = "\n".join(summary_lines)

    try:
        response = call_gemini(
            system_prompt=_JUDGE_SYSTEM_PROMPT,
            user_message=user_msg,
            model_name=model_name,
            project_id=project_id,
            temperature=0.0,
        )
        result = extract_json_from_response(response)
        if isinstance(result, dict):
            return SemanticValidationResult(
                status=result.get("status", "pass"),
                issues=result.get("issues", []),
            )
    except Exception as e:
        return SemanticValidationResult(status="pass", issues=[f"Judge call failed (non-blocking): {e}"])

    return SemanticValidationResult(status="pass", issues=[])
