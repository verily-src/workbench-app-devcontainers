"""Data profiling: metrics and histogram-style visualizations."""
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st


def numeric_metrics(series: pd.Series) -> dict:
    """Basic metrics for numeric column."""
    return {
        "count": int(series.count()),
        "null_count": int(series.isna().sum()),
        "null_pct": round(100 * series.isna().mean(), 2),
        "mean": round(series.mean(), 4) if series.dtype.kind in "fc" else None,
        "std": round(series.std(), 4) if series.dtype.kind in "fc" else None,
        "min": series.min(),
        "q25": series.quantile(0.25),
        "median": series.median(),
        "q75": series.quantile(0.75),
        "max": series.max(),
    }


def categorical_metrics(series: pd.Series) -> dict:
    """Basic metrics for categorical column."""
    vc = series.astype(str).value_counts()
    return {
        "count": int(series.count()),
        "null_count": int(series.isna().sum()),
        "null_pct": round(100 * series.isna().mean(), 2),
        "unique_count": int(series.nunique()),
        "top_value": vc.index[0] if len(vc) else None,
        "top_count": int(vc.iloc[0]) if len(vc) else None,
    }


def column_metrics(df: pd.DataFrame, col: str) -> dict:
    """Metrics for one column (numeric or categorical)."""
    s = df[col]
    if s.dtype.kind in "fc" or (s.dtype == "object" and pd.to_numeric(s, errors="coerce").notna().any()):
        try:
            s = pd.to_numeric(s, errors="coerce")
        except Exception:
            pass
    if s.dtype.kind in "fc" or (s.dtype == "Int64"):
        return {"type": "numeric", **numeric_metrics(s)}
    return {"type": "categorical", **categorical_metrics(s)}


def profile_dataframe(df: pd.DataFrame) -> dict[str, dict]:
    """Profile all columns; return dict of column name -> metrics."""
    return {col: column_metrics(df, col) for col in df.columns}


def render_histogram(series: pd.Series, title: str) -> None:
    """Render a histogram in Streamlit using Plotly."""
    s = series.dropna()
    if s.dtype.kind in "fc" or pd.api.types.is_numeric_dtype(s):
        fig = px.histogram(x=s, title=title, nbins=min(50, max(10, s.nunique())))
    else:
        vc = s.astype(str).value_counts().head(30)
        fig = px.bar(x=vc.index, y=vc.values, title=title, labels={"x": "Value", "y": "Count"})
    fig.update_layout(height=280, margin=dict(l=20, r=20, t=40, b=20))
    st.plotly_chart(fig, use_container_width=True)


def render_profile_ui(df: pd.DataFrame) -> None:
    """Render full profiling: metrics table + histograms per column."""
    metrics = profile_dataframe(df)
    st.subheader("Data profiling metrics")
    rows = []
    for col, m in metrics.items():
        row = {"column": col, "type": m.get("type", ""), "count": m.get("count"), "nulls": m.get("null_count"), "null_%": m.get("null_pct")}
        if m.get("type") == "numeric":
            row["mean"] = m.get("mean")
            row["min"] = m.get("min")
            row["median"] = m.get("median")
            row["max"] = m.get("max")
        else:
            row["unique"] = m.get("unique_count")
            row["top"] = m.get("top_value")
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.subheader("Histograms by column")
    for col in df.columns:
        with st.expander(col, expanded=False):
            render_histogram(df[col], col)
