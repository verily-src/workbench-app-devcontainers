# Data Profiling Dashboard

Same app as the Lab Results Analyzer (dashboard + Python profiling), packaged for use in **another Workbench workspace**.

Use this template when you create an app in a **new workspace**: you get JupyterLab, the profiling notebook, and the `run_data_profiling.py` script that loads from GCS and generates the HTML report.

## What’s included

- **JupyterLab** (port 8888) with the notebook and script in `/home/jovyan`
- **Lab_Results_Analysis.ipynb** – configure `GCS_BUCKET` and `FILE_NAME`, run cells to load from GCS and generate a ydata-profiling report
- **run_data_profiling.py** – same flow from the terminal: edit `GCS_BUCKET` and `FILE_NAME` at the top, then run `python run_data_profiling.py`

## Using this app in a new workspace

1. **Push this repo** (with the `data-profiling-dashboard` folder) to your fork, e.g. `SIVerilyDP/workbench-app-devcontainers`.

2. In the **new Workbench workspace**, create a custom app:
   - Source: your fork (e.g. `SIVerilyDP/workbench-app-devcontainers`)
   - **Template path**: `src/data-profiling-dashboard`
   - Create the app and start it.

3. **Set your data** for that workspace:
   - In the notebook: set `GCS_BUCKET` and `FILE_NAME` in the first code cell.
   - In the script: edit `GCS_BUCKET` and `FILE_NAME` at the top of `run_data_profiling.py`.

4. **Run**:
   - Open `Lab_Results_Analysis.ipynb` in JupyterLab and run all cells, or
   - In a terminal: `python run_data_profiling.py`

The HTML report is saved as `data_profile_report.html` in the current directory (and opened in the browser when using the script, if possible).

## Configuration

- **Image**: `jupyter/scipy-notebook`
- **Port**: 8888
- **User**: jovyan
- **Workspace folder**: `/workspace`; app files are copied to `/home/jovyan` at startup

## Difference from lab-results-analyzer-dev

- **data-profiling-dashboard**: No OpenAI/Secret Manager; only GCS + ydata-profiling. Use this in any workspace where you just need dashboarding and profiling.
- **lab-results-analyzer-dev**: Same base plus optional OpenAI integration and extra scripts; use when you need those features.
