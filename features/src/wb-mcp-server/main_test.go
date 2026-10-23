package main

import (
	"reflect"
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

func TestSwitchesWorkspace(t *testing.T) {
	for _, tt := range []struct {
		name, command string
		want          bool
	}{
		{"server_set", "", true},
		{"wb_execute", "workspace set --id=other", true},
		{"wb_execute", "server set --name=dev", true},
		{"wb_execute", "workspace describe", false},
		{"wb_execute", "resource list", false},
		{"gsutil_execute", "workspace set", false},
	} {
		params := CallToolParams{Name: tt.name, Arguments: map[string]interface{}{"command": tt.command}}
		if got := switchesWorkspace(params); got != tt.want {
			t.Errorf("switchesWorkspace(%s %q) = %v, want %v", tt.name, tt.command, got, tt.want)
		}
	}
}
