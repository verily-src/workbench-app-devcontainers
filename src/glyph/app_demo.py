"""
Glyph Annotation Tool - DEMO MODE

This is a demo version that runs locally without BigQuery/GCS.
Uses local file storage and serves images from data/images/

Usage:
    python app_demo.py
    # Open http://localhost:8080
"""

from flask import Flask, render_template, request, jsonify, send_from_directory
from datetime import datetime
import uuid
import json
import os
from pathlib import Path

app = Flask(__name__)

# In-memory storage (for demo)
TASKS = []
ANNOTATIONS = []
TASK_ID_COUNTER = 1

# Get absolute path to images
BASE_DIR = Path(__file__).parent.parent
IMAGES_DIR = BASE_DIR / "data" / "images"


def load_demo_tasks():
    """Load tasks from local images directory."""
    global TASK_ID_COUNTER, TASKS

    if not IMAGES_DIR.exists():
        print(f"⚠️  Images directory not found: {IMAGES_DIR}")
        return

    # Find all images
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
    image_files = [
        f for f in IMAGES_DIR.iterdir()
        if f.suffix.lower() in image_extensions
    ]

    TASKS = []
    for img_file in sorted(image_files):
        task = {
            'task_id': f'task_{TASK_ID_COUNTER:03d}',
            'image_path': img_file.name,
            'task_type': 'bbox',
            'labels': ['Batting', 'Bowling', 'Fielding', 'Wicketkeeping', 'Ball'],
            'metadata': {'filename': img_file.name},
            'status': 'pending'
        }
        TASKS.append(task)
        TASK_ID_COUNTER += 1

    print(f"✓ Loaded {len(TASKS)} demo tasks")


@app.route('/')
def index():
    """Main annotation interface."""
    return render_template('index.html')


@app.route('/images/<path:filename>')
def serve_image(filename):
    """Serve images from local directory."""
    return send_from_directory(IMAGES_DIR, filename)


@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    """Fetch pending annotation tasks."""
    limit = request.args.get('limit', 10, type=int)
    status = request.args.get('status', 'pending')

    # Filter by status
    filtered_tasks = [t for t in TASKS if t['status'] == status]

    # Limit results
    tasks_to_return = filtered_tasks[:limit]

    # Add image URLs
    for task in tasks_to_return:
        task['image_url'] = f'/images/{task["image_path"]}'

    return jsonify({'tasks': tasks_to_return, 'count': len(tasks_to_return)})


@app.route('/api/tasks/<task_id>/start', methods=['POST'])
def start_task(task_id):
    """Mark task as in_progress."""
    for task in TASKS:
        if task['task_id'] == task_id:
            task['status'] = 'in_progress'
            return jsonify({'status': 'success', 'task_id': task_id})

    return jsonify({'status': 'error', 'message': 'Task not found'}), 404


@app.route('/api/annotations', methods=['POST'])
def save_annotation():
    """Save annotation."""
    data = request.json

    annotation_id = str(uuid.uuid4())

    annotation = {
        'annotation_id': annotation_id,
        'task_id': data['task_id'],
        'annotator': data.get('annotator', 'demo_user'),
        'annotation_data': data['annotation_data'],
        'annotation_type': data.get('annotation_type', 'bbox'),
        'created_at': datetime.utcnow().isoformat(),
        'updated_at': datetime.utcnow().isoformat()
    }

    ANNOTATIONS.append(annotation)

    # Update task status
    for task in TASKS:
        if task['task_id'] == data['task_id']:
            task['status'] = 'completed'
            break

    print(f"✓ Saved annotation: {annotation_id} for task {data['task_id']}")
    print(f"  Boxes: {len(data['annotation_data'].get('bboxes', []))}")

    return jsonify({
        'status': 'success',
        'annotation_id': annotation_id,
        'task_id': data['task_id']
    })


@app.route('/api/annotations/<task_id>', methods=['GET'])
def get_annotation(task_id):
    """Fetch existing annotation for a task."""
    for annotation in reversed(ANNOTATIONS):
        if annotation['task_id'] == task_id:
            return jsonify({'annotation': annotation})

    return jsonify({'annotation': None})


@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get annotation statistics."""
    stats = {'total': len(TASKS)}

    for task in TASKS:
        status = task['status']
        stats[status] = stats.get(status, 0) + 1

    return jsonify(stats)


@app.route('/api/export', methods=['GET'])
def export_annotations():
    """Export all annotations to COCO format."""
    coco = {
        'info': {
            'description': 'Glyph Annotations (Demo)',
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

    for idx, task in enumerate(TASKS, 1):
        if task['status'] != 'completed':
            continue

        # Add image
        coco['images'].append({
            'id': idx,
            'file_name': task['image_path'],
            'width': 1000,
            'height': 1000
        })

        # Find annotation
        task_annotation = None
        for ann in ANNOTATIONS:
            if ann['task_id'] == task['task_id']:
                task_annotation = ann
                break

        if not task_annotation:
            continue

        # Add bounding boxes
        for bbox in task_annotation['annotation_data'].get('bboxes', []):
            x = bbox['x'] * 10
            y = bbox['y'] * 10
            w = bbox['width'] * 10
            h = bbox['height'] * 10

            coco['annotations'].append({
                'id': annotation_id,
                'image_id': idx,
                'category_id': cat_name_to_id.get(bbox['label'], 1),
                'bbox': [x, y, w, h],
                'area': w * h,
                'iscrowd': 0
            })

            annotation_id += 1

    return jsonify(coco)


if __name__ == '__main__':
    print("\n" + "="*60)
    print("Verily - Glyph, an annotations tool - DEMO MODE")
    print("="*60)
    print("")

    # Load demo tasks
    load_demo_tasks()

    if not TASKS:
        print("⚠️  No images found!")
        print(f"   Please add images to: {IMAGES_DIR}")
        print("")
        print("   Or check existing images:")
        print(f"   ls '{IMAGES_DIR}'")
        print("")
    else:
        print(f"✓ Loaded {len(TASKS)} tasks from {IMAGES_DIR}")
        print("")

    port = int(os.getenv('PORT', 8080))
    print(f"🚀 Starting server on http://localhost:{port}")
    print(f"📝 Open in browser to start annotating")
    print(f"📊 Export annotations: http://localhost:{port}/api/export")
    print("")
    print("Press Ctrl+C to stop")
    print("="*60)
    print("")

    app.run(host='0.0.0.0', port=port, debug=True)
