#!/usr/bin/env python3
"""
Export annotations from BigQuery to various formats.

Usage:
    python export_annotations.py --format coco --output annotations.json
    python export_annotations.py --format csv --output annotations.csv
"""

import argparse
import json
from google.cloud import bigquery
import csv


def export_to_coco(project_id, dataset, output_path):
    """Export annotations to COCO format."""
    client = bigquery.Client(project=project_id)

    query = f"""
        SELECT
            t.task_id,
            t.image_gcs_path,
            a.annotation_data,
            a.annotator,
            a.created_at
        FROM `{project_id}.{dataset}.annotation_tasks` t
        JOIN `{project_id}.{dataset}.annotations` a
        ON t.task_id = a.task_id
        WHERE t.status = 'completed'
    """

    results = client.query(query).result()

    coco = {
        'info': {
            'description': 'Glyph Action Annotations',
            'version': '1.0',
            'year': 2026
        },
        'images': [],
        'annotations': [],
        'categories': [
            {'id': 1, 'name': 'Batting', 'supercategory': 'action'},
            {'id': 2, 'name': 'Bowling', 'supercategory': 'action'},
            {'id': 3, 'name': 'Fielding', 'supercategory': 'action'},
            {'id': 4, 'name': 'Wicketkeeping', 'supercategory': 'action'},
            {'id': 5, 'name': 'Ball', 'supercategory': 'object'},
        ]
    }

    cat_name_to_id = {cat['name']: cat['id'] for cat in coco['categories']}

    annotation_id = 1

    for idx, row in enumerate(results, 1):
        # Add image
        coco['images'].append({
            'id': idx,
            'file_name': row.image_gcs_path,
            'width': 1000,  # Update with actual dimensions if available
            'height': 1000
        })

        # Parse annotation data
        ann_data = json.loads(row.annotation_data)

        # Add bounding boxes
        for bbox in ann_data.get('bboxes', []):
            # Convert percentage to pixels
            x = bbox['x'] * 10
            y = bbox['y'] * 10
            w = bbox['width'] * 10
            h = bbox['height'] * 10

            coco['annotations'].append({
                'id': annotation_id,
                'image_id': idx,
                'category_id': cat_name_to_id[bbox['label']],
                'bbox': [x, y, w, h],
                'area': w * h,
                'iscrowd': 0
            })

            annotation_id += 1

    # Save to file
    with open(output_path, 'w') as f:
        json.dump(coco, f, indent=2)

    print(f"✓ Exported {len(coco['images'])} images to COCO format")
    print(f"✓ Total annotations: {len(coco['annotations'])}")
    print(f"✓ Saved to {output_path}")


def export_to_csv(project_id, dataset, output_path):
    """Export annotations to CSV format."""
    client = bigquery.Client(project=project_id)

    query = f"""
        SELECT
            t.task_id,
            t.image_gcs_path,
            a.annotation_data,
            a.annotator,
            a.created_at
        FROM `{project_id}.{dataset}.annotation_tasks` t
        JOIN `{project_id}.{dataset}.annotations` a
        ON t.task_id = a.task_id
        WHERE t.status = 'completed'
    """

    results = client.query(query).result()

    rows = []

    for row in results:
        ann_data = json.loads(row.annotation_data)

        for bbox in ann_data.get('bboxes', []):
            rows.append({
                'task_id': row.task_id,
                'image_gcs_path': row.image_gcs_path,
                'label': bbox['label'],
                'x': bbox['x'],
                'y': bbox['y'],
                'width': bbox['width'],
                'height': bbox['height'],
                'annotator': row.annotator,
                'created_at': row.created_at.isoformat()
            })

    # Save to CSV
    with open(output_path, 'w', newline='') as f:
        if rows:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

    print(f"✓ Exported {len(rows)} annotations to CSV")
    print(f"✓ Saved to {output_path}")


def export_to_json(project_id, dataset, output_path):
    """Export annotations to simple JSON format."""
    client = bigquery.Client(project=project_id)

    query = f"""
        SELECT
            t.task_id,
            t.image_gcs_path,
            a.annotation_data,
            a.annotator,
            a.created_at
        FROM `{project_id}.{dataset}.annotation_tasks` t
        JOIN `{project_id}.{dataset}.annotations` a
        ON t.task_id = a.task_id
        WHERE t.status = 'completed'
    """

    results = client.query(query).result()

    annotations = []

    for row in results:
        annotations.append({
            'task_id': row.task_id,
            'image_gcs_path': row.image_gcs_path,
            'annotation_data': json.loads(row.annotation_data),
            'annotator': row.annotator,
            'created_at': row.created_at.isoformat()
        })

    # Save to JSON
    with open(output_path, 'w') as f:
        json.dump(annotations, f, indent=2)

    print(f"✓ Exported {len(annotations)} annotations to JSON")
    print(f"✓ Saved to {output_path}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Export annotations from BigQuery')
    parser.add_argument('--format', required=True, choices=['coco', 'csv', 'json'], help='Export format')
    parser.add_argument('--output', required=True, help='Output file path')
    parser.add_argument('--project-id', default='your-project-id', help='GCP project ID')
    parser.add_argument('--dataset', default='image_annotations', help='BigQuery dataset')

    args = parser.parse_args()

    if args.format == 'coco':
        export_to_coco(args.project_id, args.dataset, args.output)
    elif args.format == 'csv':
        export_to_csv(args.project_id, args.dataset, args.output)
    elif args.format == 'json':
        export_to_json(args.project_id, args.dataset, args.output)
