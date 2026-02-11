"""
GCP Data Chat — Flask-based Workbench custom app.
Talk to your GCP data using an LLM with a modern guided GUI.
"""
import os
import json
import traceback

from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import pandas as pd

from gcp_tools import (
    get_default_project,
    list_gcs_buckets,
    list_gcs_blobs,
    load_from_gcs,
    list_bigquery_datasets,
    list_bigquery_tables,
    load_from_bigquery,
    fetch_secret,
)
from llm_engine import chat_with_data

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    static_folder=os.path.join(SCRIPT_DIR, "static"),
    template_folder=os.path.join(SCRIPT_DIR, "templates"),
)
app.secret_key = os.urandom(24)
CORS(app)

# ---------------------------------------------------------------------------
# In-memory state (single-user Workbench app — no multi-tenant concerns)
# ---------------------------------------------------------------------------
_state = {
    "df": None,
    "data_summary": "",
    "schema_and_sample": "",
    "api_key": "",
    "chat_history": [],
    "source_info": "",
    "gcp_project": "",
}


def _build_data_context(df: pd.DataFrame) -> tuple[str, str]:
    """Build data summary and schema strings for LLM context."""
    summary = (
        f"Rows: {len(df):,}, Columns: {len(df.columns)}. "
        f"Column names: {list(df.columns)}."
    )
    schema = (
        f"dtypes:\n{df.dtypes.to_string()}\n\n"
        f"Sample (first 20 rows):\n{df.head(20).to_string()}"
    )
    try:
        desc = df.describe(include="all").to_string()
        schema += f"\n\nDescribe (statistics):\n{desc}"
    except Exception:
        pass
    return summary, schema


# ---------------------------------------------------------------------------
# Routes — Pages
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Routes — API
# ---------------------------------------------------------------------------
@app.route("/api/status")
def api_status():
    """Return current app state for the frontend."""
    df = _state["df"]
    return jsonify(
        {
            "has_data": df is not None,
            "has_key": bool(_state["api_key"]),
            "source_info": _state["source_info"],
            "row_count": len(df) if df is not None else 0,
            "col_count": len(df.columns) if df is not None else 0,
            "columns": list(df.columns) if df is not None else [],
            "default_project": _state["gcp_project"] or get_default_project() or "",
            "chat_count": len(_state["chat_history"]),
        }
    )


@app.route("/api/set-project", methods=["POST"])
def api_set_project():
    """Set the GCP project to use."""
    data = request.json
    project = data.get("project", "").strip()
    if not project:
        return jsonify({"error": "Project ID is required"}), 400
    _state["gcp_project"] = project
    return jsonify({"success": True, "project": project})


@app.route("/api/fetch-key", methods=["POST"])
def api_fetch_key():
    """Fetch OpenAI API key from Secret Manager."""
    data = request.json
    project = data.get("project", "").strip()
    secret_name = data.get("secret_name", "").strip()
    version = data.get("version", "latest").strip() or "latest"
    if not project or not secret_name:
        return jsonify({"error": "Project and secret name are required"}), 400
    try:
        key = fetch_secret(project, secret_name, version)
        _state["api_key"] = key
        return jsonify({"success": True, "message": "API key loaded from Secret Manager"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/set-key", methods=["POST"])
def api_set_key():
    """Set API key directly (paste)."""
    data = request.json
    key = data.get("key", "").strip()
    if not key:
        return jsonify({"error": "Key is required"}), 400
    _state["api_key"] = key
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Discovery endpoints
# ---------------------------------------------------------------------------
@app.route("/api/discover/buckets")
def api_discover_buckets():
    project = request.args.get("project", "").strip() or _state["gcp_project"] or None
    try:
        buckets = list_gcs_buckets(project)
        return jsonify({"buckets": buckets})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/discover/blobs")
def api_discover_blobs():
    bucket = request.args.get("bucket", "").strip()
    prefix = request.args.get("prefix", "").strip()
    if not bucket:
        return jsonify({"error": "Bucket is required"}), 400
    try:
        blobs = list_gcs_blobs(bucket, prefix)
        return jsonify({"blobs": blobs})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/discover/datasets")
def api_discover_datasets():
    project = request.args.get("project", "").strip() or _state["gcp_project"]
    if not project:
        return jsonify({"error": "Project is required"}), 400
    try:
        datasets = list_bigquery_datasets(project)
        return jsonify({"datasets": datasets})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/discover/tables")
def api_discover_tables():
    project = request.args.get("project", "").strip() or _state["gcp_project"]
    dataset = request.args.get("dataset", "").strip()
    if not project or not dataset:
        return jsonify({"error": "Project and dataset are required"}), 400
    try:
        tables = list_bigquery_tables(project, dataset)
        return jsonify({"tables": tables})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
@app.route("/api/load", methods=["POST"])
def api_load():
    """Load data from GCS or BigQuery."""
    data = request.json
    source_type = data.get("source_type", "")
    try:
        if source_type == "gcs":
            bucket = data.get("bucket", "").strip()
            path = data.get("path", "").strip()
            fmt = data.get("format", "csv").strip()
            if not bucket or not path:
                return jsonify({"error": "Bucket and file path are required"}), 400
            df = load_from_gcs(bucket, path, fmt)
            _state["source_info"] = f"gs://{bucket}/{path}"

        elif source_type == "bigquery":
            project = data.get("project", "").strip() or _state["gcp_project"]
            dataset = data.get("dataset", "").strip()
            table = data.get("table", "").strip()
            limit = int(data.get("limit", 50_000))
            if not project or not dataset or not table:
                return jsonify({"error": "Project, dataset, and table are required"}), 400
            df = load_from_bigquery(project, dataset, table, limit)
            _state["source_info"] = f"{project}.{dataset}.{table}"

        else:
            return jsonify({"error": f"Invalid source type: {source_type}"}), 400

        _state["df"] = df
        _state["chat_history"] = []
        summary, schema = _build_data_context(df)
        _state["data_summary"] = summary
        _state["schema_and_sample"] = schema

        # Build preview (first 100 rows, JSON-safe)
        preview_df = df.head(100).copy()
        for col in preview_df.columns:
            preview_df[col] = preview_df[col].astype(str)
        preview = preview_df.to_dict(orient="records")
        columns = list(df.columns)
        dtypes = {col: str(df[col].dtype) for col in df.columns}

        return jsonify(
            {
                "success": True,
                "rows": len(df),
                "cols": len(df.columns),
                "columns": columns,
                "dtypes": dtypes,
                "preview": preview,
                "source_info": _state["source_info"],
            }
        )
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/preview")
def api_preview():
    """Return a preview of the loaded data."""
    if _state["df"] is None:
        return jsonify({"error": "No data loaded"}), 400
    df = _state["df"]
    preview_df = df.head(100).copy()
    for col in preview_df.columns:
        preview_df[col] = preview_df[col].astype(str)
    return jsonify(
        {
            "preview": preview_df.to_dict(orient="records"),
            "columns": list(df.columns),
            "dtypes": {col: str(df[col].dtype) for col in df.columns},
            "total_rows": len(df),
        }
    )


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------
@app.route("/api/chat", methods=["POST"])
def api_chat():
    """Chat with the loaded data via LLM."""
    if _state["df"] is None:
        return jsonify({"error": "No data loaded. Please load data first (Step 2)."}), 400
    if not _state["api_key"]:
        return jsonify({"error": "No API key set. Please configure your API key (Step 1)."}), 400

    data = request.json
    question = data.get("question", "").strip()
    if not question:
        return jsonify({"error": "Please enter a question."}), 400

    model = data.get("model", "gpt-4o-mini").strip() or "gpt-4o-mini"
    use_us_endpoint = data.get("use_us_endpoint", True)

    # Add user message to chat history
    _state["chat_history"].append({"role": "user", "content": question})

    try:
        result = chat_with_data(
            api_key=_state["api_key"],
            data_summary=_state["data_summary"],
            schema_and_sample=_state["schema_and_sample"],
            question=question,
            df=_state["df"],
            model=model,
            use_us_endpoint=use_us_endpoint,
            chat_history=_state["chat_history"][:-1],
        )

        _state["chat_history"].append({"role": "assistant", "content": result["text"]})
        return jsonify(result)

    except Exception as e:
        traceback.print_exc()
        error_msg = f"Error: {str(e)}"
        _state["chat_history"].append({"role": "assistant", "content": error_msg})
        return jsonify({"text": error_msg, "chart": None}), 500


@app.route("/api/chat/clear", methods=["POST"])
def api_chat_clear():
    """Clear chat history."""
    _state["chat_history"] = []
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Auto-fetch API key from Secret Manager if env vars are set
    _project = os.environ.get("OPENAI_SECRET_PROJECT", "").strip()
    _secret = os.environ.get("OPENAI_SECRET_NAME", "").strip()
    _version = os.environ.get("OPENAI_SECRET_VERSION", "latest").strip() or "latest"
    if _project and _secret:
        try:
            _state["api_key"] = fetch_secret(_project, _secret, _version)
            print(f"[startup] API key auto-loaded from Secret Manager ({_project}/{_secret})")
        except Exception as e:
            print(f"[startup] Could not auto-load API key: {e}")

    # Auto-detect GCP project
    detected = get_default_project()
    if detected:
        _state["gcp_project"] = detected
        print(f"[startup] Detected GCP project: {detected}")

    app.run(host="0.0.0.0", port=8080, debug=False, threaded=True)
