package main

import (
	"fmt"
	"strconv"
)

// workflow_job_describe and workflow_job_list from the workflow manager's API, the one the
// workflow diagnostics call: about 3 s, against 11 s and 9 s for `wb workflow job describe` and
// `list`, which an agent following a run calls again and again. On any error they fall back to
// the CLI.

var (
	runDescribe = workflowDiagnostic{
		tool: Tool{Name: "workflow_job_describe", InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"workspaceId": map[string]interface{}{"type": "string", "format": "uuid"},
				"runId":       map[string]interface{}{"type": "string", "format": "uuid"},
			},
			Required: []string{"workspaceId", "runId"},
		}},
		method: "GET",
		path:   "/api/runs/v1/{runId}",
	}
	runList = workflowDiagnostic{
		tool: Tool{Name: "workflow_job_list", InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"workspaceId": map[string]interface{}{"type": "string", "format": "uuid"},
				"limit":       map[string]interface{}{"type": "integer", "minimum": 1, "maximum": 1000},
			},
			Required: []string{"workspaceId"},
		}},
		method: "GET",
		path:   "/api/runs/v1",
	}
	// runListLimit is how many of the newest runs workflow_job_list returns unless asked for more or fewer.
	runListLimit = 10
)

// runListLimitArg is the limit argument of workflow_job_list, checked against the Workflow API's
// bounds.
func runListLimitArg(arguments map[string]interface{}) (int, error) {
	value, ok := arguments["limit"]
	if !ok {
		return runListLimit, nil
	}
	text, err := workflowArgument(value, runList.tool.InputSchema.Properties["limit"].(map[string]interface{}))
	if err != nil {
		return 0, fmt.Errorf("limit %w", err)
	}
	return strconv.Atoi(text)
}

// describeRun is one run (a job), by workspace (ID or UUID) and job ID.
func describeRun(workspace, jobID string) (string, error) {
	uuid, err := resolveWorkspaceId(workspace)
	if err == nil {
		var out []byte
		if out, err = callWorkflowDiagnostic(runDescribe, map[string]interface{}{"workspaceId": uuid, "runId": jobID}); err == nil {
			return string(out), nil
		}
	}
	return executeWbCommand([]string{"workflow", "job", "describe", "--workspace=" + cliWorkspaceID(workspace), "--job-id=" + jobID})
}

// listRuns is the current workspace's newest runs, up to limit.
func listRuns(limit int) (string, error) {
	uuid, err := getCurrentWorkspaceUUID()
	if err == nil {
		var out []byte
		if out, err = callWorkflowDiagnostic(runList, map[string]interface{}{"workspaceId": uuid, "limit": float64(limit)}); err == nil {
			return string(out), nil
		}
	}
	return executeWbCommand([]string{"workflow", "job", "list", "--limit=" + strconv.Itoa(limit)})
}
