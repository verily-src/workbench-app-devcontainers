import logging

from pydantic import BaseModel, Field

import bedrock
import config
import vertexai_auth

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

_LABELS = {"anthropic": "Anthropic", "openai": "OpenAI",
           "gemini": "Gemini", "openrouter": "OpenRouter",
           "bedrock": "Amazon Bedrock", "vertexai": "Google Vertex AI"}

def validate_config(cfg: dict) -> dict:
    label = _LABELS.get(cfg["provider"], cfg["provider"])
    if cfg["provider"] == "bedrock":
        if not cfg["region"]:
            raise LLMNotConfigured(
                "AWS region is required for Amazon Bedrock; set AWS_REGION "
                "or AWS_DEFAULT_REGION.")
    elif cfg["provider"] == "vertexai":
        if not cfg.get("project"):
            raise LLMNotConfigured(
                "Google Cloud project is required for Vertex AI; set "
                "GOOGLE_CLOUD_PROJECT or VERTEXAI_PROJECT.")
        if not cfg.get("location"):
            raise LLMNotConfigured(
                "Vertex AI location is required; set GOOGLE_CLOUD_LOCATION "
                "or VERTEXAI_LOCATION.")
        try:
            vertexai_auth.endpoint(cfg["project"], cfg["location"])
        except ValueError as exc:
            raise LLMNotConfigured(str(exc)) from exc
    elif not cfg["api_key"]:
        raise LLMNotConfigured(
            f"No {label} API key configured — add one in Settings.")
    if not cfg["model"]:
        raise LLMNotConfigured(
            f"No {label} model set — enter a model name in Settings.")
    return cfg

def _cfg() -> dict:
    return validate_config(config.get_llm_config())

def _openai_client(cfg: dict):
    if cfg["provider"] == "vertexai":
        try:
            client, credentials, request = vertexai_auth.new_client(
                cfg["project"], cfg["location"])
            vertexai_auth.refresh_client(client, credentials, request)
            return client, credentials, request
        except vertexai_auth.VertexAuthUnavailable as exc:
            raise LLMNotConfigured(str(exc)) from exc
    from openai import OpenAI
    kwargs = {"api_key": cfg["api_key"]}
    if cfg["base_url"]:
        kwargs["base_url"] = cfg["base_url"]
    return OpenAI(**kwargs), None, None

def test_connection() -> dict:

    cfg = _cfg()
    if cfg["provider"] == "bedrock":
        return bedrock.test_connection(cfg["model"], cfg["region"])
    if cfg["provider"] == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=cfg["api_key"])
        info = client.models.retrieve(cfg["model"])
        return {"ok": True, "provider": "anthropic", "model": info.id,
                "display_name": info.display_name}

    client, _, _ = _openai_client(cfg)
    try:
        client.chat.completions.create(
            model=cfg["model"],
            messages=[{"role": "user", "content": "ping"}])
    finally:
        client.close()
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
    elif cfg["provider"] == "bedrock":
        suggestion = _bedrock_suggestion(cfg, system, prompt)
    else:
        suggestion = _openai_suggestion(cfg, system, prompt)
    if suggestion is None:
        explanation = "Could not parse a filter suggestion."
        if cfg["provider"] == "bedrock":
            explanation = (
                "Bedrock did not return a filter tool result. Choose a model "
                "that supports Converse tool use.")
        return {"filters": current_filters,
                "explanation": explanation}
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

    client, _, _ = _openai_client(cfg)
    schema = FilterSuggestion.model_json_schema()
    try:
        resp = client.chat.completions.create(
            model=cfg["model"],
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
    finally:
        client.close()

def _bedrock_suggestion(cfg: dict, system: str,
                        prompt: str) -> "FilterSuggestion | None":

    schema = {
        "type": "object",
        "properties": {
            "filters": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "column": {"type": "string"},
                    "kind": {"type": "string",
                             "enum": ["categorical", "range"]},
                    "values": {"type": "array",
                               "items": {"type": "string"}},
                    "min": {"type": "number"},
                    "max": {"type": "number"},
                },
                "required": ["column", "kind"],
            }},
            "explanation": {"type": "string"},
        },
        "required": ["filters", "explanation"],
    }
    data = bedrock.structured_call(
        cfg["model"], cfg["region"],
        system + " Return the result by calling the supplied tool.",
        prompt, "submit_filter_suggestion",
        "Return the complete cohort filter suggestion.", schema)
    if not data:
        return None
    try:
        return FilterSuggestion.model_validate(data)
    except Exception as exc:
        logger.warning("Could not parse Bedrock filter result: %s", exc)
        return None

def validate_filters(filters: list[dict], columns: list[dict]) -> list[dict]:

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
