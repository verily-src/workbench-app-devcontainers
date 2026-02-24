# File Processor Template

A file upload and processing template for Verily Workbench with GCS integration.

## Features

- **Drag & Drop Upload**: Easy file upload interface
- **Multi-format Support**: CSV, JSON, Excel files
- **Auto-processing**: Extracts metadata, row counts, column info
- **GCS Integration**: Save processed files to workspace buckets
- **Schema Validation**: Validate JSON against schemas

## Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web UI for file upload |
| `/health` | GET | Health check |
| `/buckets` | GET | List workspace buckets |
| `/upload` | POST | Upload and process file |
| `/validate` | POST | Validate file against schema |

## Supported File Types

| Type | Extensions | Processing |
|------|------------|------------|
| CSV | `.csv` | Row/column counts, schema, null detection |
| JSON | `.json` | Type detection, key enumeration |
| Excel | `.xlsx`, `.xls` | Row/column counts, schema |

## Customization

1. Edit `app/main.py` to add processing logic
2. Update `app/requirements.txt` for additional libraries
3. Add validation schemas to `/app/schemas/`

## Local Testing

```bash
cd app && pip install -r requirements.txt && python main.py
```

Open http://localhost:8080 in your browser.

## Workspace Resources

Workspace buckets are auto-discovered:
- `WORKBENCH_<resource_name>` environment variables
- Displayed in the web UI sidebar
- Used for automatic file storage

## API Usage

```bash
# Upload a file
curl -X POST http://localhost:8080/upload \
  -F "file=@data.csv" \
  -F "save_to_gcs=true"

# Validate JSON against schema
curl -X POST http://localhost:8080/validate \
  -F "file=@data.json" \
  -F 'schema={"type": "object", "required": ["id", "name"]}'
```
