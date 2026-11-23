# Workbench Analytics Agent

Prototype Streamlit app for asking plain-language analytics questions from inside a Verily Workbench workspace. Each user launches their own copy of the app.

**Current state:** a chat-style page. You ask a question and it appears in a conversation thread, followed by a reply saying the app cannot answer yet. It is not connected to data or to a model.

## Files

| File | Purpose |
|---|---|
| `.devcontainer.json` | Tells Workbench which compose file and service to run. |
| `docker-compose.yaml` | Builds the image from `app/` and exposes port 8501 on `app-network`. |
| `devcontainer-template.json` | App name and description. |
| `app/Dockerfile` | Python 3.11 image that installs the requirements and runs Streamlit as a non-root user. |
| `app/requirements.txt` | Pinned Python dependencies. |
| `app/.streamlit/config.toml` | Streamlit settings, including the browser origin the app accepts connections from. |
| `app/main.py` | The page. |
| `app/style.css` | Page styling. |
| `app/static/fonts/` | Poppins and Inter font files (SIL Open Font License), served with the app. |

The app code is copied into the image at build time. Nothing is mounted over it, and no Workbench startup scripts run, so the container has no bucket mounts and no `wb` CLI.

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
| Page stays on "Please wait" | Streamlit refused the page's live connection. `docker logs application-server` shows `Rejecting WebSocket connection with disallowed Origin or Host header` and the origin the browser used. Add that origin to `corsAllowedOrigins` in `app/.streamlit/config.toml`. |
