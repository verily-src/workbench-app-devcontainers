# GCP Talk to Your Data (GUI)

Streamlit app to connect to your GCP data (GCS or BigQuery) and **talk to your data** using an LLM (OpenAI-compatible, with optional US endpoint for company keys).

Same structure as the [gcp-talk-to-your-data](../gcp-talk-to-your-data) Jupyter app: pre-built image, no Docker build, runs reliably on Verily Workbench.

---

## Setup and test (step-by-step)

### 1. Prerequisites

- Access to **Verily Workbench** and permission to create custom apps.
- Your **fork** of `workbench-app-devcontainers` with the `gcp-talk-to-your-data-gui` app (ensure branch has the latest code, e.g. `master`).
- GCP permissions in the Workbench environment:
  - **GCS**: list buckets/blobs and read objects (or use a project where you have access).
  - **BigQuery**: list datasets/tables and run queries (or use a project where you have access).
  - **Secret Manager** (if using company key): access to the secret, e.g. in project `wb-smart-cabbage-5940`, secret `si-ops-openai-api-key`.

### 2. Create the app in Workbench

1. In Workbench, go to create/launch a **custom application** (or “Custom app” / “From devcontainer template”).
2. Set:
   - **Repository URL**: `https://github.com/<your-org>/workbench-app-devcontainers` (your fork).
   - **Branch**: `master` (or the branch where the app lives).
   - **Repository folder path**: `src/gcp-talk-to-your-data-gui`
   - **Port**: `8501`
3. If your Workbench supports **environment variables** for the app, optionally set (for auto-fetch of the API key):
   - `OPENAI_SECRET_PROJECT` = `wb-smart-cabbage-5940`
   - `OPENAI_SECRET_NAME` = `si-ops-openai-api-key`
   - `OPENAI_SECRET_VERSION` = `latest` (optional)
4. Create/start the application. Wait until the app is running and the UI is reachable (Workbench usually shows an “Open” or link to the app).

### 3. Open the app

- Use the link Workbench provides (e.g. “Open application” or the URL for port 8501). The Streamlit UI should load.

### 4. Set the API key (if not using auto-fetch)

- **Option A – Auto-fetch**: If you set the env vars in step 2, the key should load automatically. Check the sidebar for: *“Key loaded from Secret Manager (auto-fetch)”*.
- **Option B – Paste**: In the sidebar, choose **“Paste key”** and enter your OpenAI API key.
- **Option C – Secret Manager**: Choose **“Secret Manager”**, enter GCP project (e.g. `wb-smart-cabbage-5940`), secret name (e.g. `si-ops-openai-api-key`), version (e.g. `latest`), then click **“Fetch key from Secret Manager”**.
- Leave **“Use US endpoint (company keys)”** checked if you use the Verily company key.

### 5. Load data

- In the sidebar, under **Data source**, choose **GCS** or **BigQuery**.
- **GCS**: Select or enter project → bucket → optional prefix → file path → format (csv/parquet/json) → click **“Load from GCS”**.
- **BigQuery**: Select project → dataset → table → row limit → click **“Load from BigQuery”**.
- Wait for a success message (e.g. “Loaded N rows”). The main area will show a data preview.

### 6. Test “Talk to your data”

- In the main area, type a question in **“Question about the data”** (e.g. “What columns are in this dataset?” or “What is the range of values in column X?”).
- Optionally change the **Model** (default `gpt-4o-mini`).
- Click **“Ask”**.
- You should see the model’s answer below. Ask follow-up questions as needed (each uses the same loaded data and key).

### 7. Troubleshooting

| Issue | What to do |
|-------|------------|
| App doesn’t start or port not reachable | Confirm repository folder path is exactly `src/gcp-talk-to-your-data-gui` and port is `8501`. Check Workbench logs. |
| “Set your API key in the sidebar” | Provide key via Paste, Secret Manager, or env-based auto-fetch (step 4). |
| 401 / “incorrect regional hostname” from OpenAI | Keep **“Use US endpoint (company keys)”** checked for the company key. |
| GCS/BigQuery permission errors | Use a GCP project (and bucket/dataset) where your Workbench identity has list/read or query permissions. |
| Secret Manager permission denied | Confirm your Workbench environment has access to the secret in the given project. |

---

## Workbench reference

- **Repository URL**: your fork of `workbench-app-devcontainers`
- **Branch**: `master`
- **Repository folder path**: `src/gcp-talk-to-your-data-gui`
- **Port**: 8501

## Features

- **Sidebar**: Choose API key (paste or fetch from Secret Manager), then pick data source:
  - **GCS**: Select project → bucket → prefix (optional) → file path → format (csv/parquet/json) → Load
  - **BigQuery**: Select project → dataset → table → row limit → Load
- **Main area**: Data preview and “Ask a question” with model choice. Uses **US endpoint** by default for company keys (e.g. Secret Manager `si-ops-openai-api-key`).

## Secret Manager

For **Paste key**: enter your OpenAI API key in the sidebar.

For **Secret Manager**: set GCP project (e.g. `wb-smart-cabbage-5940`), secret name (e.g. `si-ops-openai-api-key`), and version (e.g. `latest`), then click **Fetch key from Secret Manager**. Keep **Use US endpoint (company keys)** checked for Verily keys.

### Auto-fetch on load (no pasting)

To have the key loaded automatically from Secret Manager when the app starts, set these **environment variables** (e.g. in your Workbench app configuration or in `docker-compose.yaml`):

- `OPENAI_SECRET_PROJECT` – GCP project (e.g. `wb-smart-cabbage-5940`)
- `OPENAI_SECRET_NAME` – Secret name (e.g. `si-ops-openai-api-key`)
- `OPENAI_SECRET_VERSION` – Optional; default `latest`

The key is fetched once per session. You can still override by pasting a key or fetching manually in the sidebar.

## Local run (optional)

```bash
pip install -r requirements.txt
streamlit run app.py --server.port=8501 --server.address=0.0.0.0
```

Uses Application Default Credentials for GCP (no API key needed for GCS/BigQuery in Workbench).
