# MDV in Verily Workbench: user guide

[MDV](https://mdv.ndm.ox.ac.uk/) (Multi-Dimensional Viewer) is an interactive viewer for
single-cell, spatial, variant and other multi-dimensional data, developed at the University of
Oxford. This guide explains how to set up MDV in a Verily Workbench workspace and open your
workspace data in it.

**In short:** create the MDV app once, open it, then click **Workspace data** in MDV to open
files straight from your workspace's buckets. Nothing needs to be uploaded or copied.

## Before you start

- **Browser:** Google Chrome or Microsoft Edge, version 137 or later (check at
  `chrome://version` or `edge://version`). MDV doesn't work in Firefox or Safari in Workbench yet.
- **Workbench access:** a workspace where you can create apps. If you can't, ask the workspace's
  owner.
- **Your data in a workspace bucket.** See [Getting data into a bucket](#getting-data-into-a-bucket).
  You can create the app first; MDV opens with sample data until your data is there.

## 1. Create the MDV app

You do this once.

1. In your workspace, go to **Apps** → **Create app** → **Custom app**.
2. Fill in **Provide container**:

   | Field | Value |
   | --- | --- |
   | App name | `MDV` (or any name) |
   | Description | Optional |
   | Repository URL | `https://github.com/verily-src/workbench-app-devcontainers` |
   | Repository branch | Leave blank (until the MDV app is released, use `erogge/mdv-workspace-data`) |
   | Repository folder path | `src/mdv` |

3. In **Compute options**, choose a machine with enough memory for your largest files:

   | Your data | Suggested machine |
   | --- | --- |
   | Files up to about 1 GB | 4 vCPUs, 15 GB memory (for example `n1-standard-4`) |
   | Larger `.h5ad`/`.h5mu` files | As a rule of thumb, memory of at least 4 times your largest file (for example `n1-highmem-8`, 52 GB) |

   You can change the machine later by stopping the app and editing it.
4. Review and create. The first start takes about 15–25 minutes while the app is built. Later
   starts take a few minutes.

## 2. Open MDV

Open the app from the workspace's **Apps** list. MDV opens inside Workbench and shows its project
list.

If none of your buckets has MDV data yet, you'll see sample projects to explore MDV with:

- **`sample--pbmc3k-processed`**: 2,638 blood cells (the dataset from MDV's tutorials).
- **`sample--1000genomes-chr1-variants`**: about 6.5 million genetic variants on chromosome 1
  from the 1000 Genomes Project. It appears about 15–20 minutes after the app first starts,
  while it downloads and converts. On smaller machines it includes fewer variants.

The samples disappear automatically once you open your own data.

## 3. Open your data

### With the Workspace data button

1. In MDV, click **Workspace data** in the bottom-right corner. It's on every MDV page.
2. Click a bucket, then go to the folder with your data.
3. Click **Open** next to a file or MDV project.

MDV converts or links the data directly from the bucket, then opens it. Small files take
seconds; large files can take several minutes, and you can keep the dialog open while you wait.
Next time, the project is already in MDV's project list, and clicking **Open** again goes
straight to it.

MDV can open:

| Data | Files |
| --- | --- |
| Single-cell (AnnData) | `.h5ad` |
| Multi-modal (MuData) | `.h5mu` |
| Variants | `.vcf`, `.vcf.gz` |
| Tables | `.csv`, `.tsv` (optionally `.gz`) |
| MDV projects | A folder containing `datasources.json`, for example made with `mdvtools` (see [Preparing data](#preparing-data-with-mdvtools)) |

Other files are shown greyed out.

### Automatically, with an `mdv` folder

To have data appear in MDV without clicking anything, for example for everyone in the workspace
who uses MDV, put it in a folder named `mdv` at the top of a bucket:

- `mdv/data/` for files (any of the types above)
- `mdv/projects/<name>/` for MDV project folders

MDV checks for new or changed data when the app starts and every 10 minutes.

### Project names

Projects are named `<bucket>--<file or folder name>`, where `<bucket>` is the bucket's name in
the workspace. For example, `experiments/tumour-B.h5ad` in a bucket named `oxford-results`
becomes `oxford-results--tumour-B`.

## 4. Working with your data

- **Your bucket data is never changed by MDV.** MDV reads it in place (MDV projects) or converts
  a copy on the app's disk (files). For MDV projects opened from a bucket, actions that would
  change the project's data, such as adding a datasource, fail with an error.
- **Views and layouts you save are kept in your app**, including across stops and restarts.
- **Updating data:** replace the file or project in the bucket. MDV picks up the change within
  10 minutes or at the next app start. When a converted file changes, it's converted again and
  that project's saved views are reset.
- **Removing data:** delete it from the bucket, and its project disappears from MDV.
- **Uploading from your computer** with MDV's own upload still works for small files, but the
  data stays only in your app. For anything you want to keep or share, put it in a bucket.

## Getting data into a bucket

Any of these work:

- **Workbench UI:** open the bucket in your workspace's **Resources** and upload files.
- **Command line** (your computer or a Workbench app terminal):
  `gcloud storage cp my-data.h5ad gs://<bucket>/experiments/`
- **From another Workbench app** (for example JupyterLab): workspace buckets are mounted under
  `~/workspace/<bucket>/`; save files there.

Buckets added to the workspace after your MDV app started appear in **Workspace data** after you
stop and start the app.

**BigQuery tables:** export the table or query result to a bucket as CSV (BigQuery's **Export**
or `bq extract --destination_format=CSV`), then open the CSV.

## Preparing data with mdvtools

For the best results with large or complex data, convert it to an MDV project yourself with
[`mdvtools`](https://mdv.ndm.ox.ac.uk/docs/tutorials/backend-tools-tutorial), then put the
project folder in a bucket:

```bash
pip install mdvtools
mdvtools convert-scanpy my-project my-data.h5ad --chunk_data   # or convert-mudata, convert-vcf, convert-spatial
gcloud storage cp -r my-project gs://<bucket>/mdv/projects/
```

This lets you choose conversion options and handle formats the app doesn't convert itself, such
as SpatialData (`convert-spatial`). MDV then opens the project instantly, without converting it.

## Public datasets

MDV can load public data from the web where the hosting site allows it, which most large public
repositories (for example EBI and public cloud storage buckets) do. If MDV can't load a public
dataset directly, download it into a workspace bucket and open it with **Workspace data**.

## Sharing with colleagues

- Everyone in the workspace who uses an MDV app sees the same bucket data, through
  **Workspace data** and the `mdv` folders.
- Saved views and layouts are kept in each person's own app, and aren't shared.

## Stopping the app and costs

The app runs on a cloud machine that costs money while it's running. **Stop the app** from the
workspace's Apps list when you're not using it. Your projects and saved views are kept while the
app is stopped.

**Deleting the app** deletes its converted projects and saved views. Data in your buckets isn't
affected; you can open it again in a new app.

## Troubleshooting

| Problem | What to do |
| --- | --- |
| `SharedArrayBuffer is not defined` when opening a project | Use Chrome or Edge 137 or later. |
| No **Workspace data** button | Reload the page. |
| **Workspace data** shows no buckets, or a bucket is missing | Buckets are made available when the app starts. Wait a minute after starting, or stop and start the app if the bucket was created after the app started. |
| A new file isn't listed | Wait a minute, then click the folder again. |
| "Couldn't open …" | Click **Details** in the dialog. Very large files may need a bigger machine (see step 1). |
| A project shows an error just after the app started | Wait a minute and reload; buckets are reconnected shortly after start. |
| Large sample never appears | It downloads about 1.2 GB on first start. Stop and start the app to retry. |

When asking for help, include what you did, any message from the **Details** section, and the
app's activity log: click **Workspace data**, then **Activity log** at the bottom of the dialog,
and copy its contents.

## For workspace administrators

Settings such as the sync interval, sample data and the cross-origin isolation mode are in the
app definition; see the [app README](README.md#configuration). Changing them requires a copy of
the app definition in your own repository.
