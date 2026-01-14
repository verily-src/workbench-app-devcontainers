# Streamlit Natural Language to SQL Dashboard

A custom Workbench application that converts natural language questions into SQL queries using Vertex AI Gemini and executes them on BigQuery with interactive visualizations.

## Features

- 🗣️ **Natural Language Interface**: Ask questions in plain English
- 🤖 **AI-Powered**: Uses Vertex AI Gemini 1.5 Pro for intelligent SQL generation
- 🔒 **Secure**: Multi-layer SQL validation and injection prevention
- 📊 **Interactive Visualizations**: Auto-generate charts from query results
- 📜 **Query History**: Track and reuse previous queries
- 📥 **Export**: Download results as CSV or JSON
- ⚡ **Fast**: BigQuery query caching and optimized execution
- 🎯 **Schema-Aware**: Understands your dataset structure for better queries

## Architecture

```
┌─────────────────────┐
│   Streamlit UI      │
│   (Port 8501)       │
└──────────┬──────────┘
           │
    ┌──────┴──────┐
    │             │
    ▼             ▼
┌────────┐   ┌─────────┐
│ Gemini │   │BigQuery │
│   AI   │   │         │
└────────┘   └─────────┘
    │             │
    └─────┬───────┘
          ▼
    ┌───────────┐
    │ Security  │
    │Validation │
    └───────────┘
```

**Components:**
- **Frontend**: Streamlit (Python web framework)
- **AI Service**: Vertex AI Gemini API for NL-to-SQL conversion
- **Data Backend**: BigQuery for query execution
- **Security**: SQL validation with sqlparse
- **Auth**: Workbench Application Default Credentials

## Configuration

| Setting | Value | Description |
|---------|-------|-------------|
| **Image** | Python 3.11 (custom) | Built from Dockerfile |
| **Port** | 8501 | Streamlit default port |
| **User** | streamlit | Non-root user |
| **Home** | /home/streamlit | User home directory |
| **Network** | app-network | Workbench external network |

## Security Measures

This application implements multiple security layers:

### 1. Query Type Restriction
- **Only SELECT queries allowed**
- All other operations (DELETE, UPDATE, INSERT, DROP, etc.) are blocked

### 2. Keyword Blocking
Blocked keywords:
- DDL: `DROP`, `CREATE`, `ALTER`, `TRUNCATE`
- DML: `DELETE`, `UPDATE`, `INSERT`
- Security: `GRANT`, `REVOKE`, `EXEC`, `EXECUTE`

### 3. SQL Validation
- Parses SQL structure with `sqlparse`
- Detects multiple statements (prevents semicolon injection)
- Validates query structure and syntax
- Enforces query size limits (100KB max)

### 4. Execution Limits
- **Timeout**: 30 seconds per query
- **Result Limit**: 10,000 rows maximum
- **Billing Limit**: 10GB data processed per query
- **Query Cache**: Enabled for faster repeated queries

### 5. Prompt Engineering
- Gemini is explicitly instructed to generate only SELECT statements
- Includes schema context to prevent hallucinations
- Uses low temperature (0.1) for deterministic output

## Usage

### In Workbench

1. **Create Custom App**:
   - Navigate to Custom Apps in Workbench UI
   - Click "Create Custom App"
   - Point to this repository URL
   - Select `streamlit-nl-sql` template
   - Choose `gcp` for cloud provider
   - Launch the app

2. **Wait for Container Build**:
   - First launch builds the Docker image (~2-3 minutes)
   - Subsequent launches are faster

3. **Access the App**:
   - Click the app URL in Workbench
   - The Streamlit interface will open

### Example Queries

**Basic Queries:**
- "Show me the first 10 rows from any table"
- "Count the total number of records"
- "List all unique values in the category column"

**Aggregation Queries:**
- "Show me the top 10 customers by revenue"
- "What is the average order value by month?"
- "Count records grouped by status"

**Time-based Queries:**
- "Show sales trends for the last 30 days"
- "What were the total sales by month in 2023?"
- "Find records created this week"

**Filtering Queries:**
- "Show customers who haven't purchased in 90 days"
- "Find orders above $1000"
- "List active users from California"

## Workflow

1. **Select Dataset**: Choose BigQuery dataset from sidebar
2. **Optional: View Schema**: Check available tables and columns
3. **Enter Question**: Type your question in natural language
4. **Generate SQL**: Click "Generate SQL" button
5. **Review**: Check generated SQL, confidence level, and explanation
6. **Execute**: Click "Execute Query" to run on BigQuery
7. **Visualize**: View results as table, charts, or export to CSV/JSON

## File Structure

```
streamlit-nl-sql/
├── .devcontainer.json          # Dev container configuration
├── docker-compose.yaml         # Docker compose setup
├── Dockerfile                  # Custom Python 3.11 image
├── devcontainer-template.json  # Template metadata
├── requirements.txt            # Python dependencies
├── README.md                   # This file
└── app/
    ├── __init__.py            # Package initialization
    ├── main.py                # Main Streamlit application
    ├── config.py              # Configuration management
    ├── security.py            # SQL validation and security
    ├── gemini_service.py      # Vertex AI Gemini integration
    ├── bigquery_service.py    # BigQuery query execution
    └── utils.py               # Helper functions
```

## Local Development

### Prerequisites
- Docker and Docker Compose
- GCP credentials with BigQuery and Vertex AI access

### Setup

1. **Create Docker network**:
   ```bash
   docker network create app-network
   ```

2. **Set environment variables**:
   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json
   export GCP_PROJECT=your-project-id
   export VERTEX_AI_LOCATION=us-central1  # optional
   ```

3. **Build and run**:
   ```bash
   cd src/streamlit-nl-sql
   docker-compose build
   docker-compose up
   ```

4. **Access app**:
   ```
   http://localhost:8501
   ```

### Development Tips

- **Live Reload**: Streamlit auto-reloads on file changes
- **Logs**: Check Docker logs for errors: `docker-compose logs -f`
- **Debug Mode**: Set `STREAMLIT_SERVER_FILE_WATCHER_TYPE=poll` for better live reload
- **Cache Clear**: Use Streamlit's "Clear Cache" from the hamburger menu

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GCP_PROJECT` | GCP project ID | Auto-detected from metadata |
| `GOOGLE_CLOUD_PROJECT` | Alternative to GCP_PROJECT | - |
| `VERTEX_AI_LOCATION` | Vertex AI region | us-central1 |

## Troubleshooting

### "Unable to determine GCP project ID"
**Solution**: Ensure you're running in a Workbench environment or set `GCP_PROJECT`:
```bash
export GCP_PROJECT=your-project-id
```

### "Permission denied" errors
**Cause**: Missing BigQuery or Vertex AI permissions

**Solution**: Ensure your Workbench user has:
- `roles/bigquery.user` or higher for BigQuery
- `roles/aiplatform.user` for Vertex AI
- Dataset-specific read permissions

### Slow query generation (>10 seconds)
**Cause**: Large schema context or Gemini API latency

**Solutions**:
- Reduce number of tables in schema view
- Use simpler questions
- Check Vertex AI API quotas

### "Query timeout exceeded"
**Cause**: Query takes longer than 30 seconds

**Solutions**:
- Add LIMIT clause to restrict results
- Optimize query (add WHERE filters)
- Query smaller tables

### Generated SQL is incorrect
**Causes**:
- Ambiguous question
- Schema not loaded
- Complex query beyond Gemini's capabilities

**Solutions**:
- Rephrase question more specifically
- Load schema to provide context
- Use "Edit SQL" to manually correct
- Break complex queries into simpler steps

### Container fails to start
**Debugging steps**:
```bash
# Check logs
docker-compose logs

# Rebuild image
docker-compose build --no-cache

# Verify network exists
docker network ls | grep app-network
```

## Testing

To test this app template:

```bash
cd test
./test.sh streamlit-nl-sql streamlit false false
```

## Dependencies

### Python Packages

| Package | Version | Purpose |
|---------|---------|---------|
| streamlit | 1.30.0 | Web UI framework |
| google-cloud-bigquery | 3.14.1 | BigQuery client |
| google-cloud-aiplatform | 1.39.0 | Vertex AI SDK |
| pandas | 2.1.4 | Data processing |
| plotly | 5.18.0 | Interactive charts |
| sqlparse | 0.4.4 | SQL validation |

## Contributing

To customize this app:

1. Fork the workbench-app-devcontainers repository
2. Modify files in `src/streamlit-nl-sql/`
3. Test locally using Docker Compose
4. Commit and push to your fork
5. Update custom app in Workbench UI

## Version History

- **1.0.0** (2026-01-14): Initial release
  - Natural language to SQL conversion
  - BigQuery integration
  - Interactive visualizations
  - Security validation
  - Query history
  - CSV/JSON export
