# Verily Product Analytics Agent

Prototype Streamlit app for asking plain-language analytics questions from inside a Verily Workbench workspace. Each user launches their own copy of the app.

**Current state:** a chat-style page. You ask a question and it appears in a conversation thread, followed by a reply saying the app cannot answer yet. A **Data connection** dialog shows which identity the app queries as and checks that it can read a BigQuery dataset. Questions are not linked to the data or to a model yet.

## Files

| File | Purpose |
|---|---|
| `.devcontainer.json` | Tells Workbench which compose file and service to run. |
| `docker-compose.yaml` | Builds the image from `app/` and exposes port 8501 on `app-network`. |
| `devcontainer-template.json` | App name and description. |
| `app/Dockerfile` | Python 3.11 image that installs the requirements and runs Streamlit as a non-root user. |
| `app/requirements.txt` | Pinned Python dependencies. |
| `app/.streamlit/config.toml` | Streamlit settings, including the browser origin the app accepts connections from. |
| `app/launcher.py` | Container entry point. Fetches the latest copy of the app, then starts Streamlit. |
| `app/main.py` | The page. |
| `app/data.py` | BigQuery access: the connection, two built-in queries, and the limits every query runs under. |
| `tests/test_data.py` | Tests for `app/data.py`, using a stand-in for BigQuery. |
| `tests/test_launcher.py` | Tests for `app/launcher.py`. They do not use the network. |
| `app/style.css` | Page styling. |
| `app/static/fonts/` | Poppins and Inter font files (SIL Open Font License), served with the app. |

The app code is copied into the image at build time, and refreshed from GitHub each time the container starts (see below). Nothing is mounted over it, and no Workbench startup scripts run, so the container has no bucket mounts and no `wb` CLI.

## Run locally

Needs Python 3.11 or newer.

```bash
cd src/workbench-analytics-agent/app
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run main.py
```

Open http://localhost:8501.

## Launch in Workbench

1. In a workspace, create a new app and choose **Custom App**.
2. Enter:
   - **Repository:** `https://github.com/verily-src/workbench-app-devcontainers.git`
   - **Branch:** the branch that contains this folder
   - **Folder:** `src/workbench-analytics-agent`
3. Create the app, wait until it is running, then open it.

Workbench clones the repository and builds the image on the app's VM. The build needs to reach GitHub, Docker Hub (base image) and PyPI (Python packages).

## Data connection

Open **Data connection** in the top bar.

- **Identity.** The app queries BigQuery with the credentials its environment already has. In Workbench that is the service account Workbench creates for the person who launched the app, so they see only data they have been given access to. Queries are billed to the workspace's project.
- **Dataset.** Enter the dataset as `project.dataset`. It is kept for the browser session only and is never written to this repository.
- **Check connection** lists the dataset's tables and views. **Count rows** counts one of them. These are the only two queries the app runs for now, and neither names a dataset or table in code.
- **Limits.** Every query is checked before it runs. Anything that is not a plain `SELECT` is refused, a query that would read more than 5 GB never starts, a query is stopped after 30 seconds, and at most 500 rows are shown.
- **No access.** If the identity cannot read the dataset or table, the dialog says so instead of showing an error trace.

Keep dataset names, table names, queries that name them, and results out of this repository. It is public.

Run the tests from this folder:

```bash
app/.venv/bin/python -m unittest discover -s tests
```

## Updating a running app

Workbench builds the image once, when the app is created, and a stop and start does not rebuild it. To avoid recreating the app for every change, the container downloads the latest copy of `app/` from the branch each time it starts and runs that copy.

- **To pick up a change:** push it to the branch, then select **Update to the latest version** at the bottom of the page. The app fetches the new code and restarts itself; the machine keeps running. Stopping and starting the app in Workbench does the same thing, more slowly.
- **What is picked up:** the page, styling, fonts, Streamlit settings and Python packages.
- **What still needs a new app:** changes to `Dockerfile`, `docker-compose.yaml`, `.devcontainer.json` or `launcher.py`.
- **Which version is running:** the line at the bottom of the page shows the commit, for example `version 0800aba`.
- **If the update fails:** the app keeps running the copy it had, and the bottom line gives the reason, for example `version 0800aba (not updated: could not reach GitHub)`.

The branch, repository and folder are set in `docker-compose.yaml`. Set `ASK_WORKBENCH_REF` to a tag or commit to pin a version, or to an empty string to turn updates off.

## Check that it starts and restarts

1. The app reaches the running state and the page loads from the Workbench app link.
2. Type a question and press Enter. Your question appears in the thread, followed by a reply saying the app cannot answer yet. This also proves the page's live connection works through the Workbench proxy.
3. Note the "App started" time at the bottom of the page.
4. Stop the app, start it again, and reopen it. The page loads, asking a question still works, and the "App started" time is later than before.

## Troubleshooting

If the app does not reach the running state, or the page does not load, SSH into the app's VM and check:

```bash
# Clone, build and start log for the app
sudo journalctl -u devcontainer.service --no-pager | tail -100

# Is the container up, and what did it print?
docker ps -a
docker logs application-server 2>&1 | tail -50
```

| Symptom | Likely cause |
|---|---|
| Clone fails | The VM cannot reach GitHub, or the branch or folder is wrong. |
| Build fails pulling `python:3.11-slim` or during `pip install` | The workspace's network policy blocks Docker Hub or PyPI. |
| Container restarts in a loop | The app crashes on start. `docker logs application-server` shows why. |
| Page does not come back after **Update to the latest version** | Refresh the page. If the app is still not there, stop and start it in Workbench, which always brings it back. |
| Page stays on "Please wait" | Streamlit refused the page's live connection. `docker logs application-server` shows `Rejecting WebSocket connection with disallowed Origin or Host header` and the origin the browser used. Add that origin to `corsAllowedOrigins` in `app/.streamlit/config.toml`. |
