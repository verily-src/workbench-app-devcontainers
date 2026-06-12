# Architecture - In-House Annotation Tool

## System Design

### High-Level Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      USERS / ANNOTATORS                       │
│                     (Web Browser)                             │
└──────────────────────────┬───────────────────────────────────┘
                           │ HTTPS
                           ↓
┌──────────────────────────────────────────────────────────────┐
│                    ANNOTATION WEB APP                         │
│                  (Flask + HTML/JS + Fabric.js)                │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐     │
│  │              Frontend (index.html)                  │     │
│  │  - Task list UI                                     │     │
│  │  - Canvas-based annotation (Fabric.js)              │     │
│  │  - Bounding box drawing                             │     │
│  │  - Label selection                                  │     │
│  │  - Keyboard shortcuts                               │     │
│  └──────────────────────┬──────────────────────────────┘     │
│                         │ REST API calls                      │
│  ┌──────────────────────▼──────────────────────────────┐     │
│  │              Backend (app.py - Flask)               │     │
│  │                                                     │     │
│  │  API Endpoints:                                     │     │
│  │  - GET  /api/tasks          (fetch pending tasks)  │     │
│  │  - POST /api/tasks/:id/start (mark in-progress)    │     │
│  │  - POST /api/annotations     (save annotation)     │     │
│  │  - GET  /api/annotations/:id (get annotation)      │     │
│  │  - GET  /api/stats           (progress metrics)    │     │
│  │                                                     │     │
│  │  Core Functions:                                    │     │
│  │  - Query BigQuery for tasks                        │     │
│  │  - Generate GCS signed URLs                        │     │
│  │  - Insert annotations to BigQuery                  │     │
│  └──────────┬────────────────────────┬─────────────────┘     │
└─────────────┼────────────────────────┼───────────────────────┘
              │                        │
              ↓                        ↓
┌─────────────────────────┐  ┌──────────────────────┐
│      BigQuery           │  │   Cloud Storage      │
│                         │  │                      │
│  Tasks Table:           │  │  Images:             │
│  ┌───────────────────┐  │  │  gs://bucket/        │
│  │ task_id           │  │  │  ├── image_001.jpg   │
│  │ image_gcs_path    │  │  │  ├── image_002.jpg   │
│  │ task_type         │  │  │  └── ...             │
│  │ labels []         │  │  │                      │
│  │ status            │  │  │  Signed URLs:        │
│  │ created_at        │  │  │  (1 hour expiry)     │
│  └───────────────────┘  │  │                      │
│                         │  └──────────────────────┘
│  Annotations Table:     │
│  ┌───────────────────┐  │
│  │ annotation_id     │  │
│  │ task_id           │  │
│  │ annotator         │  │
│  │ annotation_data   │  │
│  │ created_at        │  │
│  └───────────────────┘  │
└─────────────────────────┘
```

---

## Data Flow

### 1. Task Loading (Offline)

```
ML Engineer
    │
    ↓ uploads images
┌─────────────┐
│   GCS Bucket│
└──────┬──────┘
       │
       ↓ python scripts/load_tasks.py
┌─────────────────────────┐
│   BigQuery              │
│   annotation_tasks      │
│   ┌───────────────────┐ │
│   │ task_id: abc123   │ │
│   │ image: gs://...   │ │
│   │ status: pending   │ │
│   └───────────────────┘ │
└─────────────────────────┘
```

### 2. Annotation Workflow (Real-time)

```
Annotator opens web app
    │
    ↓ GET /api/tasks
Flask queries BigQuery
    │
    ↓ Returns tasks
Web UI displays task list
    │
    ↓ User clicks task
Flask generates signed URL
    │
    ↓ Returns image URL
Browser loads image from GCS
    │
    ↓ User draws boxes
JavaScript collects bbox data
    │
    ↓ POST /api/annotations
Flask saves to BigQuery
    │
    ↓ Updates task status
Task marked as 'completed'
```

### 3. Export (Offline)

```
ML Engineer
    │
    ↓ python scripts/export_annotations.py
BigQuery annotations table
    │
    ↓ JOIN with tasks table
Convert to COCO/CSV format
    │
    ↓ Save to file
annotations.json (COCO)
    │
    ↓ Use for training
YOLO / Detectron2 / etc.
```

---

## Database Schema

### Tasks Table

```sql
CREATE TABLE annotation_tasks (
  task_id STRING NOT NULL,           -- UUID
  image_gcs_path STRING NOT NULL,    -- gs://bucket/path/image.jpg
  task_type STRING NOT NULL,         -- 'bbox', 'classification', etc.
  labels ARRAY<STRING>,              -- ['Batting', 'Bowling', ...]
  metadata JSON,                     -- Flexible extra data
  status STRING DEFAULT 'pending',   -- 'pending', 'in_progress', 'completed'
  created_at TIMESTAMP,
  assigned_to STRING                 -- Optional: user email
);
```

**Indexes**: 
- Primary: `task_id`
- Query: `status` (for fetching pending tasks)

---

### Annotations Table

```sql
CREATE TABLE annotations (
  annotation_id STRING NOT NULL,     -- UUID
  task_id STRING NOT NULL,           -- FK to annotation_tasks
  annotator STRING NOT NULL,         -- user email
  annotation_data JSON,              -- Flexible annotation format
  annotation_type STRING,            -- 'bbox', 'classification', etc.
  created_at TIMESTAMP,
  updated_at TIMESTAMP
);
```

**Sample annotation_data for bounding boxes:**
```json
{
  "bboxes": [
    {
      "label": "Batting",
      "x": 10.5,
      "y": 20.3,
      "width": 30.2,
      "height": 40.1
    },
    {
      "label": "Bowling",
      "x": 50.0,
      "y": 30.0,
      "width": 25.0,
      "height": 35.0
    }
  ]
}
```

**Indexes**:
- Primary: `annotation_id`
- Foreign key: `task_id`
- Query: `annotator` (for tracking user work)

---

## API Endpoints

### GET /api/tasks

**Purpose**: Fetch pending annotation tasks

**Query Params**:
- `limit` (int): Number of tasks (default: 10)
- `status` (string): Filter by status (default: 'pending')

**Response**:
```json
{
  "tasks": [
    {
      "task_id": "abc-123",
      "image_url": "https://storage.googleapis.com/...",
      "task_type": "bbox",
      "labels": ["Batting", "Bowling"],
      "metadata": {},
      "status": "pending"
    }
  ],
  "count": 10
}
```

---

### POST /api/tasks/:id/start

**Purpose**: Mark task as in-progress when annotator starts

**Response**:
```json
{
  "status": "success",
  "task_id": "abc-123"
}
```

---

### POST /api/annotations

**Purpose**: Save completed annotation

**Request Body**:
```json
{
  "task_id": "abc-123",
  "annotator": "user@example.com",
  "annotation_type": "bbox",
  "annotation_data": {
    "bboxes": [
      {
        "label": "Batting",
        "x": 10.5,
        "y": 20.3,
        "width": 30.2,
        "height": 40.1
      }
    ]
  }
}
```

**Response**:
```json
{
  "status": "success",
  "annotation_id": "xyz-789",
  "task_id": "abc-123"
}
```

---

### GET /api/stats

**Purpose**: Get overall progress statistics

**Response**:
```json
{
  "pending": 50,
  "in_progress": 5,
  "completed": 45,
  "total": 100
}
```

---

## Component Details

### Frontend (Fabric.js Canvas)

**Technology**: Fabric.js for interactive canvas

**Features**:
- Draw rectangles by click-and-drag
- Resize/move existing boxes
- Multi-select and delete
- Label colors for visual distinction
- Undo/redo functionality

**Key Code**:
```javascript
// Create rectangle on mouse down
canvas.on('mouse:down', function(options) {
  const pointer = canvas.getPointer(options.e);
  currentRect = new fabric.Rect({
    left: pointer.x,
    top: pointer.y,
    fill: 'transparent',
    stroke: labelColors[selectedLabel],
    strokeWidth: 3
  });
  canvas.add(currentRect);
});
```

---

### Backend (Flask)

**Technology**: Flask (Python)

**Key Functions**:

1. **GCS Signed URLs**:
```python
def generate_signed_url(gcs_path):
    bucket = gcs_client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    return blob.generate_signed_url(
        version="v4",
        expiration=timedelta(hours=1),
        method="GET"
    )
```

2. **BigQuery Queries**:
```python
query = """
    SELECT task_id, image_gcs_path
    FROM annotation_tasks
    WHERE status = 'pending'
    LIMIT 10
"""
results = bq_client.query(query).result()
```

3. **Save Annotations**:
```python
rows = [{
    'annotation_id': str(uuid.uuid4()),
    'task_id': task_id,
    'annotation_data': json.dumps(data)
}]
bq_client.insert_rows_json(table_id, rows)
```

---

## Deployment Architectures

### Development (Workbench)

```
Jupyter Notebook
    ↓ python app.py
Flask (localhost:8080)
    ↓ queries
BigQuery (same project)
GCS (same project)
```

**Pros**: Fast iteration, easy debugging  
**Cons**: Single user, not persistent

---

### Production (Cloud Run)

```
Internet
    ↓ HTTPS
Cloud Load Balancer
    ↓
Cloud Run (auto-scales 0→10 instances)
    ↓ IAM auth
BigQuery (shared dataset)
GCS (shared bucket)
```

**Pros**: Auto-scaling, serverless, HTTPS  
**Cost**: ~$5-20/month

---

### Enterprise (GKE)

```
Internet
    ↓ HTTPS
Ingress Controller
    ↓
Kubernetes Service
    ↓
Pods (Flask app) × N
    ↓
BigQuery + GCS
```

**Pros**: Full control, advanced features  
**Cons**: More complex, higher cost

---

## Security Model

### Authentication Flow

```
User → Cloud IAM Identity
    ↓
Cloud Run (requires auth)
    ↓
Service Account (app)
    ↓ minimal permissions
BigQuery (dataEditor)
GCS (objectViewer)
```

### Permissions Required

**App Service Account**:
- `roles/bigquery.dataEditor` - Read/write annotation tables
- `roles/storage.objectViewer` - Read images
- `roles/iam.serviceAccountTokenCreator` - Generate signed URLs

**Annotator Users**:
- `roles/run.invoker` - Access Cloud Run service

---

## Performance Characteristics

### Latency

- **Load tasks**: ~200ms (BigQuery query)
- **Load image**: ~500ms (GCS signed URL + download)
- **Save annotation**: ~300ms (BigQuery insert)

### Throughput

- **Single annotator**: 5-10 images/hour
- **10 annotators**: 50-100 images/hour
- **Auto-scaling**: Handles 100+ concurrent users

### Costs (per 10,000 annotations)

- **BigQuery**: <$1 (queries + storage)
- **GCS**: ~$2 (image storage)
- **Cloud Run**: ~$5 (compute)
- **Total**: **~$8/month**

---

## Comparison to Label Studio

| Aspect | In-House Tool | Label Studio |
|--------|---------------|--------------|
| **Setup** | 30 min | 4 hours |
| **Cost** | $8/mo | $500/mo (managed) |
| **GCP Integration** | Native | Via connectors |
| **Customization** | Full control | Limited |
| **Scalability** | Serverless auto-scale | Requires k8s |
| **Features** | Bbox, classification | Advanced (segmentation, NER) |
| **Use Case** | Simple annotations | Complex multi-modal |

---

## Future Enhancements

### Phase 2
- User authentication with Google OAuth
- Annotation review workflow
- Inter-annotator agreement metrics
- Annotation quality scoring

### Phase 3
- Active learning integration
- Model-assisted pre-annotation
- Video frame annotation
- Segmentation support

---

This architecture provides a **lightweight, cost-effective, and scalable** alternative to Label Studio for Google Cloud environments! 🎯
