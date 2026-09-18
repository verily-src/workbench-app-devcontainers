package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const testWorkspace = "11111111-1111-4111-8111-111111111111"
const testRun = "22222222-2222-4222-8222-222222222222"
const testTask = "33333333-3333-4333-8333-333333333333"

type workflowTransport func(*http.Request) (*http.Response, error)

func (f workflowTransport) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }
func fakeWorkflowCLI(t *testing.T) {
	t.Helper()
	dir := t.TempDir()
	script := `#!/bin/sh
case "$*" in
 'auth print-access-token') printf '%s' 'test-token' ;;
 *) exit 99 ;;
esac
`
	if err := os.WriteFile(filepath.Join(dir, "wb"), []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir+string(os.PathListSeparator)+os.Getenv("PATH"))
	t.Setenv("WORKBENCH_CONTEXT_PARENT_DIR", dir)
	if err := os.Mkdir(filepath.Join(dir, ".workbench"), 0700); err != nil {
		t.Fatal(err)
	}
	setWorkflowContext(t, `{"server":{"workflowManagerUri":"https://workflow.test/custom"}}`)
	old := httpClient
	t.Cleanup(func() { httpClient = old })
}
func TestWorkflowDiagnosticRequests(t *testing.T) {
	fakeWorkflowCLI(t)
	tests := []struct {
		name, path, extra string
		post              bool
	}{
		{"workflow_inputs_get", "/api/workflows/v1/" + testRun + "/inputs", `"workflowId":"` + testRun + `"`, false},
		{"workflow_task_list", "/api/runs/v1/" + testRun + "/tasks", `"runId":"` + testRun + `","status":"FAILED","limit":25,"pageToken":"a+/=&?","search":"hello & world","sortField":"status","sortDirection":"ASC","startTime":"2026-09-01T00:00:00Z","endTime":"2026-09-02T00:00:00Z"`, false},
		{"workflow_task_get", "/api/runs/v1/tasks/" + testTask, `"taskId":"` + testTask + `"`, false},
		{"workflow_run_logs", "/api/runs/v1/" + testRun + "/logs", `"runId":"` + testRun + `","taskId":"` + testTask + `","limit":25,"pageToken":"a+/=&?"`, false},
		{"workflow_run_trace", "/api/runs/v1/" + testRun + "/trace", `"runId":"` + testRun + `"`, false},
		{"workflow_run_costs", "/api/runs/v1/costs", `"runIds":["` + testRun + `"]`, true},
		{"workflow_batch_status_counts", "/api/runs/v1/" + testRun + "/statusCounts", `"runId":"` + testRun + `"`, false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var args map[string]interface{}
			if err := json.Unmarshal([]byte(`{"workspaceId":"`+testWorkspace+`",`+tt.extra+`}`), &args); err != nil {
				t.Fatal(err)
			}
			calls := 0
			httpClient = &http.Client{Transport: workflowTransport(func(r *http.Request) (*http.Response, error) {
				calls++
				method := "GET"
				if tt.post {
					method = "POST"
				}
				if r.Method != method || r.URL.Host != "workflow.test" || r.URL.Path != "/custom"+tt.path {
					t.Errorf("unexpected request: %s %s", r.Method, r.URL)
				}
				if r.Header.Get("Authorization") != "Bearer test-token" {
					t.Error("missing authentication")
				}
				for key, value := range args {
					if key == "runIds" || strings.Contains(tt.path, fmt.Sprint(value)) {
						continue
					}
					if got := r.URL.Query().Get(key); got != fmt.Sprint(value) {
						t.Errorf("%s: got %q want %v", key, got, value)
					}
				}
				if tt.post {
					b, err := io.ReadAll(r.Body)
					if err != nil {
						t.Fatal(err)
					}
					if string(b) != `{"runIds":["`+testRun+`"]}` {
						t.Errorf("wrong cost body: %s", b)
					}
				} else if r.Body != nil {
					t.Error("GET has body")
				}
				return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(`{"nextPageToken":"next","items":[]}`)), Header: http.Header{}}, nil
			})}
			r := handleCallTool(CallToolParams{Name: tt.name, Arguments: args})
			if r.IsError || calls != 1 || r.Content[0].Text != `{"nextPageToken":"next","items":[]}` {
				t.Fatalf("calls=%d result=%+v", calls, r)
			}
		})
	}
}
func TestWorkflowValidationAndErrors(t *testing.T) {
	fakeWorkflowCLI(t)
	calls := 0
	httpClient = &http.Client{Transport: workflowTransport(func(r *http.Request) (*http.Response, error) {
		calls++
		return &http.Response{StatusCode: 403, Body: io.NopCloser(strings.NewReader("denied")), Header: http.Header{}}, nil
	})}
	tests := []struct{ name, extra string }{
		{"workflow_run_logs", `"runId":"bad"`},
		{"workflow_run_logs", `"runId":"` + testRun + `","limit":1.5`},
		{"workflow_run_logs", `"runId":"` + testRun + `","limit":0`},
		{"workflow_run_logs", `"runId":"` + testRun + `","bogus":true`},
		{"workflow_run_logs", `"runId":"` + testRun + `","taskId":null`},
		{"workflow_task_list", `"runId":"` + testRun + `","status":"UNKNOWN"`},
		{"workflow_task_list", `"runId":"` + testRun + `","startTime":"yesterday"`},
		{"workflow_task_list", `"runId":"` + testRun + `","sortDirection":"sideways"`},
	}
	for _, tt := range tests {
		var args map[string]interface{}
		_ = json.Unmarshal([]byte(`{"workspaceId":"`+testWorkspace+`",`+tt.extra+`}`), &args)
		if r := handleCallTool(CallToolParams{Name: tt.name, Arguments: args}); !r.IsError {
			t.Fatalf("accepted invalid args: %s", tt.extra)
		}
	}
	for _, ids := range []interface{}{[]interface{}{}, []interface{}{"bad"}, make([]interface{}, 1001), "not-an-array"} {
		if r := handleCallTool(CallToolParams{Name: "workflow_run_costs", Arguments: map[string]interface{}{"workspaceId": testWorkspace, "runIds": ids}}); !r.IsError {
			t.Fatal("accepted invalid runIds")
		}
	}
	if r := handleCallTool(CallToolParams{Name: "workflow_run_trace"}); !r.IsError {
		t.Fatal("accepted missing args")
	}
	if calls != 0 {
		t.Fatal("invalid arguments reached HTTP")
	}
	args := map[string]interface{}{"workspaceId": testWorkspace, "runId": testRun}
	r := handleCallTool(CallToolParams{Name: "workflow_run_trace", Arguments: args})
	if !r.IsError || !strings.Contains(r.Content[0].Text, "403") || !strings.Contains(r.Content[0].Text, "denied") {
		t.Fatalf("lost backend error: %+v", r)
	}
	for _, status := range []string{`{}`, `not-json`, `{"server":{"workflowManagerUri":"file:///tmp/test"}}`} {
		setWorkflowContext(t, status)
		if r := handleCallTool(CallToolParams{Name: "workflow_run_trace", Arguments: args}); !r.IsError {
			t.Fatal("accepted invalid status")
		}
	}
	if calls != 1 {
		t.Fatal("invalid config reached HTTP")
	}
}
func TestWorkflowToolsRegistered(t *testing.T) {
	counts := map[string]int{}
	for _, tool := range wbTools {
		counts[tool.Name]++
	}
	for _, d := range workflowDiagnostics {
		if counts[d.tool.Name] != 1 {
			t.Errorf("%s registered %d times", d.tool.Name, counts[d.tool.Name])
		}
	}
}

func setWorkflowContext(t *testing.T, content string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(os.Getenv("WORKBENCH_CONTEXT_PARENT_DIR"), ".workbench", "context.json"), []byte(content), 0600); err != nil {
		t.Fatal(err)
	}
}

func TestWorkflowContextReloadAndTransportErrors(t *testing.T) {
	fakeWorkflowCLI(t)
	args := map[string]interface{}{"workspaceId": testWorkspace, "runId": testRun}
	httpClient = &http.Client{Transport: workflowTransport(func(r *http.Request) (*http.Response, error) {
		if r.URL.Host != "changed.test" {
			t.Errorf("stale host: %s", r.URL.Host)
		}
		return nil, fmt.Errorf("test connection failure")
	})}
	setWorkflowContext(t, `{"server":{"workflowManagerUri":"https://changed.test/api/workflow"}}`)
	r := handleCallTool(CallToolParams{Name: "workflow_run_trace", Arguments: args})
	if !r.IsError || !strings.Contains(r.Content[0].Text, "test connection failure") {
		t.Fatalf("lost transport error: %+v", r)
	}
	setWorkflowContext(t, `{"server":{"workflowManagerUri":"https://changed.test/api/workflow","iapAudience":"test-audience"}}`)
	r = handleCallTool(CallToolParams{Name: "workflow_run_trace", Arguments: args})
	if !r.IsError || !strings.Contains(r.Content[0].Text, "IAP") {
		t.Fatalf("missing IAP limitation: %+v", r)
	}
	if err := os.Remove(filepath.Join(os.Getenv("WORKBENCH_CONTEXT_PARENT_DIR"), ".workbench", "context.json")); err != nil {
		t.Fatal(err)
	}
	r = handleCallTool(CallToolParams{Name: "workflow_run_trace", Arguments: args})
	if !r.IsError || !strings.Contains(r.Content[0].Text, "cannot read Workbench context") {
		t.Fatalf("missing context accepted: %+v", r)
	}
}

func TestWorkflowTaskListLimit(t *testing.T) {
	fakeWorkflowCLI(t)
	calls := 0
	httpClient = &http.Client{Transport: workflowTransport(func(r *http.Request) (*http.Response, error) {
		calls++
		if got := r.URL.Query().Get("limit"); got != "1000" {
			t.Errorf("limit = %q, want 1000", got)
		}
		return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(`{"tasks":[]}`)), Header: http.Header{}}, nil
	})}
	for _, tool := range wbTools {
		if tool.Name == "workflow_task_list" {
			if got := tool.InputSchema.Properties["limit"].(map[string]interface{})["maximum"]; got != 1000 {
				t.Fatalf("advertised maximum = %v, want 1000", got)
			}
		}
	}
	for _, limit := range []float64{1000, 1001, 5000} {
		t.Run(fmt.Sprint(limit), func(t *testing.T) {
			before := calls
			result := handleCallTool(CallToolParams{Name: "workflow_task_list", Arguments: map[string]interface{}{
				"workspaceId": testWorkspace, "runId": testRun, "limit": limit,
			}})
			if limit == 1000 {
				if result.IsError || calls != before+1 {
					t.Fatalf("valid boundary rejected: %+v", result)
				}
			} else {
				if !result.IsError || calls != before || !strings.Contains(result.Content[0].Text, "at most 1000") {
					t.Fatalf("limit %v was not rejected locally: %+v", limit, result)
				}
			}
		})
	}
}

func TestWorkflowArgumentUsesSchemaBounds(t *testing.T) {
	schema := map[string]interface{}{"type": "integer", "minimum": 2, "maximum": 5}
	for _, value := range []float64{1, 2, 5, 6} {
		_, err := workflowArgument(value, schema)
		wantError := value < 2 || value > 5
		if (err != nil) != wantError {
			t.Errorf("value %v: error = %v, wantError = %v", value, err, wantError)
		}
	}
}
