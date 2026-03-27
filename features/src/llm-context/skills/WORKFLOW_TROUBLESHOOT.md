# WDL Workflow Troubleshooting Skill

**Trigger:** User asks to troubleshoot, debug, or fix a failed workflow.

## ⚡ LLM Behavior: Be Proactive!

**Once the user confirms which job to investigate, DO NOT ask which diagnostic steps to run.** Instead:
1. **Run all diagnostic commands automatically** (Steps 2-4 at minimum)
2. **Analyze the results** and identify the root cause
3. **Report your diagnosis** with evidence (error messages, exit codes, log snippets)
4. **Propose a fix** with specific changes
5. **THEN ask** if they want you to apply the fix or investigate further

❌ Don't say: "Would you like me to check the logs?"
✅ Do say: "I checked the logs and found an OOM error. The task requested 8GB but needed more. I recommend increasing memory to 16GB in the runtime block."

---

## Quick Diagnosis (Start Here)

```bash
# 1. Find failed jobs
wb workflow job list --format=json | jq -r '.[] | select(.status=="FAILED") | "\(.id)\t\(.workflowName)\t\(.startTime)"'

# 2. Get error message (replace JOB_ID)
wb workflow job describe --job=<JOB_ID> --format=json | jq -r '.failureMessage // "No message"'

# 3. Find failed task
wb workflow job task list --job=<JOB_ID> --format=json | jq -r '.[] | select(.status=="FAILED") | .name'

# 4. Get task error + logs
wb workflow job task describe --job=<JOB_ID> --task=<TASK_NAME> --format=json | jq '{stderr, stdout, exitCode, failureMessage}'
```

**After running these 4 commands, you'll know:** which job failed, why, which task, and where logs are.

---

## Step-by-Step Guide

### Step 1: Identify Failed Job

```bash
# List all failed jobs
wb workflow job list --format=json | jq '.[] | select(.status == "FAILED") | {id, workflowName, status, startTime, endTime}'
```

**For batch jobs:**
```bash
# List failed sub-jobs within a batch
wb workflow job batch list --job=<JOB_ID> --format=json | jq '.[] | select(.status == "FAILED") | {id, status}'
```

**Ask user:** Confirm which job ID to investigate (if multiple failed jobs).

---

### Step 2: Get Job Details & Inputs

```bash
# Full job metadata
wb workflow job describe --job=<JOB_ID> --format=json
```

**Key fields to extract:**
```bash
# Error message
wb workflow job describe --job=<JOB_ID> --format=json | jq -r '.failureMessage'

# Inputs used
wb workflow job describe --job=<JOB_ID> --format=json | jq '.inputs'

# Outputs (if any)
wb workflow job describe --job=<JOB_ID> --format=json | jq '.outputs'
```

---

### Step 3: Find Failed Task & Get Logs

```bash
# List all tasks with status
wb workflow job task list --job=<JOB_ID> --format=json | jq '.[] | {name, status, exitCode}'

# Get failed task details
wb workflow job task describe --job=<JOB_ID> --task=<TASK_NAME> --format=json
```

**Extract log URLs:**
```bash
# Get stderr and stdout URLs
TASK_INFO=$(wb workflow job task describe --job=<JOB_ID> --task=<TASK_NAME> --format=json)
STDERR_URL=$(echo $TASK_INFO | jq -r '.stderr')
STDOUT_URL=$(echo $TASK_INFO | jq -r '.stdout')

echo "stderr: $STDERR_URL"
echo "stdout: $STDOUT_URL"
```

---

### Step 4: Pull and Analyze Task Logs

#### Read Log Contents

```bash
# Read stderr (usually contains errors)
gsutil cat "$STDERR_URL" 2>/dev/null | tail -100

# Read stdout
gsutil cat "$STDOUT_URL" 2>/dev/null | tail -100

# Search for common error patterns
gsutil cat "$STDERR_URL" 2>/dev/null | grep -i -E "error|exception|failed|denied|killed|oom|memory|disk|timeout" | head -30
```

#### Common Log File Patterns

Cromwell execution logs are typically at:
```
gs://<execution-bucket>/<workflow-id>/<call-name>/execution/
├── stdout          # Task standard output
├── stderr          # Task standard error  
├── script          # The actual command that ran
├── rc              # Return code (exit code)
└── script.submit   # Submission script
```

**One-liner to read all execution files:**
```bash
# Find execution directory from task describe, then:
EXEC_DIR=$(echo $TASK_INFO | jq -r '.executionDirectory // empty')
if [ -n "$EXEC_DIR" ]; then
  echo "=== script ===" && gsutil cat "$EXEC_DIR/script" 2>/dev/null
  echo "=== rc ===" && gsutil cat "$EXEC_DIR/rc" 2>/dev/null
  echo "=== stderr (last 50 lines) ===" && gsutil cat "$EXEC_DIR/stderr" 2>/dev/null | tail -50
fi
```

---

### Step 5: Check Resource Allocation & Usage

#### What Was Requested (from WDL runtime)

```bash
# Get workflow definition to see runtime requirements
wb workflow describe --workflow=<WORKFLOW_ID> --format=json | jq '.sourceUrl'

# Read WDL file
gsutil cat gs://<bucket>/<path>/workflow.wdl | grep -A10 "runtime {"
```

#### Check Actual Resource Usage (GCP Batch)

```bash
# For GCP Cromwell jobs, get batch job details
gcloud batch jobs list --filter="status.state=FAILED" --format="table(name,status.state,createTime)"

# Describe specific batch job
gcloud batch jobs describe <BATCH_JOB_NAME> --format=json | jq '{
  status: .status.state,
  statusEvents: .status.statusEvents,
  taskGroups: .taskGroups[0].taskSpec.computeResource
}'
```

#### Memory-Specific Checks

```bash
# Check if OOM (Out of Memory) killed the task
gsutil cat "$STDERR_URL" 2>/dev/null | grep -i -E "oom|out of memory|killed|cannot allocate|memory"

# Check what memory was requested in batch job
gcloud batch jobs describe <BATCH_JOB_NAME> --format=json | jq '.taskGroups[0].taskSpec.computeResource.memoryMib'

# Check dmesg/syslog for OOM events (if available in logs)
gsutil cat "$STDERR_URL" 2>/dev/null | grep -i "killed process"
```

---

### Step 6: Diagnose by Error Type

#### Memory Issues (OOM)

**Symptoms:**
- Exit code 137 (SIGKILL) or 143
- "Killed" in stderr
- "Cannot allocate memory"
- Task succeeded locally but fails at scale

**Diagnosis:**
```bash
# Check requested memory
gcloud batch jobs describe <BATCH_JOB_NAME> --format=json | jq '.taskGroups[0].taskSpec.computeResource'

# Look for memory errors in logs
gsutil cat "$STDERR_URL" 2>/dev/null | grep -i -E "memory|oom|killed|malloc"
```

**Fix:** Increase `memory` in WDL runtime block:
```wdl
runtime {
  memory: "32G"  # Increase from previous value
}
```

#### Disk Issues

**Symptoms:**
- "No space left on device"
- "Disk quota exceeded"

**Diagnosis:**
```bash
gsutil cat "$STDERR_URL" 2>/dev/null | grep -i -E "space|disk|quota"
```

**Fix:** Increase disk in WDL runtime:
```wdl
runtime {
  disks: "local-disk 200 SSD"  # Increase size
}
```

#### Input File Issues

**Symptoms:**
- "FileNotFoundException"
- "Localization failed"
- File not found errors

**Diagnosis:**
```bash
# Check if input files exist
wb workflow job describe --job=<JOB_ID> --format=json | jq -r '.inputs | to_entries[] | .value' | while read path; do
  if [[ $path == gs://* ]]; then
    echo -n "$path: " && gsutil ls "$path" 2>&1 | head -1
  fi
done
```

#### Permission Issues

**Symptoms:**
- "Permission denied"
- "Access denied"
- 403 errors

**Diagnosis:**
```bash
# Check service account permissions
gcloud batch jobs describe <BATCH_JOB_NAME> --format=json | jq '.taskGroups[0].taskSpec.serviceAccount'

# Test bucket access
gsutil ls gs://<bucket>/ 2>&1 | head -5
```

---

### Step 7: Propose Solution

Based on diagnosis, recommend one of:

| Issue | Solution Template |
|-------|-------------------|
| **OOM** | "Increase memory from X to Y in the runtime block" |
| **Disk full** | "Increase disk size from X to Y GB" |
| **Missing input** | "Input file doesn't exist. Verify path: `gsutil ls <path>`" |
| **Permission** | "Service account lacks access. Grant `roles/storage.objectViewer` on bucket" |
| **Timeout** | "Task exceeded time limit. Increase `maxRetries` or optimize task" |
| **Docker** | "Image pull failed. Verify image exists and is accessible" |

**Re-run after fixing:**
```bash
wb workflow job run --workflow=<WORKFLOW_ID> --inputs=<INPUTS_JSON>
```

---

## Quick Reference

### Essential Commands

```bash
# Failed jobs
wb workflow job list --format=json | jq '.[] | select(.status=="FAILED") | {id, workflowName}'

# Job error
wb workflow job describe --job=<ID> --format=json | jq '.failureMessage'

# Failed tasks
wb workflow job task list --job=<ID> --format=json | jq '.[] | select(.status=="FAILED") | .name'

# Task logs
wb workflow job task describe --job=<ID> --task=<TASK> --format=json | jq '.stderr' | xargs -I{} gsutil cat {} | tail -50

# Memory check
gcloud batch jobs describe <BATCH_JOB> --format=json | jq '.taskGroups[0].taskSpec.computeResource'
```

### Error → Cause → Fix

| Exit Code | Meaning | Common Fix |
|-----------|---------|------------|
| 1 | General error | Check stderr for details |
| 2 | Misuse of command | Check script syntax |
| 126 | Permission problem | Check file permissions |
| 127 | Command not found | Check PATH, container image |
| 137 | SIGKILL (OOM) | **Increase memory** |
| 139 | Segfault | Check input data, memory |
| 143 | SIGTERM | Task timeout or preemption |

---

## Workbench-Specific Notes

- **Log retention:** Cromwell logs persist in workspace execution bucket
- **Batch jobs:** Each sub-job has independent logs; troubleshoot specific failed sub-job
- **VPC-SC:** Run `gcloud batch` commands from within workspace app
- **Preemption:** If using spot VMs, set `preemptible: 0` for reliability
