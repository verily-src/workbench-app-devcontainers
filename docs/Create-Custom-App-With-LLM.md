# Step-by-Step: Create a Verily Workbench Custom App Using an LLM

This guide is for **product managers** (or anyone without deep devcontainer experience) who want to create a custom app on Verily Workbench by **using their favourite LLM** (e.g. ChatGPT, Claude, Cursor, Copilot) to generate the app code. You point the LLM at the Workbench devcontainer repo and describe the app you want; the LLM produces the files; you add them to your fork and create the app in Workbench.

---

## Overview

1. You have a **fork** of the Workbench devcontainer repo (e.g. `https://github.com/YOUR_ORG/workbench-app-devcontainers`).
2. You give your **LLM** a single, detailed **prompt** that includes:
   - A link to the **original repo** and its rules
   - The **exact app you want** (described clearly)
3. The LLM generates the **app folder** (e.g. a new folder under `src/` with the right config and code).
4. You **add that folder** to your fork, **push**, then **create the app in Workbench** using the repo and path.

The example below is a **sample lab data + basic reports** app so you can copy-paste and adapt.

---

## Step 1: Fork the repository (if you haven’t already)

1. Open **https://github.com/verily-src/workbench-app-devcontainers**
2. Click **Fork** and choose your GitHub user or organization.
3. Note your fork URL, e.g. `https://github.com/YOUR_ORG/workbench-app-devcontainers`

---

## Step 2: Copy the prompt below into your LLM

Open your favourite LLM (ChatGPT, Claude, Cursor, etc.) and paste the **entire prompt** below. Replace `YOUR_ORG` with your GitHub org/username and `your-app-name` with the app name you want (e.g. `sample-lab-reports`). The LLM will generate the app files for you.

---

### Prompt to paste into your LLM

```
I need you to create a Verily Workbench custom app. Use the official repo as the only source of truth for structure and rules.

**Repository (read this for requirements and patterns):**  
https://github.com/verily-src/workbench-app-devcontainers  

Important rules from that repo:
- Custom apps live under `src/<app-name>/`.
- Each app MUST have: `.devcontainer.json`, `docker-compose.yaml`, and `devcontainer-template.json`.
- In `docker-compose.yaml`: use a PRE-BUILT image only (no `build:`). The working apps use `image: "jupyter/scipy-notebook"`. The container name MUST be `application-server`. Port must be exposed (e.g. 8888). The service MUST use network `app-network` (external: true) and include: cap_add: SYS_ADMIN, devices: /dev/fuse, security_opt: apparmor:unconfined.
- In `.devcontainer.json`: use the same pattern as `src/lab-results-analyzer-dev`: postCreateCommand with `./startupscript/post-startup.sh` (user and home dir), postStartCommand with `./startupscript/remount-on-restart.sh`, workspaceFolder `/workspace`, and the same features (java, aws-cli, google-cloud-cli). Include workbench customizations with fileUrlSuffix "/lab/tree/{path}".
- The repo is cloned so that the FULL repo (including `startupscript/`) is available when the container runs; postCreateCommand runs from the repo root context.

**App I want you to create:**  
App name: **your-app-name** (use a folder name like `sample-lab-reports`).

**Behavior:**
1. The app is a JupyterLab app (same base as lab-results-analyzer-dev: jupyter/scipy-notebook, port 8888, user jovyan).
2. It provides a single Jupyter notebook that:
   - **Generates sample lab data:** Create a pandas DataFrame with exactly 10 columns of synthetic lab-like data (e.g. patient_id, lab_type, lab_value, lab_date, result_unit, specimen_type, ordering_provider, facility, encounter_id, and one more of your choice). Use realistic-looking sample data (e.g. 500–1000 rows), with some missing values (nulls) so we can report null%.
   - **Produces a basic report** that shows, for each column:
     - Distribution (e.g. value counts for categorical columns, or histogram for numeric)
     - Null count and null % (for all columns)
     - Min and max where applicable (numeric columns)
   - The notebook should run top-to-bottom and display the report in the notebook (tables and simple plots). Use pandas, matplotlib/seaborn or similar; no external APIs.

**Deliverables:**  
Generate the following files for the new app under `src/your-app-name/`:

1. **.devcontainer.json** – Same structure as lab-results-analyzer-dev but name and (if needed) postCreateCommand curl URL updated to your-app-name. Use user jovyan, home /home/jovyan. Do NOT use a custom Dockerfile or build step.

2. **docker-compose.yaml** – Same as lab-results-analyzer-dev: image jupyter/scipy-notebook, container_name application-server, port 8888, user jovyan, volumes .:/workspace and work:/home/jovyan/work, command for start-notebook.sh, app-network, cap_add/devices/security_opt as above.

3. **devcontainer-template.json** – id and name set to your-app-name, description mentioning sample lab data and basic reports (distribution, null%, min/max).

4. **README.md** – Short description: app name, that it generates sample lab data (10 columns) and basic reports (distribution, null%, min/max).

5. **Sample_Lab_Report.ipynb** – One Jupyter notebook that:
   - Generates the 10-column sample lab DataFrame (with some nulls).
   - For each column: show null count and null %, and for numeric columns min/max.
   - For each column: show distribution (value_counts or histogram).
   - Use markdown cells to explain steps. Keep it simple and runnable in order.

6. **postCreateCommand in .devcontainer.json** – Should copy or make the notebook available in the user’s home so it opens in JupyterLab. Use the same pattern as lab-results-analyzer-dev: e.g. curl to raw GitHub for `Sample_Lab_Report.ipynb` from `https://raw.githubusercontent.com/YOUR_ORG/workbench-app-devcontainers/master/src/your-app-name/Sample_Lab_Report.ipynb`, or copy from /workspace if present, and chown to jovyan:users.

Use YOUR_ORG and your-app-name consistently (e.g. sample-lab-reports). Do not add a Dockerfile or build step. Output the full contents of each file so I can save them into my fork.
```

---

## Step 3: Replace placeholders in the prompt

Before sending the prompt to the LLM, replace:

| Placeholder    | Replace with |
|----------------|--------------|
| `YOUR_ORG`     | Your GitHub organization or username (e.g. `SIVerilyDP`) |
| `your-app-name`| The app folder name (e.g. `sample-lab-reports`) |

Use the **same** app name in the prompt everywhere (folder path, .devcontainer name, devcontainer-template id/name, and in the curl URL).

---

## Step 4: Get the files from the LLM and add them to your fork

1. Run the prompt in your LLM.
2. The LLM should return the contents of:
   - `src/<your-app-name>/.devcontainer.json`
   - `src/<your-app-name>/docker-compose.yaml`
   - `src/<your-app-name>/devcontainer-template.json`
   - `src/<your-app-name>/README.md`
   - `src/<your-app-name>/Sample_Lab_Report.ipynb` (or the notebook filename the LLM uses)
3. On your machine, clone your fork (if needed) and create the app folder:
   ```bash
   git clone https://github.com/YOUR_ORG/workbench-app-devcontainers.git
   cd workbench-app-devcontainers
   mkdir -p src/<your-app-name>
   ```
4. Save each file the LLM produced into the correct path under `src/<your-app-name>/`. If the LLM gave a different notebook name, use that and update the postCreateCommand in `.devcontainer.json` to match (e.g. curl to that notebook filename).
5. Commit and push:
   ```bash
   git add src/<your-app-name>
   git commit -m "Add custom app: <your-app-name> (sample lab data + basic reports)"
   git push origin master
   ```

---

## Step 5: Create the app in Workbench

1. In **Verily Workbench**, open your workspace (or create one).
2. Go to **Apps → Create App → Custom** (or the equivalent in your Workbench UI).
3. Enter:
   - **Repository URL:** `https://github.com/YOUR_ORG/workbench-app-devcontainers`
   - **Branch:** `master` (or your default branch)
   - **Repository folder path to the .devcontainer.json file:** `src/<your-app-name>`
     - Example: `src/sample-lab-reports`
4. If prompted, choose the template that matches your app name (e.g. **sample-lab-reports**).
5. Set options (e.g. **Cloud: GCP**) and create the app.
6. Wait for the app to start (JupyterLab on port **8888**). Open the app URL and you should see your notebook (e.g. **Sample_Lab_Report.ipynb**). Run it to generate the sample data and view the basic reports (distribution, null%, min/max).

---

## Step 6: If something doesn’t work

- **App doesn’t start:** Ensure your app uses a **pre-built image** only (`image: "jupyter/scipy-notebook"`) and **no** `build:` in `docker-compose.yaml`. Check that `container_name` is `application-server`, and that `postCreateCommand` uses `./startupscript/post-startup.sh` with the same pattern as `lab-results-analyzer-dev`.
- **Notebook not found:** Confirm the notebook filename in the app folder matches the name used in the postCreateCommand (e.g. curl URL or copy from `/workspace`).
- **Wrong repo/branch:** Double-check Repository URL, Branch, and the folder path (`src/<your-app-name>`).

---

## Quick reference: parameters for Workbench

| Parameter | Value |
|-----------|--------|
| **Repository URL** | `https://github.com/YOUR_ORG/workbench-app-devcontainers` |
| **Branch** | `master` (or your default) |
| **Repository folder path to .devcontainer.json** | `src/<your-app-name>` (e.g. `src/sample-lab-reports`) |
| **Template** | Same as your app name (e.g. `sample-lab-reports`) |

---

## Summary

1. Fork **verily-src/workbench-app-devcontainers**.
2. Paste the **prompt** (Step 2) into your LLM, with `YOUR_ORG` and `your-app-name` set.
3. Save the generated files into `src/<your-app-name>/` in your fork.
4. Push to GitHub.
5. In Workbench, create a custom app with your fork URL, branch, and path `src/<your-app-name>`.
6. Open the app and run the notebook to get sample lab data and basic reports (distribution, null%, min/max).

Using this flow, a product manager can create a custom app by describing it to an LLM and following these steps, without writing devcontainer or Docker details by hand.
