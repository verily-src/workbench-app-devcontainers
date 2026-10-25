from pathlib import Path


_GUIDE = Path(__file__).with_name("AGENT_GUIDE.md").read_text(encoding="utf-8")


def _tool_details(schemas: list[dict] | None) -> list[tuple[str, str]]:
    details = []
    for schema in schemas or []:
        spec = schema.get("function") or schema.get("toolSpec") or {}
        name = spec.get("name")
        if name:
            details.append((str(name), str(spec.get("description") or "")))
    return details


def system_guidance(role: str, tool_schemas: list[dict] | None = None,
                    output_schema: dict | None = None) -> str:
    tools = _tool_details(tool_schemas)
    if tools:
        tool_list = "\n".join(
            f"- {name}: {description}".rstrip()
            for name, description in tools)
    else:
        tool_list = "None. Do not imply that an action or lookup was run."
    fields = (output_schema or {}).get("properties", {})
    field_list = ", ".join(fields) if fields else "not specified"
    return (
        f"You are an expert {role} assistant.\n\n"
        f"{_GUIDE}\n\n"
        "Available tools (use only these; names and descriptions are exact):\n"
        f"{tool_list}\n"
        f"Available structured response fields: {field_list}.\n\n"
        "Work with scientific care. State the population, unit, source, and "
        "data scope when they affect a result. Separate loaded or sampled "
        "rows from full-source results. Keep current filters and user-selected "
        "criteria in scope; do not silently broaden them. Preserve source and "
        "transformation provenance. Check identifiers, entity level, join "
        "cardinality, missingness, and duplicate risk before interpreting a "
        "combined dataset. For OMOP work, distinguish person-level cohorts "
        "from event-level records, use CDM metadata and grounded concept IDs, "
        "and make temporal criteria explicit. Never invent a join key, "
        "clinical fact, statistic, source, or tool result. Do not write or "
        "execute free-form SQL, change data, or perform an unrequested action. "
        "Report only completed actions supported by tool results; say when "
        "evidence or a required tool is unavailable. Keep the response concise."
    )
