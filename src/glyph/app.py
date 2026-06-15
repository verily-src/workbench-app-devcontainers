"""
In-House Annotation Tool - Flask Backend

A lightweight annotation tool for Google Cloud.
- Fetches tasks from BigQuery
- Serves images from GCS with signed URLs
- Saves annotations to BigQuery
"""

from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename
from google.cloud import bigquery, storage
from datetime import datetime, timedelta
import uuid
import os
import json
from fhir_export import export_to_fhir_bundle, generate_observation, generate_diagnostic_report

app = Flask(__name__)

# Configuration
GCP_PROJECT_ID = os.getenv('GCP_PROJECT_ID', 'your-project-id')
BQ_DATASET = os.getenv('BQ_DATASET', 'image_annotations')
GCS_BUCKET = os.getenv('GCS_BUCKET', 'image-images')

# Initialize clients
bq_client = bigquery.Client(project=GCP_PROJECT_ID)
gcs_client = storage.Client(project=GCP_PROJECT_ID)


@app.route('/')
def index():
    """Main annotation interface."""
    return render_template('index.html')


@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    """Fetch pending annotation tasks from BigQuery.

    Query params:
        limit (int): Number of tasks to fetch (default: 10)
        status (str): Filter by status (default: 'pending')
    """
    # Security: Validate and limit query parameters
    limit = request.args.get('limit', 10, type=int)
    limit = min(max(1, limit), 100)  # Clamp between 1-100

    status = request.args.get('status', 'pending')
    # Validate status is one of allowed values
    allowed_statuses = {'pending', 'in_progress', 'completed'}
    if status not in allowed_statuses:
        return jsonify({'error': 'Invalid status'}), 400

    query = f"""
        SELECT
            task_id,
            image_gcs_path,
            task_type,
            labels,
            metadata,
            status
        FROM `{GCP_PROJECT_ID}.{BQ_DATASET}.annotation_tasks`
        WHERE status = @status
        ORDER BY created_at ASC
        LIMIT @limit
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("status", "STRING", status),
            bigquery.ScalarQueryParameter("limit", "INT64", limit),
        ]
    )

    query_job = bq_client.query(query, job_config=job_config)
    results = query_job.result()

    tasks = []
    for row in results:
        # Generate signed URL for image
        image_url = generate_signed_url(row.image_gcs_path)

        tasks.append({
            'task_id': row.task_id,
            'image_url': image_url,
            'task_type': row.task_type,
            'labels': row.labels,
            'metadata': json.loads(row.metadata) if row.metadata else {},
            'status': row.status
        })

    return jsonify({'tasks': tasks, 'count': len(tasks)})


@app.route('/api/tasks/<task_id>/start', methods=['POST'])
def start_task(task_id):
    """Mark task as in_progress when annotator starts working."""
    query = f"""
        UPDATE `{GCP_PROJECT_ID}.{BQ_DATASET}.annotation_tasks`
        SET status = 'in_progress'
        WHERE task_id = @task_id
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("task_id", "STRING", task_id),
        ]
    )

    bq_client.query(query, job_config=job_config).result()

    return jsonify({'status': 'success', 'task_id': task_id})


@app.route('/api/annotations', methods=['POST'])
def save_annotation():
    """Save annotation to BigQuery.

    Request body:
        {
            "task_id": "task_123",
            "annotator": "user@example.com",
            "annotation_data": {
                "bboxes": [
                    {"x": 100, "y": 200, "width": 50, "height": 80, "label": "Batting"}
                ]
            },
            "annotation_type": "bbox"
        }
    """
    # Security: Validate content length
    MAX_PAYLOAD_SIZE = 1_000_000  # 1MB
    if request.content_length and request.content_length > MAX_PAYLOAD_SIZE:
        return jsonify({'error': 'Payload too large'}), 413

    data = request.json

    # Security: Validate required fields
    if not data or 'task_id' not in data or 'annotation_data' not in data:
        return jsonify({'error': 'Missing required fields: task_id, annotation_data'}), 400

    # Security: Validate annotation data structure
    ann_data = data['annotation_data']
    if not isinstance(ann_data, dict):
        return jsonify({'error': 'annotation_data must be an object'}), 400

    # Security: Limit number of bounding boxes
    MAX_BBOXES = 100
    bboxes = ann_data.get('bboxes', [])
    if not isinstance(bboxes, list):
        return jsonify({'error': 'bboxes must be an array'}), 400
    if len(bboxes) > MAX_BBOXES:
        return jsonify({'error': f'Too many bounding boxes (max {MAX_BBOXES})'}), 400

    # Validate each bbox has required fields
    for bbox in bboxes:
        if not isinstance(bbox, dict):
            return jsonify({'error': 'Each bbox must be an object'}), 400
        required_fields = ['label', 'x', 'y', 'width', 'height']
        if not all(field in bbox for field in required_fields):
            return jsonify({'error': f'Each bbox must have: {required_fields}'}), 400

    annotation_id = str(uuid.uuid4())

    # Insert annotation
    table_id = f"{GCP_PROJECT_ID}.{BQ_DATASET}.annotations"

    rows_to_insert = [{
        'annotation_id': annotation_id,
        'task_id': data['task_id'],
        'annotator': data.get('annotator', 'unknown'),
        'annotation_data': json.dumps(ann_data),
        'annotation_type': data.get('annotation_type', 'bbox'),
        'created_at': datetime.utcnow().isoformat(),
        'updated_at': datetime.utcnow().isoformat()
    }]

    errors = bq_client.insert_rows_json(table_id, rows_to_insert)

    if errors:
        return jsonify({'status': 'error', 'errors': errors}), 500

    # Update task status to completed
    update_query = f"""
        UPDATE `{GCP_PROJECT_ID}.{BQ_DATASET}.annotation_tasks`
        SET status = 'completed'
        WHERE task_id = @task_id
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("task_id", "STRING", data['task_id']),
        ]
    )

    bq_client.query(update_query, job_config=job_config).result()

    return jsonify({
        'status': 'success',
        'annotation_id': annotation_id,
        'task_id': data['task_id']
    })


@app.route('/api/annotations/<task_id>', methods=['GET'])
def get_annotation(task_id):
    """Fetch existing annotation for a task."""
    query = f"""
        SELECT
            annotation_id,
            annotation_data,
            annotation_type,
            annotator,
            created_at
        FROM `{GCP_PROJECT_ID}.{BQ_DATASET}.annotations`
        WHERE task_id = @task_id
        ORDER BY created_at DESC
        LIMIT 1
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("task_id", "STRING", task_id),
        ]
    )

    query_job = bq_client.query(query, job_config=job_config)
    results = list(query_job.result())

    if not results:
        return jsonify({'annotation': None})

    row = results[0]

    return jsonify({
        'annotation': {
            'annotation_id': row.annotation_id,
            'annotation_data': json.loads(row.annotation_data),
            'annotation_type': row.annotation_type,
            'annotator': row.annotator,
            'created_at': row.created_at.isoformat()
        }
    })


@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get annotation statistics."""
    query = f"""
        SELECT
            status,
            COUNT(*) as count
        FROM `{GCP_PROJECT_ID}.{BQ_DATASET}.annotation_tasks`
        GROUP BY status
    """

    query_job = bq_client.query(query)
    results = query_job.result()

    stats = {'total': 0}
    for row in results:
        stats[row.status] = row.count
        stats['total'] += row.count

    return jsonify(stats)


def generate_signed_url(gcs_path):
    """Generate a signed URL for GCS object.

    Args:
        gcs_path: GCS path like 'gs://bucket/path/to/image.jpg'
                  or 'bucket/path/to/image.jpg'

    Returns:
        Signed URL valid for 1 hour
    """
    # Parse GCS path
    if gcs_path.startswith('gs://'):
        gcs_path = gcs_path[5:]  # Remove 'gs://'

    parts = gcs_path.split('/', 1)
    bucket_name = parts[0]
    blob_name = parts[1] if len(parts) > 1 else ''

    # Generate signed URL
    bucket = gcs_client.bucket(bucket_name)
    blob = bucket.blob(blob_name)

    url = blob.generate_signed_url(
        version="v4",
        expiration=timedelta(hours=1),
        method="GET"
    )

    return url


@app.route('/api/export/fhir', methods=['GET'])
def export_fhir():
    """Export all annotations as a FHIR Bundle."""
    try:
        # Query completed tasks
        tasks_query = f"""
            SELECT task_id, image_gcs_path, created_at, metadata
            FROM `{GCP_PROJECT_ID}.{BQ_DATASET}.annotation_tasks`
            WHERE status = 'completed'
        """
        tasks_results = bq_client.query(tasks_query).result()
        tasks = [{'task_id': row.task_id, 'image_path': row.image_gcs_path,
                  'created_at': row.created_at.isoformat() if row.created_at else None,
                  'metadata': json.loads(row.metadata) if row.metadata else {}}
                 for row in tasks_results]

        # Query annotations
        annotations_query = f"""
            SELECT annotation_id, task_id, annotator, annotation_data, created_at
            FROM `{GCP_PROJECT_ID}.{BQ_DATASET}.annotations`
            WHERE task_id IN (SELECT task_id FROM `{GCP_PROJECT_ID}.{BQ_DATASET}.annotation_tasks` WHERE status = 'completed')
        """
        annotations_results = bq_client.query(annotations_query).result()
        annotations = [{'annotation_id': row.annotation_id, 'task_id': row.task_id,
                        'annotator': row.annotator,
                        'annotation_data': json.loads(row.annotation_data) if isinstance(row.annotation_data, str) else row.annotation_data,
                        'created_at': row.created_at.isoformat() if row.created_at else None}
                       for row in annotations_results]

        # Generate FHIR Bundle
        bundle = export_to_fhir_bundle(annotations, tasks)

        return jsonify(bundle)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/export/fhir/observation/<task_id>', methods=['GET'])
def export_fhir_observation(task_id):
    """Export annotations for a specific task as FHIR Observations."""
    try:
        # Query task
        task_query = f"""
            SELECT task_id, image_gcs_path, created_at, metadata
            FROM `{GCP_PROJECT_ID}.{BQ_DATASET}.annotation_tasks`
            WHERE task_id = @task_id
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("task_id", "STRING", task_id)]
        )
        task_results = list(bq_client.query(task_query, job_config=job_config).result())

        if not task_results:
            return jsonify({'error': 'Task not found'}), 404

        task = {'task_id': task_results[0].task_id, 'image_path': task_results[0].image_gcs_path,
                'created_at': task_results[0].created_at.isoformat() if task_results[0].created_at else None}

        # Query annotations
        ann_query = f"""
            SELECT annotation_id, task_id, annotator, annotation_data, created_at
            FROM `{GCP_PROJECT_ID}.{BQ_DATASET}.annotations`
            WHERE task_id = @task_id
        """
        ann_results = bq_client.query(ann_query, job_config=job_config).result()
        annotations = [{'annotation_id': row.annotation_id, 'task_id': row.task_id,
                        'annotator': row.annotator,
                        'annotation_data': json.loads(row.annotation_data) if isinstance(row.annotation_data, str) else row.annotation_data,
                        'created_at': row.created_at.isoformat() if row.created_at else None}
                       for row in ann_results]

        if not annotations:
            return jsonify({'error': 'No annotations found'}), 404

        # Generate Observations
        observations = []
        for ann in annotations:
            obs = generate_observation(ann, task)
            if obs:
                observations.append(obs)

        return jsonify({
            'resourceType': 'Bundle',
            'type': 'collection',
            'entry': [{'resource': obs} for obs in observations]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/export/fhir/report/<task_id>', methods=['GET'])
def export_fhir_report(task_id):
    """Export DiagnosticReport for a specific task."""
    try:
        # Query task
        task_query = f"""
            SELECT task_id, image_gcs_path, created_at, metadata
            FROM `{GCP_PROJECT_ID}.{BQ_DATASET}.annotation_tasks`
            WHERE task_id = @task_id
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("task_id", "STRING", task_id)]
        )
        task_results = list(bq_client.query(task_query, job_config=job_config).result())

        if not task_results:
            return jsonify({'error': 'Task not found'}), 404

        task = {'task_id': task_results[0].task_id, 'image_path': task_results[0].image_gcs_path,
                'created_at': task_results[0].created_at.isoformat() if task_results[0].created_at else None}

        # Query annotations
        ann_query = f"""
            SELECT annotation_id, task_id, annotator, annotation_data, created_at
            FROM `{GCP_PROJECT_ID}.{BQ_DATASET}.annotations`
            WHERE task_id = @task_id
        """
        ann_results = bq_client.query(ann_query, job_config=job_config).result()
        annotations = [{'annotation_id': row.annotation_id, 'task_id': row.task_id,
                        'annotator': row.annotator,
                        'annotation_data': json.loads(row.annotation_data) if isinstance(row.annotation_data, str) else row.annotation_data,
                        'created_at': row.created_at.isoformat() if row.created_at else None}
                       for row in ann_results]

        if not annotations:
            return jsonify({'error': 'No annotations found'}), 404

        # Generate DiagnosticReport
        report = generate_diagnostic_report(annotations, task)

        return jsonify(report)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=True)
