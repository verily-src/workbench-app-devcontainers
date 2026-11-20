package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"testing"
)

func TestEveryToolHasAGroup(t *testing.T) {
	seen := map[string]bool{}
	for _, tool := range wbTools {
		if seen[tool.Name] {
			t.Errorf("tool %s is defined twice", tool.Name)
		}
		seen[tool.Name] = true
		group, ok := toolGroups[tool.Name]
		if !ok {
			t.Errorf("tool %s has no entry in toolGroups", tool.Name)
		} else if !isToolGroup(group) {
			t.Errorf("tool %s is in unknown group %q", tool.Name, group)
		}
	}
	for name := range toolGroups {
		if !seen[name] {
			t.Errorf("toolGroups lists %s, which isn't a tool", name)
		}
	}
	for _, m := range []map[string]bool{gcpOnlyTools, awsOnlyTools} {
		for name := range m {
			if !seen[name] {
				t.Errorf("cloud-only list has %s, which isn't a tool", name)
			}
		}
	}
}

func TestParseToolsets(t *testing.T) {
	enabled, unknown := parseToolsets("")
	if got := enabledGroupNames(enabled); got != "core" || len(unknown) != 0 {
		t.Errorf(`parseToolsets("") = %s, %v; want core`, got, unknown)
	}
	enabled, unknown = parseToolsets(" Workflows, dataexplorer ,bogus")
	if got := enabledGroupNames(enabled); got != "core,workflows,dataexplorer" {
		t.Errorf("enabled = %s", got)
	}
	if len(unknown) != 1 || unknown[0] != "bogus" {
		t.Errorf("unknown = %v, want [bogus]", unknown)
	}
	enabled, _ = parseToolsets("all")
	if len(enabled) != len(toolGroupDescriptions) {
		t.Errorf(`"all" enabled %d groups, want %d`, len(enabled), len(toolGroupDescriptions))
	}
}

func toolNames(tools []Tool) []string {
	var names []string
	for _, tool := range tools {
		names = append(names, tool.Name)
	}
	sort.Strings(names)
	return names
}

func TestDefaultToolList(t *testing.T) {
	core, _ := parseToolsets("core")
	for _, tt := range []struct {
		cloud, want, notWant string
	}{
		{"GCP", "bq_query", "s3_list_objects"},
		{"AWS", "s3_list_objects", "bq_query"},
		{"", "bq_query", "workflow_job_run"}, // unknown cloud: both clouds' core tools
		{"", "s3_list_objects", "cohort_create_in_workspace"},
	} {
		names := strings.Join(toolNames(listTools(core, tt.cloud)), " ")
		if !strings.Contains(" "+names+" ", " "+tt.want+" ") {
			t.Errorf("cloud %q: default tools lack %s: %s", tt.cloud, tt.want, names)
		}
		if strings.Contains(" "+names+" ", " "+tt.notWant+" ") {
			t.Errorf("cloud %q: default tools include %s", tt.cloud, tt.notWant)
		}
	}

	// The default list is sent with every model request; keep it small. About
	// 3.4 characters of tool JSON make one token for the models we've measured.
	const budget = 10000
	tools := listTools(core, "GCP")
	b, _ := json.Marshal(tools)
	if len(b) > budget {
		t.Errorf("default GCP tool list is %d characters of JSON (%d tools), budget %d", len(b), len(tools), budget)
	}
	all, _ := parseToolsets("all")
	if got := len(listTools(all, "")); got != len(wbTools) {
		t.Errorf("all groups, unknown cloud: %d tools, want %d", got, len(wbTools))
	}
}

func TestToolUnavailableReason(t *testing.T) {
	core, _ := parseToolsets("core")
	for _, tt := range []struct {
		name, cloud, want string
	}{
		{"wb_status", "GCP", ""},
		{"cohort_create_in_workspace", "GCP", `"dataexplorer" tool group`},
		{"workflow_run_logs", "GCP", "no wb CLI equivalent"},
		{"workflow_job_run", "GCP", "Use the wb CLI through wb_execute"},
		{"s3_read_file", "GCP", "only works in AWS"},
		{"bq_query", "AWS", "only works in GCP"},
		{"list_files", "GCP", "Unknown tool"},
		{"resource_credentials", "GCP", "Unknown tool"},
	} {
		got := toolUnavailableReason(tt.name, core, tt.cloud)
		if (tt.want == "") != (got == "") || !strings.Contains(got, tt.want) {
			t.Errorf("toolUnavailableReason(%s, %s) = %q, want %q", tt.name, tt.cloud, got, tt.want)
		}
	}
}

func TestWbHelp(t *testing.T) {
	core, _ := parseToolsets("core")
	for _, topic := range helpTopicNames() {
		text, err := wbHelp(topic, core, "GCP")
		if err != nil || len(text) < 200 {
			t.Errorf("wbHelp(%q) = %d chars, %v", topic, len(text), err)
		}
	}
	text, _ := wbHelp("toolsets", core, "GCP")
	for _, want := range []string{"Enabled tool groups: core", "dataexplorer", "cohort_create_in_workspace", "?toolsets="} {
		if !strings.Contains(text, want) {
			t.Errorf("toolsets help lacks %q", want)
		}
	}
	if _, err := wbHelp("nope", core, "GCP"); err == nil {
		t.Error("wbHelp(nope) succeeded")
	}
}

// Tool names in the llm-context feature (the generated CLAUDE.md and the skills)
// must be real tools, or models call tools that don't exist. Tools in the
// CLAUDE.md tables of default tools must be in the core group.
func TestLLMContextToolReferences(t *testing.T) {
	dir := filepath.Join("..", "llm-context")
	if _, err := os.Stat(dir); err != nil {
		t.Skip("llm-context feature not found")
	}
	prefixes := map[string]bool{"list": true, "read": true, "get": true}
	for name := range toolGroups {
		prefixes[strings.SplitN(name, "_", 2)[0]] = true
	}
	ref := regexp.MustCompile("\\\\?`([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\\\\?`")
	mcpRef := regexp.MustCompile(`mcp__wb__([a-z0-9_]+)`)
	tableRow := regexp.MustCompile("(?m)^\\|.*$")

	var files []string
	filepath.Walk(filepath.Join(dir, "skills"), func(path string, info os.FileInfo, err error) error {
		if err == nil && strings.HasSuffix(path, ".md") {
			files = append(files, path)
		}
		return nil
	})
	files = append(files, filepath.Join(dir, "generate-context.sh"))
	for _, path := range files {
		b, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		for _, m := range ref.FindAllStringSubmatch(string(b), -1) {
			name := m[1]
			if _, ok := toolGroups[name]; !ok && prefixes[strings.SplitN(name, "_", 2)[0]] {
				t.Errorf("%s mentions %s, which isn't a wb-mcp-server tool", path, name)
			}
		}
		for _, m := range mcpRef.FindAllStringSubmatch(string(b), -1) {
			if _, ok := toolGroups[m[1]]; !ok {
				t.Errorf("%s mentions %s, which isn't a wb-mcp-server tool", path, m[0])
			}
		}
	}

	b, err := os.ReadFile(filepath.Join(dir, "generate-context.sh"))
	if err != nil {
		t.Fatal(err)
	}
	// Rows of the default-tool tables are between these markers.
	text := string(b)
	for {
		start := strings.Index(text, "# BEGIN default MCP tools")
		if start < 0 {
			break
		}
		end := strings.Index(text[start:], "# END default MCP tools")
		if end < 0 {
			t.Fatal("unterminated default MCP tools block in generate-context.sh")
		}
		for _, row := range tableRow.FindAllString(text[start:start+end], -1) {
			// Every tool name in a row, not only the first, is a default tool.
			for _, m := range ref.FindAllStringSubmatch(row, -1) {
				g, ok := toolGroups[m[1]]
				if !ok {
					t.Errorf("generate-context.sh row %q has %s, which isn't a wb-mcp-server tool", row, m[1])
				} else if g != groupCore {
					t.Errorf("generate-context.sh lists %s as a default tool, but it is in group %q", m[1], g)
				}
			}
		}
		text = text[start+end:]
	}
}

func TestRefusalSaysWhenAToolHasNoCLIEquivalent(t *testing.T) {
	core, _ := parseToolsets("core")
	// Every handler of these tools calls an HTTP API, not the wb CLI.
	var noCLI []string
	for name, group := range toolGroups {
		if group == groupDataExplorer {
			noCLI = append(noCLI, name)
		}
	}
	noCLI = append(noCLI, "workflow_run_logs", "workflow_run_trace", "workflow_run_costs", "workflow_task_get")
	for _, name := range noCLI {
		got := toolUnavailableReason(name, core, "GCP")
		group := toolGroups[name]
		for _, want := range []string{"no wb CLI equivalent", `enable the "` + group + `" group`, "?toolsets="} {
			if !strings.Contains(got, want) {
				t.Errorf("refusal for %s lacks %q: %s", name, want, got)
			}
		}
		if strings.Contains(got, "Use the wb CLI") {
			t.Errorf("refusal for %s sends the model to the wb CLI: %s", name, got)
		}
	}
	// Tools with a CLI route keep pointing at wb_execute.
	for _, name := range []string{"workflow_job_run", "app_create", "workspace_list_all", "workflow_task_list"} {
		if got := toolUnavailableReason(name, core, "GCP"); !strings.Contains(got, "Use the wb CLI through wb_execute") || strings.Contains(got, "no wb CLI equivalent") {
			t.Errorf("refusal for %s = %s", name, got)
		}
	}
	text, _ := wbHelp("toolsets", core, "GCP")
	for _, want := range []string{"no wb CLI equivalent", "workflow_run_logs", "workflow_run_trace", "workflow_run_costs", "workflow_task_get", "every tool in the dataexplorer group"} {
		if !strings.Contains(text, want) {
			t.Errorf("toolsets help lacks %q", want)
		}
	}
	// The cohorts and export guides are core help for dataexplorer tools: they say how to enable the group.
	for _, topic := range []string{"cohorts", "export"} {
		guide, _ := wbHelp(topic, core, "GCP")
		if !strings.Contains(guide, `"dataexplorer" group`) || !strings.Contains(guide, `topic "toolsets"`) {
			t.Errorf("%s guide does not say which group to enable and where to read how", topic)
		}
	}
}

func TestLoopbackDetection(t *testing.T) {
	for host, want := range map[string]bool{
		"127.0.0.1": true, "127.0.0.2": true, "::1": true, "localhost": true,
		"0.0.0.0": false, "::": false, "10.0.0.5": false, "": false, "example.internal": false,
	} {
		if got := isLoopbackBind(host); got != want {
			t.Errorf("isLoopbackBind(%q) = %t, want %t", host, got, want)
		}
	}
}

// listedAt returns the tool names a tools/list request to the HTTP handler gets for a ?toolsets= value.
func listedAt(t *testing.T, query string) map[string]bool {
	t.Helper()
	body := `{"jsonrpc":"2.0","id":1,"method":"tools/list"}`
	req := httptest.NewRequest(http.MethodPost, "/"+query, strings.NewReader(body))
	rec := httptest.NewRecorder()
	handleHTTP(rec, req)
	var resp struct {
		Result struct {
			Tools []struct{ Name string } `json:"tools"`
		} `json:"result"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("tools/list response: %v: %s", err, rec.Body.String())
	}
	names := map[string]bool{}
	for _, tool := range resp.Result.Tools {
		names[tool.Name] = true
	}
	return names
}

func TestToolsetsQueryIsACeilingOffLoopback(t *testing.T) {
	oldDefault, oldLoopback := defaultToolsets, listensOnLoopback
	t.Cleanup(func() { defaultToolsets, listensOnLoopback = oldDefault, oldLoopback })
	defaultToolsets = "core,workflows"
	fakeWb(t, "exit 1\n") // tools/list reads the workspace context; keep the real one out of the caches
	cloud := currentCloudPlatform()

	listensOnLoopback = false
	if r := toolUnavailableReason("workspace_add_user", requestToolsets("all"), cloud); r == "" {
		t.Error("off loopback, ?toolsets=all enabled an admin tool the server was not configured with")
	}
	if listed := listedAt(t, "?toolsets=all"); listed["workspace_add_user"] || !listed["workflow_job_list"] {
		t.Errorf("off loopback, ?toolsets=all: admin listed = %t, workflows listed = %t", listed["workspace_add_user"], listed["workflow_job_list"])
	}
	if r := toolUnavailableReason("workflow_job_list", requestToolsets("all"), cloud); r != "" {
		t.Errorf("off loopback, a configured workflows tool was refused: %s", r)
	}
	if r := toolUnavailableReason("workflow_job_list", requestToolsets("core"), cloud); r == "" {
		t.Error("off loopback, ?toolsets=core did not narrow away workflows")
	}
	if listed := listedAt(t, "?toolsets=core"); listed["workflow_job_list"] {
		t.Error("off loopback, ?toolsets=core still lists a workflows tool")
	}
	if got := requestToolsets(""); enabledGroupNames(got) != "core,workflows" {
		t.Errorf("no query: groups = %s, want the configured core,workflows", enabledGroupNames(got))
	}

	listensOnLoopback = true
	if listed := listedAt(t, "?toolsets=all"); !listed["workspace_add_user"] {
		t.Error("on loopback, ?toolsets=all did not list an admin tool")
	}
}
