package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// slowSubmitWb is a wb whose `workflow job run` takes delay and logs each submission.
func slowSubmitWb(t *testing.T, delay string, fail bool) (dir string, submitted func() int) {
	t.Helper()
	exit := "0"
	if fail {
		exit = "1"
	}
	dir = fakeWb(t, `case "$*" in
 'workflow job run'*) echo "$*" >> "$WORKBENCH_CONTEXT_PARENT_DIR/submitted"; sleep `+delay+`; echo "Job submitted: run-1"; exit `+exit+` ;;
esac
`)
	submissionsMu.Lock()
	submissions = map[string]*submission{}
	submissionsMu.Unlock()
	oldWait := submitWait
	t.Cleanup(func() { submitWait = oldWait })
	return dir, func() int {
		data, _ := os.ReadFile(filepath.Join(dir, "submitted"))
		return strings.Count(string(data), "\n")
	}
}

func runArgs(description string) map[string]interface{} {
	return map[string]interface{}{"workspaceId": "ws-a", "workflowId": "nf-core-sarek", "outputBucketId": "out",
		"paramsFileBucketId": "out", "paramsFilePath": "cohort/params.yaml", "profile": "gpu", "description": description}
}

func TestASlowSubmissionAnswersInTimeAndARetryDoesNotSubmitAgain(t *testing.T) {
	_, submitted := slowSubmitWb(t, "1", false)
	submitWait = 200 * time.Millisecond
	all, _ := parseToolsets("all")

	first := callEnabledTool(CallToolParams{Name: "workflow_job_run", Arguments: runArgs("Variant calling")}, all)
	if first.IsError || !strings.Contains(first.Content[0].Text, "still being submitted") {
		t.Fatalf("first call = %+v, want an answer before the submission finishes", first)
	}
	// The agent retries with a new description while the first submission runs.
	again := callEnabledTool(CallToolParams{Name: "workflow_job_run", Arguments: runArgs("Variant calling v2")}, all)
	if !strings.Contains(again.Content[0].Text, "still being submitted") {
		t.Fatalf("retry during the submission = %q", again.Content[0].Text)
	}
	time.Sleep(1500 * time.Millisecond)
	after := callEnabledTool(CallToolParams{Name: "workflow_job_run", Arguments: runArgs("Variant calling v3")}, all)
	if !strings.Contains(after.Content[0].Text, "Not submitted again") || !strings.Contains(after.Content[0].Text, "run-1") {
		t.Fatalf("retry after the submission = %q, want the first answer", after.Content[0].Text)
	}
	if n := submitted(); n != 1 {
		t.Fatalf("submitted %d times, want 1", n)
	}

	// A different run is submitted.
	other := runArgs("other")
	other["paramsFilePath"] = "other/params.yaml"
	submitWait = 5 * time.Second
	if r := callEnabledTool(CallToolParams{Name: "workflow_job_run", Arguments: other}, all); !strings.Contains(r.Content[0].Text, "run-1") {
		t.Fatalf("a different run = %q", r.Content[0].Text)
	}
	if n := submitted(); n != 2 {
		t.Fatalf("submitted %d times, want 2", n)
	}
}

func TestAFailedSubmissionMayBeRetried(t *testing.T) {
	_, submitted := slowSubmitWb(t, "0", true)
	submitWait = 5 * time.Second
	all, _ := parseToolsets("all")
	for i := 0; i < 2; i++ {
		r := callEnabledTool(CallToolParams{Name: "workflow_job_run", Arguments: runArgs("x")}, all)
		if strings.Contains(r.Content[0].Text, "Not submitted again") {
			t.Fatalf("call %d after a failure was refused: %q", i, r.Content[0].Text)
		}
	}
	if n := submitted(); n != 2 {
		t.Fatalf("submitted %d times, want 2 (a failure is retried)", n)
	}
}

func TestTheRunKeyLeavesOutTheDescriptionAndJobID(t *testing.T) {
	a, b := runArgs("one"), runArgs("two")
	b["jobId"] = "my-job"
	if submissionKey(a) != submissionKey(b) {
		t.Fatal("description or job ID changed the run key")
	}
	b["profile"] = "test"
	if submissionKey(a) == submissionKey(b) {
		t.Fatal("a different profile made the same run key")
	}
}
