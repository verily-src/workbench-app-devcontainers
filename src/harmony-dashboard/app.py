"""Harmony Data Harmonization Dashboard.

4-phase view over the agentic FHIR harmonization pipeline:
  1. Profiling      — resource discovery and initial findings
  2. Mapping Run    — iteration hill-climbing, SQL evolution per resource
  3. Combine SQL    — UNION ALL queries per FHIR resource type, coverage
  4. Audit Report   — T1 DQ checks and final audit findings

Reads from:
  output_{run}/work/resources/{name}/status.json + latest_evaluation.json + findings.md
  output_{run}/work/resources/{name}/mapping*.sql
  output_{run}/work/coverage_snapshots.json
  output_{run}/combined/{ResourceType}.sql
  output_{run}/iter_{N}/{resource}/dq.md, llm_judge.md, coverage.md, reasonableness.md
  output_{run}/audit_report_t1.md

Environment variables: HARMONY_LOCAL_PATH or HARMONY_GCS_PATH
"""

import difflib
import html as _html
import os

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

import loader

DATASET_NAME     = os.environ.get("HARMONY_DATASET_NAME", "Harmony")
DATASET_SUBTITLE = os.environ.get("HARMONY_DATASET_SUBTITLE", "Agentic FHIR Harmonization")

st.set_page_config(
    page_title=f"{DATASET_NAME} | Agentic Data Harmonization",
    page_icon="🧩",
    layout="wide",
    initial_sidebar_state="expanded",
)

GREEN_DARK  = "#1B5E3B"
GREEN_MID   = "#2E7D52"
GREEN_LIGHT = "#E8F5EE"
CREAM       = "#FAFAF7"
AMBER       = "#B45309"
AMBER_BG    = "#FFFBEB"
RED         = "#B91C1C"
RED_BG      = "#FEF2F2"

st.markdown(f"""
<style>
/* Main background and text */
.stApp {{ background: {CREAM}; color: #0F2419; }}

/* Top sticky bar — dataset label from HARMONY_DATASET_NAME env var */
.stAppHeader, [data-testid="stHeader"] {{
  background-color: {CREAM} !important;
  border-bottom: none !important;
}}
[data-testid="stHeader"]::before, .stAppHeader::before {{
  content: "{DATASET_NAME}";
  position: absolute;
  left: 1.5rem;
  top: 50%;
  transform: translateY(-50%);
  font-size: 1.05rem;
  font-weight: 800;
  color: #000000;
  letter-spacing: -0.01em;
  background: transparent !important;
  height: auto !important;
  width: auto !important;
  display: block;
}}
[data-testid="stHeader"] button svg,
[data-testid="stHeader"] [data-testid="stToolbar"] svg {{ fill: #FFFFFF !important; }}
[data-testid="stMainMenu"] {{ visibility: hidden; }}
[data-testid="stMainBlockContainer"] {{ padding-top: 0.75rem; }}

/* Expander headers — force legible text on cream */
[data-testid="stExpander"] {{
  background: #FFFFFF;
  border: 1px solid #D1E8DB !important;
  border-radius: 8px;
}}
[data-testid="stExpander"] details summary,
[data-testid="stExpander"] details summary * {{
  color: #0F2419 !important;
  background: #FFFFFF !important;
}}
[data-testid="stExpander"] details summary:hover,
[data-testid="stExpander"] details summary:hover * {{
  background: {GREEN_LIGHT} !important;
  color: #0F2419 !important;
}}
div[class*="streamlit-expanderHeader"],
div[class*="streamlit-expanderHeader"] * {{
  color: #0F2419 !important;
  background: #FFFFFF !important;
}}

/* Force dark text in main content */
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
[data-testid="stMarkdownContainer"] td,
[data-testid="stMarkdownContainer"] th,
[data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3,
[data-testid="stMarkdownContainer"] h4,
.stMarkdown p, .stMarkdown li, .stMarkdown td, .stMarkdown th,
.element-container p, .element-container li {{ color: #0F2419 !important; }}

/* Sidebar */
[data-testid="stSidebar"] {{ background: {GREEN_DARK}; }}
[data-testid="stSidebar"] * {{ color: #E8F5EE !important; }}
[data-testid="stSidebar"] input {{ color: #0F2419 !important; background: #FFFFFF !important; }}
[data-testid="stSidebar"] .stRadio label {{ font-size: 0.86rem; padding: 3px 0; }}
[data-testid="stSidebar"] .stRadio label:hover {{ color: #FFFFFF !important; }}
[data-testid="stSidebar"] hr {{ border-color: #2E7D52; }}

/* Badges */
.badge {{
  display: inline-block;
  padding: 2px 9px;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.03em;
}}
.badge-passed   {{ background:{GREEN_LIGHT}; color:{GREEN_DARK}; }}
.badge-pending  {{ background:#FEF9EE;       color:{AMBER};      }}
.badge-blocked  {{ background:{RED_BG};      color:{RED};        }}
.badge-running  {{ background:#EEF9F4;       color:{GREEN_MID};  }}
.badge-notrun   {{ background:#F1F5F9;       color:#64748B;      }}

/* Cards */
.step-card {{
  background: #FFFFFF;
  border: 1px solid #D1E8DB;
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 10px;
  box-shadow: 0 1px 2px rgba(15, 36, 25, 0.03);
  color: #0F2419;
}}
.step-label {{
  font-size: 0.70rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: {GREEN_MID};
  margin-bottom: 3px;
}}
.step-value {{ font-size: 0.94rem; color: #0F2419; }}

/* Section headers */
.section-header {{
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: {GREEN_MID};
  margin: 18px 0 8px 0;
  border-bottom: 1px solid #D1E8DB;
  padding-bottom: 4px;
}}

/* Metric pills */
.metric-pill {{
  display: inline-block;
  background: #FFFFFF;
  border: 1px solid #D1E8DB;
  border-radius: 10px;
  padding: 8px 18px;
  text-align: center;
  margin: 4px 6px 4px 0;
}}
.metric-pill .mp-value {{ font-size: 1.4rem; font-weight: 700; color: {GREEN_DARK}; }}
.metric-pill .mp-label {{ font-size: 0.72rem; color: {GREEN_MID}; }}

/* Sidebar button — keep text visible on hover */
[data-testid="stSidebar"] .stButton button {{
  background: rgba(255,255,255,0.12);
  color: #E8F5EE !important;
  border: 1px solid rgba(232,245,238,0.3);
}}
[data-testid="stSidebar"] .stButton button:hover {{
  background: rgba(255,255,255,0.25) !important;
  color: #FFFFFF !important;
  border-color: rgba(232,245,238,0.6) !important;
}}

/* Fix selectbox: white background + dark text in both focused and unfocused states */
[data-baseweb="select"] > div:first-child {{
  background-color: #FFFFFF !important;
  border-color: #D1E8DB !important;
  color: #0F2419 !important;
}}
[data-baseweb="select"] span,
[data-baseweb="select"] [data-testid="stSelectboxValue"] {{
  color: #0F2419 !important;
}}
[data-baseweb="popover"] [role="option"] {{
  color: #0F2419 !important;
  background: #FFFFFF !important;
}}
[data-baseweb="popover"] [role="option"]:hover {{
  background: {GREEN_LIGHT} !important;
}}

/* Phase stepper */
.phase-bar {{
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  margin-top: 40px;
  margin-bottom: 24px;
}}
.phase-node {{
  background: #FFFFFF;
  border: 1px solid #D1E8DB;
  border-radius: 10px;
  padding: 10px 14px;
  box-shadow: 0 1px 2px rgba(15,36,25,0.04);
  color: #0F2419;
}}
.phase-node-active {{
  border: 2px solid {GREEN_DARK};
  background: {GREEN_LIGHT};
}}
.phase-num {{
  font-size: 0.65rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: {GREEN_MID};
}}
.phase-title {{
  font-size: 0.88rem;
  font-weight: 700;
  color: #0F2419;
  margin: 2px 0 4px;
}}
.phase-sub {{
  font-size: 0.74rem;
  color: #475569;
}}
</style>
""", unsafe_allow_html=True)


def _badge(state: str, label: str | None = None) -> str:
    cls = {
        "passed": "badge-passed",
        "complete": "badge-passed",
        "blocked": "badge-blocked",
        "failed": "badge-blocked",
        "max_iterations_reached": "badge-pending",
        "pending": "badge-pending",
        "running": "badge-running",
        "in_progress": "badge-running",
        "not_run": "badge-notrun",
        "unknown": "badge-notrun",
    }.get(state.lower(), "badge-pending")
    text = label or state.replace("_", " ").title()
    return f'<span class="badge {cls}">{text}</span>'


def _metric_pill(value, label: str) -> str:
    return (
        f'<div class="metric-pill">'
        f'<div class="mp-value">{value}</div>'
        f'<div class="mp-label">{label}</div>'
        f'</div>'
    )


def _section(text: str) -> str:
    return f'<div class="section-header">{text}</div>'


def _sql_diff_html(old_sql: str, new_sql: str, old_label: str, new_label: str) -> str:
    """Render a git-style unified diff between two SQL strings as HTML."""
    WRAP = (
        'display:block;font-family:"Courier New",Courier,monospace;'
        'font-size:0.76rem;line-height:1.55;padding:1px 12px;white-space:pre;'
    )
    if not old_sql:
        lines = new_sql.splitlines()
        rows = "".join(
            f'<span style="{WRAP}color:#0F2419;">{_html.escape(l)}</span>' for l in lines
        )
        return (
            f'<div style="border:1px solid #D1E8DB;border-radius:8px;'
            f'overflow-x:auto;background:#FFFFFF;">{rows}</div>'
        )

    diff = list(difflib.unified_diff(
        old_sql.splitlines(), new_sql.splitlines(),
        fromfile=old_label, tofile=new_label, lineterm="", n=4,
    ))
    if not diff:
        return (
            '<div style="color:#64748B;font-style:italic;padding:10px 14px;'
            'border:1px solid #D1E8DB;border-radius:8px;">No changes from previous version.</div>'
        )

    rows = []
    for line in diff:
        esc = _html.escape(line)
        if line.startswith("+++") or line.startswith("---"):
            style = f"{WRAP}background:#EEF9F4;color:#2E7D52;font-weight:600;"
        elif line.startswith("@@"):
            style = f"{WRAP}background:#F0F4FF;color:#475569;"
        elif line.startswith("+"):
            style = f"{WRAP}background:#E8F5EE;color:#1B5E3B;"
        elif line.startswith("-"):
            style = f"{WRAP}background:#FEF2F2;color:#B91C1C;"
        else:
            style = f"{WRAP}color:#0F2419;"
        rows.append(f'<span style="{style}">{esc}</span>')

    return (
        f'<div style="border:1px solid #D1E8DB;border-radius:8px;'
        f'overflow-x:auto;background:#FFFFFF;">{"".join(rows)}</div>'
    )


def _style_fig(fig, height: int = 300):
    _text = "#0F2419"
    fig.update_layout(
        height=height,
        margin=dict(t=30, b=80, l=10, r=10),
        plot_bgcolor="white",
        paper_bgcolor=CREAM,
        font=dict(color=_text, size=12),
        title_font=dict(color=_text, size=13),
        xaxis=dict(
            gridcolor="#E8F5EE",
            tickfont=dict(color=_text),
            title_font=dict(color=_text),
        ),
        yaxis=dict(
            gridcolor="#E8F5EE",
            tickfont=dict(color=_text),
            title_font=dict(color=_text),
        ),
        legend=dict(font=dict(color=_text)),
    )
    return fig


@st.cache_data(ttl=120, show_spinner=False)
def _load_runs(override_path: str = ""):
    return loader.list_runs_with_errors(override_path)


@st.cache_data(ttl=120, show_spinner=False)
def _ws_resources(run_id: str, mapping_path: str) -> list[dict]:
    run = loader.RunMeta(run_id=run_id, mapping_path=mapping_path)
    return loader.load_workspace_resources(run)


@st.cache_data(ttl=120, show_spinner=False)
def _findings(run_id: str, mapping_path: str, name: str) -> str:
    run = loader.RunMeta(run_id=run_id, mapping_path=mapping_path)
    return loader.load_resource_findings(run, name)


@st.cache_data(ttl=120, show_spinner=False)
def _draft_sqls(run_id: str, mapping_path: str, name: str) -> list[tuple[str, str]]:
    run = loader.RunMeta(run_id=run_id, mapping_path=mapping_path)
    return loader.load_resource_draft_sqls(run, name)


@st.cache_data(ttl=120, show_spinner=False)
def _combined_sqls(run_id: str, mapping_path: str) -> dict[str, str]:
    run = loader.RunMeta(run_id=run_id, mapping_path=mapping_path)
    return loader.load_combined_sqls(run)


@st.cache_data(ttl=120, show_spinner=False)
def _coverage_snapshots(run_id: str, mapping_path: str) -> dict:
    run = loader.RunMeta(run_id=run_id, mapping_path=mapping_path)
    return loader.load_coverage_snapshots(run)


@st.cache_data(ttl=120, show_spinner=False)
def _audit_report(run_id: str, mapping_path: str) -> str:
    run = loader.RunMeta(run_id=run_id, mapping_path=mapping_path)
    return loader.load_audit_report(run)


def _phase_bar(active: str):
    phases = [
        ("1", "Profiling", "Data exploration & initial findings"),
        ("2", "Mapping Run", "Iteration hill-climbing, SQL evolution"),
        ("3", "Combine SQL", "UNION ALL per resource type, coverage"),
        ("4", "Audit Report", "T1 DQ checks, final issues"),
    ]
    html = '<div class="phase-bar">'
    for num, title, sub in phases:
        full = f"{num}. {title}"
        is_active = active == full
        cls = "phase-node phase-node-active" if is_active else "phase-node"
        html += (
            f'<div class="{cls}">'
            f'<div class="phase-num">Phase {num}</div>'
            f'<div class="phase-title">{title}</div>'
            f'<div class="phase-sub">{sub}</div>'
            f'</div>'
        )
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


def _sidebar() -> tuple[loader.RunMeta | None, str]:
    with st.sidebar:
        st.markdown("### Harmony")
        st.caption("Agentic Clinical Data Harmonization")
        st.divider()

        st.markdown(_section("Artifact Root"), unsafe_allow_html=True)
        default_root = loader.get_configured_root()
        override_path = st.text_input(
            "Artifact Root",
            value=default_root,
            placeholder="gs://bucket/path or /local/path",
            label_visibility="collapsed",
        )

        runs, errors = _load_runs(override_path)
        for err in errors:
            st.warning(err)

        if not runs:
            st.error("No runs found (`output_*` or `run_*`) under `mapping/`.")
            return None, ""

        st.markdown(_section("Select Run"), unsafe_allow_html=True)
        run_labels = [r.run_id for r in runs]
        idx = st.radio(
            "run",
            range(len(runs)),
            format_func=lambda i: run_labels[i],
            label_visibility="collapsed",
        )
        run = runs[idx]

        st.divider()
        st.markdown(_section("Phase"), unsafe_allow_html=True)
        pages = ["1. Profiling", "2. Mapping Run", "3. Combine SQL", "4. Audit Report"]
        page = st.radio("page", pages, label_visibility="collapsed")

        st.divider()
        if st.button("Refresh Artifacts", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    return run, page


def page_profiling(run: loader.RunMeta):
    st.markdown(f"## Phase 1 — Profiling · `{run.run_id}`")
    st.caption("Resource discovery: what source tables were found, initial agent findings, and mapping state.")

    resources = _ws_resources(run.run_id, run.mapping_path)
    if not resources:
        st.info("No resources found in `work/resources/`. Check the artifact root path.")
        return

    # State breakdown
    state_counts: dict[str, int] = {}
    for r in resources:
        s = r["state"]
        state_counts[s] = state_counts.get(s, 0) + 1

    pills = ""
    pills += _metric_pill(len(resources), "total resources")
    pills += _metric_pill(state_counts.get("passed", 0), "passed")
    pills += _metric_pill(state_counts.get("max_iterations_reached", 0), "max iters")
    pills += _metric_pill(state_counts.get("blocked", 0), "blocked")
    st.markdown(pills, unsafe_allow_html=True)

    st.markdown(_section("All Resources"), unsafe_allow_html=True)

    rows = []
    for r in resources:
        judge = r["judge_score"]
        dq = r["dq_passed"]
        cov = r["coverage_pct"]
        rows.append({
            "Resource": r["name"],
            "FHIR Type": r["resource"],
            "Source Table": r["source_table"],
            "State": r["state"],
            "Iter": r["iteration"] or "",
            "Judge": f"{judge}/5" if judge is not None else "—",
            "DQ": "✓" if dq else ("✗" if dq is False else "—"),
            "Cov %": f"{cov}%" if cov is not None else "—",
        })

    df = pd.DataFrame(rows)

    state_color = {
        "passed": "background-color: #E8F5EE; color: #1B5E3B",
        "blocked": "background-color: #FEF2F2; color: #B91C1C",
        "max_iterations_reached": "background-color: #FFFBEB; color: #B45309",
        "in_progress": "background-color: #EEF9F4; color: #2E7D52",
    }

    def _row_style(row):
        s = state_color.get(row["State"], "")
        return [s] * len(row)

    styled = df.style.apply(_row_style, axis=1)
    st.dataframe(styled, use_container_width=True, hide_index=True)

    st.markdown(_section("Resource Findings"), unsafe_allow_html=True)
    names = [r["name"] for r in resources]
    sel = st.selectbox("Select resource to view findings", names, key="profiling_sel")
    if sel:
        md = _findings(run.run_id, run.mapping_path, sel)
        blocked = next((r["blocked_reason"] for r in resources if r["name"] == sel), "")
        if blocked:
            st.error(f"**Blocked:** {blocked}")
        if md:
            st.markdown(md)
        else:
            st.info("No `findings.md` available for this resource.")


def page_mapping_run(run: loader.RunMeta):
    st.markdown(f"## Phase 2 — Mapping Run · `{run.run_id}`")
    st.caption("How many FHIR resources pass each evaluation gate per iteration (hill-climbing), and the SQL revision history per resource.")

    resources = _ws_resources(run.run_id, run.mapping_path)
    if not resources:
        return

    st.markdown(_section("Resource Status Summary"), unsafe_allow_html=True)

    rows2 = []
    for r in resources:
        j = r["judge_score"]
        rows2.append({
            "Resource": r["name"],
            "FHIR Type": r["resource"],
            "State": r["state"],
            "Iter": r["iteration"] or "—",
            "Judge Score": f"{j}/5" if j is not None else "—",
            "DQ": "✓" if r["dq_passed"] else ("✗" if r["dq_passed"] is False else "—"),
            "Reasonableness": "✓" if r["reasonableness_passed"] else ("✗" if r["reasonableness_passed"] is False else "—"),
            "Coverage %": f"{r['coverage_pct']}%" if r["coverage_pct"] is not None else "—",
            "All Passed": "✓" if r["all_passed"] else ("✗" if r["all_passed"] is False else "—"),
        })

    df2 = pd.DataFrame(rows2)
    st.dataframe(df2, use_container_width=True, hide_index=True)

    st.markdown(_section("SQL Revision History"), unsafe_allow_html=True)
    names = [r["name"] for r in resources]
    sel = st.selectbox("Select resource to view SQL evolution", names, key="mapping_run_sel")
    if sel:
        findings_md = _findings(run.run_id, run.mapping_path, sel)
        drafts = _draft_sqls(run.run_id, run.mapping_path, sel)

        if findings_md:
            with st.expander("Agent Findings — what drove these changes", expanded=False):
                st.markdown(findings_md)

        if not drafts:
            st.info("No SQL files found for this resource.")
        elif len(drafts) == 1:
            label, sql = drafts[0]
            st.caption(f"1 SQL version ({label})")
            st.code(sql, language="sql")
        else:
            chain = " → ".join(label for label, _ in drafts)
            st.caption(f"{len(drafts)} versions: {chain}")
            for i, (label, sql) in enumerate(drafts):
                is_last = i == len(drafts) - 1
                if i == 0:
                    old_sql, old_label = "", "initial"
                    title = f"Initial — {label}"
                    subtitle = f"{len(sql.splitlines())} lines"
                else:
                    old_label, old_sql = drafts[i - 1]
                    title = f"{old_label} → {label}"
                    diff_lines = list(difflib.unified_diff(
                        old_sql.splitlines(), sql.splitlines(), lineterm="",
                    ))
                    n_add = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++"))
                    n_del = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---"))
                    subtitle = f"+{n_add} lines  −{n_del} lines"

                with st.expander(f"{title}  ({subtitle})", expanded=is_last):
                    st.markdown(_sql_diff_html(old_sql, sql, old_label, label), unsafe_allow_html=True)


def page_combine_sql(run: loader.RunMeta):
    st.markdown(f"## Phase 3 — Combine SQL · `{run.run_id}`")
    st.caption("One UNION ALL query per FHIR resource type, combining all source-table mappings.")

    sqls = _combined_sqls(run.run_id, run.mapping_path)
    snapshots = _coverage_snapshots(run.run_id, run.mapping_path)

    if not sqls:
        st.info("No combined SQL files found. Run the combine phase first.")
        return

    # Coverage bar chart from latest snapshot
    if snapshots:
        last_iter = str(max(int(k) for k in snapshots.keys()))
        last_snap = snapshots[last_iter]
        bar_df = pd.DataFrame(
            [{"Resource Type": k, "Patients": v} for k, v in sorted(last_snap.items(), key=lambda x: -x[1])]
        )
        fig = px.bar(
            bar_df, x="Resource Type", y="Patients",
            title=f"Patients covered per FHIR resource type — iter {last_iter} (cohort = 50 patients)",
            color_discrete_sequence=[GREEN_DARK],
        )
        fig.update_xaxes(tickangle=45, tickfont=dict(color="#0F2419", size=11))
        fig.update_yaxes(tickfont=dict(color="#0F2419"))
        fig.update_traces(texttemplate="%{y}", textposition="outside", textfont_color="#0F2419")
        st.plotly_chart(_style_fig(fig, height=340), use_container_width=True)
        st.caption(
            "Each bar = how many of the 50 evaluation-cohort patients have at least one "
            "FHIR resource of that type generated by the combined UNION ALL query. "
            "Max is 50 (full cohort coverage)."
        )

    st.markdown(_section("Combined SQL Viewer"), unsafe_allow_html=True)
    rtype = st.selectbox(
        "Select FHIR resource type",
        sorted(sqls.keys()),
        key="combine_sel",
    )
    if rtype:
        lines = sqls[rtype].count("\n") + 1
        st.caption(f"`combined/{rtype}.sql` — {lines} lines")
        st.code(sqls[rtype], language="sql")


def page_audit_report(run: loader.RunMeta):
    st.markdown(f"## Phase 4 — Audit Report · `{run.run_id}`")
    st.caption("T1 data quality checks and final audit findings across all mapped resources.")

    resources = _ws_resources(run.run_id, run.mapping_path)

    if resources:
        st.markdown(_section("Mapping Quality Summary"), unsafe_allow_html=True)

        passed = [r for r in resources if r["state"] == "passed"]
        max_iter = [r for r in resources if r["state"] == "max_iterations_reached"]
        blocked = [r for r in resources if r["state"] == "blocked"]

        dq_ok = sum(1 for r in resources if r["dq_passed"] is True)
        dq_total = sum(1 for r in resources if r["dq_passed"] is not None)
        judge_scores = [r["judge_score"] for r in resources if r["judge_score"] is not None]
        avg_judge = round(sum(judge_scores) / len(judge_scores), 2) if judge_scores else None

        pills = ""
        pills += _metric_pill(len(passed), "passed")
        pills += _metric_pill(len(max_iter), "max iters (incomplete)")
        pills += _metric_pill(len(blocked), "blocked")
        pills += _metric_pill(f"{dq_ok}/{dq_total}", "DQ pass")
        if avg_judge is not None:
            pills += _metric_pill(f"{avg_judge}/5", "avg judge score")
        st.markdown(pills, unsafe_allow_html=True)

        # Judge score bar chart
        if judge_scores:
            score_rows = [
                {"Resource": r["name"], "Judge Score": r["judge_score"]}
                for r in sorted(resources, key=lambda x: (x["judge_score"] or 0), reverse=True)
                if r["judge_score"] is not None
            ]
            score_df = pd.DataFrame(score_rows)
            fig = px.bar(
                score_df, x="Resource", y="Judge Score",
                title="LLM Judge Score per Resource (5 = best)",
                color="Judge Score",
                color_continuous_scale=[[0, RED], [0.5, AMBER_BG], [1, GREEN_DARK]],
                range_color=[0, 5],
            )
            fig.update_xaxes(tickangle=60, tickfont=dict(color="#0F2419", size=10))
            fig.update_yaxes(tickfont=dict(color="#0F2419"))
            fig.update_traces(texttemplate="%{y}", textposition="outside", textfont_color="#0F2419")
            fig.update_layout(coloraxis_showscale=False)
            st.plotly_chart(_style_fig(fig, height=360), use_container_width=True)

        # Blocked resources detail
        if blocked:
            st.markdown(_section("Blocked Resources"), unsafe_allow_html=True)
            for r in blocked:
                st.markdown(
                    f'<div class="step-card"><div class="step-label">{r["name"]}</div>'
                    f'<div class="step-value" style="color:{RED}">{r["blocked_reason"] or "No reason recorded"}</div></div>',
                    unsafe_allow_html=True,
                )

    # T1 audit report
    st.markdown(_section("T1 Audit Report"), unsafe_allow_html=True)
    report_md = _audit_report(run.run_id, run.mapping_path)
    if report_md:
        st.markdown(report_md)
    else:
        st.info(
            "No `audit_report_t1.md` found in this run directory. "
            "The T1 audit report is generated separately and uploaded to the run folder."
        )


def main():
    run, page = _sidebar()
    if not run:
        st.info("Select a run from the sidebar to get started.")
        return

    _phase_bar(page)

    if page == "1. Profiling":
        page_profiling(run)
    elif page == "2. Mapping Run":
        page_mapping_run(run)
    elif page == "3. Combine SQL":
        page_combine_sql(run)
    elif page == "4. Audit Report":
        page_audit_report(run)


if __name__ == "__main__":
    main()
