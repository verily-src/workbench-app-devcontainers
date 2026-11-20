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
	oldWait, oldRemember, oldTimeout := submitWait, submitRemember, submitTimeout
	t.Cleanup(func() { submitWait, submitRemember, submitTimeout = oldWait, oldRemember, oldTimeout })
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

func TestTheRunKeyLeavesOutTheDescriptionAndIncludesAnExplicitJobID(t *testing.T) {
	a, b := runArgs("one"), runArgs("two")
	if submissionKey(a) != submissionKey(b) {
		t.Fatal("description changed the run key")
	}
	b["jobId"] = ""
	if submissionKey(a) != submissionKey(b) {
		t.Fatal("an empty job ID changed the run key")
	}
	b["jobId"] = "my-job"
	if submissionKey(a) == submissionKey(b) {
		t.Fatal("an explicit job ID did not change the run key")
	}
	a["jobId"] = "my-job"
	if submissionKey(a) != submissionKey(b) {
		t.Fatal("the same job ID made different run keys")
	}
	b["profile"] = "test"
	if submissionKey(a) == submissionKey(b) {
		t.Fatal("a different profile made the same run key")
	}
}

func TestARunningSubmissionIsNotPrunedAfterTheRememberWindow(t *testing.T) {
	_, submitted := slowSubmitWb(t, "1", false)
	submitWait = 100 * time.Millisecond
	submitRemember = 200 * time.Millisecond
	all, _ := parseToolsets("all")

	callEnabledTool(CallToolParams{Name: "workflow_job_run", Arguments: runArgs("a")}, all)
	time.Sleep(400 * time.Millisecond) // past the window, still running
	r := callEnabledTool(CallToolParams{Name: "workflow_job_run", Arguments: runArgs("b")}, all)
	if !strings.Contains(r.Content[0].Text, "still being submitted") {
		t.Fatalf("retry past the window = %q", r.Content[0].Text)
	}
	time.Sleep(1200 * time.Millisecond) // finished, and older than the window
	if n := submitted(); n != 1 {
		t.Fatalf("submitted %d times, want 1", n)
	}
	submissionsMu.Lock()
	n := len(submissions)
	submissionsMu.Unlock()
	if n != 1 {
		t.Fatalf("%d entries before the next call, want 1", n)
	}
	submitWait = 5 * time.Second
	callEnabledTool(CallToolParams{Name: "workflow_job_run", Arguments: runArgs("c")}, all)
	if n := submitted(); n != 2 {
		t.Fatalf("submitted %d times, want 2 (a finished submission is forgotten after the window)", n)
	}
}

func TestASubmissionIsStoppedAfterTheTimeout(t *testing.T) {
	_, submitted := slowSubmitWb(t, "30", false)
	submitWait = 30 * time.Second // outlasts the timeout and the wait for wb's children
	submitTimeout = 300 * time.Millisecond
	all, _ := parseToolsets("all")

	start := time.Now()
	r := callEnabledTool(CallToolParams{Name: "workflow_job_run", Arguments: runArgs("x")}, all)
	if !r.IsError || !strings.Contains(r.Content[0].Text, "stopped after") && !strings.Contains(r.Content[0].Text, "signal") {
		t.Fatalf("result = %+v, want a failure after the timeout", r)
	}
	if time.Since(start) > 15*time.Second {
		t.Fatalf("took %s, the timeout did not stop wb", time.Since(start))
	}
	// A timed-out submission counts as failed and may be retried.
	callEnabledTool(CallToolParams{Name: "workflow_job_run", Arguments: runArgs("x")}, all)
	if n := submitted(); n != 2 {
		t.Fatalf("submitted %d times, want 2", n)
	}
}

func TestJobIDDecidesWhetherARepeatedRunIsSubmittedAgain(t *testing.T) {
	_, submitted := slowSubmitWb(t, "0", false)
	submitWait = 5 * time.Second
	all, _ := parseToolsets("all")
	run := func(jobID string) {
		args := runArgs("x")
		if jobID != "" {
			args["jobId"] = jobID
		}
		callEnabledTool(CallToolParams{Name: "workflow_job_run", Arguments: args}, all)
	}

	run("job-a")
	run("job-a")
	if n := submitted(); n != 1 {
		t.Fatalf("same explicit job ID twice: submitted %d times, want 1", n)
	}
	run("job-b")
	if n := submitted(); n != 2 {
		t.Fatalf("different explicit job ID: submitted %d times, want 2", n)
	}
	run("")
	run("")
	if n := submitted(); n != 3 {
		t.Fatalf("no job ID twice: submitted %d times, want 3 (one more)", n)
	}
}
