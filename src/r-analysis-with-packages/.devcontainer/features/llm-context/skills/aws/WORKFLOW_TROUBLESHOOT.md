# WDL Workflow Troubleshooting Skill (AWS)

**Trigger:** User asks to troubleshoot, debug, or fix a failed workflow.

## Behavior

**Once the user confirms which job to investigate, DO NOT ask which diagnostic steps to run.** Instead:
1. **Run all diagnostic commands automatically** (Steps 2–4 at minimum)
2. **Analyze the results** and identify the root cause
3. **Report your diagnosis** with evidence (error messages, exit codes, log snippets)
4. **Propose a fix** with specific changes
5. **THEN ask** if they want you to apply the fix or investigate further

Don't say: "Would you like me to check the logs?"
Do say: "I checked the logs and found an OOM error. The task requested 8GB but needed more. I recommend increasing memory to 16GB in the runtime block."

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
wb workflow job list --format=json | jq '.[] | select(.status == "FAILED") | {id, workflowName, status, startTime, endTime}'
```

**For batch jobs:**
```bash
wb workflow job batch list --job=<JOB_ID> --format=json | jq '.[] | select(.status == "FAILED") | {id, status}'
```

**Ask user:** Confirm which job ID to investigate (if multiple failed jobs).

---

### Step 2: Get Job Details & Inputs

```bash
wb workflow job describe --job=<JOB_ID> --format=json
```

**Key fields to extract:**
```bash
wb workflow job describe --job=<JOB_ID> --format=json | jq -r '.failureMessage'
wb workflow job describe --job=<JOB_ID> --format=json | jq '.inputs'
wb workflow job describe --job=<JOB_ID> --format=json | jq '.outputs'
```

---

### Step 3: Find Failed Task & Get Logs

```bash
wb workflow job task list --job=<JOB_ID> --format=json | jq '.[] | {name, status, exitCode}'
wb workflow job task describe --job=<JOB_ID> --task=<TASK_NAME> --format=json
```

**Extract log URLs:**
```bash
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
# Read stderr (usually contains errors) — logs are in S3
aws s3 cp "$STDERR_URL" - 2>/dev/null | tail -100

# Read stdout
aws s3 cp "$STDOUT_URL" - 2>/dev/null | tail -100

# Search for common error patterns
aws s3 cp "$STDERR_URL" - 2>/dev/null | grep -i -E "error|exception|failed|denied|killed|oom|memory|disk|timeout" | head -30
```

#### Common Log File Patterns

Cromwell execution logs are typically at:
```
s3://<execution-bucket>/<workflow-id>/<call-name>/execution/
├── stdout          # Task standard output
├── stderr          # Task standard error
├── script          # The actual command that ran
├── rc              # Return code (exit code)
└── script.submit   # Submission script
```

**One-liner to read all execution files:**
```bash
EXEC_DIR=$(echo $TASK_INFO | jq -r '.executionDirectory // empty')
if [ -n "$EXEC_DIR" ]; then
  echo "=== script ===" && aws s3 cp "$EXEC_DIR/script" - 2>/dev/null
  echo "=== rc ===" && aws s3 cp "$EXEC_DIR/rc" - 2>/dev/null
  echo "=== stderr (last 50 lines) ===" && aws s3 cp "$EXEC_DIR/stderr" - 2>/dev/null | tail -50
fi
```

---

### Step 5: Check Resource Allocation & Usage

#### What Was Requested (from WDL runtime)

```bash
wb workflow describe --workflow=<WORKFLOW_ID> --format=json | jq '.sourceUrl'

# Read WDL file
aws s3 cp s3://<bucket>/<path>/workflow.wdl - | grep -A10 "runtime {"
```

#### Check Actual Resource Usage (AWS Batch)

```bash
# List failed AWS Batch jobs
aws batch list-jobs --job-queue <QUEUE_NAME> --job-status FAILED \
  --query 'jobSummaryList[*].{id:jobId,name:jobName,status:status}' --output table

# Describe specific batch job
aws batch describe-jobs --jobs <JOB_ID> | jq '.jobs[0] | {
  status: .status,
  statusReason: .statusReason,
  container: .container.resourceRequirements
}'
```

#### Memory-Specific Checks

```bash
# Check if OOM killed the task
aws s3 cp "$STDERR_URL" - 2>/dev/null | grep -i -E "oom|out of memory|killed|cannot allocate|memory"

# Check what memory was requested in the batch job
aws batch describe-jobs --jobs <JOB_ID> | jq '.jobs[0].container.resourceRequirements[] | select(.type=="MEMORY")'

# Check for OOM kill signal in stderr
aws s3 cp "$STDERR_URL" - 2>/dev/null | grep -i "killed process"
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
aws batch describe-jobs --jobs <JOB_ID> | jq '.jobs[0].container.resourceRequirements'
aws s3 cp "$STDERR_URL" - 2>/dev/null | grep -i -E "memory|oom|killed|malloc"
```

**Fix:** Increase `memory` in WDL runtime block:
```wdl
runtime {
  memory: "32G"
}
```

#### Disk Issues

**Symptoms:**
- "No space left on device"
- "Disk quota exceeded"

**Diagnosis:**
```bash
aws s3 cp "$STDERR_URL" - 2>/dev/null | grep -i -E "space|disk|quota"
```

**Fix:** Increase disk in WDL runtime:
```wdl
runtime {
  disks: "local-disk 200 SSD"
}
```

#### Input File Issues

**Symptoms:**
- "FileNotFoundException"
- "Localization failed"
- File not found errors

**Diagnosis:**
```bash
wb workflow job describe --job=<JOB_ID> --format=json | jq -r '.inputs | to_entries[] | .value' | while read path; do
  if [[ $path == s3://* ]]; then
    echo -n "$path: " && aws s3 ls "$path" 2>&1 | head -1
  fi
done
```

#### Permission Issues

**Symptoms:**
- "Permission denied" / "Access denied" / 403 errors

**Diagnosis:**
```bash
# Check IAM role attached to batch job
aws batch describe-jobs --jobs <JOB_ID> | jq '.jobs[0].jobDefinition'

# Test bucket access
aws s3 ls s3://<bucket>/ 2>&1 | head -5
```

---

### Step 7: Propose Solution

| Issue | Solution Template |
|-------|-------------------|
| **OOM** | "Increase memory from X to Y in the runtime block" |
| **Disk full** | "Increase disk size from X to Y GB" |
| **Missing input** | "Input file doesn't exist. Verify path: `aws s3 ls <path>`" |
| **Permission** | "IAM role lacks S3 access. Grant `s3:GetObject` on the bucket" |
| **Timeout** | "Task exceeded time limit. Increase `maxRetries` or optimize task" |
| **Docker** | "Image pull failed. Verify image exists and is accessible" |
| **Other** | Describe the root cause from logs and propose a fix based on the specific error |

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

# Task logs (S3)
wb workflow job task describe --job=<ID> --task=<TASK> --format=json | jq -r '.stderr' | xargs -I{} aws s3 cp {} - | tail -50

# Memory check (AWS Batch)
aws batch describe-jobs --jobs <JOB_ID> | jq '.jobs[0].container.resourceRequirements'
```

### Error -> Cause -> Fix

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

- **Log retention:** Cromwell logs persist in workspace execution bucket (S3)
- **Batch jobs:** Each sub-job has independent logs; troubleshoot specific failed sub-job
- **Preemption:** If using spot instances, set `preemptible: 0` for reliability
