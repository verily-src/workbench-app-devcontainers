# Testing the MDV app in Verily Workbench

Step-by-step checks to run in Workbench before merging this branch. Each step says what to do,
what you should see, and what to record. Allow about 1.5 hours, most of it waiting for the app
to build and the large sample to download.

What's being tested:

1. **Cross-origin isolation inside the Workbench frame.** MDV gets `SharedArrayBuffer` while
   framed by Workbench (Document-Isolation-Policy), so its worker threads can load data.
2. **Workspace data, no uploads.** Users open files and MDV projects from any workspace bucket
   with **Open from workspace**, built into MDV's catalog and project toolbar; data in a bucket's
   `mdv/` folder appears automatically.
   Bucket data stays read-only.
3. **Sample data.** When no bucket has MDV data, MDV opens with sample projects.
4. **Public data.** Public datasets can be fetched by MDV's worker threads into shared memory.

Already verified locally (Chromium 141, MDV framed by a non-isolated page from another origin;
not a substitute for these steps): all four above, including **Open from workspace** end to
end in light and dark mode (browse, open, convert, MDV opens the project), restart ordering, and removal. Not verifiable locally: real Workbench framing, `wb` bucket mounts (gcsfuse) and
the Workbench proxy.

## 0. Before you start

You need:

- **Chrome or Edge, version 137 or later** (check at `chrome://version`). Firefox and Safari
  don't support Document-Isolation-Policy yet; step 10 checks the expected failure there.
- A Workbench workspace where you can create apps, with a **controlled bucket** you can upload to.
  For step 3, at least one bucket must be mounted and none may have an `mdv/` folder at the top
  level. If you aren't sure, create a new controlled bucket before creating the app (buckets are
  mounted when the app starts).
- About 25 MB of test data: download
  [`pbmc3k.h5ad`](https://raw.githubusercontent.com/chanzuckerberg/cellxgene/main/example-dataset/pbmc3k.h5ad)
  (cellxgene's example dataset) to your computer. Don't upload it yet.

Branch under test: `erogge/mdv-workspace-data` in
`https://github.com/verily-src/workbench-app-devcontainers`.

## 1. Create the app

1. In the workspace, go to **Apps** → **Create app** → **Custom app**.
2. **Provide container**:
   - App name: `mdv-test`
   - Repository URL: `https://github.com/verily-src/workbench-app-devcontainers`
   - Repository branch: `erogge/mdv-workspace-data`
   - Repository folder path: `src/mdv`
3. **Compute options**: at least **4 vCPUs and 15 GB memory** (for example `n1-standard-4`).
   The large sample scales to memory, using up to half of the free memory at about 0.6 GB per
   million variants. With 15 GB it uses all 6.5 million chromosome 1 variants (measured peak
   3.2 GB, about 4 minutes to convert).
4. **Review details** → create. Wait until the app shows **Running**. The first start builds the
   image and can take 15–25 minutes.

**Record:** machine type, time to Running. If it fails, record the error from the app's status
or logs.

## 2. Open MDV and check isolation inside the Workbench frame

1. Open the app from Workbench. MDV's project list (catalog) appears inside Workbench.
2. Open Chrome DevTools (**F12**) → **Console**. In the context dropdown at the top of the
   Console (it says `top`), choose the app's frame. Its name contains `workbench-app` (for
   example `<id>.workbench-app-prod.verily.com`).
3. Run:

   ```js
   ({ isolated: crossOriginIsolated, sab: typeof SharedArrayBuffer, app: location.origin })
   ```

**Expect:** `isolated: true`, `sab: "function"`.

4. Switch the context back to `top` and run the same line.

**Expect:** `isolated: false`. Workbench's own page isn't isolated; only MDV's frame is. This is
the case DIP is designed for.

5. **Network** tab → reload → click the first document request for the app's host → **Response
   Headers**.

**Expect:**
- `Document-Isolation-Policy: isolate-and-credentialless`
- `Cross-Origin-Embedder-Policy: credentialless` (exactly one)
- `Cross-Origin-Opener-Policy: same-origin`

**Record:** the outputs, the app origin and Chrome version. If `isolated` is `false` in the app
frame, also record the headers and any Console errors, then stop — the approach doesn't work in
Workbench.

## 3. Sample data when the workspace has no MDV data

1. In the MDV catalog, find **`sample--pbmc3k-processed`**. It should be there within a minute of
   the app opening.
2. Open it. **Expect:** `cells` (2,638) and `genes` (1,838) tables load with no
   `SharedArrayBuffer is not defined` error.
3. Read the sync log: click **Open from workspace** → **View activity** (bottom of the dialog), or in
   the Console with the app frame selected, run

   ```js
   fetch('/_workspace-sync.log', { cache: 'no-store' }).then(r => r.text()).then(t => console.log(t))
   ```

   **Expect:** lines like `read-only mount: /home/pn/workspace/<bucket> -> /mnt/mdv-workspace-ro/<bucket>`,
   `0 workspace source(s) in N mounted resource(s)`, `linked /opt/mdv-samples/pbmc3k-processed`,
   then `building sample 1000genomes-chr1-variants with up to N variants`.
4. Wait for the large sample. Rerun the log command every few minutes until you see
   `sample ready` (expect roughly 15–20 minutes: a 1.2 GB download, about 6 minutes of extraction,
   then about 4 minutes of conversion). Reload the MDV catalog.
5. **Expect:** **`sample--1000genomes-chr1-variants`** in the catalog. Open it; the variant table
   loads. Try a filter or a histogram on `POS` or `QUAL`.

**Record:** the number of mounted resources, the variant count and timings from the log
(`extracted N variants in S s`, `converted in S s`), and whether the VCF project is responsive.
If you see `sample build failed`, record the line.

## 4. Public data fetched by worker threads into shared memory

With an MDV project open and the app frame selected in the Console, run:

```js
(async () => {
  const urls = [
    new URL('datasources.json', location.href).href,  // workspace data, same origin
    'https://viv-demo.storage.googleapis.com/LuCa-7color_3x3component_data.ome.tif',  // public GCS
    'https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/README_ebi_aspera_info.md',           // public EBI
  ];
  const code = `onmessage = async ({ data: { sab, urls } }) => {
    const v = new Int32Array(sab);
    for (let i = 0; i < urls.length; i++) {
      try { const r = await fetch(urls[i], { headers: i ? { Range: 'bytes=0-1023' } : {} });
            Atomics.store(v, i, r.ok ? (await r.arrayBuffer()).byteLength : -r.status); }
      catch (e) { Atomics.store(v, i, -1); }
    }
    postMessage('done'); };`;
  const sab = new SharedArrayBuffer(4 * urls.length);
  const w = new Worker(URL.createObjectURL(new Blob([code], { type: 'text/javascript' })));
  await new Promise(r => { w.onmessage = r; w.postMessage({ sab, urls }); });
  const v = new Int32Array(sab);
  const img = await new Promise(r => { const i = new Image(); i.onload = () => r('loaded');
    i.onerror = () => r('blocked'); i.src = 'https://www.ebi.ac.uk/favicon.ico?' + Date.now(); });
  return { workspaceBytes: v[0], publicGcsBytes: v[1], publicEbiBytes: v[2], publicImageNoCors: img };
})()
```

The URL is relative to the page, so run it on a project page (the address ends in
`/project/<id>/`), not the catalog.

**Expect:** all three byte counts positive (`1024` for the two public ranges) and
`publicImageNoCors: "loaded"`. Negative numbers are HTTP errors; `-1` means the request was
blocked.

**Record:** the returned object. If any value is negative, also record the Console errors (look
for `ERR_BLOCKED_BY_RESPONSE`).

## 5. Open from workspace

1. In Workbench, open the controlled bucket and upload `pbmc3k.h5ad` to a new folder named
   `experiments` (not `mdv`): `experiments/pbmc3k.h5ad`. The app doesn't need restarting; the
   bucket is already mounted.
2. In MDV's project list, check there's an **Open from workspace** card next to "Create new
   project" and "Import an existing project", styled like them. Click it.
   **Expect:**
   - A dialog titled **Open from workspace**, showing your workspace's name.
   - Under **Resources**: the workspace's Workbench folders, then its buckets, each labelled
     **Cloud Storage bucket · Controlled** (or **Referenced**) with its Workbench description.
   - If buckets show without these labels, the Workbench CLI wasn't logged in; record that.
3. Go into the bucket, then `experiments`. **Expect:** `pbmc3k.h5ad` with "AnnData · 24.x MB ·
   Modified <date>". If it isn't listed yet, wait a minute and open the folder again (bucket
   listings can be cached briefly). Unsupported files are greyed out.
4. Select `pbmc3k.h5ad` and click **Open**. **Expect:** "Converting pbmc3k.h5ad…" with a progress
   bar and elapsed time, then MDV opens project **`pbmc3k`** (2,700 cells) by itself, typically
   within a minute. The sample projects disappear from the catalog.
5. On the new project, rerun the step 2 isolation check and the step 4 snippet.
6. In the project toolbar, check there's a folder button after **Add Datasource**, with the
   tooltip "Open from workspace". Click it. **Expect:** the dialog reopens in `experiments`.
   Double-click `pbmc3k.h5ad`. **Expect:** MDV goes straight to the same project, without
   converting.
7. Switch MDV to dark mode (theme button in the toolbar) and open the dialog again. **Expect:**
   the dialog is dark too.
8. Back in MDV's project list, open the `pbmc3k` card's **⋮** menu → **Project Info**.
   **Expect:** it says "Converted from the Workbench workspace:" with the bucket and path.

**Record:** time from clicking **Open** to the project showing, the snippet outputs, and
screenshots of the catalog card, the dialog at **Resources**, and the toolbar button. If it
fails, record the message and expand **Details** in the dialog.

## 6. Workspace data in the bucket's `mdv/` folder (automatic)

1. Upload the same file again as `mdv/data/pbmc3k-auto.h5ad` (note the `mdv/data/` folder at the
   top of the bucket).

   (Optional, if you have `mdvtools`: `pip install mdvtools`, then
   `mdvtools convert-scanpy pbmc3k-project pbmc3k.h5ad`, and upload the `pbmc3k-project`
   folder to `mdv/projects/pbmc3k-project/`.)
2. Wait up to 10 minutes (the sync interval), or **stop and start the app** to pick it up
   immediately.
3. Reload the MDV catalog.

**Expect:**
- **`pbmc3k-auto`** appears without using **Open from workspace**.
- The optional ready-made project appears as **`pbmc3k-project`**.
- The sync log shows `converting .../mdv/data/pbmc3k-auto.h5ad`, `converted ... in N s` and
  `registered new projects with MDV`.

4. Open `pbmc3k-auto`. Data loads.

**Record:** project names and the conversion time from the log.

## 7. Workspace data is read-only; views still save

Use the ready-made project if you uploaded it (it's linked to the bucket). Otherwise use a
converted project, which is a local copy, so only the view part applies.

1. Change the layout (for example add a chart), then click **Save view** (disk icon). Reload the
   page. **Expect:** the change is still there.
2. Linked project only: try an action that changes data, such as uploading a datasource from the
   project's upload button. **Expect:** it fails with an error; nothing is written to the bucket.
3. In the bucket, confirm no files under `mdv/projects/pbmc3k-project/` changed. Check that the
   modified times haven't changed.

**Record:** results of each check.

## 8. App restart

1. Stop the app in Workbench, then start it again.
2. Open MDV.

**Expect:**
- The same projects are listed (including the one opened with the button), with saved views kept.
- Converted projects aren't converted again (no new `converting` line in the sync log for
  unchanged files).
- Data loads. If a linked project shows an error in the first minute after start, wait a minute
  and reload: buckets are remounted just after MDV starts.

**Record:** results, and how long until data loaded.

## 9. Removing workspace data

1. Delete `experiments/pbmc3k.h5ad` and `mdv/data/pbmc3k-auto.h5ad` from the bucket (and the
   optional `mdv/projects/pbmc3k-project/`).
2. Wait up to 10 minutes, or restart the app.

**Expect:** their projects disappear from the catalog; the log shows `removed pbmc3k`, `removed pbmc3k-auto`, and so on
for each. Once no workspace data is open in MDV, the sample projects come back (with new names
ending `-2`).

**Record:** results.

## 10. Unsupported browsers (expected failure)

Open the app in **Firefox** (and Safari if available) and open any project.

**Expect:** data fails to load with `SharedArrayBuffer is not defined`. This is the known
limitation of Document-Isolation-Policy.

**Record:** browser versions and the message shown.

## Results to send back

| Step | Result | Notes / recorded values |
|---|---|---|
| 1 Create app | | machine type, time to Running |
| 2 Isolation in frame | | app frame `isolated`/`sab`, top `isolated`, headers |
| 3 Samples | | variant count, timings |
| 4 Worker + shared memory, public data | | returned object |
| 5 Open from workspace | | time to open, snippet outputs, screenshots, dark mode |
| 6 `mdv/` folder | | project names, conversion time |
| 7 Read-only, views save | | |
| 8 Restart | | |
| 9 Removal | | |
| 10 Firefox/Safari | | |

Also attach the full sync log (step 3 command) at the end of testing.

## Troubleshooting

| Symptom | Check |
|---|---|
| App doesn't reach Running | App logs in Workbench. First builds take longer; retry once. |
| `isolated: false` in the app frame | Response headers in step 2.5, and the Chrome version (must be 137+). |
| No buckets in the sync log (`0 mounted resource(s)`) | Buckets created after the app started aren't mounted until a restart. |
| Workspace project missing | The folder must be `mdv/` at the top of the bucket, with files under `mdv/data/` or `mdv/projects/<name>/`. Check the sync log for `skipping` or `conversion failed`. |
| No **Open from workspace** card or toolbar button | Reload the page. Check that `<script src="/_workspace/ui.js"` is in the page source of the app frame. A floating **Open from workspace** button instead means MDV's layout wasn't recognised; record the MDV version. |
| Button shows no buckets | Buckets are mounted when the app starts; wait a minute after start, or restart the app if the bucket was created after it started. |
| "Couldn't open …" in the dialog | Expand **Details** and record it, with the sync log. |
| Large sample never appears | Look for `sample build failed` in the sync log. It retries after 6 hours; restart the app to retry immediately. |
| Public data blocked (negative values in step 4) | The host must send CORS headers for data read by JavaScript. Record the URL and Console error. |
