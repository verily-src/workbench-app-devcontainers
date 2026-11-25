package main

import (
	"fmt"
	"net"
	"sort"
	"strings"
)

// Tool groups keep the tool list that clients send to the model small. Every
// tool definition is sent with every model request, and the full list is about
// 14,000 tokens (core alone is about 1,400). Only the core group is enabled by default; the others are
// enabled with the -toolsets flag, the WB_MCP_TOOLSETS environment variable, or
// a ?toolsets= query parameter on the HTTP endpoint.
const (
	groupCore         = "core"
	groupWorkflows    = "workflows"
	groupDataExplorer = "dataexplorer"
	groupApps         = "apps"
	groupAdmin        = "admin"
	groupLegacy       = "legacy"
	groupDocs         = "docs"
)

// toolGroupDescriptions lists every group, in display order.
var toolGroupDescriptions = []struct{ name, description string }{
	{groupCore, "Workspace status and resources, data collections, app URLs, BigQuery/GCS or S3/Aurora access, wb_execute, wb_help. Always enabled."},
	{groupWorkflows, "List, describe, run and cancel workflows and jobs; task lists, logs, traces and costs."},
	{groupDataExplorer, "Underlay schemas, studies, cohort building, filters and cohort export."},
	{groupApps, "Create, delete, start and stop apps."},
	{groupAdmin, "Create, update and delete workspaces, resources and folders; users, groups, pods and organizations; servers."},
	{groupDocs, "Search and read the Workbench documentation (support.workbench.verily.com)."},
	{groupLegacy, "Notebook and cluster tools, and tools covered by others (wb_workspace_list, folder_list_tree, server_status, auth_status, version, resource_open_console)."},
}

// toolGroups maps every tool to its group. TestEveryToolHasAGroup keeps it in
// sync with wbTools.
var toolGroups = map[string]string{
	// Core: what most tasks need.
	"wb_status":                       groupCore,
	"wb_help":                         groupCore,
	"wb_execute":                      groupCore,
	"workspace_list_resources":        groupCore,
	"workspace_list_data_collections": groupCore,
	"platform_list_data_collections":  groupCore,
	"resource_list_tree":              groupCore,
	"app_list":                        groupCore,
	"app_get_url":                     groupCore,
	"bq_query":                        groupCore,
	"bq_execute":                      groupCore,
	"gcloud_execute":                  groupCore,
	"gsutil_execute":                  groupCore,
	"s3_list_objects":                 groupCore,
	"s3_read_file":                    groupCore,
	"aurora_query":                    groupCore,
	"aurora_list_tables":              groupCore,
	"aurora_describe_table":           groupCore,

	"wb_docs_search": groupDocs,
	"wb_docs_read":   groupDocs,

	"workflow_list":                groupWorkflows,
	"workflow_describe":            groupWorkflows,
	"workflow_create":              groupWorkflows,
	"workflow_job_list":            groupWorkflows,
	"workflow_job_describe":        groupWorkflows,
	"workflow_job_run":             groupWorkflows,
	"workflow_job_cancel":          groupWorkflows,
	"workflow_inputs_get":          groupWorkflows,
	"workflow_task_list":           groupWorkflows,
	"workflow_task_get":            groupWorkflows,
	"workflow_run_logs":            groupWorkflows,
	"workflow_run_trace":           groupWorkflows,
	"workflow_run_costs":           groupWorkflows,
	"workflow_batch_status_counts": groupWorkflows,
	"cromwell_generate_config":     groupWorkflows,

	"underlay_list":                    groupDataExplorer,
	"underlay_get_schema":              groupDataExplorer,
	"underlay_list_entities":           groupDataExplorer,
	"underlay_get_entity":              groupDataExplorer,
	"underlay_list_criteria_selectors": groupDataExplorer,
	"data_query_hints":                 groupDataExplorer,
	"data_sample_instances":            groupDataExplorer,
	"study_list":                       groupDataExplorer,
	"study_list_cohorts":               groupDataExplorer,
	"cohort_create_in_workspace":       groupDataExplorer,
	"cohort_update_criteria":           groupDataExplorer,
	"cohort_count_instances":           groupDataExplorer,
	"export_list_models":               groupDataExplorer,
	"export_describe":                  groupDataExplorer,
	"export_preview":                   groupDataExplorer,
	"export_cohort":                    groupDataExplorer,
	"filter_build_attribute":           groupDataExplorer,
	"filter_build_relationship":        groupDataExplorer,
	"filter_build_boolean_logic":       groupDataExplorer,
	"filter_build_hierarchy":           groupDataExplorer,

	"app_create": groupApps,
	"app_delete": groupApps,
	"app_start":  groupApps,
	"app_stop":   groupApps,

	"workspace_get":                      groupAdmin,
	"workspace_list_all":                 groupAdmin,
	"workspace_create":                   groupAdmin,
	"workspace_delete":                   groupAdmin,
	"workspace_update":                   groupAdmin,
	"workspace_duplicate":                groupAdmin,
	"workspace_set_property":             groupAdmin,
	"workspace_delete_property":          groupAdmin,
	"workspace_add_user":                 groupAdmin,
	"workspace_remove_user":              groupAdmin,
	"workspace_list_users":               groupAdmin,
	"workspace_configure_aws":            groupAdmin,
	"resource_create_bucket":             groupAdmin,
	"resource_create_bq_dataset":         groupAdmin,
	"resource_create_aurora_database":    groupAdmin,
	"resource_create_s3_folder":          groupAdmin,
	"resource_create_s3_external_bucket": groupAdmin,
	"resource_delete":                    groupAdmin,
	"resource_update":                    groupAdmin,
	"resource_add_reference":             groupAdmin,
	"resource_move":                      groupAdmin,
	"resource_check_access":              groupAdmin,
	"resource_mount":                     groupAdmin,
	"resource_unmount":                   groupAdmin,
	"resolve":                            groupAdmin,
	"folder_create":                      groupAdmin,
	"folder_delete":                      groupAdmin,
	"folder_update":                      groupAdmin,
	"aurora_resolve_connection":          groupAdmin,
	"s3_write_file":                      groupAdmin,
	"s3_copy":                            groupAdmin,
	"git_execute":                        groupAdmin,
	"group_create":                       groupAdmin,
	"group_delete":                       groupAdmin,
	"group_list":                         groupAdmin,
	"group_describe":                     groupAdmin,
	"group_add_user":                     groupAdmin,
	"group_remove_user":                  groupAdmin,
	"pod_list":                           groupAdmin,
	"pod_describe":                       groupAdmin,
	"pod_role_list":                      groupAdmin,
	"pod_role_grant":                     groupAdmin,
	"pod_role_revoke":                    groupAdmin,
	"organization_list":                  groupAdmin,
	"server_list":                        groupAdmin,
	"server_set":                         groupAdmin,
	"server_list_regions":                groupAdmin,

	"notebook_start":        groupLegacy,
	"notebook_stop":         groupLegacy,
	"notebook_launch":       groupLegacy,
	"cluster_start":         groupLegacy,
	"cluster_stop":          groupLegacy,
	"cluster_launch":        groupLegacy,
	"wb_workspace_list":     groupLegacy, // workspace_list_all
	"folder_list_tree":      groupLegacy, // resource_list_tree
	"server_status":         groupLegacy, // wb_status
	"auth_status":           groupLegacy, // wb_status
	"version":               groupLegacy, // wb_execute "version"
	"resource_open_console": groupLegacy,
}

// noCLIEquivalentTools are tools outside the dataexplorer group whose handlers call a Workbench
// HTTP API directly and have no `wb` command, so wb_execute cannot stand in for them. Every tool
// in the dataexplorer group is also without a CLI equivalent (the data-explorer command only
// reloads an underlay).
var noCLIEquivalentTools = map[string]bool{
	"workflow_run_logs": true, "workflow_run_trace": true, "workflow_run_costs": true, "workflow_task_get": true,
	"wb_docs_search": true, "wb_docs_read": true,
}

func hasNoCLIEquivalent(tool string) bool {
	return toolGroups[tool] == groupDataExplorer || noCLIEquivalentTools[tool]
}

// Tools that only work in one cloud. They are hidden in workspaces on the other
// cloud, or shown everywhere if the workspace's cloud isn't known.
var (
	gcpOnlyTools = map[string]bool{
		"bq_query": true, "bq_execute": true, "gcloud_execute": true, "gsutil_execute": true,
		"resource_create_bucket": true, "resource_create_bq_dataset": true,
	}
	awsOnlyTools = map[string]bool{
		"s3_list_objects": true, "s3_read_file": true, "s3_write_file": true, "s3_copy": true,
		"aurora_query": true, "aurora_list_tables": true, "aurora_describe_table": true,
		"aurora_resolve_connection": true, "resource_create_aurora_database": true,
		"resource_create_s3_folder": true, "resource_create_s3_external_bucket": true,
		"workspace_configure_aws": true,
	}
)

// defaultToolsets is the group list used when a request doesn't specify one.
var defaultToolsets = groupCore

// serverPort is the HTTP port, for the instructions in wb_help.
var serverPort = "9242"

// parseToolsets turns a comma-separated group list into a set. "all" enables
// every group, and core is always enabled. Unknown names are returned separately.
func parseToolsets(spec string) (map[string]bool, []string) {
	enabled := map[string]bool{groupCore: true}
	var unknown []string
	for _, name := range strings.Split(spec, ",") {
		name = strings.ToLower(strings.TrimSpace(name))
		switch {
		case name == "":
		case name == "all":
			for _, g := range toolGroupDescriptions {
				enabled[g.name] = true
			}
		case isToolGroup(name):
			enabled[name] = true
		default:
			unknown = append(unknown, name)
		}
	}
	return enabled, unknown
}

// listensOnLoopback is whether the HTTP server listens only on a loopback address. It is
// set before serving; stdio mode and tests use the loopback behaviour.
var listensOnLoopback = true

// isLoopbackBind reports whether a listen host is a loopback address or "localhost".
// An empty or unparseable host is not loopback.
func isLoopbackBind(host string) bool {
	if strings.EqualFold(host, "localhost") {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

// requestToolsets returns the groups for an HTTP request with this ?toolsets= value. On
// loopback the request chooses; otherwise it can only narrow the configured groups.
func requestToolsets(query string) map[string]bool {
	configured, _ := parseToolsets(defaultToolsets)
	if query == "" {
		return configured
	}
	requested, _ := parseToolsets(query)
	if listensOnLoopback {
		return requested
	}
	for g := range requested {
		if !configured[g] {
			delete(requested, g)
		}
	}
	return requested
}

// toolsetsQueryPolicy says, for the logs and wb_help, what ?toolsets= can do.
func toolsetsQueryPolicy() string {
	if listensOnLoopback {
		return "clients can add ?toolsets="
	}
	return "clients can narrow them with ?toolsets="
}

func isToolGroup(name string) bool {
	for _, g := range toolGroupDescriptions {
		if g.name == name {
			return true
		}
	}
	return false
}

func enabledGroupNames(enabled map[string]bool) string {
	var names []string
	for _, g := range toolGroupDescriptions {
		if enabled[g.name] {
			names = append(names, g.name)
		}
	}
	return strings.Join(names, ",")
}

func currentCloudPlatform() string {
	cacheMu.Lock()
	defer cacheMu.Unlock()
	return cachedCloudPlatform
}

// toolUnavailableReason returns "" if the tool can be called with these groups
// in this cloud, or an explanation the model can pass on to the user.
func toolUnavailableReason(name string, enabled map[string]bool, cloud string) string {
	group, ok := toolGroups[name]
	if !ok {
		return fmt.Sprintf("Unknown tool: %s", name)
	}
	if cloud == "GCP" && awsOnlyTools[name] {
		return fmt.Sprintf("Tool %s only works in AWS workspaces; this workspace is on GCP.", name)
	}
	if cloud == "AWS" && gcpOnlyTools[name] {
		return fmt.Sprintf("Tool %s only works in GCP workspaces; this workspace is on AWS.", name)
	}
	if !enabled[group] && hasNoCLIEquivalent(name) {
		return fmt.Sprintf("Tool %s is in the %q tool group, which isn't enabled (enabled: %s). "+
			"It has no wb CLI equivalent, so wb_execute cannot replace it: the user must enable the %q group "+
			"("+enableHow()+"). "+
			"Call wb_help with topic \"toolsets\" for how.", name, group, enabledGroupNames(enabled), group)
	}
	if !enabled[group] {
		return fmt.Sprintf("Tool %s is in the %q tool group, which isn't enabled (enabled: %s). "+
			"Use the wb CLI through wb_execute instead, or ask the user to enable the group; "+
			"call wb_help with topic \"toolsets\" for how.", name, group, enabledGroupNames(enabled))
	}
	return ""
}

// enableHow says where a group can be enabled.
func enableHow() string {
	if listensOnLoopback {
		return "the server's toolsets setting, or ?toolsets= in the client's server URL"
	}
	return "the server's toolsets setting; ?toolsets= in a client's server URL can only narrow it"
}

// listTools returns the tool definitions available with these groups in this cloud.
func listTools(enabled map[string]bool, cloud string) []Tool {
	var tools []Tool
	for _, t := range wbTools {
		if toolUnavailableReason(t.Name, enabled, cloud) == "" {
			tools = append(tools, t)
		}
	}
	return tools
}

// toolsetsHelp describes the groups for wb_help(topic="toolsets").
func toolsetsHelp(enabled map[string]bool, cloud string) string {
	var b strings.Builder
	fmt.Fprintf(&b, "Enabled tool groups: %s. Workspace cloud: %s.\n\n", enabledGroupNames(enabled), orUnknown(cloud))
	b.WriteString("Groups:\n")
	for _, g := range toolGroupDescriptions {
		var names []string
		for tool, group := range toolGroups {
			if group == g.name {
				names = append(names, tool)
			}
		}
		sort.Strings(names)
		fmt.Fprintf(&b, "- %s: %s\n  Tools: %s\n", g.name, g.description, strings.Join(names, ", "))
	}
	var urlWays string
	if listensOnLoopback {
		urlWays = fmt.Sprintf(`- Claude Code: claude mcp add --transport http wb "http://127.0.0.1:%[1]s/?toolsets=core,dataexplorer"
- Gemini CLI: set mcpServers.wb.url to "http://127.0.0.1:%[1]s/?toolsets=core,dataexplorer" in ~/.gemini/settings.json
`, serverPort)
	} else {
		urlWays = "- A client's ?toolsets= can only narrow the groups the server's toolsets setting enables; it cannot add one.\n"
	}
	fmt.Fprintf(&b, `
To enable more groups (the user must do this; the change applies to new sessions):
%[3]s- Every client of this server: export WB_MCP_TOOLSETS=core,dataexplorer, then run
  /opt/wb-mcp-server/stop-server.sh && /opt/wb-mcp-server/start-server.sh
- stdio clients: start the server with -toolsets=core,dataexplorer
Use "all" for every group.

Most tools outside the enabled groups can be replaced by a wb CLI command through wb_execute. These
have no wb CLI equivalent and are only available when their group is enabled: %[2]s.
`, serverPort, noCLIEquivalentList(), urlWays)
	return b.String()
}

// noCLIEquivalentList names the tools and groups that wb_execute cannot replace.
func noCLIEquivalentList() string {
	var names []string
	for tool := range noCLIEquivalentTools {
		names = append(names, tool)
	}
	sort.Strings(names)
	return "every tool in the " + groupDataExplorer + " group, " + strings.Join(names, ", ")
}

func orUnknown(s string) string {
	if s == "" {
		return "unknown"
	}
	return s
}
