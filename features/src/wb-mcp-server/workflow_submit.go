package main

import (
	"context"
	"encoding/json"
	"fmt"
	"sync"
	"time"
)

// workflow_job_run, submitted once. The CLI took up to 85 s to submit a job, past OpenCode's 60 s
// call timeout; the agent saw a timeout, called again with a new description, and the same
// pipeline ran twice. So a submission runs in the background: a call answers within submitWait,
// and the same run asked for again (same workflow, inputs, params file, profile, outputs and job
// ID if one is given; the description aside) within submitRemember waits on the first submission or gets its
// answer, and is not submitted again. A submission that failed may be retried at once. A submission
// that runs longer than submitTimeout is stopped and counts as failed. An entry is forgotten
// submitRemember after it started, but only once its submission has finished.

var (
	submitWait     = 40 * time.Second
	submitRemember = 15 * time.Minute
	submitTimeout  = 10 * time.Minute
)

type submission struct {
	done    chan struct{}
	output  string
	err     error
	started time.Time
}

var (
	submissionsMu sync.Mutex
	submissions   = map[string]*submission{}
)

// submissionKey identifies a run by what it computes and where it writes, and by the job ID when
// the caller sets one.
func submissionKey(arguments map[string]interface{}) string {
	key := map[string]interface{}{}
	for _, name := range []string{"workspaceId", "workflowId", "outputBucketId", "outputPath", "inputs",
		"inputsUri", "profile", "paramsFileBucketId", "paramsFilePath"} {
		if v, ok := arguments[name]; ok {
			key[name] = v
		}
	}
	if id, ok := arguments["jobId"].(string); ok && id != "" {
		key["jobId"] = id
	}
	encoded, _ := json.Marshal(key) // map keys are sorted
	return string(encoded)
}

// submitWorkflowJob runs `wb workflow job run` with args once per run (submissionKey).
func submitWorkflowJob(arguments map[string]interface{}, args []string) (string, error) {
	key := submissionKey(arguments)
	submissionsMu.Lock()
	for k, s := range submissions {
		select {
		case <-s.done:
			if time.Since(s.started) > submitRemember {
				delete(submissions, k)
			}
		default: // still running: a retry must wait on it, not start another
		}
	}
	s, repeat := submissions[key]
	if !repeat {
		s = &submission{done: make(chan struct{}), started: time.Now()}
		submissions[key] = s
		go func() {
			ctx, cancel := context.WithTimeout(context.Background(), submitTimeout)
			defer cancel()
			s.output, s.err = executeWbCommandContext(ctx, args)
			if s.err != nil && ctx.Err() == context.DeadlineExceeded {
				s.err = fmt.Errorf("submission stopped after %s: %w", submitTimeout, s.err)
			}
			if s.err != nil {
				submissionsMu.Lock()
				if submissions[key] == s {
					delete(submissions, key)
				}
				submissionsMu.Unlock()
			}
			close(s.done)
		}()
	}
	submissionsMu.Unlock()

	select {
	case <-s.done:
		if repeat && s.err == nil {
			return fmt.Sprintf("Not submitted again: the same run (workflow, inputs, params file, profile and "+
				"outputs) was submitted %s ago. That submission's answer:\n%s",
				time.Since(s.started).Round(time.Second), s.output), nil
		}
		return s.output, s.err
	case <-time.After(submitWait):
		return fmt.Sprintf("The run is still being submitted (started %s ago; submitting can take over a "+
			"minute). Do not call workflow_job_run again: check workflow_job_list in a minute, which will "+
			"show the run.", time.Since(s.started).Round(time.Second)), nil
	}
}
