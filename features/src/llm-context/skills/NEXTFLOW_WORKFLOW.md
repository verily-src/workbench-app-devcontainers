# Nextflow Workflow Skill

**Trigger:** User mentions Nextflow, nf-core, `nextflow run`, Nextflow modules, or a Nextflow pipeline (RNA-seq, DNA-seq, variant calling, ChIP-seq, etc.).

This is the Workbench adapter for Nextflow. It covers:
1. [Authoring pipelines](#authoring-pipelines) — delegates to upstream skills
2. [Launching in Workbench](#launching-in-workbench) — via `wb workflow job run`
3. [Troubleshooting](#troubleshooting-nextflow-jobs-in-workbench) — Workbench job navigation + Nextflow-specific log inspection

> **Upstream skill files** (kept verbatim for easy updates):
> - `~/.claude/skills/nextflow/run-module.md` — running individual Registry modules
> - `~/.claude/skills/nextflow/create-workflow.md` — composing multi-module pipelines

---

## Authoring Pipelines

For running individual modules or building multi-module pipelines, delegate to the upstream skills:

- **Running a single module** → read `~/.claude/skills/nextflow/run-module.md`
- **Building a pipeline from multiple modules** → read `~/.claude/skills/nextflow/create-workflow.md`

### Workbench Overrides for Authoring

The upstream skills reference Seqera Platform for launching. **In Workbench, ignore all Seqera Platform (`nextflow auth`, `nextflow launch`) instructions.** Use `wb workflow job run` instead (see [Launching in Workbench](#launching-in-workbench)).

Wave + Conda container config from the upstream skills still applies:
```groovy
wave.enabled = true
wave.strategy = 'conda,container'
docker.enabled = true
```

---

## Launching in Workbench

Workflows must be registered in the workspace before they can be run.

```bash
# List registered workflows
wb workflow list

# Run a Nextflow workflow (registered in workspace)
wb workflow job run --workflow=<WORKFLOW_ID> --inputs=<INPUTS_JSON>

# Check job status
wb workflow job list --format=json | jq '.[] | {id, status, workflowName}'

# Get job details
wb workflow job describe --job=<JOB_ID> --format=json
```

### Input JSON for Nextflow

Nextflow inputs follow the same pattern as WDL — pass a JSON file or inline JSON:
```bash
wb workflow job run --workflow=<WORKFLOW_ID> \
  --inputs='{"input": "gs://my-bucket/reads/*.fq.gz", "outdir": "gs://my-bucket/results/"}'
```

### Saving Outputs

Nextflow writes outputs to the `outdir` parameter. Always point `outdir` to a GCS bucket — local app storage is ephemeral:
```bash
# Use an environment variable for the bucket path
wb workflow job run --workflow=<WORKFLOW_ID> \
  --inputs="{\"outdir\": \"${WORKBENCH_my_bucket}/nextflow-results/\"}"
```

---

## Troubleshooting Nextflow Jobs in Workbench

### Quick Diagnosis

```bash
# 1. Find failed jobs
wb workflow job list --format=json | jq -r '.[] | select(.status=="FAILED") | "\(.id)\t\(.workflowName)\t\(.startTime)"'

# 2. Get error message
wb workflow job describe --job=<JOB_ID> --format=json | jq -r '.failureMessage // "No message"'

# 3. Find failed task
wb workflow job task list --job=<JOB_ID> --format=json | jq -r '.[] | select(.status=="FAILED") | .name'

# 4. Get task logs
wb workflow job task describe --job=<JOB_ID> --task=<TASK_NAME> --format=json | jq '{stderr, stdout, exitCode, failureMessage}'
```

### Nextflow-Specific Log Locations

Unlike WDL/Cromwell, Nextflow stores execution state in two places:

**`.nextflow.log`** — the main Nextflow engine log, written to the launch directory:
```bash
# Find and read the Nextflow engine log
gsutil cat gs://<execution-bucket>/<run-id>/.nextflow.log 2>/dev/null | tail -100

# Search for errors
gsutil cat gs://<execution-bucket>/<run-id>/.nextflow.log 2>/dev/null | grep -i -E "error|failed|exception" | head -30
```

**`work/` directory** — each process task gets a unique hash subdirectory:
```
gs://<execution-bucket>/<run-id>/work/<ab>/<cdef1234>/
├── .command.sh      # The exact script that ran
├── .command.log     # Combined stdout + stderr
├── .command.err     # stderr only
├── .command.out     # stdout only
├── .exitcode        # Exit code (0 = success)
└── .nextflow.trace  # Resource usage trace
```

```bash
# Get the work directory from the task describe
EXEC_DIR=$(wb workflow job task describe --job=<JOB_ID> --task=<TASK_NAME> --format=json | jq -r '.executionDirectory // empty')

# Read the failed task script and logs
echo "=== script ===" && gsutil cat "$EXEC_DIR/.command.sh" 2>/dev/null
echo "=== exit code ===" && gsutil cat "$EXEC_DIR/.exitcode" 2>/dev/null
echo "=== stderr (last 50 lines) ===" && gsutil cat "$EXEC_DIR/.command.err" 2>/dev/null | tail -50
```

### Diagnose by Error Type

#### Memory / CPU Issues

**Symptoms:** Exit code 137 (SIGKILL/OOM), `Killed` in `.command.err`, task retried then failed

```bash
gsutil cat "$EXEC_DIR/.command.err" 2>/dev/null | grep -i -E "memory|oom|killed|malloc"
```

**Fix:** Increase resources in `nextflow.config` or the process definition:
```groovy
process {
    withName: 'ALIGN' {
        memory = '32 GB'
        cpus = 8
    }
}
```

#### Missing Input Files

**Symptoms:** `FileNotFoundException`, `No such file or directory`, process immediately exits

```bash
# Verify input paths exist
gsutil ls gs://<bucket>/path/to/inputs/ 2>&1
```

#### Container / Wave Issues

**Symptoms:** `Unable to pull image`, `wave.io` errors in `.nextflow.log`

```bash
# Confirm Wave config is present
gsutil cat gs://<execution-bucket>/<run-id>/nextflow.config 2>/dev/null | grep -A3 wave
```

Ensure `nextflow.config` includes:
```groovy
wave.enabled = true
wave.strategy = 'conda,container'
docker.enabled = true
```

#### Permission Issues

**Symptoms:** `403 Forbidden`, `Access denied` when reading/writing GCS paths

```bash
# Test bucket access from within the app
gsutil ls gs://<bucket>/ 2>&1 | head -5
```

### Error → Cause → Fix Reference

| Exit Code | Meaning | Common Fix |
|-----------|---------|------------|
| 1 | General error | Check `.command.err` for details |
| 2 | Misuse of shell command | Check `.command.sh` for syntax errors |
| 126 | Permission problem | Check file permissions |
| 127 | Command not found | Verify container image / Wave config |
| 137 | SIGKILL (OOM) | Increase `memory` in process config |
| 139 | Segfault | Check input data integrity |
| 143 | SIGTERM (timeout/preemption) | Increase `time` limit or disable spot VMs |

### Re-run After Fix

```bash
wb workflow job run --workflow=<WORKFLOW_ID> --inputs=<INPUTS_JSON>
```

Use `-resume` in your `nextflow.config` to skip already-completed tasks:
```groovy
resume = true
```

---

## Workbench-Specific Notes

- **Execution bucket**: Nextflow writes its work directory to the workspace execution bucket — check `wb workspace describe` for the bucket path
- **Local storage is ephemeral**: Always set `outdir` to a cloud storage path, not a local path
- **VPC-SC**: Run cloud CLI commands (`gsutil`, `aws s3`) from within the workspace app, not externally
- **Preemption**: If using spot VMs, set `google.spot = false` in `nextflow.config` for reliability

> **AWS workspaces**: This skill uses GCP examples (`gsutil`, `gs://` paths). For AWS workspaces, substitute `aws s3 cp` for `gsutil cat` and `s3://` paths for `gs://` paths when reading task logs from the work directory.

---

## Updating Upstream Skills

The files in `~/.claude/skills/nextflow/` are kept verbatim from [nextflow-io/agent-skills](https://github.com/nextflow-io/agent-skills). To update them, run from the `llm-context` feature directory:

```bash
curl -s https://raw.githubusercontent.com/nextflow-io/agent-skills/master/skills/run-module/SKILL.md \
  > features/src/llm-context/skills/nextflow/run-module.md
curl -s https://raw.githubusercontent.com/nextflow-io/agent-skills/master/skills/create-workflow/SKILL.md \
  > features/src/llm-context/skills/nextflow/create-workflow.md
```
