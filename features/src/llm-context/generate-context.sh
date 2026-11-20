#!/bin/bash
# shellcheck disable=SC2016 # Single-quoted strings with $ and backticks are intentional template text
#
# Workbench LLM Context Generator
# 
# This script generates a single CLAUDE.md file that provides LLMs (like 
# Claude Code) with full context about the current Workbench workspace,
# resources, workflows, and available tools. The file includes embedded
# JSON for machine-readable data.
#
# Usage: ./generate-context.sh
#
# Prerequisites:
#   - Workbench CLI (wb) installed and authenticated
#   - jq installed for JSON processing
#   - Active workspace set (wb workspace set --id=<workspace-id>)
#
# CLI JSON Field Reference:
#   Workspace (UFWorkspaceLight.java):
#     - id: user-facing ID (e.g., "my-workspace")
#     - uuid: UUID
#     - name: display name
#     - description
#     - cloudPlatform: GCP or AWS
#     - googleProjectId, awsAccountId
#     - highestRole: OWNER, WRITER, READER
#     - orgId, podId
#     - userEmail
#     - createdDate, lastUpdatedDate
#     - properties: Map<String, String>
#
#   Resource (UFResource.java):
#     - id: resource name
#     - uuid
#     - description
#     - resourceType: GCS_BUCKET, BQ_DATASET, GIT_REPO, GCS_OBJECT, BQ_TABLE (GCP)
#                       AWS_S3_STORAGE_FOLDER, AWS_AURORA_DATABASE, AWS_AURORA_DATABASE_REFERENCE (AWS)
#     - stewardshipType: CONTROLLED, REFERENCED
#     - region
#     - For GCS: bucketName, location
#     - For BQ: projectId, datasetId
#
#   Workflow (UFWorkflow.java):
#     - id: name
#     - workflowId: UUID
#     - displayName
#     - description
#     - bucketSource or gitSource
#

set -e

# Configuration — accept an optional home directory argument (e.g., /config, /home/jupyter)
USER_HOME="${1:-${HOME}}"
CONTEXT_DIR="${USER_HOME}/.claude"
SKILLS_DIR="${CONTEXT_DIR}/skills"
CLAUDE_FILE="${CONTEXT_DIR}/CLAUDE.md"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1" >&2
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1" >&2
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    if ! command -v wb &> /dev/null; then
        log_error "Workbench CLI (wb) not found. Please install it first."
        exit 1
    fi
    
    if ! command -v jq &> /dev/null; then
        log_error "jq is required but not found. Please install jq."
        exit 1
    fi
    
    # Check if workspace is set
    if ! wb workspace describe --format=json &> /dev/null; then
        log_error "No workspace set or not authenticated. Please run:"
        log_error "  wb auth login   (GCP: add --mode=APP_DEFAULT_CREDENTIALS inside Workbench apps)"
        log_error "  wb workspace set --id=<workspace-id>"
        exit 1
    fi
    
    log_info "Prerequisites OK"
}

# Create output directory
setup_directories() {
    log_info "Setting up directories..."
    mkdir -p "${CONTEXT_DIR}"
    mkdir -p "${SKILLS_DIR}"
}

# Install skill files from /opt/llm-context/skills/ (copied at install time)
# $1: cloud_platform — "GCP" (default) or "AWS"
install_skills() {
    local cloud_platform="${1:-GCP}"
    local source_skills="/opt/llm-context/skills"
    log_info "Installing skill files..."

    if [[ ! -d "${source_skills}" ]]; then
        log_warn "Skill source directory not found at ${source_skills}, skipping skill installation"
        return
    fi

    # Remove the skill file that WDL_WORKFLOW_TROUBLESHOOT.md replaces
    rm -f "${SKILLS_DIR}/WORKFLOW_TROUBLESHOOT.md"

    # Copy all base skill files
    for skill_file in "${source_skills}"/*.md; do
        [[ -f "${skill_file}" ]] && cp "${skill_file}" "${SKILLS_DIR}/"
    done

    # Copy scientific skills
    if [[ -d "${source_skills}/scientific" ]]; then
        mkdir -p "${SKILLS_DIR}/scientific"
        for skill_file in "${source_skills}/scientific"/*.md; do
            [[ -f "${skill_file}" ]] && cp "${skill_file}" "${SKILLS_DIR}/scientific/"
        done
    fi

    # Copy upstream Nextflow skills (verbatim from nextflow-io/agent-skills)
    if [[ -d "${source_skills}/nextflow" ]]; then
        mkdir -p "${SKILLS_DIR}/nextflow"
        for skill_file in "${source_skills}/nextflow"/*.md; do
            [[ -f "${skill_file}" ]] && cp "${skill_file}" "${SKILLS_DIR}/nextflow/"
        done
    fi

    # AWS-specific skill overrides — overwrite only the platform-sensitive skills.
    if [ "$cloud_platform" = "AWS" ] && [[ -d "${source_skills}/aws" ]]; then
        log_info "Applying AWS skill variants for WDL_WORKFLOW_TROUBLESHOOT and DASHBOARD_BUILDER..."
        for skill_file in "${source_skills}/aws"/*.md; do
            [[ -f "${skill_file}" ]] && cp "${skill_file}" "${SKILLS_DIR}/"
        done
        log_info "AWS skill variants applied."
    fi

    log_info "Skill files installed."
}

# Fetch workspace information
fetch_workspace() {
    log_info "Fetching workspace information..."
    wb workspace describe --format=json 2>/dev/null || echo "{}"
}

# Fetch resources
fetch_resources() {
    log_info "Fetching resources..."
    wb resource list --format=json 2>/dev/null || echo "[]"
}

# Fetch workflows (may not exist in all workspaces)
fetch_workflows() {
    log_info "Fetching workflows..."
    wb workflow list --format=json 2>/dev/null || echo "[]"
}

# Fetch apps
fetch_apps() {
    log_info "Fetching apps..."
    wb app list --format=json 2>/dev/null || echo "[]"
}

# Generate embedded JSON (returns JSON to stdout, doesn't write to file)
# Resources listed in CLAUDE.md. Larger workspaces get a pointer to workspace_list_resources,
# since this file is sent to the model with every request.
MAX_LISTED_RESOURCES=50
MAX_LISTED_BUCKETS=20

generate_embedded_json() {
    local resources="$1"

    # `(if type == "array" then . else [] end)` guards against non-array input.
    # The environment variable for a resource is WORKBENCH_<id> with "-" replaced by "_",
    # so only the paths are listed.
    local result
    result=$(printf '%s' "${resources:-[]}" | jq -c --argjson max "${MAX_LISTED_RESOURCES}" '
        def cloud_path:
            if .resourceType == "GCS_BUCKET"              then "gs://\(.bucketName)"
            elif .resourceType == "AWS_S3_STORAGE_FOLDER" then "s3://\(.bucketName // "unknown")/\(.prefix // "")"
            elif .resourceType == "AWS_AURORA_DATABASE"   then "\(.rwEndpoint // "unknown"):\(.port // "5432")/\(.databaseName // "")"
            elif .resourceType == "BQ_DATASET"            then "\(.projectId).\(.datasetId)"
            elif .resourceType == "BQ_TABLE"              then "\(.projectId).\(.datasetId).\(.tableId // "")"
            elif .resourceType == "GIT_REPO"              then .gitRepoUrl
            elif .resourceType == "GCS_OBJECT"            then "gs://\(.bucketName)/\(.objectName // "")"
            else null end;
        (if type == "array" then . else [] end)
        | map({key: .id, value: cloud_path}) | map(select(.value != null))
        | {"resourcePaths": (.[:$max] | from_entries)}
          + (if length > $max then {"notListed": (length - $max), "listAll": "workspace_list_resources"} else {} end)
    ' 2>/dev/null | head -1)

    # A variable, because a literal "{...}" default inside ${result:-...} ends at its first "}".
    local empty='{"resourcePaths":{}}'
    printf '%s\n' "${result:-$empty}"
}

generate_bucket_list() {
    local resources="$1"
    local cloud_platform="${2:-GCP}"

    if [ "$cloud_platform" = "AWS" ]; then
        local buckets
        buckets=$(echo "$resources" | jq '[.[] | select(.resourceType == "AWS_S3_STORAGE_FOLDER")]' 2>/dev/null || echo "[]")
        local count
        count=$(echo "$buckets" | jq 'length' 2>/dev/null || echo "0")

        if [ "$count" -eq 0 ] || [ "$count" = "0" ]; then
            echo "*No S3 buckets in this workspace.* Create one with:"
            echo '```bash'
            echo 'wb resource create s3-storage-folder --id=my-storage --description "Storage for results"'
            echo '```'
            return
        fi

        echo "| Bucket Name | Resource ID | Description |"
        echo "|-------------|-------------|-------------|"
        echo "$buckets" | jq -r --argjson max "${MAX_LISTED_BUCKETS}" '.[:$max][] | "| `s3://\(.bucketName // "unknown")/\(.prefix // "")` | `\(.id // "—")` | \(.description // "—" | if . == "" then "—" else . end) |"' 2>/dev/null || true
        if [ "$count" -gt "${MAX_LISTED_BUCKETS}" ]; then
            echo "| … | $((count - MAX_LISTED_BUCKETS)) more | Use \`workspace_list_resources\` |"
        fi
    else
        # GCP
        local buckets
        buckets=$(echo "$resources" | jq '[.[] | select(.resourceType == "GCS_BUCKET")]' 2>/dev/null || echo "[]")
        local count
        count=$(echo "$buckets" | jq 'length' 2>/dev/null || echo "0")

        if [ "$count" -eq 0 ] || [ "$count" = "0" ]; then
            echo "*No GCS buckets in this workspace.* Create one with:"
            echo '```bash'
            echo 'wb resource create gcs-bucket --id=my-storage --description "Storage for results"'
            echo '```'
            return
        fi

        echo "| Bucket Name | Resource ID | Description |"
        echo "|-------------|-------------|-------------|"
        echo "$buckets" | jq -r --argjson max "${MAX_LISTED_BUCKETS}" '.[:$max][] | "| `gs://\(.bucketName // "unknown")/` | `\(.id // "—")` | \(.description // "—" | if . == "" then "—" else . end) |"' 2>/dev/null || true
        if [ "$count" -gt "${MAX_LISTED_BUCKETS}" ]; then
            echo "| … | $((count - MAX_LISTED_BUCKETS)) more | Use \`workspace_list_resources\` |"
        fi
    fi
}

# Generate CLAUDE.md
generate_claude_md() {
    log_info "Generating CLAUDE.md..."
    
    local workspace="$1"
    local resources="$2"
    # $3 (workflows) and $4 (apps) reserved for future use

    # Extract workspace values - field names match UFWorkspaceLight.java
    local ws_name ws_id ws_desc ws_cloud ws_gcp_project ws_aws_account ws_role ws_user ws_org ws_server
    ws_name=$(echo "$workspace" | jq -r '.name // "Unnamed Workspace"')
    ws_id=$(echo "$workspace" | jq -r '.id // "unknown"')
    ws_desc=$(echo "$workspace" | jq -r '.description // "No description"')
    ws_cloud=$(echo "$workspace" | jq -r '.cloudPlatform // "GCP"')
    ws_gcp_project=$(echo "$workspace" | jq -r '.googleProjectId // ""')
    ws_aws_account=$(echo "$workspace" | jq -r '.awsAccountId // ""')
    ws_role=$(echo "$workspace" | jq -r '.highestRole // "READER"')
    ws_user=$(echo "$workspace" | jq -r '.userEmail // "unknown"')
    ws_org=$(echo "$workspace" | jq -r '.orgId // ""')
    ws_server=$(echo "$workspace" | jq -r '.serverName // ""')
    
    # Determine project display
    local project_display="$ws_gcp_project"
    if [ -n "$ws_aws_account" ] && [ "$ws_aws_account" != "null" ] && [ "$ws_aws_account" != "" ]; then
        project_display="$ws_aws_account"
    fi
    
    # Set platform-specific template content (generator branches; output file is clean, no conditionals)
    local storage_bucket_type storage_save_cmd resource_table_rows
    local mcp_default_tools_rows cloud_cli_section cloud_path_hint env_var_example
    local data_preview_query_section create_resources_section
    if [ "$ws_cloud" = "AWS" ]; then
        storage_bucket_type="S3 bucket"
        storage_save_cmd='aws s3 cp <file> s3://<bucket>/'
        resource_table_rows='| `AWS_S3_STORAGE_FOLDER` | AWS S3 storage folder | `wb resource create s3-storage-folder` |
| `AWS_AURORA_DATABASE` | Aurora PostgreSQL database | `wb resource create aurora-database` |
| `AWS_AURORA_DATABASE_REFERENCE` | Aurora DB reference (external) | `wb resource add-ref aurora-database` |
| `GIT_REPO` | Git repository reference | `wb resource add-ref git-repo` |'

        # BEGIN default MCP tools (core group; TestLLMContextToolReferences in wb-mcp-server checks these)
        mcp_default_tools_rows='| `wb_status` | `wb status` | Current workspace, server and user |
| `workspace_list_resources` | `wb resource list` | List all resources in the workspace |
| `workspace_list_data_collections` | N/A | **List data collections and their resources** |
| `platform_list_data_collections` | N/A | Search data collections across all of Workbench (read `DATA_DISCOVERY.md` first) |
| `resource_list_tree` | `wb resource list-tree` | List resources organized by folder |
| `app_list` / `app_get_url` | `wb app list` | List apps; get a running app'"'"'s proxy URL |
| `s3_list_objects` | `aws s3 ls` | List files in an S3 storage folder |
| `s3_read_file` | `aws s3 cp <key> -` | Read contents of a file from S3 |
| `aurora_query` / `aurora_list_tables` / `aurora_describe_table` | `psql` | Query and inspect Aurora databases |
| `wb_execute` | `wb ...` | Any `wb` command, without the `wb` prefix |
| `wb_help` | — | Guides: `toolsets`, `cohorts`, `export`, `data-collections` |'
        # END default MCP tools

        cloud_cli_section='### Cloud CLIs

No direct AWS CLI MCP wrapper — use `aws` CLI commands in the terminal:
- **S3**: `aws s3 ls s3://<bucket>/`, `aws s3 cp <src> <dst>`
- **Batch**: `aws batch list-jobs --job-queue <queue> --job-status FAILED`
- **Aurora**: requires IAM auth token — see Aurora connection instructions in DASHBOARD_BUILDER skill'

        cloud_path_hint='# Look for: bucketName+prefix (S3), rwEndpoint+port+databaseName (Aurora), gitRepoUrl'

        env_var_example='echo $WORKBENCH_my_bucket      # → s3://bucket/prefix
env | grep WORKBENCH_           # List all'

        data_preview_query_section='**S3:**
```bash
aws s3 ls s3://<bucket>/<prefix>/
aws s3 cp s3://<bucket>/<prefix>/file.csv - | head -20
```

**Aurora PostgreSQL** (requires IAM auth + SSL — plain passwords are rejected):
```bash
# Step 1: get temporary credentials from Workbench
wb resource credentials --id=<resource-id> --scope=WRITE_READ --format=json
# Returns: {"AccessKeyId":"...","SecretAccessKey":"...","SessionToken":"..."}

# Step 2: export credentials, generate auth token, connect
export AWS_ACCESS_KEY_ID="..." AWS_SECRET_ACCESS_KEY="..." AWS_SESSION_TOKEN="..."
TOKEN=$(aws rds generate-db-auth-token --hostname <rwEndpoint> --port 5432 --region us-west-2 --username <user>)
PGSSLMODE=require psql "host=<rwEndpoint> port=5432 dbname=<db> user=<user> password=$TOKEN"
# \dt  →  list tables;  SELECT * FROM table_name LIMIT 10;
```

### Query Data

**Python (S3):**
```python
import boto3, pandas as pd

s3 = boto3.client("s3")
obj = s3.get_object(Bucket="<bucket>", Key="<prefix>/file.csv")
df = pd.read_csv(obj["Body"])

# Read Parquet directly (requires s3fs)
df = pd.read_parquet("s3://<bucket>/<prefix>/file.parquet")
```

**Python (Aurora — IAM auth required):**
```python
import json, subprocess, boto3, psycopg2

# Get temporary credentials from Workbench
creds = json.loads(subprocess.run(
    ["wb", "resource", "credentials", "--id=<resource-id>", "--scope=WRITE_READ", "--format=json"],
    capture_output=True, text=True, check=True
).stdout)

# Generate IAM auth token
session = boto3.Session(
    aws_access_key_id=creds["AccessKeyId"],
    aws_secret_access_key=creds["SecretAccessKey"],
    aws_session_token=creds["SessionToken"],
    region_name="us-west-2"
)
auth_token = session.client("rds").generate_db_auth_token(
    DBHostname="<rwEndpoint>", Port=5432, DBUsername="<user>", Region="us-west-2"
)

# Connect — sslmode="require" is mandatory
conn = psycopg2.connect(
    host="<rwEndpoint>", port=5432, database="<db>",
    user="<user>", password=auth_token, sslmode="require"
)
df = pd.read_sql("SELECT * FROM table_name LIMIT 100", conn)
conn.close()
```'

        create_resources_section='```bash
# S3 storage folder
wb resource create s3-storage-folder --id=my-storage --description "My storage folder"

# Aurora PostgreSQL database
wb resource create aurora-database --id=my-db --database-name=<DATABASE_NAME> --description "My database"

# Reference an external Aurora database
wb resource add-ref aurora-database --id=external-db --source-workspace-id=<WORKSPACE_ID> --source-resource-id=<RESOURCE_ID>
```'

    else
        storage_bucket_type="GCS bucket"
        storage_save_cmd='gcloud storage cp <file> gs://<bucket>/'
        resource_table_rows='| `GCS_BUCKET` | Google Cloud Storage bucket | `wb resource create gcs-bucket` |
| `BQ_DATASET` | BigQuery dataset | `wb resource create bq-dataset` |
| `GIT_REPO` | Git repository reference | `wb resource add-ref git-repo` |
| `GCS_OBJECT` | Individual GCS file reference | `wb resource add-ref gcs-object` |
| `BQ_TABLE` | BigQuery table reference | `wb resource add-ref bq-table` |'

        # BEGIN default MCP tools (core group; TestLLMContextToolReferences in wb-mcp-server checks these)
        mcp_default_tools_rows='| `wb_status` | `wb status` | Current workspace, server and user |
| `workspace_list_resources` | `wb resource list` | List all resources in the workspace |
| `workspace_list_data_collections` | N/A | **List data collections and their resources** |
| `platform_list_data_collections` | N/A | Search data collections across all of Workbench (read `DATA_DISCOVERY.md` first) |
| `resource_list_tree` | `wb resource list-tree` | List resources organized by folder |
| `app_list` / `app_get_url` | `wb app list` | List apps; get a running app'"'"'s proxy URL |
| `bq_query` | `bq query` | Run SQL against BigQuery (`sql` argument) |
| `bq_execute` | `bq ls` / `bq show` | Other `bq` commands (`ls`, `show --schema`, `head`) |
| `gsutil_execute` | `gsutil ls` / `gsutil cat` | List or read files in a GCS bucket (e.g. `ls gs://<bucket>/`) |
| `gcloud_execute` | `gcloud ...` | Any other `gcloud` command |
| `wb_execute` | `wb ...` | Any `wb` command, without the `wb` prefix |
| `wb_help` | — | Guides: `toolsets`, `cohorts`, `export`, `data-collections` |'
        # END default MCP tools

        cloud_cli_section=''

        cloud_path_hint='# Look for: bucketName, projectId+datasetId, gitRepoUrl'

        env_var_example='echo $WORKBENCH_my_bucket      # → gs://actual-bucket-name
env | grep WORKBENCH_           # List all'

        data_preview_query_section='**BigQuery:**
```bash
bq head -n 10 <project>:<dataset>.<table>
bq show --schema <project>:<dataset>.<table>
bq query --use_legacy_sql=false '"'"'SELECT * FROM `project.dataset.table` LIMIT 10'"'"'
```

**GCS:**
```bash
gcloud storage ls gs://<bucket>/
gcloud storage cat gs://<bucket>/path/file.csv --range=0-1024
```

### Query Data

**CLI:**
```bash
bq query --use_legacy_sql=false '"'"'SELECT col1, col2 FROM `project.dataset.table` LIMIT 100'"'"'
```

**Python:**
```python
from google.cloud import bigquery
client = bigquery.Client()
df = client.query("SELECT * FROM `project.dataset.table` LIMIT 100").to_dataframe()

import pandas as pd
df = pd.read_parquet("gs://bucket-name/path/file.parquet")
```'

        create_resources_section='```bash
# GCS bucket
wb resource create gcs-bucket --id=my-bucket --description "My bucket"

# BigQuery dataset
wb resource create bq-dataset --id=my-dataset --description "My dataset"

# Reference external GCS bucket
wb resource add-ref gcs-bucket --id=external-data --bucket-name=existing-bucket
```'
    fi

    # Generate dynamic sections
    local embedded_json bucket_list
    embedded_json=$(generate_embedded_json "$resources")
    bucket_list=$(generate_bucket_list "$resources" "$ws_cloud")
    
    # Write the file
    cat > "${CLAUDE_FILE}" << EOF
# Workbench Context

You are working inside **Verily Workbench**, a secure cloud-based research environment for biomedical data analysis.

---

## Current Workspace

| Property | Value |
|----------|-------|
| **Name** | ${ws_name} |
| **ID** | \`${ws_id}\` |
| **Cloud Platform** | ${ws_cloud} |
| **Project/Account** | \`${project_display}\` |
| **Your Role** | ${ws_role} |
| **User** | ${ws_user} |
| **Organization** | ${ws_org:-"—"} |
| **Server** | ${ws_server:-"—"} |

### Description
${ws_desc}

---

## Key Concepts

### Workspaces
A **workspace** is a secure container for your research project. It contains:
- **Resources**: Cloud assets like buckets, datasets, repos
- **Workflows**: Reproducible analysis pipelines
- **Apps**: Interactive compute environments (this app!)
- **Policies**: Access controls and constraints

### Resources
Resources are cloud assets managed by Workbench:

| Type | Description | CLI Create Command |
|------|-------------|-------------------|
${resource_table_rows}

**Environment Variables**: Each resource is available as \`\$WORKBENCH_<resource_name>\` (e.g., \`\$WORKBENCH_my_bucket\`).

### Data Collections
Curated datasets published to the Workbench catalog. When added to a workspace, their resources are cloned as **folders** — they may look like user-created resources but originated externally. Common types include clinical data (OMOP, FHIR), genomics (VCF, BAM), and wearables.

Data collections can carry **policies** that restrict how their data is used (region, export controls, access groups).

**To identify resources from data collections:**
1. Use \`workspace_list_data_collections\` — groups resources by source collection (preferred)
2. Or use \`workspace_list_resources\` with \`workspaceId\` — returns full resource metadata including \`resourceLineage\`, which contains the source collection ID and original resource ID

### Workflows
Workflows are reproducible pipelines in WDL or Nextflow format, registered in the workspace.

### Policies & Constraints
Workspaces may have policies that restrict:
- **Region**: Where data and compute must reside
- **Groups**: Who can access the workspace
- **Export**: Whether data can leave the workspace

Check with: \`wb workspace describe\`

---

## ⚠️ Important: Data Persistence

Local app storage is ephemeral — files saved to the app's local disk are **lost when the app stops or restarts**. Always encourage users to save important work to a ${storage_bucket_type} in their workspace.

- **When users create files locally**, suggest saving to a bucket: \`${storage_save_cmd}\`
- **When users finish analysis**, remind: *"Save important outputs to cloud storage before stopping the app."*
- **Available buckets in this workspace:**

${bucket_list}

---

## Most Commonly Used MCP Tools

> **Always use MCP tools before falling back to CLI. MCP tools return structured JSON and are faster.**

| Interface | Best For |
|-----------|----------|
| **MCP Tools** | List/query operations — structured responses, no shell needed |
| **CLI (\`wb\`)** | Complex operations or anything not covered by MCP |

### Default Tools

| MCP Tool | CLI Equivalent | Description |
|----------|----------------|-------------|
${mcp_default_tools_rows}

### More Tool Groups (Off by Default)

| Group | For | Example tools |
|-------|-----|---------------|
| workflows | Running, cancelling and debugging workflows: tasks, logs, traces, costs | \`workflow_job_run\`, \`workflow_run_logs\` |
| dataexplorer | Underlay schemas, studies, building and exporting cohorts | \`underlay_list\`, \`cohort_create_in_workspace\` |
| apps | Creating, deleting, starting and stopping apps | \`app_create\`, \`app_start\` |
| admin | Workspaces, resources, folders, users, groups | \`resource_create_bucket\`, \`resource_delete\` |
| legacy | Notebook and cluster tools, older duplicates | — |

Only call tools that are in your tool list; don't guess names. Most groups have \`wb\` CLI equivalents, so if a tool from a group that's off is needed, use the CLI (through \`wb_execute\` or the terminal). These have no CLI equivalent: the Data Explorer tools (group \`dataexplorer\`; direct API calls) and \`workflow_run_logs\`, \`workflow_run_trace\`, \`workflow_run_costs\` and \`workflow_task_get\`. For those, ask the user to enable the group: the MCP server feature's \`toolsets\` option, or \`?toolsets=\` in the server URL (\`wb_help\` with topic \`toolsets\` explains).

${cloud_cli_section}

**Terminal only:** \`wb workspace set\`, \`wb auth login\`

## CLI Quick Reference

\`\`\`bash
# Workspace
wb workspace describe          # Current workspace details
wb workspace list              # All your workspaces
wb workspace set --id=<id>     # Switch workspace

# Resources
wb resource list               # List resources
wb resource describe --id=<name>   # Resource details
wb resource delete --id=<name>     # Delete resource

# Workflows
wb workflow list               # List workflows
wb workflow describe --workflow=<id>   # Workflow details
wb workflow job list                   # List jobs
wb workflow job describe --job-id=<id> # Job status

# Apps
wb app list                    # List running apps
wb app describe --id=<name>      # App details

# Auth
wb auth status                 # Check authentication
wb auth login                  # Re-authenticate
\`\`\`

---

## Data Discovery & Querying

> **⚡ MCP FIRST:** Always check if an MCP tool exists before using CLI commands.

### Find Your Resources

**Use MCP tools (preferred):**
| What You Need | MCP Tool |
|---------------|----------|
| Data collections + their resources | \`workspace_list_data_collections\` |
| All resources (flat list) | \`workspace_list_resources\` |
| Resources organized by folder | \`resource_list_tree\` |

**CLI fallback:**
\`\`\`bash
wb resource list --format=json | jq '.[] | {name: .id, type: .resourceType}'
\`\`\`

### Get the Cloud Path for a Resource

\`\`\`bash
wb resource describe --id=<resource-name> --format=json
${cloud_path_hint}
\`\`\`

### Use Environment Variables (Easiest)

\`\`\`bash
${env_var_example}
\`\`\`

### Preview Data

${data_preview_query_section}

---

## How to Run Workflows

\`\`\`bash
# List workflows
wb workflow list

# Run a workflow
wb workflow job run --workflow=<workflow-id> --output-bucket-id=<bucket-id> --inputs='{"param": "value"}'

# Check status
wb workflow job describe --job-id=<job-id>

# List the tasks of a job
wb workflow job task list --job-id=<job-id>
\`\`\`

---

## How to Create Resources

${create_resources_section}

---

## ⚠️ Workbench Web Apps & Proxy URLs

> **🚨 If the user wants a dashboard, chart, Flask app, HTML page, or ANY web UI — read \`~/.claude/skills/DASHBOARD_BUILDER.md\` first.**

### Proxy URL Format

The proxy URL is the **only valid way** to access web apps in Workbench:
\`\`\`
https://workbench.verily.com/app/[APP_UUID]/proxy/[PORT]/[PATH]
\`\`\`

Retrieve the App UUID automatically:
\`\`\`bash
wb app list --format=json | jq -r '.[] | select(.status == "RUNNING") | .id' | head -1
\`\`\`

### Common Ports

| Content Type | Port |
|--------------|------|
| Flask/FastAPI | 8080 |
| Streamlit | 8501 |
| Static HTML | 8000 |
| R Shiny | 3838 |

### ⚠️ JavaScript: Always Use Relative Paths

All \`fetch()\` calls in JavaScript **must** use relative paths (no leading \`/\`):

\`\`\`javascript
fetch('api/data')   // ✅ resolves to workbench.verily.com/app/UUID/proxy/8080/api/data
fetch('/api/data')  // ❌ resolves to workbench.verily.com/api/data — 404!
\`\`\`

### ❌ Wrong URL Formats

\`\`\`
https://UUID.workbench-app.verily.com/   ← Bad Request error
http://localhost:8080/                   ← Not accessible externally
file:///home/jupyter/dashboard.html      ← JavaScript blocked
\`\`\`

---

## Available Skills

### Scientific Skills

> **📚 Read \`~/.claude/skills/SCIENTIFIC_SKILLS_INDEX.md\` first** to navigate scientific domain skills.

| Domain | Skill File | Covers |
|--------|------------|--------|
| 🧬 Bioinformatics | \`scientific/BIOINFORMATICS.md\` | scanpy, anndata, pydeseq2, biopython, scvelo |
| 💊 Drug Discovery | \`scientific/DRUG_DISCOVERY.md\` | rdkit, deepchem, chembl, drugbank, opentargets |
| 🔬 Genomics DBs | \`scientific/GENOMICS_DATABASES.md\` | ensembl, uniprot, clinvar, pdb |
| 📊 Data Analysis | \`scientific/DATA_ANALYSIS.md\` | sklearn, statsmodels, plotly, seaborn |
| 🏥 Clinical | \`scientific/CLINICAL.md\` | clinicaltrials.gov, pubmed, lifelines |

### When to Read a Skill

Read the skill file in \`~/.claude/skills/\` **before** starting these tasks:
- **\`DATA_DISCOVERY.md\`**: before calling \`platform_list_data_collections\`, and whenever the user searches for data collections across Workbench ("find data collections about <topic>", "what can I add?"). For collections already in this workspace, call \`workspace_list_data_collections\` directly.
- **\`DASHBOARD_BUILDER.md\`**: any dashboard, chart, Flask/Streamlit/Plotly app, web page, or anything served on a port or shown in a browser.
- **\`CUSTOM_APP.md\`**: a deployable custom app, API service or backend built from scratch.
- **\`APP_TEMPLATES.md\`**: starter templates for dashboards, APIs and file processors.
- **\`WDL_WORKFLOW_TROUBLESHOOT.md\`**: a failed WDL/Cromwell job ("workflow failed", "task failed", "out of memory", "check logs"). If the workflow type is unclear, check \`wb workflow list\` first.
- **\`NEXTFLOW_WORKFLOW.md\`**: writing, running or troubleshooting Nextflow or nf-core pipelines.
- **\`SCIENTIFIC_SKILLS_INDEX.md\`**, then the domain file: single-cell/RNA-seq, molecules/drugs, genes/proteins/variants, machine learning/statistics, clinical trials/PubMed/survival analysis.

---

## Quick Reference (Machine-Readable)

Use this JSON for the exact cloud path of each resource:

\`\`\`json
${embedded_json}
\`\`\`

**Usage:**
- \`resourcePaths["my-bucket"]\` → exact cloud storage/database path
- The JSON has no environment variables; each resource is also set as \`\$WORKBENCH_<resource id>\` with \`-\` replaced by \`_\` (e.g. \`\$WORKBENCH_my_bucket\`)
- \`notListed\` and \`listAll\` (large workspaces only): how many resources were left out, and the tool that lists all of them (\`workspace_list_resources\`)

To refresh after workspace changes:
\`\`\`bash
~/.claude/generate-context.sh
\`\`\`

---

## Getting Help

- **Docs**: https://support.workbench.verily.com
- **Custom Apps Guide**: https://support.workbench.verily.com/docs/guides/cloud_apps/create_custom_apps/
- **Devcontainers Repo**: https://github.com/verily-src/workbench-app-devcontainers
- **Devcontainer Reference**: https://containers.dev/implementors/json_reference/
- **CLI Help**: \`wb --help\` or \`wb <command> --help\`
- **Support**: support@workbench.verily.com

---

*Generated: $(date -u +"%Y-%m-%d %H:%M:%S UTC")*
EOF

    log_info "Created ${CLAUDE_FILE}"
}

# Main function
main() {
    echo ""
    echo "=========================================="
    echo "  Workbench LLM Context Generator"
    echo "=========================================="
    echo ""
    
    check_prerequisites
    setup_directories

    # Fetch all data first so we can detect cloud platform before generating skills
    WORKSPACE=$(fetch_workspace)
    RESOURCES=$(fetch_resources)
    WORKFLOWS=$(fetch_workflows)
    APPS=$(fetch_apps)

    # Detect cloud platform for platform-specific skill and context generation
    local cloud_platform
    cloud_platform=$(echo "$WORKSPACE" | jq -r '.cloudPlatform // "GCP"')
    log_info "Detected cloud platform: ${cloud_platform}"

    install_skills "$cloud_platform"

    # Generate single CLAUDE.md file with embedded JSON
    generate_claude_md "$WORKSPACE" "$RESOURCES" "$WORKFLOWS" "$APPS"

    echo "" >&2
    log_info "Context generation complete!"
    echo "" >&2
    echo "Generated file:" >&2
    echo "  - ${CLAUDE_FILE}" >&2
    echo "" >&2
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" >&2
    echo "✅ Claude Code will automatically discover ~/.claude/CLAUDE.md" >&2
    echo "" >&2
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" >&2
    echo "" >&2
}

# Run main
main "$@"
