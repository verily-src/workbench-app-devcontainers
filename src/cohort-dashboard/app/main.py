"""Cohort Dashboard — no-code cohort exploration over Aurora PostgreSQL.

A Panel app. All data access is SQL against one Aurora connection: native
tables, views, and aurora_analytics foreign tables that read Parquet or
Iceberg directly from S3. For local development without a workspace,
upload a CSV/TSV instead.

Run with:  panel serve main.py --port 8080
"""

import io
import logging

import hvplot.pandas  # noqa: F401 — registers the DataFrame.hvplot accessor
import pandas as pd
import panel as pn

import db
import lineage
import queries

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

pn.extension("tabulator", throttled=True, notifications=True)

GRID_PAGE_SIZE = 25
BAR_TOP_N = 25
CHART_OPTS = {"responsive": True, "min_height": 300}

# panel serve re-runs this script per browser session, so everything below
# is per-session state. Only the caches inside db.py are shared.
state = {
    "df": None,            # full loaded DataFrame (capped at queries.ROW_CAP)
    "source": "",          # human-readable datasource label
    "engine": None,        # SQLAlchemy engine for the active resource
    "region": "us-east-1", # region of the active resource, for foreign tables
}
filter_widgets: dict[str, pn.widgets.Widget] = {}
chart_configs: list[dict] = []


# ---------------------------------------------------------------- filtering

def filtered_df() -> pd.DataFrame:
    df = state["df"]
    if df is None:
        return pd.DataFrame()
    for col, widget in filter_widgets.items():
        if isinstance(widget, pn.widgets.MultiChoice):
            if widget.value:
                df = df[df[col].astype(str).isin(widget.value)]
        elif isinstance(widget, pn.widgets.RangeSlider):
            lo, hi = widget.value
            if (lo, hi) != (widget.start, widget.end):
                df = df[df[col].between(lo, hi)]
    return df


def build_filter_widgets(df: pd.DataFrame):
    filter_widgets.clear()
    kinds = queries.infer_filter_kinds(df)
    for col, kind in kinds.items():
        if kind == "categorical":
            options = sorted(df[col].dropna().astype(str).unique().tolist())
            widget = pn.widgets.MultiChoice(name=col, options=options,
                                            placeholder="All values")
        elif kind == "range":
            lo, hi = float(df[col].min()), float(df[col].max())
            if lo == hi:
                continue
            widget = pn.widgets.RangeSlider(name=col, start=lo, end=hi,
                                            value=(lo, hi))
        else:
            continue
        widget.param.watch(lambda _event: refresh(), "value")
        filter_widgets[col] = widget
    filter_box.objects = list(filter_widgets.values()) or [
        pn.pane.Markdown("*No filterable columns found.*")
    ]


def reset_filters(_event=None):
    for widget in filter_widgets.values():
        if isinstance(widget, pn.widgets.MultiChoice):
            widget.value = []
        elif isinstance(widget, pn.widgets.RangeSlider):
            widget.value = (widget.start, widget.end)
    refresh()


# ------------------------------------------------------------------- charts

def numeric_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]


def render_chart(df: pd.DataFrame, config: dict):
    kind, x, y = config["kind"], config["x"], config.get("y")
    if df.empty or x not in df.columns:
        return pn.pane.Markdown("*No data for this chart.*")
    try:
        if kind == "bar":
            counts = (df[x].astype(str).value_counts().head(BAR_TOP_N)
                      .rename_axis(x).reset_index(name="count"))
            return counts.hvplot.bar(x=x, y="count", rot=45, **CHART_OPTS)
        if kind == "histogram":
            return df.hvplot.hist(x, bins=30, **CHART_OPTS)
        if kind == "kde":
            return df.hvplot.kde(x, **CHART_OPTS)
        if kind == "box":
            if y:
                return df.hvplot.box(y=x, by=y, rot=45, **CHART_OPTS)
            return df.hvplot.box(y=x, **CHART_OPTS)
        if kind == "scatter":
            return df.hvplot.scatter(x=x, y=y, alpha=0.5, **CHART_OPTS)
        if kind == "heatmap":
            counts = df.groupby([x, y], observed=True).size().reset_index(name="count")
            return counts.hvplot.heatmap(x=x, y=y, C="count", rot=45, **CHART_OPTS)
    except Exception as e:
        return pn.pane.Markdown(f"*Chart failed: {e}*")
    return pn.pane.Markdown(f"*Unknown chart type: {kind}*")


def chart_card(df: pd.DataFrame, config: dict) -> pn.Card:
    title = f"{config['kind']}: {config['x']}" + (
        f" × {config['y']}" if config.get("y") else "")
    remove = pn.widgets.Button(name="✕", width=30, align="end")

    def _remove(_event):
        chart_configs.remove(config)
        refresh()

    remove.on_click(_remove)
    return pn.Card(render_chart(df, config), header=pn.Row(
        pn.pane.Markdown(f"**{title}**"), pn.Spacer(), remove),
        width=520, collapsible=False)


TWO_FIELD_KINDS = ("scatter", "heatmap")
NUMERIC_KINDS = ("histogram", "kde", "box", "scatter")


def update_chart_selectors():
    df = state["df"]
    if df is None:
        return
    kind = chart_kind_select.value
    if kind in ("bar", "heatmap"):
        chart_x_select.options = list(df.columns)
    elif kind in NUMERIC_KINDS:
        chart_x_select.options = numeric_columns(df)
    chart_y_select.visible = kind in TWO_FIELD_KINDS or kind == "box"
    if kind == "scatter":
        chart_y_select.options = numeric_columns(df)
    elif kind == "heatmap":
        chart_y_select.options = list(df.columns)
    elif kind == "box":
        categorical = [c for c in df.columns
                       if not pd.api.types.is_numeric_dtype(df[c])]
        chart_y_select.options = [""] + categorical


def add_chart(_event):
    if state["df"] is None or not chart_x_select.value:
        return
    config = {"kind": chart_kind_select.value, "x": chart_x_select.value}
    if chart_y_select.visible and chart_y_select.value:
        config["y"] = chart_y_select.value
    chart_configs.append(config)
    refresh()


# ------------------------------------------------------------------ refresh

def refresh():
    df = filtered_df()
    total = len(state["df"]) if state["df"] is not None else 0
    cap_note = (" (display capped)" if total >= queries.ROW_CAP else "")
    count_pane.object = (
        f"### {state['source']}\n**{len(df):,}** of **{total:,}** rows{cap_note}")
    grid.value = df
    chart_box.objects = [chart_card(df, c) for c in chart_configs] or [
        pn.pane.Markdown("*Add a chart with the controls above.*")
    ]


def load_dataframe(df: pd.DataFrame, source: str):
    state["df"] = df
    state["source"] = source
    chart_configs.clear()
    build_filter_widgets(df)
    update_chart_selectors()
    refresh()
    pn.state.notifications.success(f"Loaded {len(df):,} rows from {source}")


# ------------------------------------------------------- datasource loading

resource_select = pn.widgets.Select(name="Aurora resource", options=[])
table_select = pn.widgets.Select(name="Table", options=[])
load_button = pn.widgets.Button(name="Load table", button_type="primary")
status_pane = pn.pane.Markdown("Connecting to workspace…")

csv_input = pn.widgets.FileInput(accept=".csv,.tsv,.txt", name="Upload CSV/TSV")

s3_name_input = pn.widgets.TextInput(name="Table name", placeholder="my_s3_table")
s3_location_input = pn.widgets.TextInput(name="S3 location",
                                         placeholder="s3://bucket/path/")
s3_format_select = pn.widgets.Select(name="Format",
                                     options=["parquet", "iceberg"])
s3_register_button = pn.widgets.Button(name="Register S3 data",
                                       button_type="success")


def active_engine():
    resource_id = resource_select.value
    if not resource_id:
        return None
    return db.get_engine_for_resource(resource_id)


def lineage_engine():
    """Aurora when connected, SQLite file otherwise (local CSV mode)."""
    return active_engine() or lineage.sqlite_fallback_engine()


def on_resource_change(_event=None):
    engine = active_engine()
    if engine is None:
        return
    for r in db.list_aurora_resources():
        if r["id"] == resource_select.value and r.get("region"):
            state["region"] = r["region"]
    table_select.loading = True
    try:
        tables = queries.list_tables(engine)
        table_select.options = {
            f"{t['name']} ({t['kind']})": t["name"] for t in tables}
    except Exception as e:
        pn.state.notifications.error(f"Could not list tables: {e}", duration=0)
        table_select.options = []
    finally:
        table_select.loading = False


def on_load_table(_event):
    engine = active_engine()
    if engine is None or not table_select.value:
        return
    load_button.loading = True
    try:
        df = queries.fetch_table(engine, table_select.value)
        load_dataframe(df, f"{resource_select.value} / {table_select.value}")
        lineage.record(
            engine, "table_loaded", "table", table_select.value,
            payload={"resource_id": resource_select.value, "rows": len(df),
                     "row_cap": queries.ROW_CAP})
    except Exception as e:
        pn.state.notifications.error(f"Load failed: {e}", duration=0)
    finally:
        load_button.loading = False


def on_csv_upload(_event):
    if not csv_input.value:
        return
    sep = "\t" if csv_input.filename.lower().endswith((".tsv", ".txt")) else ","
    df = pd.read_csv(io.BytesIO(csv_input.value), sep=sep)
    load_dataframe(df, csv_input.filename)
    lineage.record(
        lineage_engine(), "csv_uploaded", "file", csv_input.filename,
        payload={"rows": len(df), "columns": list(df.columns)})


def on_register_s3(_event):
    engine = active_engine()
    if engine is None:
        pn.state.notifications.warning("Select an Aurora resource first.")
        return
    s3_register_button.loading = True
    try:
        queries.create_s3_foreign_table(
            engine,
            name=s3_name_input.value.strip(),
            location=s3_location_input.value.strip(),
            file_format=s3_format_select.value,
            region=state["region"],
        )
        pn.state.notifications.success(
            f"Registered {s3_name_input.value} — select it in the table list.")
        lineage.record(
            engine, "s3_registered", "table", s3_name_input.value.strip(),
            payload={"location": s3_location_input.value.strip(),
                     "format": s3_format_select.value,
                     "region": state["region"]},
            parents=[("s3", s3_location_input.value.strip())])
        on_resource_change()
    except Exception as e:
        pn.state.notifications.error(f"Registration failed: {e}", duration=0)
    finally:
        s3_register_button.loading = False


demo_table_button = pn.widgets.Button(name="Create synthetic demo table")
gtex_button = pn.widgets.Button(name="Load GTEx V8 sample data",
                                button_type="primary")


def _seed(button, action, label):
    engine = active_engine()
    if engine is None:
        pn.state.notifications.warning("Select an Aurora resource first.")
        return
    button.loading = True
    try:
        action(engine)
        pn.state.notifications.success(f"{label} ready — select it above.")
        on_resource_change()
    except Exception as e:
        pn.state.notifications.error(f"{label} failed: {e}", duration=0)
    finally:
        button.loading = False


def _seed_demo(engine):
    name = queries.create_demo_table(engine)
    lineage.record(engine, "demo_table_created", "table", name,
                   payload={"rows": 500})


def _seed_gtex(engine):
    rows = queries.load_gtex_samples(engine)
    lineage.record(engine, "gtex_loaded", "table", "gtex_samples",
                   payload={"rows": rows, "source": queries.GTEX_SAMPLES_URL},
                   parents=[("url", queries.GTEX_SAMPLES_URL)])


demo_table_button.on_click(
    lambda _e: _seed(demo_table_button, _seed_demo, "demo_samples"))
gtex_button.on_click(
    lambda _e: _seed(gtex_button, _seed_gtex, "gtex_samples"))


def poll_resources():
    """Populate the resource list once the shared cache warms up."""
    if not db.resources_ready():
        return
    resources = db.list_aurora_resources()
    resource_select.options = [r["id"] for r in resources]
    if resources:
        status_pane.object = f"**{len(resources)}** Aurora resource(s) found"
    else:
        status_pane.object = ("*No Aurora resources in this workspace. "
                              "Upload a CSV below to explore local data.*")
    _resource_poller.stop()


# -------------------------------------------------------------- page layout

resource_select.param.watch(on_resource_change, "value")
load_button.on_click(on_load_table)
csv_input.param.watch(on_csv_upload, "value")
s3_register_button.on_click(on_register_s3)

count_pane = pn.pane.Markdown("### No data loaded")
grid = pn.widgets.Tabulator(
    pd.DataFrame(), pagination="local", page_size=GRID_PAGE_SIZE,
    disabled=True, sizing_mode="stretch_width", show_index=False)
filter_box = pn.Column(pn.pane.Markdown("*Load a table to see filters.*"))
reset_button = pn.widgets.Button(name="Reset filters")
reset_button.on_click(reset_filters)
chart_box = pn.FlexBox()

chart_kind_select = pn.widgets.Select(
    name="Chart type",
    options=["bar", "histogram", "kde", "box", "scatter", "heatmap"],
    width=130)
chart_x_select = pn.widgets.Select(name="Field", options=[], width=180)
chart_y_select = pn.widgets.Select(name="Second field", options=[],
                                   visible=False, width=180)
add_chart_button = pn.widgets.Button(name="+ Add chart", button_type="primary",
                                     align="end")
chart_kind_select.param.watch(lambda _event: update_chart_selectors(), "value")
add_chart_button.on_click(add_chart)


def export_tsv() -> io.BytesIO:
    df = filtered_df()
    buffer = io.BytesIO()
    df.to_csv(buffer, sep="\t", index=False)
    buffer.seek(0)
    lineage.record(
        lineage_engine(), "export", "export", state["source"],
        payload={"rows": len(df),
                 "filters": {col: list(w.value) for col, w in
                             filter_widgets.items() if w.value}},
        parents=[("table", state["source"])])
    return buffer


export_button = pn.widgets.FileDownload(
    callback=export_tsv, filename="cohort.tsv", label="Export TSV",
    button_type="default", align="end")

sidebar = pn.Column(
    status_pane,
    pn.pane.Markdown("## Datasource"),
    resource_select,
    table_select,
    load_button,
    pn.Accordion(
        ("Upload CSV/TSV (local dev)", pn.Column(csv_input)),
        ("Seed demo data", pn.Column(
            pn.pane.Markdown(
                "*Loads open-access [GTEx V8](https://gtexportal.org/home/) "
                "sample attributes (~22k rows) or a 500-row synthetic table "
                "into the selected Aurora database.*"),
            gtex_button, demo_table_button)),
        ("Register S3 data (aurora_analytics)", pn.Column(
            pn.pane.Markdown(
                "*Creates a foreign table reading Parquet/Iceberg directly "
                "from S3. Requires Aurora PostgreSQL 17.11+ with the "
                "aurora_analytics extension enabled on the cluster.*"),
            s3_name_input, s3_location_input, s3_format_select,
            s3_register_button)),
    ),
    pn.pane.Markdown("## Filters"),
    reset_button,
    filter_box,
)

lineage_grid = pn.widgets.Tabulator(
    lineage.recent_events(lineage.sqlite_fallback_engine()),
    pagination="local", page_size=GRID_PAGE_SIZE, disabled=True,
    sizing_mode="stretch_width", show_index=False)
lineage_refresh_button = pn.widgets.Button(name="Refresh lineage")


def refresh_lineage(_event=None):
    lineage_grid.value = lineage.recent_events(lineage_engine())


lineage_refresh_button.on_click(refresh_lineage)

explore_tab = pn.Column(
    pn.Row(count_pane, pn.Spacer(), export_button),
    pn.Row(chart_kind_select, chart_x_select, chart_y_select, add_chart_button),
    chart_box,
    pn.pane.Markdown("## Rows"),
    grid,
)

lineage_tab = pn.Column(
    pn.pane.Markdown(
        "Loads, S3 registrations, and exports are recorded in the active "
        "Aurora database (`_lineage_event` / `_lineage_edge`), or a local "
        "SQLite file when no resource is connected."),
    lineage_refresh_button,
    lineage_grid,
)

main = pn.Tabs(("Explore", explore_tab), ("Lineage", lineage_tab))


def on_tab_change(event):
    if event.new == 1:
        refresh_lineage()


main.param.watch(on_tab_change, "active")

db.warm_resource_cache()
_resource_poller = pn.state.add_periodic_callback(poll_resources, period=2000)

pn.template.FastListTemplate(
    title="Cohort Dashboard",
    sidebar=[sidebar],
    main=[main],
    accent="#4a148c",
).servable()
