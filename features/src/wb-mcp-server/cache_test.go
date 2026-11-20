package main

import (
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

const (
	workspaceA = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
	workspaceB = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
)

// fakeWb puts a wb script first on PATH, points the wb context at a temp
// directory, and resets the server's cached state.
func fakeWb(t *testing.T, script string) string {
	t.Helper()
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "wb"), []byte("#!/bin/sh\n"+script), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(filepath.Join(dir, ".workbench"), 0700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir+string(os.PathListSeparator)+os.Getenv("PATH"))
	t.Setenv("WORKBENCH_CONTEXT_PARENT_DIR", dir)
	reset := func() {
		cacheMu.Lock()
		cachedToken, cachedTokenExpiry = "", time.Time{}
		cachedWorkspaceUUID, cachedGoogleProject, cachedCloudPlatform, workspaceContextKey = "", "", "", ""
		workspaceIdCache = map[string]string{}
		toolResultCache = map[string]cachedResult{}
		cacheMu.Unlock()
		collectionNamesMu.Lock()
		collectionNamesCache, collectionNamesFetched = nil, time.Time{}
		collectionNamesMu.Unlock()
	}
	reset()
	oldClient := httpClient
	t.Cleanup(func() {
		reset()
		httpClient = oldClient
	})
	return dir
}

func workspaceContext(uuid, project string) string {
	return fmt.Sprintf(`{"server":{"name":"test"},"workspace":{"uuid":%q,"userFacingId":"ws-%s","googleProjectId":%q,"cloudPlatform":"GCP"}}`,
		uuid, project, project)
}

func writeWorkspaceContext(t *testing.T, dir, content string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(dir, ".workbench", "context.json"), []byte(content), 0600); err != nil {
		t.Fatal(err)
	}
}

func cacheOutput(key, output string) {
	cacheMu.Lock()
	toolResultCache[key] = cachedResult{output: output, expires: time.Now().Add(time.Hour)}
	cacheMu.Unlock()
}

func isCached(key string) bool {
	cacheMu.Lock()
	defer cacheMu.Unlock()
	_, ok := toolResultCache[key]
	return ok
}

func TestCallToolClearsCacheOnStateChange(t *testing.T) {
	dir := fakeWb(t, "echo ok\n")
	writeWorkspaceContext(t, dir, workspaceContext(workspaceA, "project-a"))
	syncWorkspaceContext()
	all, _ := parseToolsets("all")

	cacheOutput("wb_status", "cached status")
	cacheOutput("app_list", "cached apps")
	r := callEnabledTool(CallToolParams{Name: "wb_status"}, all)
	if r.IsError || r.Content[0].Text != "cached status" {
		t.Fatalf("wb_status = %+v, want the cached status", r)
	}
	if !isCached("app_list") {
		t.Fatal("a read-only tool call cleared the cache")
	}

	callEnabledTool(CallToolParams{Name: "wb_execute", Arguments: map[string]interface{}{"command": "resource list"}}, all)
	if isCached("app_list") {
		t.Fatal("wb_execute did not clear the cache")
	}
	if !isCached("wb_status") {
		t.Fatal("wb_execute cleared wb_status, which a state change does not affect")
	}
}

func TestStaleStatusIsAnsweredAtOnceAndRefreshedBehind(t *testing.T) {
	dir := fakeWb(t, `case "$*" in
 'status --format=json') sleep 1; echo '{"workspace":{"id":"ws-a","uuid":"`+workspaceA+`"},"fresh":true}' ;;
esac
`)
	writeWorkspaceContext(t, dir, workspaceContext(workspaceA, "project-a"))
	syncWorkspaceContext()
	cacheMu.Lock()
	toolResultCache["wb_status"] = cachedResult{output: "stale status", expires: time.Now().Add(-time.Minute)}
	cacheMu.Unlock()

	start := time.Now()
	out, err := statusResult()
	if err != nil || out != "stale status" || time.Since(start) > 500*time.Millisecond {
		t.Fatalf("statusResult = %q %v in %v, want the stale status at once", out, err, time.Since(start))
	}
	deadline := time.Now().Add(10 * time.Second)
	for time.Now().Before(deadline) {
		if out, _ := statusResult(); strings.Contains(out, `"fresh":true`) {
			return
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Fatal("the stale status was not refreshed in the background")
}

func TestStatusTooOldIsFetchedNow(t *testing.T) {
	dir := fakeWb(t, `echo '{"workspace":{"id":"ws-a","uuid":"`+workspaceA+`"},"fresh":true}'`+"\n")
	writeWorkspaceContext(t, dir, workspaceContext(workspaceA, "project-a"))
	syncWorkspaceContext()
	cacheMu.Lock()
	toolResultCache["wb_status"] = cachedResult{output: "ancient", expires: time.Now().Add(-statusStaleMax - time.Minute)}
	cacheMu.Unlock()
	if out, err := statusResult(); err != nil || !strings.Contains(out, `"fresh":true`) {
		t.Fatalf("statusResult = %q %v, want a fresh status", out, err)
	}
}

func TestDataCollectionNamesAreCachedAndRefetchedForAnUnknownOne(t *testing.T) {
	fakeWb(t, "echo ok\n")
	calls := 0
	names := map[string]string{"c1": "Collection One"}
	old := fetchCollectionNames
	fetchCollectionNames = func() (map[string]string, error) {
		calls++
		out := map[string]string{}
		for k, v := range names {
			out[k] = v
		}
		return out, nil
	}
	t.Cleanup(func() { fetchCollectionNames = old })

	if got := dataCollectionNames([]string{"c1"}); got["c1"] != "Collection One" || calls != 1 {
		t.Fatalf("names = %v after %d fetches", got, calls)
	}
	dataCollectionNames([]string{"c1"})
	if calls != 1 {
		t.Fatalf("a known collection was fetched again (%d fetches)", calls)
	}
	// A collection added since: not fetched again within collectionNamesRetry, then fetched.
	names["c2"] = "Collection Two"
	if got := dataCollectionNames([]string{"c2"}); got["c2"] != "" || calls != 1 {
		t.Fatalf("refetched within the retry interval: %v, %d fetches", got, calls)
	}
	collectionNamesMu.Lock()
	collectionNamesFetched = time.Now().Add(-collectionNamesRetry)
	collectionNamesMu.Unlock()
	if got := dataCollectionNames([]string{"c2"}); got["c2"] != "Collection Two" || calls != 2 {
		t.Fatalf("names = %v after %d fetches, want c2 fetched", got, calls)
	}
	// A failed fetch keeps the cached names.
	fetchCollectionNames = func() (map[string]string, error) { return nil, fmt.Errorf("down") }
	collectionNamesMu.Lock()
	collectionNamesFetched = time.Now().Add(-collectionNamesTTL)
	collectionNamesMu.Unlock()
	if got := dataCollectionNames(nil); got["c1"] != "Collection One" {
		t.Fatalf("a failed fetch lost the cache: %v", got)
	}
}

func TestWorkspaceChangeOutsideServer(t *testing.T) {
	// wb workspace create makes the new workspace current, like wb workspace set.
	dir := fakeWb(t, fmt.Sprintf(`case "$*" in
 'workspace create'*) printf '%%s' '%s' > "$WORKBENCH_CONTEXT_PARENT_DIR/.workbench/context.json" ;;
esac
`, workspaceContext(workspaceA, "project-a")))
	all, _ := parseToolsets("all")
	readOnly := CallToolParams{Name: "wb_status"}

	writeWorkspaceContext(t, dir, workspaceContext(workspaceB, "project-b"))
	syncWorkspaceContext()
	cacheOutput("wb_status", "status b")
	callEnabledTool(readOnly, all)
	if got := currentGoogleProject(); got != "project-b" {
		t.Fatalf("project = %q, want project-b", got)
	}

	// A terminal switch is seen on the next call, and clears results cached for
	// the old workspace.
	writeWorkspaceContext(t, dir, workspaceContext(workspaceA, "project-a"))
	callEnabledTool(readOnly, all)
	if isCached("wb_status") {
		t.Fatal("results for the old workspace stayed cached")
	}
	uuid, err := getCurrentWorkspaceUUID()
	if got := currentGoogleProject(); got != "project-a" || uuid != workspaceA || err != nil {
		t.Fatalf("workspace = %q %q %v, want %s project-a", uuid, got, err, workspaceA)
	}

	writeWorkspaceContext(t, dir, workspaceContext(workspaceB, "project-b"))
	syncWorkspaceContext()
	callEnabledTool(CallToolParams{Name: "workspace_create", Arguments: map[string]interface{}{"id": "ws-a", "podId": "pod"}}, all)
	callEnabledTool(readOnly, all)
	if got := currentGoogleProject(); got != "project-a" {
		t.Fatalf("after workspace_create, project = %q, want project-a", got)
	}
}

func TestTokenCacheAndUnauthorizedRetry(t *testing.T) {
	dir := fakeWb(t, `n=$(cat "$WORKBENCH_CONTEXT_PARENT_DIR/count" 2>/dev/null || echo 0)
n=$((n + 1))
echo "$n" > "$WORKBENCH_CONTEXT_PARENT_DIR/count"
printf 'token-%s' "$n"
`)
	tokenFetches := func() string {
		b, _ := os.ReadFile(filepath.Join(dir, "count"))
		return strings.TrimSpace(string(b))
	}
	var seen []string
	httpClient = &http.Client{Transport: workflowTransport(func(r *http.Request) (*http.Response, error) {
		auth := r.Header.Get("Authorization")
		seen = append(seen, auth)
		status := http.StatusOK
		if auth == "Bearer token-1" {
			status = http.StatusUnauthorized
		}
		return &http.Response{StatusCode: status, Body: http.NoBody, Header: http.Header{}}, nil
	})}

	if _, err := makeAPIRequest("GET", "https://wsm.test/api", nil); err != nil {
		t.Fatalf("request after 401 retry: %v", err)
	}
	if _, err := makeAPIRequest("GET", "https://wsm.test/api", nil); err != nil {
		t.Fatalf("second request: %v", err)
	}
	want := []string{"Bearer token-1", "Bearer token-2", "Bearer token-2"}
	if strings.Join(seen, ",") != strings.Join(want, ",") {
		t.Fatalf("Authorization headers = %v, want %v", seen, want)
	}
	if got := tokenFetches(); got != "2" {
		t.Fatalf("wb auth print-access-token ran %s times, want 2", got)
	}

	cacheMu.Lock()
	cachedTokenExpiry = time.Now().Add(-time.Second)
	cacheMu.Unlock()
	if token, err := getToken(); err != nil || token != "token-3" {
		t.Fatalf("expired token: got %q %v, want token-3", token, err)
	}
}

func TestRegisteredWorkflowsAreCachedUntilAStateChange(t *testing.T) {
	dir := fakeWb(t, `case "$*" in
 'workflow list'*|'workflow describe'*) echo "$*" >> "$WORKBENCH_CONTEXT_PARENT_DIR/calls"; echo listed ;;
esac
`)
	writeWorkspaceContext(t, dir, workspaceContext(workspaceA, "project-a"))
	syncWorkspaceContext()
	all, _ := parseToolsets("all")
	calls := func() int {
		data, _ := os.ReadFile(filepath.Join(dir, "calls"))
		return strings.Count(string(data), "\n")
	}
	list := CallToolParams{Name: "workflow_list", Arguments: map[string]interface{}{"workspaceId": "ws-a"}}
	describe := CallToolParams{Name: "workflow_describe", Arguments: map[string]interface{}{"workspaceId": "ws-a", "workflowId": "wf"}}
	for i := 0; i < 2; i++ {
		callEnabledTool(list, all)
		callEnabledTool(describe, all)
	}
	if n := calls(); n != 2 {
		t.Fatalf("wb ran %d times for two calls each, want 2", n)
	}
	callEnabledTool(CallToolParams{Name: "workflow_create", Arguments: map[string]interface{}{"workspaceId": "ws-a"}}, all)
	callEnabledTool(list, all)
	if n := calls(); n != 3 {
		t.Fatalf("after workflow_create, wb ran %d times, want the list read again", n)
	}
}

func TestCachesAreWarmedOnceWbAnswers(t *testing.T) {
	// wb fails until a marker file exists, as when the server starts before wb is installed.
	dir := fakeWb(t, `[ -f "$WORKBENCH_CONTEXT_PARENT_DIR/ready" ] || exit 1
echo '{"workspace":{"id":"ws-a","uuid":"`+workspaceA+`"},"warm":true}'
`)
	fetched := 0
	old := fetchCollectionNames
	fetchCollectionNames = func() (map[string]string, error) {
		if _, err := os.Stat(filepath.Join(dir, "ready")); err != nil {
			return nil, fmt.Errorf("not ready")
		}
		fetched++
		return map[string]string{"c1": "One"}, nil
	}
	oldRetry, oldTries := warmRetry, warmTries
	warmRetry, warmTries = 50*time.Millisecond, 100
	t.Cleanup(func() { fetchCollectionNames, warmRetry, warmTries = old, oldRetry, oldTries })

	done := make(chan struct{})
	go func() { warmCaches(true); close(done) }()
	time.Sleep(200 * time.Millisecond)
	if isCached("wb_status") {
		t.Fatal("cached a status before wb answered")
	}
	os.WriteFile(filepath.Join(dir, "ready"), nil, 0600)
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("warmCaches did not finish once wb answered")
	}
	if out, _ := statusResult(); !strings.Contains(out, `"warm":true`) || fetched != 1 {
		t.Fatalf("status %q, names fetched %d times", out, fetched)
	}
}
