package main

import (
	"io"
	"net/http"
	"strings"
	"testing"
)

func TestRunDescribeAndListUseTheWorkflowAPI(t *testing.T) {
	fakeWorkflowCLI(t)
	setCurrentWorkspaceUUID(testWorkspace)
	var paths []string
	httpClient = &http.Client{Transport: workflowTransport(func(r *http.Request) (*http.Response, error) {
		paths = append(paths, r.Method+" "+r.URL.Path+"?"+r.URL.RawQuery)
		return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(`{"id":"run"}`)), Header: http.Header{}}, nil
	})}
	all, _ := parseToolsets("all")

	r := callEnabledTool(CallToolParams{Name: "workflow_job_describe", Arguments: map[string]interface{}{
		"workspaceId": testWorkspace, "jobId": testRun}}, all)
	if r.IsError || r.Content[0].Text != `{"id":"run"}` {
		t.Fatalf("describe = %+v", r)
	}
	r = callEnabledTool(CallToolParams{Name: "workflow_job_list"}, all)
	if r.IsError || r.Content[0].Text != `{"id":"run"}` {
		t.Fatalf("list = %+v", r)
	}
	want := []string{
		"GET /custom/api/runs/v1/" + testRun + "?workspaceId=" + testWorkspace,
		"GET /custom/api/runs/v1?limit=10&workspaceId=" + testWorkspace,
	}
	if strings.Join(paths, "\n") != strings.Join(want, "\n") {
		t.Fatalf("requests:\n%s\nwant:\n%s", strings.Join(paths, "\n"), strings.Join(want, "\n"))
	}
}

func TestRunDescribeFallsBackToTheCLI(t *testing.T) {
	// The API refuses; the CLI answers.
	dir := fakeWb(t, `case "$*" in
 'auth print-access-token') printf 'tok' ;;
 'workflow job describe'*) echo "cli: $*" ;;
esac
`)
	writeWorkspaceContext(t, dir, `{"server":{"name":"test","workflowManagerUri":"https://workflow.test/custom"},"workspace":{"uuid":"`+testWorkspace+`","userFacingId":"ws-a"}}`)
	syncWorkspaceContext()
	httpClient = &http.Client{Transport: workflowTransport(func(r *http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: 500, Body: io.NopCloser(strings.NewReader(`down`)), Header: http.Header{}}, nil
	})}
	all, _ := parseToolsets("all")
	r := callEnabledTool(CallToolParams{Name: "workflow_job_describe", Arguments: map[string]interface{}{
		"workspaceId": "ws-a", "jobId": "not-a-uuid"}}, all)
	if !strings.Contains(r.Content[0].Text, "cli: workflow job describe --workspace=ws-a --job-id=not-a-uuid") {
		t.Fatalf("describe = %q, want the CLI's answer", r.Content[0].Text)
	}
}

func TestWorkflowJobListLimit(t *testing.T) {
	fakeWorkflowCLI(t)
	setCurrentWorkspaceUUID(testWorkspace)
	var queries []string
	httpClient = &http.Client{Transport: workflowTransport(func(r *http.Request) (*http.Response, error) {
		queries = append(queries, r.URL.RawQuery)
		return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(`{}`)), Header: http.Header{}}, nil
	})}
	all, _ := parseToolsets("all")

	r := callEnabledTool(CallToolParams{Name: "workflow_job_list", Arguments: map[string]interface{}{"limit": 25.0}}, all)
	if r.IsError || len(queries) != 1 || queries[0] != "limit=25&workspaceId="+testWorkspace {
		t.Fatalf("limit 25: %+v, queries %v", r, queries)
	}
	for _, bad := range []interface{}{0.0, -1.0, 1001.0, 2.5, "10"} {
		r = callEnabledTool(CallToolParams{Name: "workflow_job_list", Arguments: map[string]interface{}{"limit": bad}}, all)
		if !r.IsError || !strings.Contains(r.Content[0].Text, "limit") {
			t.Fatalf("limit %v: %+v, want an error", bad, r)
		}
	}
	if len(queries) != 1 {
		t.Fatalf("an invalid limit reached the API: %v", queries)
	}
}
