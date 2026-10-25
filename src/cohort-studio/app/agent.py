import knowledge
import functools
import json
import logging

import pandas as pd

import bedrock
import agent_sessions
import agent_instructions
import config
import datasets
import llm
import providers
import vertexai_auth

logger = logging.getLogger(__name__)

MAX_HISTORY = 30
CHART_KINDS = ("bar", "histogram", "scatter", "heatmap")
AGGS = ("count", "mean", "median", "min", "max", "sum", "nunique")

def build_tools(df: pd.DataFrame, columns: list[dict], ui: dict,
                actions: list[str]):

    def run_query(filters_json: str = "[]") -> str:
        """Count rows matching a filter set and preview the first rows.

        Args:
            filters_json: JSON array of filters, each
                {"column": str, "kind": "categorical"|"range",
                 "values"?: [str], "min"?: number, "max"?: number}.
                Pass "[]" for the full dataset.
        """
        filters = llm.validate_filters(json.loads(filters_json), columns)
        sub = datasets.apply_filters(df, filters)
        preview = sub.head(5).astype(object).where(sub.head(5).notna(), None)
        return json.dumps({
            "total_rows": len(df),
            "matching_rows": len(sub),
            "preview": preview.to_dict(orient="records"),
        }, default=str)

    def aggregate(agg: str = "count", column: str = "",
                  group_by: str = "", filters_json: str = "[]") -> str:
        """Compute a statistic, optionally grouped and filtered.

        Args:
            agg: One of count, mean, median, min, max, sum, nunique.
            column: Numeric column the statistic applies to. Not needed
                for agg=count without a column.
            group_by: Optional categorical column to group by (top 25
                groups by size).
            filters_json: JSON array of filters to apply first (same
                shape as run_query). Pass "[]" for none.
        """
        if agg not in AGGS:
            return json.dumps({"error": f"agg must be one of {AGGS}"})
        for name in (column, group_by):
            if name and name not in df.columns:
                return json.dumps({"error": f"unknown column: {name}"})
        filters = llm.validate_filters(json.loads(filters_json), columns)
        sub = datasets.apply_filters(df, filters)
        if group_by:
            grouped = sub.groupby(sub[group_by].astype(str), observed=True)
            if agg == "count":
                series = grouped.size()
            else:
                series = getattr(grouped[column], agg)()
            series = series.sort_values(ascending=False).head(25)
            result = {str(k): (round(float(v), 4) if pd.notna(v) else None)
                      for k, v in series.items()}
        elif agg == "count":
            result = len(sub)
        else:
            value = getattr(sub[column], agg)()
            result = round(float(value), 4) if pd.notna(value) else None
        return json.dumps({"agg": agg, "column": column or None,
                           "group_by": group_by or None,
                           "rows_considered": len(sub), "result": result})

    def set_filters(filters_json: str, reason: str) -> str:
        """Replace the filters shown in the UI. The user sees the result
        immediately — the grid, counts, and every chart update.

        Args:
            filters_json: JSON array — the COMPLETE new filter set (same
                shape as run_query). "[]" clears all filters.
            reason: Short phrase shown to the user, e.g. "liver, RIN ≥ 7".
        """
        cleaned = llm.validate_filters(json.loads(filters_json), columns)
        ui["filters"] = cleaned
        count = len(datasets.apply_filters(df, cleaned))
        actions.append(f"Filters: {reason}" if cleaned else "Filters cleared")
        return json.dumps({"applied": cleaned, "matching_rows": count})

    def add_chart(kind: str, x: str, y: str = "") -> str:
        """Add a chart card to the user's dashboard.

        Args:
            kind: bar (categorical counts), histogram (numeric
                distribution), scatter (two numeric columns), or
                heatmap (two categorical columns).
            x: Column for the main axis.
            y: Second column — required for scatter and heatmap.
        """
        if kind not in CHART_KINDS:
            return json.dumps({"error": f"kind must be one of {CHART_KINDS}"})
        if x not in df.columns or (y and y not in df.columns):
            return json.dumps({"error": "unknown column"})
        if kind in ("scatter", "heatmap") and not y:
            return json.dumps({"error": f"{kind} needs a second column y"})
        spec = {"kind": kind, "x": x,
                "wide": kind in ("scatter", "heatmap")}
        if y:
            spec["y"] = y
        ui["charts"].append(spec)
        actions.append(f"Added {kind} of {x}{f' × {y}' if y else ''}")
        return json.dumps({"added": spec, "charts": ui["charts"]})

    def remove_chart(index: int) -> str:
        """Remove a chart from the dashboard by its zero-based index
        (the current charts are listed in the system prompt).

        Args:
            index: Zero-based position in the chart list.
        """
        if not 0 <= index < len(ui["charts"]):
            return json.dumps({"error": "index out of range"})
        removed = ui["charts"].pop(index)
        actions.append(f"Removed {removed['kind']} of {removed['x']}")
        return json.dumps({"removed": removed, "charts": ui["charts"]})

    return [run_query, aggregate, set_filters, add_chart, remove_chart]

def _system_prompt(source: str, df: pd.DataFrame, columns: list[dict],
                   ui: dict) -> str:
    lines = []
    for col in columns:
        if col["filter_kind"] == "categorical":
            lines.append(f"- {col['name']} (categorical: "
                         f"{', '.join(col.get('values') or [])})")
        elif col["filter_kind"] == "range":
            lines.append(f"- {col['name']} (numeric {col.get('min')}–"
                         f"{col.get('max')})")
        else:
            lines.append(f"- {col['name']} (free text, not filterable)")
    return (
        agent_instructions.system_guidance(
            "bioinformatics, data science, and data engineering",
            tool_schemas=providers.TOOL_SCHEMAS,
        ) + "\n\n"
        "You are the data assistant inside Cohort Studio, a cohort "
        "exploration app. The user is looking at one dataset and your "
        "tools act directly on their screen.\n\n"
        f"Dataset: {source} ({len(df):,} rows)\n"
        f"Columns:\n{chr(10).join(lines)}\n\n"
        f"Current UI filters: {json.dumps(ui['filters'])}\n"
        f"Current charts: {json.dumps(ui['charts'])}\n\n"
        "Ground every number in a tool result — never estimate from the "
        "column list. When the user asks to see, show, plot, or compare "
        "something, build it with add_chart (and set_filters when they "
        "ask to narrow the cohort) rather than only describing it. "
        "Filters you set replace the whole set. Keep replies to a couple "
        "of sentences; the user can see the grid and charts update."
    )

def chat(dataset_id: str, message: str, history: list[dict],
         filters: list[dict], charts: list[dict], on_step=None) -> dict:
    cfg = config.get_llm_config()
    provider = cfg["provider"]
    llm.validate_config(cfg)

    ds = datasets.get(dataset_id)
    df = ds["df"]
    columns = datasets.profile_columns(df)
    ui = {"filters": list(filters), "charts": list(charts)}
    actions: list[str] = []
    system = _system_prompt(ds["source"], df, columns, ui) + knowledge.context(message)
    stored_history = agent_sessions.start(system, cfg, message)
    if stored_history is not None:
        history = stored_history

    raw_tools = build_tools(df, columns, ui, actions)
    tool_calls: list[str] = []

    def track(fn):
        @functools.wraps(fn)
        def inner(*a, **k):
            tool_calls.append(fn.__name__)
            return fn(*a, **k)
        return inner

    wrapped = [track(fn) for fn in raw_tools]
    tool_impls = {fn.__name__: w for fn, w in zip(raw_tools, wrapped)}

    messages = [
        {"role": m["role"], "content": m["content"]}
        for m in history[-MAX_HISTORY:]
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]
    messages.append({"role": "user", "content": message})

    step = None
    if stored_history is not None or on_step is not None:
        def step(event):
            agent_sessions.event(event)
            if on_step:
                on_step(event)

    if provider == "bedrock":
        out = run_bedrock(cfg, system, messages, tool_impls,
                          providers.TOOL_SCHEMAS, on_step=step)
    else:
        try:
            out = providers.run(
                provider, cfg["model"], cfg["api_key"], cfg["base_url"],
                system, messages, tool_impls,
                vertex_config=(cfg if provider == "vertexai" else None),
                **({"on_step": step} if step else {}))
        except vertexai_auth.VertexAuthUnavailable as exc:
            raise llm.LLMNotConfigured(str(exc)) from exc

    return {"reply": out["reply"], "filters": ui["filters"], "charts": ui["charts"],
            "actions": actions, "provider": provider, "model": cfg["model"],
            "usage": out["usage"], "tool_calls": out.get("tool_calls", tool_calls)}

def run_bedrock(cfg: dict, system: str, messages: list[dict],
                tool_impls: dict, tool_schemas: list[dict], on_step=None) -> dict:

    return bedrock.run(cfg["model"], cfg.get("region"), system, messages,
                       tool_schemas, tool_impls, on_step=on_step)

def _run_anthropic(cfg: dict, system: str, messages: list[dict],
                   wrapped: list, on_step=None) -> tuple[str, dict]:
    tool_impls = {fn.__name__: fn for fn in wrapped}
    result = providers.run("anthropic", cfg["model"], cfg["api_key"], None,
                           system, messages, tool_impls,
                           tool_schemas=providers.TOOL_SCHEMAS, on_step=on_step)
    return result["reply"], result["usage"]
