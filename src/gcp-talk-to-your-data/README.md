# gcp-talk-to-your-data

JupyterLab app on Workbench (port 8888) with **GCP data source auto-discovery**, **automated data profiling**, and **Talk to your data** (LLM) using your own API key.

## Features

### 1. Auto-detect GCP data sources
- **Authenticates with GCP** using Application Default Credentials (Workbench provides these; no API key needed for GCP).
- **Discovers** your GCS buckets and BigQuery datasets/tables in the Workbench-related GCP project.
- Run the discovery cell in the notebook to list buckets and datasets; then pick a source to load.

### 2a. Automated data profiling report
- After you **pick a data source** (GCS file or BigQuery table) and load it, the notebook generates a **ydata-profiling** report.
- The report includes distributions, null %, min/max where applicable, and other per-column statistics.
- You can view it in the notebook or save it as HTML.

### 2b. Talk to your data (LLM)
- You **provide your LLM API key** when you run the “Talk to your data” section (the key is not stored).
- Once the key is set, you can **ask any question** about the loaded data; the app sends the schema and a sample to the LLM and returns the answer.
- Supports **OpenAI** or any **OpenAI-compatible** API (e.g. Azure). Use your preferred model (e.g. gpt-4o-mini).

## Main notebook

- **`GCP_Data_Profiling_and_Chat.ipynb`** – Run this for the full flow:
  1. Setup & install dependencies (google-cloud-*, ydata-profiling, openai).
  2. Authenticate with GCP and discover buckets + BigQuery datasets/tables.
  3. Pick a data source (set variables for GCS bucket/path or BQ project/dataset/table) and load into a DataFrame.
  4. Generate the ydata-profiling report.
  5. Talk to your data: enter your LLM API key when prompted, then ask questions.

Supporting file:
- **`gcp_tools.py`** – GCP discovery, load from GCS/BigQuery, and LLM `talk_to_data()` helper.

## Other files

- **`Lab_Results_Analysis.ipynb`** – Original lab results analysis notebook (still available).
- **`requirements.txt`** – Python dependencies (installed at container startup).

## Configuration

- **Image**: jupyter/scipy-notebook
- **Port**: 8888
- **User**: jovyan
- **GCP**: Uses ADC (no key needed). Ensure your Workbench workspace has access to the desired GCP project/buckets/datasets.

## Access

1. In Workbench, open the app (JupyterLab at port 8888).
2. Open **GCP_Data_Profiling_and_Chat.ipynb** (in your home directory or under `/workspace`).
3. Run cells in order: setup → discover sources → set source variables and load → profiling → talk to your data (paste API key when prompted).

## Workbench parameters

| Parameter | Value |
|-----------|--------|
| Repository folder path to .devcontainer.json | `src/gcp-talk-to-your-data` |
| Template | gcp-talk-to-your-data |

## Development

- `.devcontainer.json` – postCreateCommand installs `requirements.txt` and copies the new notebook and `gcp_tools.py` to the user’s home.
- Add or change discovery/profiling/LLM behavior in `gcp_tools.py` and the notebook.
