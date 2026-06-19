#!/usr/bin/env python3
"""
File Processor Template for Verily Workbench

Upload, validate, transform, and store files with GCS integration.
"""

import os
import json
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, request, jsonify, render_template_string
from google.cloud import storage
import pandas as pd
from jsonschema import validate, ValidationError

app = Flask(__name__)

# Configuration
UPLOAD_FOLDER = Path("/app/uploads")
PROCESSED_FOLDER = Path("/app/processed")
SCHEMAS_FOLDER = Path("/app/schemas")
MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100MB

app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

# =============================================================================
# HTML TEMPLATE
# =============================================================================

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>File Processor</title>
    <style>
        * { box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; 
            max-width: 900px; 
            margin: 0 auto; 
            padding: 40px 20px;
            background: #f5f7fa;
            color: #333;
        }
        h1 { 
            color: #1a73e8; 
            margin-bottom: 10px;
        }
        .subtitle {
            color: #666;
            margin-bottom: 30px;
        }
        .card {
            background: white;
            border-radius: 12px;
            padding: 30px;
            margin-bottom: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }
        .upload-box { 
            border: 2px dashed #1a73e8; 
            border-radius: 12px; 
            padding: 40px; 
            text-align: center;
            transition: all 0.3s ease;
            cursor: pointer;
        }
        .upload-box:hover { 
            background: #e8f0fe; 
            border-color: #174ea6;
        }
        .upload-box.dragover {
            background: #e8f0fe;
            border-color: #174ea6;
        }
        input[type="file"] { 
            margin: 15px 0;
            padding: 10px;
        }
        .btn { 
            background: #1a73e8; 
            color: white; 
            border: none; 
            padding: 14px 28px; 
            border-radius: 8px; 
            cursor: pointer; 
            font-size: 16px;
            font-weight: 500;
            transition: background 0.2s;
        }
        .btn:hover { background: #174ea6; }
        .btn:disabled { background: #ccc; cursor: not-allowed; }
        .results { 
            margin-top: 20px;
            padding: 20px;
            border-radius: 8px;
        }
        .results.success { background: #e6f4ea; border: 1px solid #34a853; }
        .results.error { background: #fce8e6; border: 1px solid #ea4335; }
        .error { color: #c5221f; }
        .success { color: #137333; }
        .file-info {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
            margin: 15px 0;
            font-family: monospace;
            font-size: 14px;
        }
        .checkbox-label {
            display: flex;
            align-items: center;
            gap: 10px;
            margin: 15px 0;
            cursor: pointer;
        }
        .checkbox-label input {
            width: 18px;
            height: 18px;
        }
        .buckets-list {
            margin-top: 20px;
            padding: 15px;
            background: #f0f4f9;
            border-radius: 8px;
        }
        .buckets-list h3 {
            margin: 0 0 10px 0;
            font-size: 14px;
            color: #666;
        }
        .bucket-item {
            font-family: monospace;
            font-size: 13px;
            padding: 5px 0;
        }
    </style>
</head>
<body>
    <h1>📁 File Processor</h1>
    <p class="subtitle">Upload, validate, transform, and store files in your Workbench buckets</p>
    
    <div class="card">
        <form id="uploadForm" enctype="multipart/form-data">
            <div class="upload-box" id="dropZone">
                <p>📤 Drag & drop a file here, or click to select</p>
                <input type="file" name="file" id="fileInput" accept=".csv,.json,.xlsx,.xls">
                <p id="fileName" style="color: #1a73e8; font-weight: 500;"></p>
            </div>
            
            <label class="checkbox-label">
                <input type="checkbox" name="save_to_gcs" id="saveToGcs"> 
                Save processed file to GCS bucket
            </label>
            
            <button type="submit" class="btn" id="submitBtn" disabled>
                Upload & Process
            </button>
        </form>
    </div>
    
    <div id="results" class="card" style="display: none;">
        <h3 id="resultTitle"></h3>
        <div id="resultContent"></div>
    </div>
    
    <div class="card buckets-list" id="bucketsList">
        <h3>📦 Available Workspace Buckets</h3>
        <div id="bucketsContent">Loading...</div>
    </div>
    
    <script>
        // Load buckets on page load
        fetch('/buckets')
            .then(r => r.json())
            .then(data => {
                const content = document.getElementById('bucketsContent');
                if (Object.keys(data).length === 0) {
                    content.innerHTML = '<em>No buckets found in workspace</em>';
                } else {
                    content.innerHTML = Object.entries(data)
                        .map(([name, path]) => `<div class="bucket-item">• ${name}: ${path}</div>`)
                        .join('');
                }
            });
        
        // File input handling
        const fileInput = document.getElementById('fileInput');
        const fileName = document.getElementById('fileName');
        const submitBtn = document.getElementById('submitBtn');
        const dropZone = document.getElementById('dropZone');
        
        fileInput.addEventListener('change', function() {
            if (this.files.length > 0) {
                fileName.textContent = this.files[0].name;
                submitBtn.disabled = false;
            }
        });
        
        // Drag and drop
        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('dragover');
        });
        
        dropZone.addEventListener('dragleave', () => {
            dropZone.classList.remove('dragover');
        });
        
        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('dragover');
            fileInput.files = e.dataTransfer.files;
            fileName.textContent = e.dataTransfer.files[0].name;
            submitBtn.disabled = false;
        });
        
        // Form submission
        document.getElementById('uploadForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            submitBtn.disabled = true;
            submitBtn.textContent = 'Processing...';
            
            const formData = new FormData();
            formData.append('file', fileInput.files[0]);
            formData.append('save_to_gcs', document.getElementById('saveToGcs').checked);
            
            try {
                const response = await fetch('/upload', { method: 'POST', body: formData });
                const result = await response.json();
                
                const resultsDiv = document.getElementById('results');
                const titleEl = document.getElementById('resultTitle');
                const contentEl = document.getElementById('resultContent');
                
                resultsDiv.style.display = 'block';
                
                if (result.error) {
                    resultsDiv.className = 'card results error';
                    titleEl.textContent = '❌ Error';
                    contentEl.innerHTML = `<p>${result.error}</p>`;
                } else {
                    resultsDiv.className = 'card results success';
                    titleEl.textContent = '✅ ' + result.message;
                    
                    let html = '<div class="file-info">';
                    html += `<strong>Rows:</strong> ${result.rows || 'N/A'}<br>`;
                    html += `<strong>Columns:</strong> ${result.columns || 'N/A'}<br>`;
                    if (result.column_names) {
                        html += `<strong>Column Names:</strong> ${result.column_names.join(', ')}<br>`;
                    }
                    if (result.gcs_path) {
                        html += `<strong>Saved to:</strong> ${result.gcs_path}`;
                    }
                    html += '</div>';
                    
                    contentEl.innerHTML = html;
                }
            } catch (err) {
                document.getElementById('results').style.display = 'block';
                document.getElementById('results').className = 'card results error';
                document.getElementById('resultTitle').textContent = '❌ Error';
                document.getElementById('resultContent').innerHTML = `<p>${err.message}</p>`;
            }
            
            submitBtn.disabled = false;
            submitBtn.textContent = 'Upload & Process';
        });
    </script>
</body>
</html>
"""

# =============================================================================
# WORKSPACE HELPERS
# =============================================================================

def get_workspace_buckets():
    """Get GCS bucket paths from workspace environment."""
    return {
        k.replace("WORKBENCH_", ""): v
        for k, v in os.environ.items()
        if k.startswith("WORKBENCH_") and v.startswith("gs://")
    }


def get_gcs_client():
    return storage.Client()


def upload_to_gcs(local_path: Path, bucket_name: str, blob_name: str):
    """Upload a file to GCS."""
    client = get_gcs_client()
    bucket = client.bucket(bucket_name.replace("gs://", ""))
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(str(local_path))
    return f"gs://{bucket.name}/{blob_name}"

# =============================================================================
# PROCESSING FUNCTIONS
# =============================================================================

def process_csv(file_path: Path) -> dict:
    """Process and validate CSV file."""
    df = pd.read_csv(file_path)
    return {
        "rows": len(df),
        "columns": len(df.columns),
        "column_names": list(df.columns),
        "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
        "null_counts": df.isnull().sum().to_dict(),
        "sample": df.head(5).to_dict(orient="records")
    }


def process_json(file_path: Path) -> dict:
    """Process and validate JSON file."""
    with open(file_path) as f:
        data = json.load(f)
    
    if isinstance(data, list):
        return {
            "type": "array",
            "length": len(data),
            "sample": data[:5] if len(data) > 5 else data
        }
    else:
        return {
            "type": "object",
            "keys": list(data.keys()),
            "sample": data
        }


def process_excel(file_path: Path) -> dict:
    """Process Excel file."""
    df = pd.read_excel(file_path)
    return {
        "rows": len(df),
        "columns": len(df.columns),
        "column_names": list(df.columns),
        "sample": df.head(5).to_dict(orient="records")
    }

# =============================================================================
# ROUTES
# =============================================================================

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/health")
def health():
    return jsonify({"status": "healthy"})


@app.route("/buckets")
def list_buckets():
    """List available workspace buckets."""
    return jsonify(get_workspace_buckets())


@app.route("/upload", methods=["POST"])
def upload_file():
    """Upload and process a file."""
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400
    
    # Save uploaded file
    file_id = str(uuid.uuid4())[:8]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{file_id}_{file.filename}"
    file_path = UPLOAD_FOLDER / filename
    file.save(file_path)
    
    try:
        # Process based on file type
        suffix = Path(file.filename).suffix.lower()
        
        if suffix == ".csv":
            result = process_csv(file_path)
        elif suffix == ".json":
            result = process_json(file_path)
        elif suffix in [".xlsx", ".xls"]:
            result = process_excel(file_path)
        else:
            return jsonify({"error": f"Unsupported file type: {suffix}"}), 400
        
        result["message"] = f"Successfully processed {file.filename}"
        result["filename"] = filename
        
        # Optionally save to GCS
        save_to_gcs = request.form.get("save_to_gcs", "false").lower() == "true"
        if save_to_gcs:
            buckets = get_workspace_buckets()
            if buckets:
                # Use first available bucket
                bucket_name = list(buckets.values())[0]
                blob_name = f"processed/{filename}"
                gcs_path = upload_to_gcs(file_path, bucket_name, blob_name)
                result["gcs_path"] = gcs_path
            else:
                result["warning"] = "No GCS buckets found in workspace"
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/validate", methods=["POST"])
def validate_file():
    """Validate file against a JSON schema."""
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    if "schema" not in request.form:
        return jsonify({"error": "No schema provided"}), 400
    
    file = request.files["file"]
    schema = json.loads(request.form["schema"])
    
    try:
        data = json.load(file)
        validate(instance=data, schema=schema)
        return jsonify({"valid": True, "message": "Validation passed"})
    except ValidationError as e:
        return jsonify({"valid": False, "error": str(e.message)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
    PROCESSED_FOLDER.mkdir(parents=True, exist_ok=True)
    
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
