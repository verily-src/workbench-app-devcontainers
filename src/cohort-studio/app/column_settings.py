from copy import deepcopy

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.exc import DataError

import datasets
import db
import live_query
from source_models import ColumnSetting


def _q(name):
    return '"' + name.replace('"', '""') + '"'


def profiles(ds):
    result = datasets.profile_columns(ds["df"])
    settings = {s["name"]: s for s in ds.get("column_settings", [])}
    for col in result:
        setting = settings.get(col["name"], {})
        col["label"] = setting.get("label") or col["name"]
        col["logical_type"] = setting.get("logical_type")
        if setting.get("filter_kind") is not None:
            col["filter_kind"] = setting["filter_kind"]
            series = ds["df"][col["name"]]
            if col["filter_kind"] == "categorical":
                col["values"] = list(series.dropna().astype(str).value_counts().head(50).index)
            elif col["filter_kind"] == "range":
                values = series.dropna()
                if len(values):
                    col["min"], col["max"] = float(values.min()), float(values.max())
    if ds.get("live_source"):
        result = live_query.profile_columns(ds["live_source"], result)
    return result


def apply(dataset_id, settings):
    ds = datasets.get(dataset_id)
    parsed = [ColumnSetting.model_validate(s).model_dump(exclude_none=True) for s in settings]
    if len({s["name"] for s in parsed}) != len(parsed):
        raise ValueError("Each column may appear only once.")
    base_frame = ds.get("settings_base_df", ds["df"])
    base_live = ds.get("settings_base_live", ds.get("live_source"))
    base_origin = ds.get("settings_base_origin", ds.get("origin"))
    frame = base_frame.copy()
    live = deepcopy(base_live)
    origin = base_origin or {}
    merged = {s["name"]: s for s in ds.get("column_settings", [])}
    for setting in parsed:
        merged[setting["name"]] = {**merged.get(setting["name"], {}), **setting}
    parsed = list(merged.values())
    if not live and origin.get("kind") == "aurora" and any(s.get("logical_type") for s in parsed):
        names = list(frame.columns)
        live = {"resource_id": origin["resource_id"],
                "sql": f"SELECT {', '.join(_q(n) for n in names)} FROM "
                       f"{_q(origin.get('schema') or 'public')}.{_q(origin['table'])}",
                "columns": {n: n for n in names}}
    for setting in parsed:
        name = setting["name"]
        if name not in frame.columns:
            raise ValueError(f"Unknown column: {name}")
        logical_type = setting.get("logical_type")
        if logical_type == "number":
            try:
                numeric = pd.to_numeric(frame[name], errors="raise")
            except (TypeError, ValueError) as e:
                raise ValueError(f"Column {name} contains non-numeric values.") from e
            if not np.isfinite(numeric.dropna().astype(float)).all():
                raise ValueError(f"Column {name} contains non-finite values.")
            frame[name] = numeric
        elif logical_type == "text":
            frame[name] = frame[name].map(lambda value: str(value) if pd.notna(value) else None)
        combined = {**merged.get(name, {}), **setting}
        if logical_type == "text" and "filter_kind" not in setting:
            combined["filter_kind"] = "categorical" if frame[name].nunique() <= 50 else "none"
        if combined.get("filter_kind") == "range" and not pd.api.types.is_numeric_dtype(frame[name]):
            raise ValueError(f"Range filters require a numeric column: {name}")
        if live and logical_type:
            pg_name = live["columns"][name]
            col = _q(pg_name)
            if logical_type == "number":
                check = (f"SELECT MIN(CAST({col} AS double precision)), "
                         f"MAX(CAST({col} AS double precision)) "
                         f"FROM ({live['sql']}) AS src")
                try:
                    with db.get_engine_for_resource(live["resource_id"]).begin() as conn:
                        conn.execute(text("SET LOCAL statement_timeout = 15000"))
                        bounds = conn.execute(text(check)).one()
                except DataError as e:
                    raise ValueError(f"Column {name} contains non-numeric or out-of-range values in the database.") from e
                if any(v is not None and not np.isfinite(v) for v in bounds):
                    raise ValueError(f"Column {name} contains non-finite values in the database.")
            target = "numeric" if logical_type == "number" else "text"
            columns = [f"CAST({_q(p)} AS {target}) AS {_q(p)}" if p == pg_name else _q(p)
                       for p in live["columns"].values()]
            live["sql"] = f"SELECT {', '.join(columns)} FROM ({live['sql']}) AS src"
        merged[name] = combined
    preview = {**ds, "df": frame, "live_source": live, "column_settings": list(merged.values())}
    columns = profiles(preview)
    ds["settings_base_df"] = base_frame
    ds["settings_base_live"] = base_live
    ds["settings_base_origin"] = base_origin
    ds["df"] = frame
    ds["live_source"] = live
    ds["column_settings"] = list(merged.values())
    if any(s.get("logical_type") for s in parsed):
        ds["origin"] = None
    if ds.get("source_ref"):
        ds["source_ref"] = {**ds["source_ref"], "settings": ds["column_settings"]}
    return {"dataset_id": dataset_id, "source": ds["source"], "rows": len(frame),
            "columns": columns, "source_ref": ds.get("source_ref"),
            "query_scope": "database" if live else "loaded"}
