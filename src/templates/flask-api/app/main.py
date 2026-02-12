#!/usr/bin/env python3
"""
Flask REST API Template for Verily Workbench

This template provides a starting point for building REST APIs that
integrate with workspace resources (GCS buckets, BigQuery tables).
"""

import os
import json
from flask import Flask, request, jsonify
from google.cloud import storage, bigquery

app = Flask(__name__)

# =============================================================================
# WORKSPACE RESOURCE HELPERS
# =============================================================================

def get_workspace_resources():
    """
    Get workspace resources from environment variables.
    
    Workbench automatically sets WORKBENCH_<resource_name> environment variables
    for each resource in the workspace.
    """
    resources = {}
    for key, value in os.environ.items():
        if key.startswith("WORKBENCH_"):
            resource_name = key.replace("WORKBENCH_", "").lower()
            resources[resource_name] = value
    return resources


def get_bucket_client():
    """Get a GCS client for workspace buckets."""
    return storage.Client()


def get_bigquery_client():
    """Get a BigQuery client for workspace datasets."""
    return bigquery.Client()


# =============================================================================
# API ENDPOINTS
# =============================================================================

@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "service": "flask-api"
    })


@app.route("/resources", methods=["GET"])
def list_resources():
    """List all workspace resources available to this app."""
    return jsonify({
        "resources": get_workspace_resources()
    })


@app.route("/buckets/<bucket_name>/files", methods=["GET"])
def list_bucket_files(bucket_name: str):
    """
    List files in a workspace bucket.
    
    Example: GET /buckets/my-bucket/files
    """
    try:
        # Remove gs:// prefix if present
        bucket_name = bucket_name.replace("gs://", "")
        
        client = get_bucket_client()
        bucket = client.bucket(bucket_name)
        
        prefix = request.args.get("prefix", "")
        blobs = bucket.list_blobs(prefix=prefix)
        
        files = [{"name": blob.name, "size": blob.size} for blob in blobs]
        
        return jsonify({
            "bucket": bucket_name,
            "files": files,
            "count": len(files)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/buckets/<bucket_name>/upload", methods=["POST"])
def upload_file(bucket_name: str):
    """
    Upload a file to a workspace bucket.
    
    Example: POST /buckets/my-bucket/upload
    Body: multipart/form-data with 'file' field
    """
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file provided"}), 400
        
        file = request.files["file"]
        dest_path = request.form.get("path", file.filename)
        
        bucket_name = bucket_name.replace("gs://", "")
        client = get_bucket_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(dest_path)
        
        blob.upload_from_file(file)
        
        return jsonify({
            "success": True,
            "path": f"gs://{bucket_name}/{dest_path}"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/bigquery/query", methods=["POST"])
def run_query():
    """
    Run a BigQuery query.
    
    Example: POST /bigquery/query
    Body: {"query": "SELECT * FROM `project.dataset.table` LIMIT 10"}
    """
    try:
        data = request.get_json()
        query = data.get("query")
        
        if not query:
            return jsonify({"error": "No query provided"}), 400
        
        client = get_bigquery_client()
        result = client.query(query).to_dataframe()
        
        return jsonify({
            "columns": list(result.columns),
            "rows": result.to_dict(orient="records"),
            "count": len(result)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/bigquery/tables/<dataset>", methods=["GET"])
def list_tables(dataset: str):
    """
    List tables in a BigQuery dataset.
    
    Example: GET /bigquery/tables/my-project.my-dataset
    """
    try:
        client = get_bigquery_client()
        tables = client.list_tables(dataset)
        
        table_list = [{"table_id": t.table_id, "table_type": t.table_type} for t in tables]
        
        return jsonify({
            "dataset": dataset,
            "tables": table_list,
            "count": len(table_list)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/process", methods=["POST"])
def process_data():
    """
    Example data processing endpoint.
    
    Customize this endpoint for your specific use case.
    """
    try:
        data = request.get_json()
        
        # TODO: Add your processing logic here
        result = {
            "input": data,
            "processed": True,
            "message": "Processing complete"
        }
        
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
