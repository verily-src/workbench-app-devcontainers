"""
Post-profiling terminology reconciliation.

After profiling multiple tables/datasets, this module:
1. Loads all semantic profiles for a project
2. Compares terminology bindings across tables
3. Uses LLM to identify same-concept columns with different bindings
4. Unifies them under canonical codes and updates profiles + registry
"""

from __future__ import annotations

from typing import Any, Optional

from verily_profiler.llm import call_gemini, extract_json_from_response
from verily_profiler.models import (
    STANDARD_SYSTEMS,
    TermEntry,
    TerminologyRegistry,
    _slugify,
)


_RECONCILE_SYSTEM_PROMPT = """\
You are a terminology alignment specialist. You receive a list of column
terminology bindings from multiple BigQuery tables and identify columns that
represent the SAME concept but were assigned DIFFERENT codes.

Your job is to produce a RECONCILIATION PLAN that unifies duplicate concepts
under a single canonical code.

RULES:
1. Two bindings represent the same concept if they describe the same real-world
   data element — even if the column names, display texts, or codes differ.
   Example: "glucose_level" (custom) and "blood_glucose_measurement" (custom)
   are the same concept and should be unified.

2. When choosing the canonical code:
   - Prefer STANDARD terminology (LOINC, SNOMED, ICD-10, etc.) over custom.
   - If both are custom, pick the more descriptive display name.
   - If both are standard, pick the more specific code.

3. Do NOT merge bindings that are genuinely different concepts.
   Example: "hemoglobin_a1c" and "hemoglobin_serum" are DIFFERENT concepts.

4. Group related concepts that should share a code. Each group is a
   reconciliation action.

Return a JSON object:
{
  "groups": [
    {
      "canonical": {
        "system": "<system URI>",
        "code": "<code>",
        "display": "<display name>"
      },
      "members": [
        {"system": "<old system>", "code": "<old code>", "display": "<old display>",
         "source_columns": ["proj.ds.table.col", ...]}
      ],
      "rationale": "Brief explanation of why these are the same concept"
    }
  ]
}

If no duplicates are found, return: {"groups": []}
Return ONLY JSON.
"""


def reconcile(
    registry: TerminologyRegistry,
    model: str = "gemini-2.5-flash",
    project_id: Optional[str] = None,
) -> list[ReconcileGroup]:
    """
    Analyze a terminology registry for duplicate concepts and propose unifications.

    Returns a list of ReconcileGroup objects describing proposed merges.
    """
    if len(registry.entries) < 2:
        return []

    user_msg = _build_reconcile_prompt(registry)

    try:
        response = call_gemini(
            system_prompt=_RECONCILE_SYSTEM_PROMPT,
            user_message=user_msg,
            model_name=model,
            project_id=project_id,
            temperature=0.0,
        )
        raw = extract_json_from_response(response)
    except Exception as e:
        print(f"Reconciliation LLM call failed: {e}")
        return []

    return _parse_reconcile_output(raw, registry)


def apply_reconciliation(
    registry: TerminologyRegistry,
    groups: list[ReconcileGroup],
    sem_profiles: Optional[dict[str, dict]] = None,
) -> tuple[TerminologyRegistry, dict[str, dict]]:
    """
    Apply reconciliation groups to the registry and optionally update
    semantic profiles in-place.

    Args:
        registry: The terminology registry to update.
        groups: Reconciliation groups from reconcile().
        sem_profiles: Optional dict of fq_table -> semantic profile dicts.
                      If provided, terminology_bindings in these profiles
                      are updated to use the canonical codes.

    Returns:
        Tuple of (updated registry, updated sem_profiles).
    """
    updated_profiles = dict(sem_profiles) if sem_profiles else {}

    for group in groups:
        canonical = group.canonical
        merged_sources: list[str] = []

        old_codes: list[tuple[str, str]] = []
        for member in group.members:
            old_codes.append((member["system"], member["code"]))
            merged_sources.extend(member.get("source_columns", []))

        existing = registry.find_by_concept(canonical.concept_key)
        if existing:
            existing.system = canonical.system
            existing.code = canonical.code
            existing.display = canonical.display
            for sc in merged_sources:
                if sc not in existing.source_columns:
                    existing.source_columns.append(sc)
        else:
            canonical.source_columns = list(set(merged_sources))
            registry.upsert(canonical)

        remove_keys = set()
        for old_sys, old_code in old_codes:
            if old_sys == canonical.system and old_code == canonical.code:
                continue
            for entry in registry.entries:
                if entry.system == old_sys and entry.code == old_code:
                    remove_keys.add(entry.concept_key)
        registry.entries = [
            e for e in registry.entries
            if e.concept_key not in remove_keys
        ]

        if updated_profiles:
            _update_profiles_for_group(updated_profiles, old_codes, canonical)

    return registry, updated_profiles


class ReconcileGroup:
    """A group of terminology entries that should be unified."""

    def __init__(
        self,
        canonical: TermEntry,
        members: list[dict[str, Any]],
        rationale: str = "",
    ):
        self.canonical = canonical
        self.members = members
        self.rationale = rationale

    def __repr__(self):
        return (
            f"ReconcileGroup(canonical={self.canonical.display!r}, "
            f"members={len(self.members)}, rationale={self.rationale!r})"
        )


def _build_reconcile_prompt(registry: TerminologyRegistry) -> str:
    lines = [f"Total entries: {len(registry.entries)}", ""]
    for i, e in enumerate(registry.entries):
        sources = ", ".join(e.source_columns[:5])
        if len(e.source_columns) > 5:
            sources += f" (+{len(e.source_columns) - 5} more)"
        lines.append(
            f"{i+1}. [{e.system}] code={e.code} display=\"{e.display}\" "
            f"sources=[{sources}]"
        )
    return "\n".join(lines)


def _parse_reconcile_output(
    raw: Any,
    registry: TerminologyRegistry,
) -> list[ReconcileGroup]:
    if not isinstance(raw, dict):
        return []
    groups_raw = raw.get("groups", [])
    if not isinstance(groups_raw, list):
        return []

    result: list[ReconcileGroup] = []
    for g in groups_raw:
        if not isinstance(g, dict):
            continue
        canon_raw = g.get("canonical", {})
        if not isinstance(canon_raw, dict) or not canon_raw.get("code"):
            continue

        canonical = TermEntry(
            system=canon_raw.get("system", STANDARD_SYSTEMS["custom"]),
            code=canon_raw.get("code", ""),
            display=canon_raw.get("display", ""),
        )

        members = g.get("members", [])
        if not isinstance(members, list) or len(members) < 1:
            continue

        rationale = str(g.get("rationale", ""))
        result.append(ReconcileGroup(canonical=canonical, members=members, rationale=rationale))

    return result


def _update_profiles_for_group(
    profiles: dict[str, dict],
    old_codes: list[tuple[str, str]],
    canonical: TermEntry,
):
    """Update terminology bindings in semantic profile dicts."""
    old_set = set(old_codes)
    for fq_table, prof in profiles.items():
        columns = prof.get("columns", [])
        for col in columns:
            bindings = col.get("terminology_bindings", [])
            for binding in bindings:
                key = (binding.get("system", ""), binding.get("code", ""))
                if key in old_set:
                    binding["system"] = canonical.system
                    binding["code"] = canonical.code
                    binding["display"] = canonical.display
