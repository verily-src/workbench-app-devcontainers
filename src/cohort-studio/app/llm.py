"""LLM features: natural-language cohort filtering via the Anthropic API.

The configured Claude model translates a question like "liver samples
with RIN above 7" into this app's filter JSON, validated against the
dataset's column profile. Uses the official Anthropic SDK with
structured outputs (messages.parse + Pydantic), so the response is
schema-valid by construction.
"""

import logging

from pydantic import BaseModel, Field

import config

logger = logging.getLogger(__name__)


class SuggestedFilter(BaseModel):
    column: str
    kind: str = Field(description="'categorical' or 'range'")
    values: list[str] | None = None
    min: float | None = None
    max: float | None = None


class FilterSuggestion(BaseModel):
    filters: list[SuggestedFilter]
    explanation: str = Field(
        description="One sentence describing the applied interpretation")


class LLMNotConfigured(RuntimeError):
    pass


def _client():
    import anthropic
    cfg = config.get_llm_config()
    if not cfg["api_key"]:
        raise LLMNotConfigured(
            "No Anthropic API key configured — add one in Settings.")
    return anthropic.Anthropic(api_key=cfg["api_key"]), cfg["model"]


def test_connection() -> dict:
    """Cheap round trip that validates the key and model."""
    client, model = _client()
    info = client.models.retrieve(model)
    return {"ok": True, "model": info.id, "display_name": info.display_name}


def suggest_filters(question: str, columns: list[dict],
                    current_filters: list[dict]) -> dict:
    client, model = _client()

    column_lines = []
    for col in columns:
        if col["filter_kind"] == "categorical":
            column_lines.append(
                f"- {col['name']} (categorical; values: "
                f"{', '.join(col.get('values') or [])})")
        elif col["filter_kind"] == "range":
            column_lines.append(
                f"- {col['name']} (numeric; min={col.get('min')}, "
                f"max={col.get('max')})")

    system = (
        "You translate a question about a tabular cohort into filters.\n"
        "Rules: only use the filterable columns listed; categorical filter "
        "values must come from the listed values (match case exactly); "
        "range filters use min/max within the listed bounds (use the "
        "column's own min or max for one-sided conditions). Interpret the "
        "question against the current filters: refinements add to them, "
        "replacements ('instead', 'actually') change them, 'clear'/'reset' "
        "removes them. Return the COMPLETE new filter set, not a delta."
    )
    prompt = (
        f"Filterable columns:\n{chr(10).join(column_lines)}\n\n"
        f"Current filters: {current_filters or 'none'}\n\n"
        f"Question: {question}"
    )

    response = client.messages.parse(
        model=model,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        output_format=FilterSuggestion,
    )
    if response.stop_reason == "refusal":
        return {"filters": current_filters,
                "explanation": "The model declined this request."}
    suggestion = response.parsed_output
    if suggestion is None:
        return {"filters": current_filters,
                "explanation": "Could not parse a filter suggestion."}

    # Server-side validation: drop anything that doesn't fit the profile.
    by_name = {c["name"]: c for c in columns}
    cleaned = []
    for f in suggestion.filters:
        col = by_name.get(f.column)
        if col is None or col["filter_kind"] not in ("categorical", "range"):
            continue
        if f.kind == "categorical" and col["filter_kind"] == "categorical":
            allowed = set(col.get("values") or [])
            values = [v for v in (f.values or []) if v in allowed]
            if values:
                cleaned.append({"column": f.column, "kind": "categorical",
                                "values": values})
        elif f.kind == "range" and col["filter_kind"] == "range":
            lo = col.get("min", float("-inf"))
            hi = col.get("max", float("inf"))
            fmin = max(f.min if f.min is not None else lo, lo)
            fmax = min(f.max if f.max is not None else hi, hi)
            if fmin <= fmax:
                cleaned.append({"column": f.column, "kind": "range",
                                "min": fmin, "max": fmax})
    return {"filters": cleaned, "explanation": suggestion.explanation}
