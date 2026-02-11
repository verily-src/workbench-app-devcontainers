# GCP Data Chat

**Talk to your GCP data using AI** — a modern web GUI for asking questions about BigQuery tables and GCS files in plain language.

## What It Does

1. **Connect to your GCP data** — Browse and load data from GCS buckets or BigQuery tables. Auto-discovers your resources using Workbench credentials.
2. **Ask questions in plain language** — Type questions like "What columns are in this table?" or "What's the range of values in column X?" and get instant answers.
3. **Generate charts and histograms** — Ask "Show me the distribution of column Y" and get inline charts rendered directly in the chat.
4. **Auto-load API key** — Uses Google Secret Manager to auto-fetch your OpenAI API key so you don't paste it every time.

## Architecture

- **Backend:** Flask (Python) serving REST APIs + static files
- **Frontend:** Modern HTML/CSS/JS with a guided 3-step wizard
- **LLM:** OpenAI API (gpt-4o-mini by default, US endpoint supported)
- **Charts:** matplotlib, executed server-side from LLM-generated code
- **GCP:** google-cloud-storage, google-cloud-bigquery, google-cloud-secret-manager

## Guided Steps

| Step | What You Do |
|------|-------------|
| **1. Configure** | Set GCP project (auto-detected) and OpenAI API key (from Secret Manager or paste) |
| **2. Connect Data** | Browse GCS buckets or BigQuery datasets, select and load a table |
| **3. Chat** | Ask questions, get text answers and inline charts |

## Deploy to Workbench

In the Workbench UI, create a custom app with:
- **Repository:** `git@github.com:verily-src/workbench-app-devcontainers.git`
- **Branch:** your branch
- **Folder:** `src/gcp-data-chat`

### Auto-load API key (optional)

Uncomment the environment variables in `docker-compose.yaml`:

```yaml
environment:
  OPENAI_SECRET_PROJECT: "wb-smart-cabbage-5940"
  OPENAI_SECRET_NAME: "si-ops-openai-api-key"
  OPENAI_SECRET_VERSION: "latest"
```

## Local Testing

```bash
# Create required network
docker network create app-network

# Build and run
cd src/gcp-data-chat
docker compose build
docker compose up

# Open http://localhost:8080
```

## File Structure

```
src/gcp-data-chat/
├── .devcontainer.json          # Workbench devcontainer config
├── devcontainer-template.json  # App metadata
├── docker-compose.yaml         # Container + network setup
├── Dockerfile                  # Build from python:3.11-slim
├── README.md
└── app/
    ├── main.py                 # Flask app + API routes
    ├── gcp_tools.py            # GCS, BigQuery, Secret Manager helpers
    ├── llm_engine.py           # OpenAI chat + chart generation engine
    ├── requirements.txt        # Python dependencies
    ├── templates/
    │   └── index.html          # Main page template
    └── static/
        ├── style.css           # Modern UI styles
        └── app.js              # Frontend interactivity
```

## Key Design Decisions

- **Flask over Streamlit** — Full control over the UI, proper REST API, better UX with guided steps
- **python:3.11-slim base** — Clean, no conflicts with Jupyter or other base image startup scripts
- **Single container** — Flask serves both the API and static files, no supervisor needed
- **Chart code execution** — The LLM generates matplotlib code which is executed server-side and returned as base64 PNG images inline in the chat
- **US endpoint support** — Company OpenAI keys that require the US endpoint are supported with a checkbox toggle
