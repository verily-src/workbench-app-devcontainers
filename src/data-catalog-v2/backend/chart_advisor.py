"""
LLM suggests chart dimensions from C2a (+ optional C2b) profile JSON.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from verily_profiler.llm import call_gemini, extract_json_from_response

CHART_SYSTEM_PROMPT = """\
You are a data visualization advisor. Given a BigQuery table technical profile (and optional semantic hints),
suggest 3 to 6 charts that would help a data steward understand the table.

Return ONLY a JSON array of objects. Each object must have:
- "chart_type": one of "bar", "pie", "histogram", "scatter", "composed"
- "columns": array of column names from the profile (use exact "name" field from columns)
- "title": short title for the chart
- "rationale": one sentence why this chart is interesting

Rules:
- Prefer bar or pie for low-cardinality string columns with top_values / value_counts.
- Prefer histogram or bar for null_percent across columns (use synthetic label "__null_rate__" only if you suggest a single composed chart — otherwise pick real columns).
- Use only column names that exist in the input.
- If semantic profile includes sensitivity, you may suggest one chart grouping PHI vs PII counts per column (still list real column names in "columns").
"""


def _summarize_profiles(technical: dict[str, Any], semantic: Optional[dict[str, Any]]) -> str:
    lines = [
        f"Table: {technical.get('table')}",
        f"Row count: {technical.get('row_count')}",
        "",
        "Columns (technical):",
    ]
    for c in technical.get("columns", [])[:80]:
        parts = [
            c.get("name"),
            c.get("data_type"),
            f"null%={c.get('null_percent')}",
            f"distinct={c.get('distinct_count')}",
        ]
        if c.get("top_values"):
            parts.append(f"top={c.get('top_values')[:5]}")
        if c.get("pattern"):
            parts.append(f"pattern={c.get('pattern')}")
        lines.append(" | ".join(str(p) for p in parts))
    if semantic and semantic.get("columns"):
        lines.append("")
        lines.append("Columns (semantic):")
        for c in semantic.get("columns", [])[:80]:
            lines.append(
                f"{c.get('name')}: sens={c.get('sensitivity')} conf={c.get('confidence')} "
                f"def={str(c.get('definition', ''))[:120]}"
            )
    return "\n".join(lines)


def suggest_charts(
    technical: dict[str, Any],
    semantic: Optional[dict[str, Any]],
    model_name: str,
    project_id: Optional[str],
) -> list[dict[str, Any]]:
    user_msg = _summarize_profiles(technical, semantic)
    text = call_gemini(
        system_prompt=CHART_SYSTEM_PROMPT,
        user_message=user_msg,
        model_name=model_name,
        project_id=project_id,
        temperature=0.2,
        max_output_tokens=8192,
    )
    parsed = extract_json_from_response(text)
    if isinstance(parsed, list):
        return [x for x in parsed if isinstance(x, dict)]
    if isinstance(parsed, dict) and "charts" in parsed:
        return [x for x in parsed["charts"] if isinstance(x, dict)]
    # Fallback: single heuristic charts from technical only
    return _fallback_charts(technical)


def _fallback_charts(technical: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cols = technical.get("columns") or []
    nulls = [(c.get("name"), float(c.get("null_percent") or 0)) for c in cols if c.get("name")]
    nulls.sort(key=lambda x: -x[1])
    if nulls[:8]:
        out.append(
            {
                "chart_type": "bar",
                "columns": [n for n, _ in nulls[:8]],
                "title": "Null % by column",
                "rationale": "Shows which columns are sparse or empty.",
            }
        )
    for c in cols:
        name = c.get("name")
        tv = c.get("top_values") or []
        if name and len(tv) >= 2:
            out.append(
                {
                    "chart_type": "bar",
                    "columns": [name],
                    "title": f"Top values: {name}",
                    "rationale": "Distribution of frequent categorical values.",
                }
            )
        if len(out) >= 4:
            break
    return out[:6]


def suggest_charts_json_response(
    technical: dict[str, Any],
    semantic: Optional[dict[str, Any]],
    model_name: str,
    project_id: Optional[str],
) -> str:
    charts = suggest_charts(technical, semantic, model_name, project_id)
    return json.dumps({"charts": charts}, indent=2)
