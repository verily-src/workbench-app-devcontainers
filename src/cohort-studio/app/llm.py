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


_LABELS = {"anthropic": "Anthropic", "openai": "OpenAI", "gemini": "Gemini"}


def _cfg() -> dict:
    cfg = config.get_llm_config()
    label = _LABELS.get(cfg["provider"], cfg["provider"])
    if not cfg["api_key"]:
        raise LLMNotConfigured(
            f"No {label} API key configured — add one in Settings.")
    if not cfg["model"]:
        raise LLMNotConfigured(
            f"No {label} model set — enter a model name in Settings.")
    return cfg


def test_connection() -> dict:
    """Cheap round trip that validates the key and model."""
    cfg = _cfg()
    if cfg["provider"] == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=cfg["api_key"])
        info = client.models.retrieve(cfg["model"])
        return {"ok": True, "provider": "anthropic", "model": info.id,
                "display_name": info.display_name}
    # OpenAI-compatible providers: a 1-token completion proves key+model.
    from openai import OpenAI
    kwargs = {"api_key": cfg["api_key"]}
    if cfg["base_url"]:
        kwargs["base_url"] = cfg["base_url"]
    client = OpenAI(**kwargs)
    client.chat.completions.create(
        model=cfg["model"], max_tokens=1,
        messages=[{"role": "user", "content": "ping"}])
    return {"ok": True, "provider": cfg["provider"], "model": cfg["model"],
            "display_name": cfg["model"]}


def suggest_filters(question: str, columns: list[dict],
                    current_filters: list[dict]) -> dict:
    cfg = _cfg()

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

    if cfg["provider"] == "anthropic":
        suggestion = _anthropic_suggestion(cfg, system, prompt)
    else:
        suggestion = _openai_suggestion(cfg, system, prompt)
    if suggestion is None:
        return {"filters": current_filters,
                "explanation": "Could not parse a filter suggestion."}
    cleaned = validate_filters(
        [f.model_dump() for f in suggestion.filters], columns)
    return {"filters": cleaned, "explanation": suggestion.explanation}


def _anthropic_suggestion(cfg: dict, system: str,
                          prompt: str) -> "FilterSuggestion | None":
    import anthropic
    client = anthropic.Anthropic(api_key=cfg["api_key"])
    response = client.messages.parse(
        model=cfg["model"], max_tokens=4096, system=system,
        messages=[{"role": "user", "content": prompt}],
        output_format=FilterSuggestion)
    if response.stop_reason == "refusal":
        return None
    return response.parsed_output


def _openai_suggestion(cfg: dict, system: str,
                       prompt: str) -> "FilterSuggestion | None":
    """OpenAI/Gemini structured output via JSON Schema response format."""
    from openai import OpenAI
    kwargs = {"api_key": cfg["api_key"]}
    if cfg["base_url"]:
        kwargs["base_url"] = cfg["base_url"]
    client = OpenAI(**kwargs)
    schema = FilterSuggestion.model_json_schema()
    resp = client.chat.completions.create(
        model=cfg["model"], max_tokens=4096,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": prompt}],
        response_format={"type": "json_schema", "json_schema": {
            "name": "filter_suggestion", "schema": schema}})
    content = resp.choices[0].message.content or ""
    try:
        return FilterSuggestion.model_validate_json(content)
    except Exception as e:
        logger.warning("Could not parse %s filter JSON: %s",
                       cfg["provider"], e)
        return None


def validate_filters(filters: list[dict], columns: list[dict]) -> list[dict]:
    """Drop or clamp model-suggested filters that don't fit the profile."""
    by_name = {c["name"]: c for c in columns}
    cleaned = []
    for f in filters:
        col = by_name.get(f.get("column"))
        if col is None or col["filter_kind"] not in ("categorical", "range"):
            continue
        if f.get("kind") == "categorical" \
                and col["filter_kind"] == "categorical":
            allowed = set(col.get("values") or [])
            values = [v for v in (f.get("values") or []) if v in allowed]
            if values:
                cleaned.append({"column": col["name"], "kind": "categorical",
                                "values": values})
        elif f.get("kind") == "range" and col["filter_kind"] == "range":
            lo = col.get("min", float("-inf"))
            hi = col.get("max", float("inf"))
            fmin = max(f["min"] if f.get("min") is not None else lo, lo)
            fmax = min(f["max"] if f.get("max") is not None else hi, hi)
            if fmin <= fmax:
                cleaned.append({"column": col["name"], "kind": "range",
                                "min": fmin, "max": fmax})
    return cleaned
