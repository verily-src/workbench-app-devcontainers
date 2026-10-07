"""Cohort Dashboard — no-code cohort exploration over Aurora PostgreSQL.

A Panel app styled after the cBioPortal study-summary page: loading a table
auto-generates a grid of distribution charts, every chart shows the full
cohort muted with the filtered cohort overlaid, tapping a bar filters the
cohort, and active filters appear as removable chips. Verily Workbench
colors throughout; light mode only.

All data access is SQL against one Aurora connection: native tables, views,
and aurora_analytics foreign tables that read Parquet/Iceberg directly from
S3. For local development without a workspace, upload a CSV/TSV instead.

Run with:  panel serve main.py --port 8080
"""

import io
import logging

import pandas as pd
import panel as pn

import charts
import db
import lineage
import queries

# force=True because Bokeh configures the root logger before this script
# runs, which would make a plain basicConfig a silent no-op and hide all
# app logs from the VM log pipeline.
logging.basicConfig(level=logging.INFO, force=True)
logger = logging.getLogger(__name__)


def short_error(e: Exception, limit: int = 200) -> str:
    """Database errors can embed entire SQL statements; keep toasts readable."""
    text = str(e).split("\n")[0]
    return text if len(text) <= limit else text[:limit] + "…"


VERILY_TEAL = "#087a6a"
FONT_URL = ("https://fonts.googleapis.com/css2?"
            "family=Inter:wght@400;500;600&display=swap")
FONT_STACK = ("Inter, -apple-system, 'SF Pro Text', 'Segoe UI', "
              "'Open Sans', sans-serif")

# Linear-inspired chrome: neutral surfaces, 1px borders instead of heavy
# shadows, Inter at small sizes, Verily teal as the single accent.
CSS = f"""
body {{ font-family: {FONT_STACK}; background: #fafafa; }}
#header {{
  box-shadow: none !important;
  border-bottom: 1px solid #e9e8ea;
}}
.title {{
  font-family: {FONT_STACK} !important;
  font-size: 14px !important; font-weight: 600 !important;
  letter-spacing: -0.01em;
}}
.chart-card {{
  background: #ffffff;
  border: 1px solid #e9e8ea;
  border-radius: 8px;
  box-shadow: 0 1px 2px rgba(0,0,0,.03);
  padding: 8px 12px 2px 12px;
  transition: border-color .12s ease;
}}
.chart-card:hover {{ border-color: #cfd0d3; }}
.card-title {{
  font-family: {FONT_STACK};
  font-weight: 500; font-size: 12px; color: #3c4043;
  letter-spacing: -0.01em;
}}
.hero-count {{
  font-family: {FONT_STACK};
  font-weight: 600; font-size: 22px; color: #17181a;
  letter-spacing: -0.02em;
}}
.hero-count .total {{ color: #6b6f76; font-weight: 500; font-size: 13px; }}
"""


def section_label(text: str) -> pn.pane.HTML:
    """Linear-style sidebar section label: 11px uppercase, muted."""
    return pn.pane.HTML(
        f'<div style="font-family:{FONT_STACK};font-size:11px;'
        f'font-weight:600;letter-spacing:.08em;text-transform:uppercase;'
        f'color:#6b6f76;margin:14px 0 2px 0;">{text}</div>')


# Panel widgets render in shadow DOM, so page-level CSS cannot reach a
# button's internals — these are injected per widget via `stylesheets`.
PRIMARY_BTN = f"""
:host .bk-btn, :host button {{
  background: {VERILY_TEAL}; color: #fff; border: none; border-radius: 6px;
  font-family: {FONT_STACK}; font-size: 12.5px; font-weight: 500;
  padding: 5px 14px; box-shadow: 0 1px 2px rgba(0,0,0,.05);
}}
:host .bk-btn:hover, :host button:hover {{ background: #065f53; }}
"""
GHOST_BTN = f"""
:host .bk-btn, :host button {{
  background: #fff; color: #3c4043; border: 1px solid #dcdbdd;
  border-radius: 6px; font-family: {FONT_STACK}; font-size: 12.5px;
  font-weight: 500; padding: 5px 12px; box-shadow: none;
}}
:host .bk-btn:hover, :host button:hover {{
  background: #f4f4f5; border-color: #c9c8cc;
}}
"""
CHIP_STYLE = f"""
:host .bk-btn, :host button {{
  border-radius: 999px; background: #eef5f3; color: #054f45;
  border: 1px solid #cfe0dc; font-family: {FONT_STACK};
  font-size: 12px; padding: 2px 10px;
}}
:host .bk-btn:hover, :host button:hover {{ background: #ddebe7; }}
"""
CHIP_CLEAR_STYLE = f"""
:host .bk-btn, :host button {{
  border-radius: 999px; background: transparent; color: #6b6f76;
  border: 1px solid #dcdbdd; font-family: {FONT_STACK};
  font-size: 12px; padding: 2px 10px;
}}
:host .bk-btn:hover, :host button:hover {{ background: #f4f4f5; }}
"""
QUIET_STYLE = f"""
:host .bk-btn, :host button {{
  background: transparent; color: #9095a0; border: none;
  font-size: 13px; padding: 0 4px; box-shadow: none;
}}
:host .bk-btn:hover, :host button:hover {{ color: #17181a; }}
"""

pn.extension("tabulator", throttled=True, notifications=True, raw_css=[CSS])

GRID_PAGE_SIZE = 25
AUTO_CHART_LIMIT = 8
CARD_W, CARD_W_WIDE = 390, 800

# panel serve re-runs this script per browser session, so everything below
# is per-session state. Only the caches inside db.py are shared.
state = {
    "df": None,            # full loaded DataFrame (capped at queries.ROW_CAP)
    "source": "",          # human-readable datasource label
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


def toggle_category(col: str, value: str):
    """Tap-to-filter: toggle one category in the column's filter widget."""
    widget = filter_widgets.get(col)
    if not isinstance(widget, pn.widgets.MultiChoice):
        return
    current = list(widget.value)
    if value in current:
        current.remove(value)
    else:
        current.append(value)
    widget.value = current  # watcher triggers refresh()


def reset_filters(_event=None):
    for widget in filter_widgets.values():
        if isinstance(widget, pn.widgets.MultiChoice):
            widget.value = []
        elif isinstance(widget, pn.widgets.RangeSlider):
            widget.value = (widget.start, widget.end)
    refresh()


def active_filters() -> list[tuple[str, str, callable]]:
    """(column, display text, clear-callback) per active filter value."""
    chips = []
    for col, widget in filter_widgets.items():
        if isinstance(widget, pn.widgets.MultiChoice):
            for val in widget.value:
                chips.append((col, f"{col}: {val}",
                              lambda c=col, v=val: toggle_category(c, v)))
        elif isinstance(widget, pn.widgets.RangeSlider):
            lo, hi = widget.value
            if (lo, hi) != (widget.start, widget.end):
                def _clear(w=widget):
                    w.value = (w.start, w.end)
                chips.append((col, f"{col}: {lo:g}–{hi:g}", _clear))
    return chips


# ------------------------------------------------------------------- charts

def numeric_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]


def auto_chart_configs(df: pd.DataFrame) -> list[dict]:
    """cBioPortal-style: one chart per informative column, best form first."""
    kinds = queries.infer_filter_kinds(df)
    configs = []
    for col, kind in kinds.items():
        if kind == "categorical" and df[col].nunique(dropna=True) >= 2:
            configs.append({"kind": "bar", "x": col, "wide": False})
        elif kind == "range":
            configs.append({"kind": "histogram", "x": col, "wide": False})
    return configs[:AUTO_CHART_LIMIT]


def chart_card(df_full: pd.DataFrame, df_filt: pd.DataFrame,
               config: dict) -> pn.Column:
    obj = charts.build(config["kind"], df_full, df_filt, config,
                       on_tap=toggle_category)
    body = (pn.pane.HoloViews(obj, sizing_mode="stretch_width",
                              linked_axes=False)
            if obj is not None else
            pn.pane.Markdown("*No data for this chart.*"))

    title = config["x"] + (f" × {config['y']}" if config.get("y") else "")
    close = pn.widgets.Button(name="✕", width=28, align="center",
                              stylesheets=[QUIET_STYLE])
    wide = pn.widgets.Button(name="⤢", width=28, align="center",
                             stylesheets=[QUIET_STYLE])

    def _close(_event):
        chart_configs.remove(config)
        refresh()

    def _wide(_event):
        config["wide"] = not config.get("wide")
        refresh()

    close.on_click(_close)
    wide.on_click(_wide)
    return pn.Column(
        pn.Row(pn.pane.HTML(f'<span class="card-title">{title}</span>'),
               pn.Spacer(), wide, close, height=34),
        body,
        css_classes=["chart-card"],
        width=CARD_W_WIDE if config.get("wide") else CARD_W,
    )


chart_field_input = pn.widgets.AutocompleteInput(
    name="Add chart", options=[], placeholder="Search columns…",
    case_sensitive=False, min_characters=0, width=220)
chart_kind_select = pn.widgets.Select(
    name="Type", options=["auto", "bar", "histogram", "box", "scatter",
                          "heatmap"], width=110)
chart_y_select = pn.widgets.Select(name="Second field", options=[],
                                   visible=False, width=180)
add_chart_button = pn.widgets.Button(name="Add", button_type="primary",
                                     align="end", width=70,
                                     stylesheets=[PRIMARY_BTN])


def _default_kind(col: str) -> str:
    df = state["df"]
    if df is not None and pd.api.types.is_numeric_dtype(df[col]) \
            and df[col].nunique(dropna=True) > queries.CATEGORICAL_THRESHOLD:
        return "histogram"
    return "bar"


def on_kind_change(_event=None):
    df = state["df"]
    if df is None:
        return
    kind = chart_kind_select.value
    chart_y_select.visible = kind in ("scatter", "heatmap", "box")
    if kind == "scatter":
        chart_y_select.options = numeric_columns(df)
    elif kind == "heatmap":
        chart_y_select.options = list(df.columns)
    elif kind == "box":
        chart_y_select.options = [""] + [
            c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]


def add_chart(_event):
    df, col = state["df"], chart_field_input.value
    if df is None or col not in df.columns:
        return
    kind = chart_kind_select.value
    if kind == "auto":
        kind = _default_kind(col)
    config = {"kind": kind, "x": col,
              "wide": kind in ("scatter", "heatmap")}
    if chart_y_select.visible and chart_y_select.value:
        config["y"] = chart_y_select.value
    chart_configs.append(config)
    chart_field_input.value = ""
    refresh()


chart_kind_select.param.watch(on_kind_change, "value")
add_chart_button.on_click(add_chart)


# ------------------------------------------------------------------ refresh

def refresh():
    df_full = state["df"]
    df = filtered_df()
    total = len(df_full) if df_full is not None else 0
    cap_note = (" · display capped" if total >= queries.ROW_CAP else "")
    count_pane.object = (
        f'<div class="hero-count">{len(df):,} '
        f'<span class="total">of {total:,} rows · {state["source"]}'
        f'{cap_note}</span></div>')

    chips = []
    for _col, text, clear in active_filters():
        btn = pn.widgets.Button(name=f"{text} ✕", css_classes=["chip"],
                                stylesheets=[CHIP_STYLE])
        btn.on_click(lambda _e, clear=clear: clear())
        chips.append(btn)
    if chips:
        clear_all = pn.widgets.Button(name="Clear all",
                                      css_classes=["chip-clear"],
                                      stylesheets=[CHIP_CLEAR_STYLE])
        clear_all.on_click(reset_filters)
        chips.append(clear_all)
    chip_box.objects = chips

    grid.value = df
    if df_full is not None:
        chart_box.objects = [chart_card(df_full, df, c)
                             for c in chart_configs]


def load_dataframe(df: pd.DataFrame, source: str):
    state["df"] = df
    state["source"] = source
    chart_configs.clear()
    chart_configs.extend(auto_chart_configs(df))
    build_filter_widgets(df)
    chart_field_input.options = list(df.columns)
    chart_kind_select.value = "auto"
    on_kind_change()
    refresh()
    pn.state.notifications.success(f"Loaded {len(df):,} rows from {source}")


# ------------------------------------------------------- datasource loading

resource_select = pn.widgets.Select(name="Aurora resource", options=[])
table_select = pn.widgets.Select(name="Table", options=[])
load_button = pn.widgets.Button(name="Load table", button_type="primary",
                                stylesheets=[PRIMARY_BTN])
status_pane = pn.pane.Markdown("Connecting to workspace…")

csv_input = pn.widgets.FileInput(accept=".csv,.tsv,.txt", name="Upload CSV/TSV")

s3_name_input = pn.widgets.TextInput(name="Table name", placeholder="my_s3_table")
s3_location_input = pn.widgets.TextInput(name="S3 location",
                                         placeholder="s3://bucket/path/")
s3_format_select = pn.widgets.Select(name="Format",
                                     options=["parquet", "iceberg"])
s3_register_button = pn.widgets.Button(name="Register S3 data",
                                       button_type="primary",
                                       stylesheets=[PRIMARY_BTN])


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
        pn.state.notifications.error(
            f"Could not list tables: {short_error(e)}", duration=0)
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
        pn.state.notifications.error(f"Load failed: {short_error(e)}",
                                     duration=0)
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
        pn.state.notifications.error(f"Registration failed: {short_error(e)}",
                                     duration=0)
    finally:
        s3_register_button.loading = False


demo_table_button = pn.widgets.Button(name="Create synthetic demo table",
                                      stylesheets=[GHOST_BTN])
gtex_button = pn.widgets.Button(name="Load GTEx V8 sample data",
                                button_type="primary",
                                stylesheets=[PRIMARY_BTN])


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
        pn.state.notifications.error(f"{label} failed: {short_error(e)}",
                                     duration=0)
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

count_pane = pn.pane.HTML('<div class="hero-count">No data loaded</div>')
chip_box = pn.FlexBox()
grid = pn.widgets.Tabulator(
    pd.DataFrame(), pagination="local", page_size=GRID_PAGE_SIZE,
    disabled=True, sizing_mode="stretch_width", show_index=False)
filter_box = pn.Column(pn.pane.Markdown("*Load a table to see filters.*"))
reset_button = pn.widgets.Button(name="Reset filters",
                                 stylesheets=[GHOST_BTN])
reset_button.on_click(reset_filters)
chart_box = pn.FlexBox(pn.pane.Markdown(
    "*Load a table — charts are generated automatically.*"))


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
    button_type="default", align="end", stylesheets=[GHOST_BTN])

sidebar = pn.Column(
    status_pane,
    section_label("Datasource"),
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
    section_label("Filters"),
    reset_button,
    filter_box,
)

lineage_grid = pn.widgets.Tabulator(
    lineage.recent_events(lineage.sqlite_fallback_engine()),
    pagination="local", page_size=GRID_PAGE_SIZE, disabled=True,
    sizing_mode="stretch_width", show_index=False)
lineage_refresh_button = pn.widgets.Button(name="Refresh lineage",
                                           stylesheets=[GHOST_BTN])


def refresh_lineage(_event=None):
    lineage_grid.value = lineage.recent_events(lineage_engine())


lineage_refresh_button.on_click(refresh_lineage)

explore_tab = pn.Column(
    pn.Row(count_pane, pn.Spacer(), export_button),
    chip_box,
    pn.Row(chart_field_input, chart_kind_select, chart_y_select,
           add_chart_button),
    chart_box,
    section_label("Rows"),
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
    header_background="#ffffff",
    header_color="#17181a",
    accent_base_color=VERILY_TEAL,
    background_color="#fafafa",
    theme_toggle=False,
    main_layout=None,
    font="Open Sans",
    font_url=FONT_URL,
).servable()
