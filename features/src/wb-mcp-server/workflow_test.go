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

func argsEqual(a, b []string) bool {
	return strings.Join(a, "\x00") == strings.Join(b, "\x00")
}

func TestWorkflowJobRunArgs(t *testing.T) {
	required := map[string]interface{}{"workspaceId": "ws", "workflowId": "wf", "outputBucketId": "out"}
	with := func(extra map[string]interface{}) map[string]interface{} {
		m := map[string]interface{}{}
		for k, v := range required {
			m[k] = v
		}
		for k, v := range extra {
			m[k] = v
		}
		return m
	}
	base := []string{"workflow", "job", "run", "--workspace=ws", "--workflow=wf", "--output-bucket-id=out"}

	t.Run("required only", func(t *testing.T) {
		got, err := workflowJobRunArgs(required)
		if err != nil || !argsEqual(got, base) {
			t.Fatalf("got %v, %v", got, err)
		}
	})
	t.Run("every optional field", func(t *testing.T) {
		got, err := workflowJobRunArgs(with(map[string]interface{}{
			"jobId": "j", "description": "d", "outputPath": "o/", "inputsUri": "gs://x/in.json",
			"profile": "gpu", "paramsFileBucketId": "cfg", "paramsFilePath": "p/params.yaml",
		}))
		want := append(append([]string{}, base...), "--job-id=j", "--description=d", "--output-path=o/",
			"--inputs-uri=gs://x/in.json", "--profile=gpu", "--params-file-bucket-id=cfg", "--params-file-path=p/params.yaml")
		if err != nil || !argsEqual(got, want) {
			t.Fatalf("got %v, %v", got, err)
		}
	})
	t.Run("inputs object", func(t *testing.T) {
		got, err := workflowJobRunArgs(with(map[string]interface{}{"inputs": map[string]interface{}{"a": 1.0}}))
		want := append(append([]string{}, base...), `--inputs={"a":1}`)
		if err != nil || !argsEqual(got, want) {
			t.Fatalf("got %v, %v", got, err)
		}
	})
	t.Run("empty inputs are no inputs", func(t *testing.T) {
		for _, empty := range []map[string]interface{}{{"inputs": map[string]interface{}{}}, {"inputs": `{}`},
			{"inputsUri": ""}, {"inputs": map[string]interface{}{}, "inputsUri": ""}} {
			got, err := workflowJobRunArgs(with(empty))
			if err != nil || !argsEqual(got, base) {
				t.Fatalf("%v: got %v, %v", empty, got, err)
			}
		}
	})
	t.Run("inputs as a JSON string", func(t *testing.T) {
		got, err := workflowJobRunArgs(with(map[string]interface{}{"inputs": `{"a": 1}`}))
		want := append(append([]string{}, base...), `--inputs={"a":1}`)
		if err != nil || !argsEqual(got, want) {
			t.Fatalf("got %v, %v", got, err)
		}
	})
	t.Run("inputs that are not an object", func(t *testing.T) {
		for _, bad := range []interface{}{`[1,2]`, `not json`, `null`, "7", []interface{}{"a"}, nil, 3.0, true} {
			got, err := workflowJobRunArgs(with(map[string]interface{}{"inputs": bad}))
			if err == nil || got != nil || !strings.Contains(err.Error(), "JSON object") {
				t.Fatalf("inputs %#v: got %v, %v", bad, got, err)
			}
		}
	})
	t.Run("empty inputs string means no inputs", func(t *testing.T) {
		got, err := workflowJobRunArgs(with(map[string]interface{}{"inputs": " "}))
		if err != nil || !argsEqual(got, base) {
			t.Fatalf("got %v, %v", got, err)
		}
	})
	t.Run("string fields that are not strings", func(t *testing.T) {
		for _, key := range []string{"inputsUri", "jobId", "outputPath", "description"} {
			for _, bad := range []interface{}{1.0, nil, map[string]interface{}{}, true} {
				got, err := workflowJobRunArgs(with(map[string]interface{}{key: bad}))
				if err == nil || got != nil || !strings.Contains(err.Error(), key+" must be a string") {
					t.Fatalf("%s %#v: got %v, %v", key, bad, got, err)
				}
			}
		}
	})
	t.Run("empty strings are absent", func(t *testing.T) {
		got, err := workflowJobRunArgs(with(map[string]interface{}{"jobId": "", "description": "", "outputPath": "", "inputsUri": ""}))
		if err != nil || !argsEqual(got, base) {
			t.Fatalf("got %v, %v", got, err)
		}
	})
	t.Run("params file needs both halves", func(t *testing.T) {
		for _, extra := range []map[string]interface{}{{"paramsFileBucketId": "cfg"}, {"paramsFilePath": "p.yaml"}} {
			got, err := workflowJobRunArgs(with(extra))
			if err == nil || got != nil || !strings.Contains(err.Error(), "both needed") {
				t.Fatalf("got %v, %v", got, err)
			}
		}
	})
	t.Run("inputs and inputsUri are exclusive", func(t *testing.T) {
		_, err := workflowJobRunArgs(with(map[string]interface{}{"inputs": map[string]interface{}{"a": 1.0}, "inputsUri": "gs://x/y"}))
		if err == nil {
			t.Fatal("expected an error")
		}
	})
	t.Run("missing required", func(t *testing.T) {
		if _, err := workflowJobRunArgs(map[string]interface{}{"workspaceId": "ws"}); err == nil {
			t.Fatal("expected an error")
		}
	})
}

func TestWorkflowCreateArgs(t *testing.T) {
	required := map[string]interface{}{"workspaceId": "ws", "workflowId": "wf", "bucketId": "b", "path": "p/main.nf"}
	base := []string{"workflow", "create", "--workspace=ws", "--workflow=wf", "--bucket-id=b", "--path=p/main.nf"}
	got, err := workflowCreateArgs(required)
	if err != nil || !argsEqual(got, base) {
		t.Fatalf("got %v, %v", got, err)
	}
	full := map[string]interface{}{"displayName": "N", "description": "D", "workflowType": "NEXTFLOW"}
	for k, v := range required {
		full[k] = v
	}
	got, err = workflowCreateArgs(full)
	want := append(append([]string{}, base...), "--display-name=N", "--description=D", "--workflow-type=NEXTFLOW")
	if err != nil || !argsEqual(got, want) {
		t.Fatalf("got %v, %v", got, err)
	}
	if _, err := workflowCreateArgs(map[string]interface{}{"workspaceId": "ws"}); err == nil {
		t.Fatal("expected an error")
	}
}

func TestWorkflowArgumentsTakeUUIDsTheCLIDoesNot(t *testing.T) {
	const ws = "44444444-4444-4444-8444-444444444444"
	const bucket = "55555555-5555-4555-8555-555555555555"
	dir := t.TempDir()
	script := `#!/bin/sh
case "$*" in
 'status --format=json') printf '%s' '{"workspace":{"id":"my-ws","uuid":"` + ws + `"}}' ;;
 'resource list --workspace=my-ws --format=json') printf '%s' '[{"id":"output","uuid":"` + bucket + `","bucketName":"acme-output"},{"id":"params","uuid":"66666666-6666-4666-8666-666666666666","bucketName":"acme-params"},{"id":"save-to-workbench","uuid":"88888888-8888-4888-8888-888888888888","bucketName":"acme-save-to-workbench"}]' ;;
 *) exit 99 ;;
esac
`
	if err := os.WriteFile(filepath.Join(dir, "wb"), []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir+string(os.PathListSeparator)+os.Getenv("PATH"))
	clearToolResultCache()
	cacheMu.Lock()
	delete(workspaceIdCache, "my-ws")
	cacheMu.Unlock()

	given := map[string]interface{}{"workspaceId": ws, "workflowId": "wf", "outputBucketId": bucket,
		"paramsFileBucketId": "66666666-6666-4666-8666-666666666666", "paramsFilePath": "p.yaml"}
	args, err := workflowJobRunArgs(withCLIIDs(given, "outputBucketId", "paramsFileBucketId"))
	if err != nil {
		t.Fatal(err)
	}
	want := "workflow job run --workspace=my-ws --workflow=wf --output-bucket-id=output --params-file-bucket-id=params --params-file-path=p.yaml"
	if got := strings.Join(args, " "); got != want {
		t.Fatalf("got  %s\nwant %s", got, want)
	}
	if given["workspaceId"] != ws {
		t.Fatal("the caller's arguments were changed")
	}
	// The tools that take only a workspace (workflow_list, workflow_describe, ...) convert it too.
	if got := withCLIIDs(map[string]interface{}{"workspaceId": ws, "jobId": "j"}); got["workspaceId"] != "my-ws" || got["jobId"] != "j" {
		t.Fatalf("workspace not converted: %v", got)
	}
	// IDs pass through untouched, and a UUID nothing matches is left for the CLI to refuse.
	same := withCLIIDs(map[string]interface{}{"workspaceId": "my-ws", "outputBucketId": "output"}, "outputBucketId")
	if same["workspaceId"] != "my-ws" || same["outputBucketId"] != "output" {
		t.Fatalf("IDs changed: %v", same)
	}
	// The cloud bucket name, with or without gs:// and a trailing slash, names its resource; a
	// hyphenated resource ID that is no bucket's name passes through.
	for given, want := range map[string]string{
		"gs://acme-output": "output", "gs://acme-params/": "params",
		"acme-output": "output", "save-to-workbench": "save-to-workbench",
		"gs://elsewhere-bucket": "gs://elsewhere-bucket",
	} {
		got := withCLIIDs(map[string]interface{}{"workspaceId": "my-ws", "outputBucketId": given}, "outputBucketId")
		if got["outputBucketId"] != want {
			t.Errorf("%s: got %v, want %s", given, got["outputBucketId"], want)
		}
	}
	unknown := "77777777-7777-4777-8777-777777777777"
	if got := withCLIIDs(map[string]interface{}{"workspaceId": "my-ws", "bucketId": unknown}, "bucketId"); got["bucketId"] != unknown {
		t.Fatalf("an unknown UUID changed: %v", got)
	}
}
