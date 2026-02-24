# Flask REST API Template

A REST API template for Verily Workbench with built-in support for GCS and BigQuery.

## Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/resources` | GET | List workspace resources |
| `/buckets/<name>/files` | GET | List files in bucket |
| `/buckets/<name>/upload` | POST | Upload file to bucket |
| `/bigquery/query` | POST | Run BigQuery query |
| `/bigquery/tables/<dataset>` | GET | List tables in dataset |
| `/process` | POST | Custom processing endpoint |

## Customization

1. Edit `app/main.py` to add your endpoints
2. Update `app/requirements.txt` for additional dependencies
3. Modify `docker-compose.yaml` for environment variables

## Local Testing

```bash
cd app && pip install -r requirements.txt && python main.py
```

## Workspace Resources

Access workspace buckets and datasets via environment variables:
- `WORKBENCH_<resource_name>` contains the resource path
- Use `GET /resources` to see all available resources

## Example Usage

```bash
# Check health
curl http://localhost:8080/health

# List resources
curl http://localhost:8080/resources

# Query BigQuery
curl -X POST http://localhost:8080/bigquery/query \
  -H "Content-Type: application/json" \
  -d '{"query": "SELECT * FROM `project.dataset.table` LIMIT 10"}'
```
