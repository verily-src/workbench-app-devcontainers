#!/usr/bin/env python3
"""
Load annotation tasks into BigQuery.

Usage:
    python load_tasks.py --csv tasks.csv
    python load_tasks.py --gcs-prefix gs://bucket/images/
"""

import argparse
import uuid
from google.cloud import bigquery
from pathlib import Path
import csv


def load_tasks_from_csv(csv_path, project_id, dataset):
    """Load tasks from CSV file.

    CSV format:
    image_gcs_path,task_type,labels
    gs://bucket/image1.jpg,bbox,"Batting,Bowling,Fielding"
    gs://bucket/image2.jpg,bbox,"Batting,Bowling"
    """
    client = bigquery.Client(project=project_id)
    table_id = f"{project_id}.{dataset}.annotation_tasks"

    rows_to_insert = []

    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            labels = row['labels'].split(',')

            task = {
                'task_id': str(uuid.uuid4()),
                'image_gcs_path': row['image_gcs_path'],
                'task_type': row.get('task_type', 'bbox'),
                'labels': labels,
                'metadata': '{}',
                'status': 'pending'
            }

            rows_to_insert.append(task)

    errors = client.insert_rows_json(table_id, rows_to_insert)

    if errors:
        print(f"❌ Errors: {errors}")
    else:
        print(f"✓ Loaded {len(rows_to_insert)} tasks into BigQuery")


def load_tasks_from_gcs_prefix(gcs_prefix, project_id, dataset, task_type='bbox', labels=None):
    """Load tasks from all images in a GCS prefix.

    Args:
        gcs_prefix: GCS path like gs://bucket/images/
        project_id: GCP project ID
        dataset: BigQuery dataset
        task_type: Type of annotation task
        labels: List of labels for the task
    """
    from google.cloud import storage

    if labels is None:
        labels = ['Batting', 'Bowling', 'Fielding', 'Wicketkeeping', 'Ball']

    # Parse GCS prefix
    if gcs_prefix.startswith('gs://'):
        gcs_prefix = gcs_prefix[5:]

    parts = gcs_prefix.split('/', 1)
    bucket_name = parts[0]
    prefix = parts[1] if len(parts) > 1 else ''

    # List all images
    storage_client = storage.Client(project=project_id)
    bucket = storage_client.bucket(bucket_name)
    blobs = bucket.list_blobs(prefix=prefix)

    # Filter image files
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
    image_blobs = [
        blob for blob in blobs
        if Path(blob.name).suffix.lower() in image_extensions
    ]

    print(f"Found {len(image_blobs)} images in gs://{bucket_name}/{prefix}")

    # Create tasks
    bq_client = bigquery.Client(project=project_id)
    table_id = f"{project_id}.{dataset}.annotation_tasks"

    rows_to_insert = []

    for blob in image_blobs:
        task = {
            'task_id': str(uuid.uuid4()),
            'image_gcs_path': f'gs://{bucket_name}/{blob.name}',
            'task_type': task_type,
            'labels': labels,
            'metadata': '{}',
            'status': 'pending'
        }

        rows_to_insert.append(task)

    # Insert in batches
    batch_size = 500
    for i in range(0, len(rows_to_insert), batch_size):
        batch = rows_to_insert[i:i+batch_size]
        errors = bq_client.insert_rows_json(table_id, batch)

        if errors:
            print(f"❌ Batch {i//batch_size + 1} errors: {errors}")
        else:
            print(f"✓ Loaded batch {i//batch_size + 1} ({len(batch)} tasks)")

    print(f"\n✓ Total: Loaded {len(rows_to_insert)} tasks into BigQuery")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Load annotation tasks into BigQuery')
    parser.add_argument('--csv', help='CSV file with tasks')
    parser.add_argument('--gcs-prefix', help='GCS prefix to scan for images')
    parser.add_argument('--project-id', default='your-project-id', help='GCP project ID')
    parser.add_argument('--dataset', default='cricket_annotations', help='BigQuery dataset')
    parser.add_argument('--task-type', default='bbox', help='Task type')
    parser.add_argument('--labels', nargs='+', help='Labels for the task')

    args = parser.parse_args()

    if args.csv:
        load_tasks_from_csv(args.csv, args.project_id, args.dataset)
    elif args.gcs_prefix:
        load_tasks_from_gcs_prefix(
            args.gcs_prefix,
            args.project_id,
            args.dataset,
            args.task_type,
            args.labels
        )
    else:
        print("Usage:")
        print("  --csv tasks.csv")
        print("  --gcs-prefix gs://bucket/images/")
