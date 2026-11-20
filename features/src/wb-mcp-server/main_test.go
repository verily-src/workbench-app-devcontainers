package main

import (
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func TestSplitCommandLine(t *testing.T) {
	tests := []struct {
		in   string
		want []string
	}{
		{"ls gs://bucket/", []string{"ls", "gs://bucket/"}},
		{"  ls   -l  ", []string{"ls", "-l"}},
		{"query --use_legacy_sql=false 'SELECT COUNT(*) FROM `p.d.t`'", []string{"query", "--use_legacy_sql=false", "SELECT COUNT(*) FROM `p.d.t`"}},
		{`ls "gs://bucket/my folder/"`, []string{"ls", "gs://bucket/my folder/"}},
		{`ls gs://bucket/my\ folder/`, []string{"ls", "gs://bucket/my folder/"}},
		{`echo "a \"b\" c"`, []string{"echo", `a "b" c`}},
		{`--flag='a b'c`, []string{"--flag=a bc"}},
		{"ls ''", []string{"ls", ""}},
		{"ls gs://x/; rm -rf /", []string{"ls", "gs://x/;", "rm", "-rf", "/"}},
		{"ls $(id)", []string{"ls", "$(id)"}},
	}
	for _, tt := range tests {
		got, err := splitCommandLine(tt.in)
		if err != nil {
			t.Errorf("splitCommandLine(%q) error: %v", tt.in, err)
			continue
		}
		if !reflect.DeepEqual(got, tt.want) {
			t.Errorf("splitCommandLine(%q) = %q, want %q", tt.in, got, tt.want)
		}
	}
	for _, bad := range []string{"ls 'unterminated", `ls "unterminated`} {
		if _, err := splitCommandLine(bad); err == nil {
			t.Errorf("splitCommandLine(%q) succeeded, want error", bad)
		}
	}
}

func TestIsSQL(t *testing.T) {
	for in, want := range map[string]bool{
		"SELECT 1":                                true,
		"  select count(*) from t":                true,
		"WITH x AS (SELECT 1) SELECT * FROM x":    true,
		"query --use_legacy_sql=false 'SELECT 1'": false,
		"ls": false,
		"":   false,
	} {
		if got := isSQL(in); got != want {
			t.Errorf("isSQL(%q) = %v, want %v", in, got, want)
		}
	}
}

func TestCleanToolOutput(t *testing.T) {
	in := " : You are authenticating using user credentials. For production, we recommend using service account credentials.\n\nTo learn more about service account credentials, see http://cloud.google.com/docs/authentication/external/set-up-adc-on-cloud\nFATAL Command 'SELECT' unknown\n"
	want := "FATAL Command 'SELECT' unknown\n"
	if got := cleanToolOutput(in); got != want {
		t.Errorf("cleanToolOutput() = %q, want %q", got, want)
	}
	if got := cleanToolOutput("plain output"); got != "plain output" {
		t.Errorf("cleanToolOutput() changed clean output: %q", got)
	}
}

func TestReferencesUndefinedWorkbenchVar(t *testing.T) {
	t.Setenv("WORKBENCH_defined", "gs://b")
	for in, want := range map[string]bool{
		"ls $WORKBENCH_defined":     false,
		"ls ${WORKBENCH_defined}/x": false,
		"ls $WORKBENCH_missing":     true,
		"ls $HOME":                  false,
	} {
		if got := referencesUndefinedWorkbenchVar(in); got != want {
			t.Errorf("referencesUndefinedWorkbenchVar(%q) = %v, want %v", in, got, want)
		}
	}
}

func fakeCommand(t *testing.T, dir, name string) {
	t.Helper()
	script := "#!/bin/sh\nfor a in \"$@\"; do printf '[%s]\\n' \"$a\"; done\n"
	if err := os.WriteFile(filepath.Join(dir, name), []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
}

func TestBQQueryProtectsSQLThatStartsWithADash(t *testing.T) {
	dir := fakeWb(t, "echo ok\n")
	fakeCommand(t, dir, "bq")
	all, _ := parseToolsets("all")
	for _, tc := range []struct{ tool, key, sql string }{
		{"bq_query", "sql", "-- count rows\nSELECT 1"},
		{"bq_query", "sql", "  \n--flag"},
		{"bq_execute", "command", "-- note\nSELECT 1"},
		{"bq_execute", "command", "/* c */ SELECT 1"},
	} {
		r := callEnabledTool(CallToolParams{Name: tc.tool, Arguments: map[string]interface{}{tc.key: tc.sql}}, all)
		out := r.Content[0].Text
		if tc.sql[0] == '/' {
			// Does not start with "-": passed as it is.
			if !strings.Contains(out, "[--max_rows=100]\n["+tc.sql+"]") {
				t.Errorf("%s %q: got %q", tc.tool, tc.sql, out)
			}
			continue
		}
		if !strings.Contains(out, "[--max_rows=100]\n[\n"+tc.sql+"]") {
			t.Errorf("%s %q: got %q, want the SQL after a newline", tc.tool, tc.sql, out)
		}
	}
	if got := bqSQLArg("SELECT 1"); got != "SELECT 1" {
		t.Errorf("bqSQLArg changed plain SQL: %q", got)
	}
}

func TestBQQueryViaWbQuotesSQLThatStartsWithADash(t *testing.T) {
	dir := fakeWb(t, "printf '[%s]\\n' \"$@\"\n")
	// bq is not installed: keep PATH to the fake wb's directory and the basics.
	t.Setenv("PATH", dir+":/usr/bin:/bin")
	if _, err := exec.LookPath("bq"); err == nil {
		t.Skip("bq is installed")
	}
	out, _ := executeBQQuery("-- c\nSELECT 'x'", 5)
	if !strings.Contains(out, "[--max_rows=5]\n['\n-- c\nSELECT '\\''x'\\'''") {
		t.Fatalf("got %q", out)
	}
}

func TestBQMaxRows(t *testing.T) {
	for _, tc := range []struct {
		in   interface{}
		want int
	}{
		{nil, 100}, {"5", 100}, {math.NaN(), 100}, {0.0, 100}, {-5.0, 1}, {0.4, 1}, {1.0, 1}, {250.0, 250},
		{10000.0, 10000}, {10001.0, 10000}, {1e18, 10000}, {math.Inf(1), 10000}, {math.Inf(-1), 1},
	} {
		if got := bqMaxRows(tc.in); got != tc.want {
			t.Errorf("bqMaxRows(%v) = %d, want %d", tc.in, got, tc.want)
		}
	}
}

func TestIsSQLSkipsCommentsAndParentheses(t *testing.T) {
	for command, want := range map[string]bool{
		"SELECT 1":                        true,
		"select 1":                        true,
		"WITH t AS (SELECT 1) SELECT *":   true,
		"(SELECT 1) UNION ALL (SELECT 2)": true,
		"  ((SELECT 1))":                  true,
		"-- comment\nSELECT 1":            true,
		"-- a\n-- b\n  WITH x AS (SELECT 1) SELECT * FROM x": true,
		"/* c */ SELECT 1":         true,
		"/* a */ -- b\n(SELECT 1)": true,
		"ls":                       false,
		"show --schema p:d.t":      false,
		"head -n 10 p:d.t":         false,
		"-- only a comment":        false,
		"/* unterminated SELECT 1": false,
		"":                         false,
		"query --use_legacy_sql=false 'SELECT 1'": false,
	} {
		if got := isSQL(command); got != want {
			t.Errorf("isSQL(%q) = %v, want %v", command, got, want)
		}
	}
}

func TestWbExecuteHonorsQuotes(t *testing.T) {
	fakeWb(t, "printf '[%s]\\n' \"$@\"\n")
	all, _ := parseToolsets("core")
	r := callEnabledTool(CallToolParams{Name: "wb_execute", Arguments: map[string]interface{}{
		"command": `resource create gcs-bucket --name b --description='My bucket'`}}, all)
	if r.IsError || !strings.Contains(r.Content[0].Text, "[--description=My bucket]") || strings.Contains(r.Content[0].Text, "[--description='My]") {
		t.Fatalf("got %+v", r)
	}
	r = callEnabledTool(CallToolParams{Name: "wb_execute", Arguments: map[string]interface{}{"command": `resource create --description='open`}}, all)
	if !r.IsError || !strings.Contains(r.Content[0].Text, "unterminated single quote") {
		t.Fatalf("unbalanced quote: %+v", r)
	}
}
