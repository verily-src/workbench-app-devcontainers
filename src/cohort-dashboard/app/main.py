"""Cohort Dashboard — no-code cohort exploration over Aurora PostgreSQL.

A Panel app styled after the cBioPortal study-summary page with Linear-
inspired chrome. Each loaded datasource opens as its own closable tab
holding an auto-generated chart dashboard: every chart shows the full
cohort muted with the filtered cohort overlaid, tapping a bar filters,
and active filters appear as removable chips. The sidebar filter panel
follows the active tab.

Datasources: Aurora tables/views (SQLAlchemy), Parquet/CSV in workspace
S3 folders (DuckDB reading S3 directly), BigQuery datasets on GCP
workspaces, and local CSV upload for development.

Run with:  panel serve main.py --port 8080
"""

import io
import logging
from contextlib import contextmanager

import pandas as pd
import panel as pn

import bq
import charts
import db
import duck
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
.activity {{
  font-family: {FONT_STACK}; font-size: 12.5px; font-weight: 500;
  color: #6b6f76; display: flex; align-items: center; gap: 7px;
}}
.activity .pulse {{
  width: 8px; height: 8px; border-radius: 50%; background: {VERILY_TEAL};
  animation: cd-pulse 1s ease-in-out infinite;
}}
@keyframes cd-pulse {{
  0%, 100% {{ opacity: .25; transform: scale(.8); }}
  50% {{ opacity: 1; transform: scale(1); }}
}}
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
INPUT_STYLE = f"""
:host input.bk-input, :host select.bk-input {{
  border: 1px solid #dcdbdd; border-radius: 6px; background: #fff;
  font-family: {FONT_STACK}; font-size: 13px; min-height: 30px;
}}
:host input.bk-input:focus, :host select.bk-input:focus {{
  border-color: {VERILY_TEAL}; box-shadow: 0 0 0 2px rgba(8,122,106,.15);
}}
:host label {{ font-family: {FONT_STACK}; font-size: 12px; color: #3c4043; }}
"""
ACCORDION_STYLE = f"""
:host .accordion {{ border: 1px solid #e9e8ea; border-radius: 8px;
  box-shadow: none; }}
:host .card-header, :host button.accordion-header {{
  background: #fff; box-shadow: none;
  font-family: {FONT_STACK}; font-size: 12.5px; font-weight: 500;
  color: #3c4043;
}}
"""

pn.extension("tabulator", throttled=True, notifications=True, raw_css=[CSS])

GRID_PAGE_SIZE = 25
AUTO_CHART_LIMIT = 8
CARD_W, CARD_W_WIDE = 390, 800


# ------------------------------------------------------- global activity

activity_pane = pn.pane.HTML("", height=24)


@contextmanager
def busy(message: str):
    """Show a pulsing activity indicator while a slow operation runs."""
    activity_pane.object = (
        f'<div class="activity"><span class="pulse"></span>{message}</div>')
    try:
        yield
    finally:
        activity_pane.object = ""


# ------------------------------------------------------------ dataset tab

class DatasetView:
    """One loaded dataset: its data, filters, charts, grid, and tab pane."""

    def __init__(self, df: pd.DataFrame, source: str):
        self.df = df
        self.source = source
        self.filter_widgets: dict[str, pn.widgets.Widget] = {}
        self.chart_configs: list[dict] = []

        self.count_pane = pn.pane.HTML("")
        self.chip_box = pn.FlexBox()
        self.chart_box = pn.FlexBox()
        self.grid = pn.widgets.Tabulator(
            pd.DataFrame(), pagination="local", page_size=GRID_PAGE_SIZE,
            disabled=True, sizing_mode="stretch_width", show_index=False)

        self.field_input = pn.widgets.AutocompleteInput(
            name="Add chart", options=list(df.columns),
            placeholder="Search columns…", case_sensitive=False,
            min_characters=0, width=220, stylesheets=[INPUT_STYLE])
        self.kind_select = pn.widgets.Select(
            name="Type", options=["auto", "bar", "histogram", "box",
                                  "scatter", "heatmap"],
            width=110, stylesheets=[INPUT_STYLE])
        self.y_select = pn.widgets.Select(
            name="Second field", options=[], visible=False, width=180,
            stylesheets=[INPUT_STYLE])
        add_button = pn.widgets.Button(
            name="Add", button_type="primary", align="end", width=70,
            stylesheets=[PRIMARY_BTN])
        export_button = pn.widgets.FileDownload(
            callback=self.export_tsv, filename="cohort.tsv",
            label="Export TSV", align="end", stylesheets=[GHOST_BTN])

        self.kind_select.param.watch(lambda _e: self._on_kind_change(),
                                     "value")
        add_button.on_click(self._add_chart)

        self.panel = pn.Column(
            pn.Row(self.count_pane, pn.Spacer(), export_button),
            self.chip_box,
            pn.Row(self.field_input, self.kind_select, self.y_select,
                   add_button),
            self.chart_box,
            section_label("Rows"),
            self.grid,
        )

        self.chart_configs.extend(self._auto_chart_configs())
        self._build_filter_widgets()
        self._on_kind_change()
        self.refresh()

    # -------------------------------------------------------- filtering

    def filtered_df(self) -> pd.DataFrame:
        df = self.df
        for col, widget in self.filter_widgets.items():
            if isinstance(widget, pn.widgets.MultiChoice):
                if widget.value:
                    df = df[df[col].astype(str).isin(widget.value)]
            elif isinstance(widget, pn.widgets.RangeSlider):
                lo, hi = widget.value
                if (lo, hi) != (widget.start, widget.end):
                    df = df[df[col].between(lo, hi)]
        return df

    def _build_filter_widgets(self):
        kinds = queries.infer_filter_kinds(self.df)
        for col, kind in kinds.items():
            if kind == "categorical":
                options = sorted(
                    self.df[col].dropna().astype(str).unique().tolist())
                widget = pn.widgets.MultiChoice(
                    name=col, options=options, placeholder="All values")
            elif kind == "range":
                lo, hi = float(self.df[col].min()), float(self.df[col].max())
                if lo == hi:
                    continue
                widget = pn.widgets.RangeSlider(name=col, start=lo, end=hi,
                                                value=(lo, hi))
            else:
                continue
            widget.param.watch(lambda _e: self.refresh(), "value")
            self.filter_widgets[col] = widget

    def toggle_category(self, col: str, value: str):
        widget = self.filter_widgets.get(col)
        if not isinstance(widget, pn.widgets.MultiChoice):
            return
        current = list(widget.value)
        if value in current:
            current.remove(value)
        else:
            current.append(value)
        widget.value = current  # watcher triggers refresh()

    def reset_filters(self, _event=None):
        for widget in self.filter_widgets.values():
            if isinstance(widget, pn.widgets.MultiChoice):
                widget.value = []
            elif isinstance(widget, pn.widgets.RangeSlider):
                widget.value = (widget.start, widget.end)
        self.refresh()

    def _active_filters(self):
        chips = []
        for col, widget in self.filter_widgets.items():
            if isinstance(widget, pn.widgets.MultiChoice):
                for val in widget.value:
                    chips.append(
                        (f"{col}: {val}",
                         lambda c=col, v=val: self.toggle_category(c, v)))
            elif isinstance(widget, pn.widgets.RangeSlider):
                lo, hi = widget.value
                if (lo, hi) != (widget.start, widget.end):
                    def _clear(w=widget):
                        w.value = (w.start, w.end)
                    chips.append((f"{col}: {lo:g}–{hi:g}", _clear))
        return chips

    # ----------------------------------------------------------- charts

    def _numeric_columns(self) -> list[str]:
        return [c for c in self.df.columns
                if pd.api.types.is_numeric_dtype(self.df[c])]

    def _auto_chart_configs(self) -> list[dict]:
        kinds = queries.infer_filter_kinds(self.df)
        configs = []
        for col, kind in kinds.items():
            if kind == "categorical" \
                    and self.df[col].nunique(dropna=True) >= 2:
                configs.append({"kind": "bar", "x": col, "wide": False})
            elif kind == "range":
                configs.append({"kind": "histogram", "x": col, "wide": False})
        return configs[:AUTO_CHART_LIMIT]

    def _default_kind(self, col: str) -> str:
        if pd.api.types.is_numeric_dtype(self.df[col]) \
                and self.df[col].nunique(dropna=True) > queries.CATEGORICAL_THRESHOLD:
            return "histogram"
        return "bar"

    def _on_kind_change(self):
        kind = self.kind_select.value
        self.y_select.visible = kind in ("scatter", "heatmap", "box")
        if kind == "scatter":
            self.y_select.options = self._numeric_columns()
        elif kind == "heatmap":
            self.y_select.options = list(self.df.columns)
        elif kind == "box":
            self.y_select.options = [""] + [
                c for c in self.df.columns
                if not pd.api.types.is_numeric_dtype(self.df[c])]

    def _add_chart(self, _event):
        col = self.field_input.value
        if col not in self.df.columns:
            return
        kind = self.kind_select.value
        if kind == "auto":
            kind = self._default_kind(col)
        config = {"kind": kind, "x": col,
                  "wide": kind in ("scatter", "heatmap")}
        if self.y_select.visible and self.y_select.value:
            config["y"] = self.y_select.value
        self.chart_configs.append(config)
        self.field_input.value = ""
        self.refresh()

    def _chart_card(self, df_filt: pd.DataFrame, config: dict) -> pn.Column:
        obj = charts.build(config["kind"], self.df, df_filt, config,
                           on_tap=self.toggle_category)
        body = (pn.pane.HoloViews(obj, sizing_mode="stretch_width",
                                  linked_axes=False)
                if obj is not None else
                pn.pane.Markdown("*No data for this chart.*"))
        title = config["x"] + (f" × {config['y']}" if config.get("y") else "")
        close = pn.widgets.Button(name="✕", width=28, align="center",
                                  stylesheets=[QUIET_STYLE])
        wide = pn.widgets.Button(name="⤢", width=28, align="center",
                                 stylesheets=[QUIET_STYLE])

        def _close(_e):
            self.chart_configs.remove(config)
            self.refresh()

        def _wide(_e):
            config["wide"] = not config.get("wide")
            self.refresh()

        close.on_click(_close)
        wide.on_click(_wide)
        return pn.Column(
            pn.Row(pn.pane.HTML(f'<span class="card-title">{title}</span>'),
                   pn.Spacer(), wide, close, height=34),
            body,
            css_classes=["chart-card"],
            width=CARD_W_WIDE if config.get("wide") else CARD_W,
        )

    # ---------------------------------------------------------- refresh

    def refresh(self):
        df = self.filtered_df()
        total = len(self.df)
        cap_note = (" · display capped" if total >= queries.ROW_CAP else "")
        self.count_pane.object = (
            f'<div class="hero-count">{len(df):,} '
            f'<span class="total">of {total:,} rows · {self.source}'
            f'{cap_note}</span></div>')

        chips = []
        for text, clear in self._active_filters():
            btn = pn.widgets.Button(name=f"{text} ✕", css_classes=["chip"],
                                    stylesheets=[CHIP_STYLE])
            btn.on_click(lambda _e, clear=clear: clear())
            chips.append(btn)
        if chips:
            clear_all = pn.widgets.Button(name="Clear all",
                                          css_classes=["chip-clear"],
                                          stylesheets=[CHIP_CLEAR_STYLE])
            clear_all.on_click(self.reset_filters)
            chips.append(clear_all)
        self.chip_box.objects = chips

        self.grid.value = df
        self.chart_box.objects = [self._chart_card(df, c)
                                  for c in self.chart_configs]
        _sync_sidebar_filters()

    def export_tsv(self) -> io.BytesIO:
        df = self.filtered_df()
        buffer = io.BytesIO()
        df.to_csv(buffer, sep="\t", index=False)
        buffer.seek(0)
        lineage.record(
            lineage_engine(), "export", "export", self.source,
            payload={"rows": len(df),
                     "filters": {col: list(w.value) for col, w in
                                 self.filter_widgets.items() if w.value}},
            parents=[("table", self.source)])
        return buffer


# ------------------------------------------------------ dataset registry

datasets: list[DatasetView] = []
dataset_tabs = pn.Tabs(closable=True, visible=False,
                       sizing_mode="stretch_width")


def active_dataset() -> DatasetView | None:
    if not datasets or dataset_tabs.active >= len(datasets):
        return None
    return datasets[dataset_tabs.active]


def open_dataset(df: pd.DataFrame, source: str, tab_title: str):
    """Open a dataset in a new tab, or re-activate an existing tab."""
    for i, ds in enumerate(datasets):
        if ds.source == source:
            dataset_tabs.active = i
            pn.state.notifications.info(f"{tab_title} is already open.")
            return
    ds = DatasetView(df, source)
    datasets.append(ds)
    dataset_tabs.append((tab_title, ds.panel))
    dataset_tabs.active = len(datasets) - 1
    empty_state.visible = False
    dataset_tabs.visible = True
    pn.state.notifications.success(f"Loaded {len(df):,} rows from {source}")


def _on_tabs_change(event):
    """Keep the registry in sync when tabs are closed or switched."""
    if event.name == "objects":
        remaining = list(event.new)
        datasets[:] = [ds for ds in datasets if ds.panel in remaining]
        if not datasets:
            dataset_tabs.visible = False
            empty_state.visible = True
    _sync_sidebar_filters()


dataset_tabs.param.watch(_on_tabs_change, ["objects", "active"])


# ------------------------------------------------------- datasource loading

status_pane = pn.pane.HTML(
    '<div class="activity"><span class="pulse"></span>'
    'Connecting to workspace…</div>')
resource_select = pn.widgets.Select(name="Datasource", options={},
                                    stylesheets=[INPUT_STYLE])
table_select = pn.widgets.Select(name="Table", options=[],
                                 stylesheets=[INPUT_STYLE])
load_button = pn.widgets.Button(name="Load table", button_type="primary",
                                stylesheets=[PRIMARY_BTN])
csv_input = pn.widgets.FileInput(accept=".csv,.tsv,.txt", name="Upload CSV/TSV")

s3_name_input = pn.widgets.TextInput(name="Table name",
                                     placeholder="my_s3_table",
                                     stylesheets=[INPUT_STYLE])
s3_location_input = pn.widgets.TextInput(name="S3 location",
                                         placeholder="s3://bucket/path/",
                                         stylesheets=[INPUT_STYLE])
s3_format_select = pn.widgets.Select(name="Format",
                                     options=["parquet", "iceberg"],
                                     stylesheets=[INPUT_STYLE])
s3_register_button = pn.widgets.Button(name="Register S3 data",
                                       button_type="primary",
                                       stylesheets=[PRIMARY_BTN])

state = {"region": "us-east-1"}


def selected_source() -> tuple[str, str] | None:
    """(kind, id) of the selected datasource: aurora, s3, or bq."""
    return resource_select.value or None


def active_engine():
    source = selected_source()
    if not source or source[0] != "aurora":
        return None
    return db.get_engine_for_resource(source[1])


def lineage_engine():
    """Aurora when connected, SQLite file otherwise (S3/BQ/CSV modes)."""
    return active_engine() or lineage.sqlite_fallback_engine()


def _bq_coords(resource_id: str) -> tuple[str, str]:
    for d in db.list_bq_datasets():
        if d["id"] == resource_id:
            return d["project"], d["dataset"]
    raise ValueError(f"Unknown BigQuery dataset: {resource_id}")


def on_resource_change(_event=None):
    source = selected_source()
    if source is None:
        return
    kind, resource_id = source
    table_select.loading = True
    try:
        if kind == "aurora":
            for r in db.list_aurora_resources():
                if r["id"] == resource_id and r.get("region"):
                    state["region"] = r["region"]
            with busy(f"Listing tables in {resource_id}…"):
                tables = db.list_aurora_tables(resource_id)
            table_select.options = {
                f"{t['name']} ({t['kind']})": t["name"] for t in tables}
        elif kind == "s3":
            with busy(f"Listing files in {resource_id}…"):
                files = duck.list_s3_files(resource_id)
            table_select.options = {f: f for f in files}
            if not files:
                pn.state.notifications.info(
                    f"No Parquet/CSV/TSV files found in {resource_id} "
                    "(searched recursively).", duration=6000)
        elif kind == "bq":
            project, dataset = _bq_coords(resource_id)
            with busy(f"Listing tables in {dataset}…"):
                tables = bq.list_tables(project, dataset)
            table_select.options = {t: t for t in tables}
    except Exception as e:
        pn.state.notifications.error(
            f"Could not list tables: {short_error(e)}", duration=0)
        table_select.options = []
    finally:
        table_select.loading = False


def on_load_table(_event):
    source = selected_source()
    if source is None or not table_select.value:
        return
    kind, resource_id = source
    table = table_select.value
    load_button.loading = True
    try:
        with busy(f"Loading {table}…"):
            if kind == "aurora":
                df = db.fetch_aurora_table(resource_id, table,
                                           queries.ROW_CAP)
            elif kind == "s3":
                df = duck.fetch_s3_file(resource_id, table, queries.ROW_CAP)
            else:
                project, dataset = _bq_coords(resource_id)
                df = bq.fetch_table(project, dataset, table, queries.ROW_CAP)
        open_dataset(df, f"{resource_id} / {table}", table.split("/")[-1])
        lineage.record(
            lineage_engine(), "table_loaded", "table", table,
            payload={"resource_id": resource_id, "source_kind": kind,
                     "rows": len(df), "row_cap": queries.ROW_CAP})
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
    open_dataset(df, csv_input.filename, csv_input.filename)
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
        with busy(f"Registering {s3_name_input.value.strip()}…"):
            queries.create_s3_foreign_table(
                engine,
                name=s3_name_input.value.strip(),
                location=s3_location_input.value.strip(),
                file_format=s3_format_select.value,
                region=state["region"],
            )
        db.list_aurora_tables.invalidate()
        db.fetch_aurora_table.invalidate()
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
        with busy(f"Seeding {label}…"):
            action(engine)
        db.list_aurora_tables.invalidate()
        db.fetch_aurora_table.invalidate()
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
    """Populate the datasource list once the shared cache warms up."""
    if not db.resources_ready():
        return
    aurora = db.list_aurora_resources()
    s3 = db.list_s3_folders()
    bigquery = db.list_bq_datasets()
    options = {}
    for r in aurora:
        options[f"{r['id']} · Aurora"] = ("aurora", r["id"])
    for r in s3:
        options[f"{r['id']} · S3"] = ("s3", r["id"])
    for r in bigquery:
        options[f"{r['id']} · BigQuery"] = ("bq", r["id"])
    resource_select.options = options
    if options:
        parts = [f"{len(src)} {label}" for src, label in
                 ((aurora, "Aurora"), (s3, "S3"), (bigquery, "BigQuery"))
                 if src]
        status_pane.object = (
            f'<div style="font-family:{FONT_STACK};font-size:12.5px;'
            f'color:#3c4043;">{" · ".join(parts)}</div>')
    else:
        status_pane.object = (
            f'<div style="font-family:{FONT_STACK};font-size:12.5px;'
            f'color:#6b6f76;">No datasources in this workspace — upload a '
            f'CSV below to explore local data.</div>')
    _resource_poller.stop()


# -------------------------------------------------------------- page layout

resource_select.param.watch(on_resource_change, "value")
load_button.on_click(on_load_table)
csv_input.param.watch(on_csv_upload, "value")
s3_register_button.on_click(on_register_s3)

filter_box = pn.Column(pn.pane.Markdown("*Load a table to see filters.*"))
reset_button = pn.widgets.Button(name="Reset filters",
                                 stylesheets=[GHOST_BTN])
reset_button.on_click(lambda _e: active_dataset()
                      and active_dataset().reset_filters())


def _sync_sidebar_filters():
    """The sidebar filter panel always shows the active tab's filters."""
    ds = active_dataset()
    if ds is None:
        filter_box.objects = [
            pn.pane.Markdown("*Load a table to see filters.*")]
        return
    filter_box.objects = list(ds.filter_widgets.values()) or [
        pn.pane.Markdown("*No filterable columns found.*")]


empty_state = pn.pane.HTML(f"""
<div style="display:flex;flex-direction:column;align-items:center;
     justify-content:center;padding:80px 24px;margin-top:16px;
     border:1px dashed #dcdbdd;border-radius:8px;background:#ffffff;">
  <svg width="36" height="36" viewBox="0 0 24 24" fill="none"
       stroke="#9095a0" stroke-width="1.5" style="margin-bottom:12px;">
    <rect x="3" y="3" width="7" height="9" rx="1.5"/>
    <rect x="14" y="3" width="7" height="5" rx="1.5"/>
    <rect x="14" y="12" width="7" height="9" rx="1.5"/>
    <rect x="3" y="16" width="7" height="5" rx="1.5"/>
  </svg>
  <div style="font-family:{FONT_STACK};font-size:14px;font-weight:600;
       color:#17181a;">No data loaded</div>
  <div style="font-family:{FONT_STACK};font-size:13px;color:#6b6f76;
       margin-top:4px;">Choose a datasource in the sidebar, or upload a
       CSV to explore locally. Each table opens in its own tab.</div>
</div>""", sizing_mode="stretch_width")

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
        stylesheets=[ACCORDION_STYLE],
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
lineage_refresh_button.on_click(
    lambda _e: setattr(lineage_grid, "value",
                       lineage.recent_events(lineage_engine())))

explore_tab = pn.Column(
    pn.Row(pn.Spacer(), activity_pane),
    empty_state,
    dataset_tabs,
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


def on_main_tab_change(event):
    if event.new == 1:
        lineage_grid.value = lineage.recent_events(lineage_engine())


main.param.watch(on_main_tab_change, "active")

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
    font="Inter",
    font_url=FONT_URL,
).servable()
