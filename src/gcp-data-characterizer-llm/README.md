# GCP Data Characterizer with LLM

Custom Verily Workbench app that lets you:

- **Connect to GCP**: Use Workbench’s GCP credentials to access **GCS buckets** and **BigQuery**.
- **Characterize data**: For a chosen GCS file or BigQuery table, get **data profiling metrics** (counts, nulls, min/max/mean for numerics; uniques, top values for categoricals) and **histogram-style visualizations** per column.
- **Talk to your data**: Use an **LLM** (you provide the API key in the app) to ask questions about the loaded data in natural language.

The app runs as a **Streamlit** UI on port **8501** and follows the [workbench-app-devcontainers](https://github.com/verily-src/workbench-app-devcontainers) requirements (e.g. `application-server`, `app-network`, gcsfuse caps).

---

## What’s in this app

| Item | Description |
|------|--------------|
| **Data sources** | GCS (list buckets → pick file) or BigQuery (project → dataset → table). |
| **Profiling** | Per-column metrics + Plotly histograms (numeric) or bar charts (categorical). |
| **LLM** | OpenAI-compatible API; you enter the API key in the sidebar when you want to use “Talk to your data.” |
| **Talk to your data** | Chat tab: ask questions about the loaded data; the LLM sees schema + sample and answers. |

---

## Step-by-step: Fork your repo and add this app

Use these steps to fork the devcontainer repo remotely and add the **gcp-data-characterizer-llm** app so you can register it in Workbench.

### 1. Fork the repository on GitHub

1. Open: [https://github.com/verily-src/workbench-app-devcontainers](https://github.com/verily-src/workbench-app-devcontainers).
2. Click **Fork** (top right).
3. Choose your user or organization and create the fork (e.g. `YOUR_ORG/workbench-app-devcontainers`).

You will add the new app to **your fork**, then point Workbench at that fork.

### 2. Clone your fork locally (if you don’t have it yet)

```bash
git clone https://github.com/YOUR_ORG/workbench-app-devcontainers.git
cd workbench-app-devcontainers
```

Replace `YOUR_ORG` with your GitHub username or org.

### 3. Add the `gcp-data-characterizer-llm` app into your fork

You can do either **A** (copy from this repo) or **B** (create from script and then replace with this app).

**Option A — Copy the app folder from this repo**

If you have this repo (e.g. `Cursor-local/workbench-app-devcontainers`) with the new app already in `src/gcp-data-characterizer-llm/`:

```bash
# From your fork’s root
cp -r /path/to/Cursor-local/workbench-app-devcontainers/src/gcp-data-characterizer-llm src/
```

Then skip to step 4.

**Option B — Create app with script, then replace with full app**

From the **root of your fork**:

```bash
./scripts/create-custom-app.sh gcp-data-characterizer-llm python:3.11-slim 8501 root /root
```

That creates a minimal app under `src/gcp-data-characterizer-llm/`. Then replace its contents with the full app (all files from this repo’s `src/gcp-data-characterizer-llm/`), including:

- `.devcontainer.json`
- `devcontainer-template.json`
- `docker-compose.yaml`
- `Dockerfile`
- `requirements.txt`
- `app.py`
- `lib/` (with `__init__.py`, `data_sources.py`, `profiling.py`, `llm_chat.py`)
- `README.md`

So either copy the whole `src/gcp-data-characterizer-llm` directory from this repo into your fork’s `src/`, or overwrite the script-generated files with the ones from this app.

### 4. Commit and push to your fork

```bash
git add src/gcp-data-characterizer-llm
git status   # confirm only intended files
git commit -m "Add GCP Data Characterizer with LLM custom app"
git push origin master
```

(Use your default branch name if it’s not `master`, e.g. `main`.)

### 5. Register the custom app in Workbench

1. In **Verily Workbench**, go to the area where you manage **Custom Apps** (or **Cloud Apps** / equivalent in your Workbench UI).
2. Create a **new custom app**.
3. When asked for the **repository**:
   - Use your fork’s clone URL, e.g. `https://github.com/YOUR_ORG/workbench-app-devcontainers`
   - Or the SSH URL if your Workbench environment uses SSH.
4. Set the **branch** to the one you pushed (e.g. `master` or `main`).
5. Select the template **“GCP Data Characterizer with LLM”** (from `devcontainer-template.json`).
6. Choose options as needed (e.g. **Cloud: GCP**).
7. Save and create the app.

After the app is created, you can open a workspace that uses this custom app.

### 6. Open the app in your workspace

1. Create or open a **Workbench workspace** that uses this custom app.
2. Once the app container is running, open the **app URL** (the one Workbench shows for the app, typically with port **8501**).
3. In the UI:
   - **Sidebar**: Choose **GCS file** or **BigQuery table**, select bucket/dataset/table and **load** data.
   - **Overview**: Preview the loaded table.
   - **Data profiling & histograms**: View metrics and histograms per column.
   - **Talk to your data**: Enter your **LLM API key** in the sidebar, then ask questions in the chat.

---

## Local testing (optional)

To run the app locally with the devcontainer CLI:

1. Install the [devcontainer CLI](https://code.visualstudio.com/docs/devcontainers/devcontainer-cli).
2. Create the external network:
   ```bash
   docker network create app-network
   ```
3. For local runs, you can temporarily comment out `postCreateCommand` and `postStartCommand` in `.devcontainer.json` (they expect Workbench scripts).
4. From the app directory:
   ```bash
   cd src/gcp-data-characterizer-llm
   devcontainer up --workspace-folder .
   ```
5. Open `http://localhost:8501` in your browser.

GCP credentials (e.g. `gcloud auth application-default login`) must be available if you want to list buckets or query BigQuery.

---

## Configuration summary

| Setting | Value |
|--------|--------|
| **App name** | gcp-data-characterizer-llm |
| **Port** | 8501 |
| **User** | root |
| **Home** | /root |
| **Container name** | application-server (required by Workbench) |
| **Network** | app-network (external) |

---

## LLM API key

- The app **does not** store your API key; it is only used in the current session.
- Supports **OpenAI** (default) and any **OpenAI-compatible** endpoint (e.g. Azure OpenAI, local models). Set **API base URL** and **Model name** in the sidebar when needed.

For more on custom apps and devcontainers in Workbench, see the [main repo README](https://github.com/verily-src/workbench-app-devcontainers) and [Workbench docs](https://support.workbench.verily.com/docs/guides/cloud_apps/create_custom_apps/).
