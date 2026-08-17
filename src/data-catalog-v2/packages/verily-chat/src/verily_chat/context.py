"""
Context builder: transforms verily-profiler output into LLM system prompts.

Two system prompt variants:
  - Metadata Q&A: answer questions about profiles, no SQL generation
  - Agent mode: NL-to-SQL with BigQuery execution rules
"""

from __future__ import annotations

from typing import Any, Optional

from verily_chat.models import ChatContext


_METADATA_SYSTEM_PROMPT = """\
You are a data steward assistant for a BigQuery data catalog. You help users
understand their datasets by answering questions about table structure, column
definitions, data quality, and metadata.

You have access to technical and semantic profiling metadata for the tables below.
Use this metadata to answer questions accurately and concisely.

CAPABILITIES:
- Explain what a table or column contains, in plain language
- Describe data quality (null rates, distinct counts, anomalies)
- Identify primary keys, join paths between tables, and data granularity
- Classify data sensitivity (PHI, PII, UID)
- Suggest which tables or columns are relevant for a given question
- Explain terminology bindings (LOINC, ICD-10, SNOMED, NDC)
- Compare statistics across columns or tables

RULES:
- Base every answer on the metadata provided below. Do NOT hallucinate columns or tables.
- If information is not available in the profiles, say so.
- When referencing columns, use their exact names.
- Format numbers with commas for readability.
- Use markdown formatting for tables and code blocks.

{table_context}
"""

_AGENT_SYSTEM_PROMPT = """\
You are a SQL expert and data analyst working with a BigQuery data catalog.
Your job is to help users explore data by answering metadata questions AND
converting natural language questions into BigQuery SQL queries.

You have access to technical and semantic profiling metadata, plus the ability
to execute SQL queries against BigQuery.

{table_context}

## RULES — You MUST follow these when generating SQL:

1. **Always use fully-qualified table names** in backticks: `project.dataset.table`

2. **Use the exact column names** shown above. NEVER invent column names.

3. **Join tables using the Primary Key** listed for each table.
   Only join tables that share a primary key or have a join path listed above.

4. **Always add LIMIT** to prevent runaway queries:
   - Use `LIMIT 100` by default for exploration queries
   - Use `LIMIT 1000` for aggregation source data
   - Only omit LIMIT when the user explicitly asks for all rows

5. **Handle NULL values** — use IFNULL, COALESCE, or explicit IS NOT NULL.

6. **Sensitive columns** (marked [PHI], [PII], [UID]) — note their sensitivity
   in your response but still include them in queries when necessary.

7. **Date handling** — use BigQuery date functions (DATE, TIMESTAMP, EXTRACT, DATE_DIFF).

{large_table_rules}

## RESPONSE FORMAT:

When the user asks a data question:
1. **Understanding**: Brief restatement of the question
2. **Data Mapping**: Which tables and columns you chose and why
3. **SQL**: The BigQuery SQL query in a ```sql block
4. **Interpretation**: What the results mean
5. **Limitations**: Any caveats, missing data, or assumptions
6. **Follow-ups**: 1-2 suggestions for next exploration steps

When the user asks a metadata question (what tables exist, what a column means):
- Answer using the profiling metadata
- Include a sample SQL query they could run

IMPORTANT:
- If a question is ambiguous, state your assumptions and ask for clarification.
- If you're not sure which table to use, list the candidates.
- If a query requires data that doesn't exist, say so clearly.
"""


def build_catalog_system_prompt(
    context: ChatContext,
    mode: str = "metadata",
) -> str:
    """
    Build a system prompt from the available profiling context.

    Args:
        context: ChatContext with profiles and project info.
        mode: "metadata" for Q&A only, "agent" for SQL generation.
    """
    table_blocks: list[str] = []

    catalog_md = ""
    if context.table_summaries:
        for s in context.table_summaries:
            if isinstance(s, dict) and "_catalog_context_md" in s:
                catalog_md = s["_catalog_context_md"]
                break

    if context.fq_table:
        tech = context.tech_profiles.get(context.fq_table)
        sem = context.sem_profiles.get(context.fq_table)
        if tech or sem:
            table_blocks.append(format_table_for_prompt(context.fq_table, tech, sem))
        if catalog_md:
            table_blocks.append(f"\n## Full catalog overview (for cross-table questions):\n{catalog_md}")
    elif catalog_md:
        table_blocks.append(catalog_md)
    else:
        all_tables = set(list(context.tech_profiles.keys()) + list(context.sem_profiles.keys()))
        if not all_tables and context.table_summaries:
            all_tables = {s.get("fq_table", "") for s in context.table_summaries if s.get("fq_table")}

        for fq in sorted(all_tables):
            tech = context.tech_profiles.get(fq)
            sem = context.sem_profiles.get(fq)
            if tech or sem:
                table_blocks.append(format_table_for_prompt(fq, tech, sem))
            else:
                summary = next((s for s in context.table_summaries if s.get("fq_table") == fq), None)
                if summary:
                    table_blocks.append(_format_summary_for_prompt(fq, summary))

    table_context = "\n\n".join(table_blocks) if table_blocks else "No profiling data available yet."

    if not table_blocks and context.table_summaries:
        lines = ["## Available tables (not yet profiled):\n"]
        for s in context.table_summaries:
            if isinstance(s, dict) and "fq_table" in s:
                fq = s.get("fq_table", "unknown")
                rows = s.get("row_count")
                rows_str = f" ({rows:,} rows)" if rows else ""
                lines.append(f"- `{fq}`{rows_str}")
        if len(lines) > 1:
            table_context = "\n".join(lines)

    large_table_rules = _build_large_table_rules(context) if mode == "agent" else ""

    if mode == "agent":
        return _AGENT_SYSTEM_PROMPT.format(
            table_context=table_context,
            large_table_rules=large_table_rules,
        )
    return _METADATA_SYSTEM_PROMPT.format(table_context=table_context)


def format_table_for_prompt(
    fq_table: str,
    tech: Optional[dict[str, Any]] = None,
    sem: Optional[dict[str, Any]] = None,
) -> str:
    """Format a single table's profiles into structured text for the LLM."""
    lines: list[str] = [f"## TABLE: `{fq_table}`"]

    if sem:
        if sem.get("business_name"):
            lines.append(f"Business Name: {sem['business_name']}")
        if sem.get("table_definition"):
            lines.append(f"Description: {sem['table_definition']}")
        domain = sem.get("semantic_domain", {})
        if domain.get("primary"):
            sub = f" / {domain['sub_domain']}" if domain.get("sub_domain") else ""
            lines.append(f"Domain: {domain['primary']}{sub}")
        if sem.get("granularity"):
            lines.append(f"Granularity: {sem['granularity']}")
        pk = sem.get("primary_key", {})
        if pk.get("columns"):
            cols_str = ", ".join(pk["columns"])
            lines.append(f"Primary Key: {cols_str} ({pk.get('pk_type', 'unknown')}, {pk.get('confidence', 'low')} confidence)")

    if tech:
        parts: list[str] = []
        rc = tech.get("row_count")
        if rc is not None:
            parts.append(f"Rows: {rc:,}")
        sb = tech.get("size_bytes")
        if sb is not None:
            mb = sb / (1024 * 1024)
            parts.append(f"Size: {mb:.1f} MB")
        if tech.get("profiled_at"):
            parts.append(f"Profiled: {tech['profiled_at']}")
        if parts:
            lines.append(" | ".join(parts))

    sem_cols = {}
    if sem:
        for sc in sem.get("columns", []):
            sem_cols[sc.get("name", sc.get("column_name", ""))] = sc

    tech_cols = tech.get("columns", []) if tech else []
    if tech_cols or sem_cols:
        lines.append("")
        lines.append("COLUMNS:")
        all_col_names: list[str] = []
        for tc in tech_cols:
            all_col_names.append(tc.get("name", tc.get("column_name", "")))
        for name in sem_cols:
            if name not in all_col_names:
                all_col_names.append(name)

        for col_name in all_col_names:
            tc = next((c for c in tech_cols if c.get("name", c.get("column_name", "")) == col_name), None)
            sc = sem_cols.get(col_name)
            lines.append(_format_column(col_name, tc, sc))

    return "\n".join(lines)


def _format_column(name: str, tc: Optional[dict], sc: Optional[dict]) -> str:
    dtype = tc.get("data_type", "UNKNOWN") if tc else "UNKNOWN"
    nullable = "NULLABLE" if (tc and tc.get("nullable", True)) else "NOT NULL"

    definition = ""
    if sc and sc.get("definition"):
        definition = f" — {sc['definition']}"

    sensitivity = ""
    if sc and sc.get("sensitivity"):
        sensitivity = f" [{sc['sensitivity']}]"

    uom = ""
    if sc and sc.get("unit_of_measure"):
        uom = f" [Unit: {sc['unit_of_measure']}]"

    header = f"  {name} ({dtype}, {nullable}){definition}{sensitivity}{uom}"

    stats_parts: list[str] = []
    if tc:
        if tc.get("null_percent") is not None:
            stats_parts.append(f"Nulls: {tc['null_percent']}%")
        if tc.get("distinct_count") is not None:
            stats_parts.append(f"Distinct: {tc['distinct_count']:,}")
        if tc.get("pattern"):
            stats_parts.append(f"Pattern: {tc['pattern']}")

        nstats = tc.get("numeric_stats") or {}
        if nstats.get("min") is not None:
            stats_parts.append(f"Range: [{nstats['min']}, {nstats['max']}]")
        if nstats.get("median") is not None:
            stats_parts.append(f"Median: {nstats['median']}")

        sstats = tc.get("string_stats") or {}
        if sstats.get("min_length") is not None:
            stats_parts.append(f"StrLen: [{sstats['min_length']}, {sstats['max_length']}]")

        top = tc.get("top_values", [])
        vcounts = tc.get("value_counts", {})
        if top and vcounts:
            items = [f"{v} ({vcounts.get(v, '?')})" for v in top[:5]]
            stats_parts.append(f"Top: {', '.join(items)}")
        elif top:
            stats_parts.append(f"Top: {', '.join(top[:5])}")

        if tc.get("anomalies"):
            stats_parts.append(f"Anomalies: {', '.join(tc['anomalies'])}")

    if sc:
        terms = sc.get("terminology_bindings", [])
        if terms:
            sys_names = [t.get("system", "").split("/")[-1] for t in terms[:3]]
            stats_parts.append(f"Terminology: {', '.join(sys_names)}")

        joins = sc.get("join_paths", [])
        if joins:
            stats_parts.append(f"Joins: {', '.join(joins[:3])}")

    if stats_parts:
        return header + "\n    " + " | ".join(stats_parts)
    return header


def _format_summary_for_prompt(fq: str, summary: dict[str, Any]) -> str:
    lines = [f"## TABLE: `{fq}`"]
    if summary.get("business_name"):
        lines.append(f"Business Name: {summary['business_name']}")
    if summary.get("table_definition"):
        lines.append(f"Description: {summary['table_definition']}")
    rc = summary.get("row_count")
    if rc is not None:
        lines.append(f"Rows: {rc:,}")
    cc = summary.get("column_count")
    if cc is not None:
        lines.append(f"Columns: {cc}")
    return "\n".join(lines)


def _build_large_table_rules(context: ChatContext) -> str:
    large: list[str] = []
    for fq, tech in context.tech_profiles.items():
        rc = tech.get("row_count", 0) or 0
        cols = tech.get("columns", [])
        if rc > 100_000 or len(cols) > 50:
            short = fq.split(".")[-1] if "." in fq else fq
            parts: list[str] = []
            if len(cols) > 50:
                parts.append(f"{len(cols)} columns — only SELECT needed columns")
            if rc > 100_000:
                parts.append(f"{rc:,} rows — always apply filters")
            large.append(f"    - `{short}`: {'; '.join(parts)}")

    if not large:
        return ""
    return "8. **Large table awareness**:\n" + "\n".join(large)
