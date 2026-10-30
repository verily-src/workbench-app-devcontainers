# Local Testing

## Prerequisites

- Docker (for Postgres)
- Go 1.23+
- Optional: `gcloud auth application-default login` (for AI generation — will be blocked by VPC-SC on the default project unless you override `VERTEX_PROJECT`)

## Quick Start

```bash
cd src/program-generator/app/local-testing
./dev.sh
```

This script:
1. Creates or starts a Postgres container (`pg-program-gen`)
2. Waits for Postgres to be ready
3. Starts the Go server on http://localhost:8080

Ctrl+C to stop the server. The Postgres container persists between runs so saved templates stick around.

## What Works Locally

| Feature | Works Locally? | Notes |
|---------|---------------|-------|
| UI loads | Yes | |
| Validate YAML (dry run) | Yes | Parses YAML and builds FHIR bundle in memory |
| Save / load templates | Yes | Stored in Postgres |
| Export YAML | Yes | Client-side download |
| AI generation | Partial | Needs ADC credentials; blocked by VPC-SC on default project |
| Seed to FHIR | No | Needs FHIR store access (inside Workbench VM or port-forwarding) |
| GCS consent PDF upload | No | Needs GCS access |

## Test Workflow

1. Open http://localhost:8080
2. Copy the contents of `test-template.yaml` and paste into the YAML editor
3. Click **Validate** — should show "Valid!" with program name and bundle count
4. Click **Save Template** — give it a name, verify it appears in the sidebar
5. Click a saved template in the sidebar — verify it loads back
6. Click **Export YAML** — verify a `.yaml` file downloads

## Environment Overrides

Override any of these when running `dev.sh`:

```bash
VERTEX_PROJECT=my-project VERTEX_REGION=us-central1 ./dev.sh
```

| Variable | Default |
|----------|---------|
| `DB_HOST` | `localhost` |
| `DB_PORT` | `5432` |
| `FHIR_STORE` | `projects/prj-d-1v-ucd/...` |
| `GCS_BUCKET` | `econsent-pdf-pilot-dev-oneverily-prj-d-1v-ucd` |
| `VERTEX_PROJECT` | `wb-agile-aubergine-8187` |
| `VERTEX_REGION` | `us-east5` |
