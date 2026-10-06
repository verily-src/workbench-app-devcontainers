"""Chart builders, cBioPortal-style.

Every distribution chart draws the FULL cohort in a muted tone with the
FILTERED cohort overlaid in Verily teal, so the effect of each filter is
visible in every chart at once. Categorical bars are tap-to-filter.

Palette: Verily-anchored, validated with the dataviz six checks against
the Workbench surface #F5F6F7 (light mode only — the app is light-locked).
Contrast WARNs on pink/gold are relieved by hover tooltips + the grid.
"""

import logging

import holoviews as hv
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

hv.extension("bokeh")

# Fixed-order categorical palette, slot 1 = Verily teal. Never cycled.
PALETTE = ["#00836e", "#d95f1e", "#2a78d6", "#e06c9b",
           "#4a3aa7", "#c78500", "#c93a38"]
TEAL = "#087a6a"          # Verily Workbench primary — the "selected" layer
MUTED = "#cfe0dc"         # full-cohort layer behind the selection
TEAL_RAMP = ["#e4f0ed", "#9fc9c0", "#4b9d8e", "#087a6a", "#054f45"]  # sequential
INK = "#212529"
INK_SOFT = "#5f6368"
GRID_LINE = "#e8eaed"

BAR_TOP_N = 12


def _chrome(plot, element):
    """Recessive axes and no toolbar — the data is the interface."""
    p = plot.state
    p.toolbar_location = None
    p.outline_line_color = None
    p.background_fill_color = None
    p.border_fill_color = None
    for ax in list(p.xaxis) + list(p.yaxis):
        ax.axis_line_color = None
        ax.major_tick_line_color = None
        ax.minor_tick_line_color = None
        ax.major_label_text_color = INK_SOFT
        ax.major_label_text_font = "Open Sans"
        ax.axis_label_text_color = INK_SOFT
    for g in list(p.xgrid) + list(p.ygrid):
        g.grid_line_color = GRID_LINE

BASE_OPTS = dict(responsive=True, hooks=[_chrome], show_legend=False)


def _bar_height(n_categories: int) -> int:
    return min(max(170, 26 * n_categories + 70), 430)


def categorical_bar(df_full: pd.DataFrame, df_filt: pd.DataFrame, col: str,
                    on_tap=None):
    """Horizontal count bars: full cohort muted, filtered overlaid, tap to filter."""
    full = df_full[col].dropna().astype(str).value_counts()
    cats = list(full.head(BAR_TOP_N).index)
    try:
        cats.sort(key=float)  # numeric categories read in value order
    except ValueError:
        pass                  # text categories stay in count order
    filt = df_filt[col].dropna().astype(str).value_counts()
    rows = [(c, int(full[c]), int(filt.get(c, 0))) for c in cats]
    if len(full) > BAR_TOP_N:
        rest = full.index[BAR_TOP_N:]
        rows.append(("Other", int(full[rest].sum()),
                     int(filt.reindex(rest).fillna(0).sum())))
    data = pd.DataFrame(rows, columns=[col, "all", "selected"])[::-1]

    opts = dict(**BASE_OPTS, invert_axes=True, xlabel="", ylabel="",
                height=_bar_height(len(data)), bar_width=0.72)
    base = hv.Bars(data, kdims=[col], vdims=["all"]).opts(
        color=MUTED, line_color=None, tools=["tap", "hover"],
        nonselection_alpha=1.0, selection_alpha=1.0, **opts)
    over = hv.Bars(data, kdims=[col], vdims=["selected"]).opts(
        color=TEAL, line_color=None, tools=["hover"], **opts)

    if on_tap is not None:
        categories = list(data[col])
        stream = hv.streams.Selection1D(source=base)

        def _tapped(event):
            for i in event.new or []:
                if categories[i] != "Other":
                    on_tap(col, categories[i])

        stream.param.watch(_tapped, "index")

    return base * over


def histogram(df_full: pd.DataFrame, df_filt: pd.DataFrame, col: str,
              bins: int = 24):
    full_vals = df_full[col].dropna().astype(float)
    if full_vals.empty:
        return None
    counts, edges = np.histogram(full_vals, bins=bins)
    filt_counts, _ = np.histogram(df_filt[col].dropna().astype(float),
                                  bins=edges)
    opts = dict(**BASE_OPTS, height=240, xlabel="", ylabel="")
    base = hv.Histogram((edges, counts)).opts(
        color=MUTED, line_color="#F5F6F7", line_width=1, tools=["hover"], **opts)
    over = hv.Histogram((edges, filt_counts)).opts(
        color=TEAL, line_color="#F5F6F7", line_width=1, tools=["hover"], **opts)
    return base * over


def box(df_filt: pd.DataFrame, col: str, by: str | None = None):
    kdims = [by] if by else []
    return hv.BoxWhisker(df_filt.dropna(subset=[col]), kdims, col).opts(
        box_fill_color=MUTED, box_line_color=TEAL, whisker_color=TEAL,
        outlier_color=INK_SOFT, xrotation=45, height=300,
        xlabel="", **BASE_OPTS)


def scatter(df_filt: pd.DataFrame, x: str, y: str):
    return hv.Scatter(df_filt.dropna(subset=[x, y]), x, y).opts(
        color=TEAL, alpha=0.45, size=6, tools=["hover"], height=300,
        **BASE_OPTS)


def heatmap(df_filt: pd.DataFrame, x: str, y: str):
    counts = (df_filt.dropna(subset=[x, y]).astype({x: str, y: str})
              .groupby([x, y], observed=True).size().reset_index(name="count"))
    return hv.HeatMap(counts, [x, y], "count").opts(
        cmap=TEAL_RAMP, xrotation=45, height=320, colorbar=False,
        tools=["hover"], xlabel="", ylabel="", **BASE_OPTS)


def build(kind: str, df_full: pd.DataFrame, df_filt: pd.DataFrame,
          config: dict, on_tap=None):
    x, y = config["x"], config.get("y")
    try:
        if kind == "bar":
            return categorical_bar(df_full, df_filt, x, on_tap)
        if kind == "histogram":
            return histogram(df_full, df_filt, x)
        if kind == "box":
            return box(df_filt, x, y)
        if kind == "scatter":
            return scatter(df_filt, x, y)
        if kind == "heatmap":
            return heatmap(df_filt, x, y)
    except Exception as e:
        logger.warning("Chart %s on %s failed: %s", kind, x, e)
        return None
    return None
