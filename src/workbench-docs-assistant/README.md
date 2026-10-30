# Workbench Docs Assistant

A custom Workbench app that lets users chat with the [Verily Workbench documentation](https://support.workbench.verily.com).
Answers are grounded in the public docs and link to the pages they came from. The model runs on
**Vertex AI in the workspace's own Google Cloud project**, so questions never leave the workspace's cloud
boundary and usage is billed to that project.

It is also a small, complete example of a custom web app: a Python backend, a single HTML page, one
port, no startup scripts.

## How it works

1. On startup the app reads the documentation site's `sitemap.xml`, fetches every page under `/docs/`,
   strips navigation, and splits each page at its headings (about 375 pages, a few thousand sections).
2. Each section is embedded with Vertex AI (`text-embedding-005`) and kept in memory. The index is cached
   in a Docker volume so restarts are quick, and it refreshes every 24 hours.
3. For each question, the most relevant sections are retrieved (embedding similarity plus a keyword boost
   for exact command names) and sent to Gemini with instructions to answer **only** from those excerpts
   and to cite them. Citations render as numbered links to the exact section of the docs.
4. If the docs don't cover a question, the assistant says so and shows the configured support contacts.

If embedding calls fail (for example, a missing IAM role), the app falls back to keyword search and
says so in the status bar, so it still works while permissions are sorted out.

## Deploying in Workbench

1. In your workspace, create a **custom app** and point it at this repository (or your fork), template
   `workbench-docs-assistant`.
2. Open the app. The status bar shows indexing progress for about a minute, then **Ready**.

### Requirements

- The **Vertex AI API** (`aiplatform.googleapis.com`) must be enabled in the workspace's Google Cloud project.
- The app's identity (the workspace service account) needs permission to call Vertex AI models
  (`roles/aiplatform.user` or equivalent). If it doesn't, the status bar shows the error and chat returns
  a clear message.
- Outbound access from the app to the documentation site and to `*.googleapis.com`.

### Options

Set these when creating the app, or change the defaults in `devcontainer-template.json` on your fork.

| Option | Default | Purpose |
|---|---|---|
| `docsBaseUrl` | `https://support.workbench.verily.com` | Site to index. Any site with a `sitemap.xml` whose pages live under `/docs/` works. |
| `geminiModel` | `gemini-3.5-flash` | Vertex AI model for answers. `gemini-3.5-flash-lite` is cheaper; `gemini-3.1-pro-preview` is stronger. |
| `vertexLocation` | `global` | Vertex AI location for the model. |
| `assistantTitle` | `Workbench Docs Assistant` | Header title. |
| `supportContacts` | `Email workbench-support@verily.com` | Shown in the footer and used by the model when the docs don't answer a question. For a customer deployment, put the customer's own escalation path here, e.g. `Trial questions: your-admin@example.org · Platform issues: workbench-support@verily.com`. |

Environment variables with the same meaning (`DOCS_BASE_URL`, `GEMINI_MODEL`, `VERTEX_LOCATION`,
`ASSISTANT_TITLE`, `SUPPORT_CONTACTS`) plus `EMBEDDING_MODEL`, `EMBEDDING_LOCATION`, `INDEX_REFRESH_HOURS`,
`TOP_K`, and `GOOGLE_CLOUD_PROJECT` can be set directly in `docker-compose.yaml`.

### Per-instance overrides (no fork needed)

Any of those settings can also be set as **VM metadata** on the app instance, using the lower-case,
hyphenated form of the variable name. Metadata wins over template options, so one app config can serve
several deployments with different contacts or models:

```bash
wb app config create --name=docs-assistant \
  --git-repo-url=https://github.com/verily-src/workbench-app-devcontainers.git \
  --dev-container-path=src/workbench-docs-assistant

wb app create gcp --config=docs-assistant --id=docs-assistant \
  -M assistant-title="Acme Research Docs Assistant" \
  -M support-contacts="Questions about this workspace: admin@acme.org. Platform issues: workbench-support@verily.com"
```

### Startup and re-indexing

- **First start** of a new app instance: the index is built from scratch, about 60–90 seconds. The
  status bar shows progress and chat says "still building" until it is done.
- **Later starts** (after a stop/start or container restart): the cached index on the `index-cache`
  volume loads in a few seconds. If it is older than 24 hours it is used immediately and refreshed in
  the background, so users never wait on a rebuild.
- `POST /api/reindex` forces a rebuild at any time.

### Cost

Indexing embeds a few million characters once a day (fractions of a cent). Each question sends roughly
8 doc sections (about 5k tokens) to Gemini. With `gemini-3.5-flash`, hundreds of questions cost well under
a dollar. Check current Vertex AI pricing for your project.

## API

| Route | Purpose |
|---|---|
| `GET /` | Chat UI |
| `GET /api/status` | Index state, model, project, contacts |
| `POST /api/chat` | `{"messages": [{"role": "user", "content": "..."}]}` → `answer_html`, `answer_markdown`, `sources` |
| `POST /api/reindex` | Rebuild the index now |
| `GET /healthz` | Liveness check |

## Running locally

```bash
cd app
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
gcloud auth application-default login            # or run where default credentials exist
export GOOGLE_CLOUD_PROJECT=<project with Vertex AI enabled> INDEX_CACHE_DIR=/tmp/docs-index
python app.py                                    # http://localhost:8080
```

## Notes

- Only the published docs are indexed. Drafts and internal pages are not.
- The frontend builds API URLs from the page's own path, so it works behind the Workbench proxy
  (`https://workbench.verily.com/app/<id>/proxy/8080/`) and at `http://localhost:8080/`.
- Model output is HTML-escaped before Markdown rendering; only the citation links are generated by the app.
