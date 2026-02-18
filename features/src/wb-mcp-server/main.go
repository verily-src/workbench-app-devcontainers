package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"strings"
	"time"
)

// MCP Protocol structures
type JSONRPCRequest struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      interface{}     `json:"id,omitempty"`
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params,omitempty"`
}

type JSONRPCResponse struct {
	JSONRPC string      `json:"jsonrpc"`
	ID      interface{} `json:"id,omitempty"`
	Result  interface{} `json:"result,omitempty"`
	Error   *RPCError   `json:"error,omitempty"`
}

type RPCError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

type InitializeParams struct {
	ProtocolVersion string                 `json:"protocolVersion"`
	Capabilities    map[string]interface{} `json:"capabilities"`
	ClientInfo      ClientInfo             `json:"clientInfo"`
}

type ClientInfo struct {
	Name    string `json:"name"`
	Version string `json:"version"`
}

type ServerInfo struct {
	Name    string `json:"name"`
	Version string `json:"version"`
}

type InitializeResult struct {
	ProtocolVersion string                 `json:"protocolVersion"`
	Capabilities    map[string]interface{} `json:"capabilities"`
	ServerInfo      ServerInfo             `json:"serverInfo"`
}

type ListToolsResult struct {
	Tools []Tool `json:"tools"`
}

type Tool struct {
	Name        string      `json:"name"`
	Description string      `json:"description"`
	InputSchema InputSchema `json:"inputSchema"`
}

type InputSchema struct {
	Type       string                 `json:"type"`
	Properties map[string]interface{} `json:"properties"`
	Required   []string               `json:"required,omitempty"`
}

type CallToolParams struct {
	Name      string                 `json:"name"`
	Arguments map[string]interface{} `json:"arguments,omitempty"`
}

type CallToolResult struct {
	Content []ContentItem `json:"content"`
	IsError bool          `json:"isError,omitempty"`
}

type ContentItem struct {
	Type string `json:"type"`
	Text string `json:"text"`
}

// Global variables
var (
	workspaceBaseURL string
	dataExplorerURL  string
	httpClient       = &http.Client{Timeout: 60 * time.Second}
)

// Tool definitions
var wbTools = []Tool{
	{
		Name:        "wb_status",
		Description: "Get workspace and server status using wb CLI",
		InputSchema: InputSchema{Type: "object", Properties: map[string]interface{}{}},
	},
	{
		Name:        "wb_workspace_list",
		Description: "List all workspaces using wb CLI",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"format": map[string]interface{}{
					"type": "string",
					"enum": []string{"json", "text"},
				},
			},
		},
	},
	{
		Name:        "wb_execute",
		Description: "Execute any wb command (without 'wb' prefix)",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"command": map[string]interface{}{"type": "string"},
			},
			Required: []string{"command"},
		},
	},

	{
		Name:        "workspace_create",
		Description: "Create a new workspace. Use this when user wants to create a new workspace for their research or project. Creates both the workspace metadata and backing cloud resources (e.g., Google Cloud project). Returns the new workspace ID.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"id":          map[string]interface{}{"type": "string", "description": "User-facing workspace ID (must be unique)"},
				"podId":       map[string]interface{}{"type": "string", "description": "Pod ID (required) - get from pod_list"},
				"name":        map[string]interface{}{"type": "string", "description": "Display name for the workspace"},
				"description": map[string]interface{}{"type": "string", "description": "Workspace description"},
				"organizationId": map[string]interface{}{"type": "string", "description": "Organization ID (optional)"},
			},
			Required: []string{"id", "podId"},
		},
	},
	{
		Name:        "workspace_delete",
		Description: "Delete a workspace. Use this when user wants to permanently remove a workspace. WARNING: This deletes all resources in the workspace. Requires OWNER role. User should confirm before executing.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"workspaceId": map[string]interface{}{"type": "string", "description": "User-facing workspace ID to delete"},
			},
			Required: []string{"workspaceId"},
		},
	},
	{
		Name:        "workspace_update",
		Description: "Update workspace metadata (name, description). Use this when user wants to change workspace display name or description without modifying resources.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"workspaceId": map[string]interface{}{"type": "string", "description": "User-facing workspace ID"},
				"name":        map[string]interface{}{"type": "string", "description": "New display name"},
				"description": map[string]interface{}{"type": "string", "description": "New description"},
			},
			Required: []string{"workspaceId"},
		},
	},
	{
		Name:        "workspace_duplicate",
		Description: "Duplicate an existing workspace. Use this when user wants to copy a workspace structure (including resources and folder organization) to a new workspace. Useful for creating similar workspaces or templates.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"sourceWorkspaceId": map[string]interface{}{"type": "string", "description": "Workspace ID to duplicate from"},
				"destWorkspaceId":   map[string]interface{}{"type": "string", "description": "New workspace ID"},
				"name":              map[string]interface{}{"type": "string", "description": "Name for new workspace"},
			},
			Required: []string{"sourceWorkspaceId", "destWorkspaceId"},
		},
	},
	{
		Name:        "workspace_set_property",
		Description: "Set custom properties on a workspace. Use this for adding metadata tags or configuration values. Properties are key-value pairs used for organization, categorization, or workspace configuration.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"workspaceId": map[string]interface{}{"type": "string", "description": "User-facing workspace ID"},
				"key":         map[string]interface{}{"type": "string", "description": "Property key"},
				"value":       map[string]interface{}{"type": "string", "description": "Property value"},
			},
			Required: []string{"workspaceId", "key", "value"},
		},
	},
	{
		Name:        "workspace_delete_property",
		Description: "Delete a custom property from a workspace. Use this to remove previously set metadata or configuration.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"workspaceId": map[string]interface{}{"type": "string", "description": "User-facing workspace ID"},
				"key":         map[string]interface{}{"type": "string", "description": "Property key to delete"},
			},
			Required: []string{"workspaceId", "key"},
		},
	},
	{
		Name:        "workspace_add_user",
		Description: "Grant a user access to a workspace. Use this when sharing a workspace with collaborators. Specify role (READER, WRITER, or OWNER) to control access level. READER can view, WRITER can modify, OWNER can manage users and delete.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"workspaceId": map[string]interface{}{"type": "string", "description": "User-facing workspace ID"},
				"email":       map[string]interface{}{"type": "string", "description": "User email address"},
				"role":        map[string]interface{}{"type": "string", "enum": []string{"READER", "WRITER", "OWNER"}, "description": "Access role"},
			},
			Required: []string{"workspaceId", "email", "role"},
		},
	},
	{
		Name:        "workspace_remove_user",
		Description: "Revoke a user's access to a workspace. Use this to remove collaborators or revoke access. Requires OWNER role.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"workspaceId": map[string]interface{}{"type": "string", "description": "User-facing workspace ID"},
				"email":       map[string]interface{}{"type": "string", "description": "User email to remove"},
			},
			Required: []string{"workspaceId", "email"},
		},
	},
	{
		Name:        "workspace_list_users",
		Description: "List all users with access to a workspace and their roles. Use this to see who has access and what level of permissions they have.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"workspaceId": map[string]interface{}{"type": "string", "description": "User-facing workspace ID"},
			},
			Required: []string{"workspaceId"},
		},
	},

	{
		Name:        "resource_create_bucket",
		Description: "Create a cloud storage bucket in the workspace. Use this when user needs file storage for data, results, or shared files. Creates a managed bucket that workspace users can access based on their roles.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"resourceId":  map[string]interface{}{"type": "string", "description": "Resource ID (used to reference in workspace)"},
				"bucketName":  map[string]interface{}{"type": "string", "description": "Cloud bucket name (globally unique)"},
				"description": map[string]interface{}{"type": "string", "description": "Resource description"},
			},
			Required: []string{"resourceId", "bucketName"},
		},
	},
	{
		Name:        "resource_create_bq_dataset",
		Description: "Create a BigQuery dataset in the workspace. Use this when user needs a database for structured data analysis, SQL queries, or data warehousing.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"resourceId":  map[string]interface{}{"type": "string", "description": "Resource ID"},
				"datasetId":   map[string]interface{}{"type": "string", "description": "BigQuery dataset ID"},
				"description": map[string]interface{}{"type": "string", "description": "Resource description"},
			},
			Required: []string{"resourceId", "datasetId"},
		},
	},
	{
		Name:        "resource_delete",
		Description: "Delete a resource from the workspace. Use this to remove buckets, datasets, or other resources. For controlled resources, this deletes the actual cloud resource. For references, only removes the reference.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"resourceId": map[string]interface{}{"type": "string", "description": "Resource ID to delete"},
			},
			Required: []string{"resourceId"},
		},
	},
	{
		Name:        "resource_update",
		Description: "Update resource metadata (name, description). Use this to change how a resource is displayed or documented without modifying the underlying cloud resource.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"resourceId":  map[string]interface{}{"type": "string", "description": "Resource ID"},
				"name":        map[string]interface{}{"type": "string", "description": "New display name"},
				"description": map[string]interface{}{"type": "string", "description": "New description"},
			},
			Required: []string{"resourceId"},
		},
	},
	{
		Name:        "resource_add_reference",
		Description: "Add a reference to an external cloud resource. Use this when user wants to reference data/resources from outside the workspace (e.g., a bucket in another project, a shared dataset). Creates a pointer without managing the resource.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"resourceId":  map[string]interface{}{"type": "string", "description": "Resource ID for the reference"},
				"resourceType": map[string]interface{}{"type": "string", "enum": []string{"gcs-bucket", "bq-dataset", "bq-table"}, "description": "Type of resource"},
				"path":        map[string]interface{}{"type": "string", "description": "Cloud path (e.g., gs://bucket-name)"},
				"description": map[string]interface{}{"type": "string", "description": "Reference description"},
			},
			Required: []string{"resourceId", "resourceType", "path"},
		},
	},
	{
		Name:        "resource_check_access",
		Description: "Check if current user has access to a resource. Use this to verify permissions before attempting operations. Useful for debugging access issues or validating setup.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"resourceId": map[string]interface{}{"type": "string", "description": "Resource ID to check"},
			},
			Required: []string{"resourceId"},
		},
	},
	{
		Name:        "resource_move",
		Description: "Move a resource to a different folder. Use this for organizing resources into logical groups within a workspace.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"resourceId": map[string]interface{}{"type": "string", "description": "Resource ID to move"},
				"folderId":   map[string]interface{}{"type": "string", "description": "Destination folder ID"},
			},
			Required: []string{"resourceId", "folderId"},
		},
	},

	{
		Name:        "folder_create",
		Description: "Create a folder in the workspace. Use this to organize resources into logical groups (e.g., 'data', 'results', 'notebooks'). Folders help maintain clean workspace organization.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"folderId":    map[string]interface{}{"type": "string", "description": "Folder ID (must be unique in workspace)"},
				"displayName": map[string]interface{}{"type": "string", "description": "Display name for folder"},
				"description": map[string]interface{}{"type": "string", "description": "Folder description"},
				"parentId":    map[string]interface{}{"type": "string", "description": "Parent folder ID (for nested folders)"},
			},
			Required: []string{"folderId", "displayName"},
		},
	},
	{
		Name:        "folder_delete",
		Description: "Delete a folder. Use this to remove folders no longer needed. NOTE: Folder must be empty (move or delete resources first).",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"folderId": map[string]interface{}{"type": "string", "description": "Folder ID to delete"},
			},
			Required: []string{"folderId"},
		},
	},
	{
		Name:        "folder_update",
		Description: "Update folder metadata (name, description). Use this to rename folders or update descriptions for better organization.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"folderId":    map[string]interface{}{"type": "string", "description": "Folder ID"},
				"displayName": map[string]interface{}{"type": "string", "description": "New display name"},
				"description": map[string]interface{}{"type": "string", "description": "New description"},
			},
			Required: []string{"folderId"},
		},
	},
	{
		Name:        "folder_list_tree",
		Description: "Show folder hierarchy as a tree. Use this to visualize workspace organization and understand the folder structure.",
		InputSchema: InputSchema{
			Type:       "object",
			Properties: map[string]interface{}{},
		},
	},
	{
		Name:        "workspace_list_data_collections",
		Description: `List all data collections in the current workspace and their associated resources.

Use this when a user asks:
- "What data collections exist in my workspace?"
- "Show me resources grouped by data collection"
- "Which resources came from which data collections?"

This tool automatically:
1. Gets all resources and identifies their sourceWorkspaceId (where they were cloned from)
2. Looks up each source workspace to get the actual data collection name
3. Groups resources by their source data collection
4. Shows resources created directly in this workspace (no source)

Returns a structured list of data collections with their resources, types, and cloud paths.`,
		InputSchema: InputSchema{
			Type:       "object",
			Properties: map[string]interface{}{},
		},
	},

	{
		Name:        "group_create",
		Description: "Create a user group. Use this when managing multiple users with same access needs. Groups simplify permission management - grant access to group instead of individual users.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"groupId":     map[string]interface{}{"type": "string", "description": "Unique group ID"},
				"name":        map[string]interface{}{"type": "string", "description": "Group display name"},
				"description": map[string]interface{}{"type": "string", "description": "Group description"},
			},
			Required: []string{"groupId", "name"},
		},
	},
	{
		Name:        "group_delete",
		Description: "Delete a user group. Use this to remove groups no longer needed. Users in the group lose group-based permissions.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"groupId": map[string]interface{}{"type": "string", "description": "Group ID to delete"},
			},
			Required: []string{"groupId"},
		},
	},
	{
		Name:        "group_list",
		Description: "List all groups the current user has a role on. Use this to see available groups for permission management.",
		InputSchema: InputSchema{
			Type:       "object",
			Properties: map[string]interface{}{},
		},
	},
	{
		Name:        "group_describe",
		Description: "Get detailed information about a group (members, roles, metadata). Use this to see who belongs to a group and their access levels.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"groupId": map[string]interface{}{"type": "string", "description": "Group ID"},
			},
			Required: []string{"groupId"},
		},
	},
	{
		Name:        "group_add_user",
		Description: "Add a user to a group. Use this when adding collaborators to a group for shared access management.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"groupId": map[string]interface{}{"type": "string", "description": "Group ID"},
				"email":   map[string]interface{}{"type": "string", "description": "User email to add"},
				"role":    map[string]interface{}{"type": "string", "enum": []string{"MEMBER", "ADMIN"}, "description": "Role in group"},
			},
			Required: []string{"groupId", "email", "role"},
		},
	},
	{
		Name:        "group_remove_user",
		Description: "Remove a user from a group. Use this to revoke group membership and associated permissions.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"groupId": map[string]interface{}{"type": "string", "description": "Group ID"},
				"email":   map[string]interface{}{"type": "string", "description": "User email to remove"},
			},
			Required: []string{"groupId", "email"},
		},
	},

	{
		Name:        "app_create",
		Description: "Create a GCP Compute Engine application in the workspace. Use this to launch analysis environments like JupyterLab, RStudio, or VSCode. Applications provide interactive compute environments.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"appId":       map[string]interface{}{"type": "string", "description": "Application ID"},
				"appConfig":   map[string]interface{}{"type": "string", "description": "App config name. Valid values: jupyter-lab, r-analysis, visual-studio-code"},
				"machineType": map[string]interface{}{"type": "string", "description": "Machine type (e.g., 'n1-standard-4')"},
				"description": map[string]interface{}{"type": "string", "description": "Description of the app"},
				"location":    map[string]interface{}{"type": "string", "description": "GCP location/zone"},
			},
			Required: []string{"appId", "appConfig"},
		},
	},
	{
		Name:        "app_delete",
		Description: "Delete an application. Use this to remove applications no longer needed. Stops the application and deletes associated resources.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"appId": map[string]interface{}{"type": "string", "description": "Application ID to delete"},
			},
			Required: []string{"appId"},
		},
	},
	{
		Name:        "app_list",
		Description: "List all applications in the workspace. Use this to see available applications, their status, and configuration.",
		InputSchema: InputSchema{
			Type:       "object",
			Properties: map[string]interface{}{},
		},
	},
	{
		Name:        "app_start",
		Description: "Start a stopped application. Use this to resume an application that was stopped to save costs. Takes a few minutes to become ready.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"appId": map[string]interface{}{"type": "string", "description": "Application ID to start"},
			},
			Required: []string{"appId"},
		},
	},
	{
		Name:        "app_stop",
		Description: "Stop a running application. Use this to pause an application to save compute costs. Data and state are preserved. Can be restarted later.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"appId": map[string]interface{}{"type": "string", "description": "Application ID to stop"},
			},
			Required: []string{"appId"},
		},
	},
	{
		Name:        "app_get_url",
		Description: "Get the launch URL for an application. Use this to get the web address to access a running application (e.g., Jupyter notebook URL).",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"appId": map[string]interface{}{"type": "string", "description": "Application ID"},
			},
			Required: []string{"appId"},
		},
	},

	{
		Name:        "auth_status",
		Description: "Get current authentication status. Use this to check if user is logged in and see which account is active.",
		InputSchema: InputSchema{
			Type:       "object",
			Properties: map[string]interface{}{},
		},
	},

	{
		Name:        "server_list",
		Description: "List all available servers. Use this to see which server environments are available (dev, staging, production).",
		InputSchema: InputSchema{
			Type:       "object",
			Properties: map[string]interface{}{},
		},
	},
	{
		Name:        "server_set",
		Description: "Set which server to connect to. Use this to switch between different environments (e.g., from production to staging for testing).",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"serverName": map[string]interface{}{"type": "string", "description": "Server name to connect to"},
			},
			Required: []string{"serverName"},
		},
	},
	{
		Name:        "server_status",
		Description: "Get server status and details. Use this to check server health and configuration information.",
		InputSchema: InputSchema{
			Type:       "object",
			Properties: map[string]interface{}{},
		},
	},
	{
		Name:        "server_list_regions",
		Description: "List valid cloud regions for a platform. Use this when creating resources to see available regions.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"cloudPlatform": map[string]interface{}{"type": "string", "description": "Cloud platform (e.g., 'gcp', 'azure')"},
			},
			Required: []string{"cloudPlatform"},
		},
	},

	{
		Name:        "pod_list",
		Description: "List all pods. Use this to see available pods (environments/tenants) and their details.",
		InputSchema: InputSchema{
			Type:       "object",
			Properties: map[string]interface{}{},
		},
	},
	{
		Name:        "pod_describe",
		Description: "Get detailed information about a pod. Use this to see pod configuration, users, and settings.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"podId": map[string]interface{}{"type": "string", "description": "Pod ID"},
			},
			Required: []string{"podId"},
		},
	},
	{
		Name:        "pod_role_list",
		Description: "List all user roles in a pod. Use this to see who has access to a pod and their permission levels.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"organizationId": map[string]interface{}{"type": "string", "description": "Organization ID"},
				"podId":          map[string]interface{}{"type": "string", "description": "Pod ID"},
			},
			Required: []string{"organizationId", "podId"},
		},
	},
	{
		Name:        "pod_role_grant",
		Description: "Grant a user a role in a pod. Use this when adding users to a pod with specific permissions.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"organizationId": map[string]interface{}{"type": "string", "description": "Organization ID"},
				"podId":          map[string]interface{}{"type": "string", "description": "Pod ID"},
				"email":          map[string]interface{}{"type": "string", "description": "User email"},
				"role":           map[string]interface{}{"type": "string", "description": "Role to grant (ADMIN, USER, SUPPORT)"},
			},
			Required: []string{"organizationId", "podId", "email", "role"},
		},
	},
	{
		Name:        "pod_role_revoke",
		Description: "Revoke a user's role in a pod. Use this to remove a user's access to a pod.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"organizationId": map[string]interface{}{"type": "string", "description": "Organization ID"},
				"podId":          map[string]interface{}{"type": "string", "description": "Pod ID"},
				"email":          map[string]interface{}{"type": "string", "description": "User email"},
				"role":           map[string]interface{}{"type": "string", "description": "Role to revoke (ADMIN, USER, SUPPORT)"},
			},
			Required: []string{"organizationId", "podId", "email", "role"},
		},
	},

	{
		Name:        "organization_list",
		Description: "List all organizations. Use this to see available organizations and their details.",
		InputSchema: InputSchema{
			Type:       "object",
			Properties: map[string]interface{}{},
		},
	},

	{
		Name:        "resource_credentials",
		Description: "Get temporary credentials for accessing a cloud resource. Use this when you need programmatic access credentials (e.g., for scripts, external tools).",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"resourceId": map[string]interface{}{"type": "string", "description": "Resource ID"},
				"duration":   map[string]interface{}{"type": "integer", "description": "Credential duration in seconds"},
			},
			Required: []string{"resourceId"},
		},
	},
	{
		Name:        "resource_open_console",
		Description: "Get cloud console link for a resource. Use this to provide users with a web link to view/manage the resource in the cloud provider's console.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"resourceId": map[string]interface{}{"type": "string", "description": "Resource ID"},
			},
			Required: []string{"resourceId"},
		},
	},
	{
		Name:        "resource_list_tree",
		Description: "List resources in tree view showing folder hierarchy. Use this to visualize workspace organization with resources grouped by folders.",
		InputSchema: InputSchema{
			Type:       "object",
			Properties: map[string]interface{}{},
		},
	},
	{
		Name:        "resource_mount",
		Description: "Mount workspace bucket resources to local filesystem. Use this when user needs to access bucket contents as if they were local files.",
		InputSchema: InputSchema{
			Type:       "object",
			Properties: map[string]interface{}{},
		},
	},
	{
		Name:        "resource_unmount",
		Description: "Unmount workspace bucket resources. Use this to disconnect previously mounted buckets from local filesystem.",
		InputSchema: InputSchema{
			Type:       "object",
			Properties: map[string]interface{}{},
		},
	},

	{
		Name:        "notebook_start",
		Description: "Start a stopped notebook instance. Use this to resume a notebook that was stopped to save costs. Convenience wrapper for app start.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"notebookId": map[string]interface{}{"type": "string", "description": "Notebook instance ID"},
			},
			Required: []string{"notebookId"},
		},
	},
	{
		Name:        "notebook_stop",
		Description: "Stop a running notebook instance. Use this to pause a notebook to save compute costs. Convenience wrapper for app stop.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"notebookId": map[string]interface{}{"type": "string", "description": "Notebook instance ID"},
			},
			Required: []string{"notebookId"},
		},
	},
	{
		Name:        "notebook_launch",
		Description: "Launch a running notebook instance. Use this to get the URL and open a notebook. Convenience wrapper for app launch.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"notebookId": map[string]interface{}{"type": "string", "description": "Notebook instance ID"},
			},
			Required: []string{"notebookId"},
		},
	},

	{
		Name:        "cluster_start",
		Description: "Start a stopped Dataproc cluster. Use this to resume a Spark cluster that was stopped to save costs.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"clusterId": map[string]interface{}{"type": "string", "description": "Cluster ID"},
			},
			Required: []string{"clusterId"},
		},
	},
	{
		Name:        "cluster_stop",
		Description: "Stop a running Dataproc cluster. Use this to pause a Spark cluster to save compute costs.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"clusterId": map[string]interface{}{"type": "string", "description": "Cluster ID"},
			},
			Required: []string{"clusterId"},
		},
	},
	{
		Name:        "cluster_launch",
		Description: "Launch Dataproc cluster proxy view. Use this to get the URL for accessing cluster monitoring and Spark UI.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"clusterId": map[string]interface{}{"type": "string", "description": "Cluster ID"},
			},
			Required: []string{"clusterId"},
		},
	},

	{
		Name:        "workflow_list",
		Description: "List all workflows. Use this to see available workflows in the workspace.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"workspaceId": map[string]interface{}{"type": "string", "description": "Workspace ID"},
			},
			Required: []string{"workspaceId"},
		},
	},
	{
		Name:        "workflow_create",
		Description: "Create a new workflow. Use this when user wants to set up a workflow for data processing or analysis pipelines.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"workspaceId":  map[string]interface{}{"type": "string", "description": "Workspace ID"},
				"workflowId":   map[string]interface{}{"type": "string", "description": "Workflow ID"},
				"bucketId":     map[string]interface{}{"type": "string", "description": "BUCKET NAME (not UUID) - e.g., 'cohort_exports'. Get from workspace_list_resources metadata.name field."},
				"path":         map[string]interface{}{"type": "string", "description": "Path to workflow definition file in bucket (e.g., 'workflows/myworkflow.wdl')"},
				"displayName":  map[string]interface{}{"type": "string", "description": "Workflow display name"},
				"description":  map[string]interface{}{"type": "string", "description": "Description of the workflow"},
			},
			Required: []string{"workspaceId", "workflowId", "bucketId", "path"},
		},
	},
	{
		Name:        "workflow_describe",
		Description: "Get detailed information about a workflow. Use this to see workflow configuration and status.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"workspaceId": map[string]interface{}{"type": "string", "description": "Workspace ID"},
				"workflowId":  map[string]interface{}{"type": "string", "description": "Workflow ID"},
			},
			Required: []string{"workspaceId", "workflowId"},
		},
	},
	{
		Name:        "workflow_job_list",
		Description: "List all workflow jobs. Use this to see job history, status, and details.",
		InputSchema: InputSchema{
			Type:       "object",
			Properties: map[string]interface{}{},
		},
	},
	{
		Name:        "workflow_job_describe",
		Description: "Get detailed information about a workflow job. Use this to see job configuration, status, inputs, and outputs.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"workspaceId": map[string]interface{}{"type": "string", "description": "Workspace ID"},
				"jobId":       map[string]interface{}{"type": "string", "description": "Job ID"},
			},
			Required: []string{"workspaceId", "jobId"},
		},
	},
	{
		Name:        "workflow_job_run",
		Description: "Start a workflow job. Use this to execute a workflow with specific inputs.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"workspaceId":      map[string]interface{}{"type": "string", "description": "Workspace ID"},
				"workflowId":       map[string]interface{}{"type": "string", "description": "Workflow ID"},
				"outputBucketId":   map[string]interface{}{"type": "string", "description": "BUCKET NAME (not UUID) for outputs - e.g., 'cohort_exports'"},
				"jobId":            map[string]interface{}{"type": "string", "description": "Optional job ID"},
				"description":      map[string]interface{}{"type": "string", "description": "Job description"},
				"outputPath":       map[string]interface{}{"type": "string", "description": "Output path in bucket"},
				"inputs":           map[string]interface{}{"type": "object", "description": "Job inputs as key-value pairs"},
			},
			Required: []string{"workspaceId", "workflowId", "outputBucketId"},
		},
	},
	{
		Name:        "workflow_job_cancel",
		Description: "Cancel a running workflow job. Use this to stop a job that is in progress.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"workspaceId": map[string]interface{}{"type": "string", "description": "Workspace ID"},
				"jobId":       map[string]interface{}{"type": "string", "description": "Job ID"},
			},
			Required: []string{"workspaceId", "jobId"},
		},
	},

	{
		Name:        "cromwell_generate_config",
		Description: "Generate Cromwell configuration file. Use this when setting up Cromwell workflows to create the required config file.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"path": map[string]interface{}{"type": "string", "description": "Output path for cromwell.conf"},
			},
			Required: []string{"path"},
		},
	},
	{
		Name:        "workspace_configure_aws",
		Description: "Generate AWS configuration file for workspace. Use this when workspace needs to access AWS resources.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"workspaceId": map[string]interface{}{"type": "string", "description": "Workspace ID"},
			},
			Required: []string{"workspaceId"},
		},
	},
	{
		Name:        "resolve",
		Description: "Resolve a resource to its cloud ID or path. Use this to get the actual cloud identifier (bucket name, dataset ID, etc.) for a workspace resource.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"resourceId": map[string]interface{}{"type": "string", "description": "Resource ID to resolve"},
			},
			Required: []string{"resourceId"},
		},
	},
	{
		Name:        "version",
		Description: "Get the installed wb CLI version. Use this to check which version is installed or for troubleshooting.",
		InputSchema: InputSchema{
			Type:       "object",
			Properties: map[string]interface{}{},
		},
	},

	{
		Name:        "bq_execute",
		Description: "Execute BigQuery command in workspace context. Use this to run bq CLI commands with workspace's BigQuery access.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"command": map[string]interface{}{"type": "string", "description": "BigQuery command (without 'bq' prefix)"},
			},
			Required: []string{"command"},
		},
	},
	{
		Name:        "gcloud_execute",
		Description: "Execute gcloud command in workspace context. Use this to run gcloud CLI commands with workspace's GCP project.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"command": map[string]interface{}{"type": "string", "description": "gcloud command (without 'gcloud' prefix)"},
			},
			Required: []string{"command"},
		},
	},
	{
		Name:        "gsutil_execute",
		Description: "Execute gsutil command in workspace context. Use this to run gsutil CLI commands for GCS operations.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"command": map[string]interface{}{"type": "string", "description": "gsutil command (without 'gsutil' prefix)"},
			},
			Required: []string{"command"},
		},
	},
	{
		Name:        "git_execute",
		Description: "Execute git command in workspace context. Use this for git operations within workspace.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"command": map[string]interface{}{"type": "string", "description": "git command (without 'git' prefix)"},
			},
			Required: []string{"command"},
		},
	},

	{
		Name:        "workspace_list_all",
		Description: "List all workspaces with optional property filters. Use properties={'terra-type': 'data-collection'} to find data collections with underlays, properties={'terra-dx-underlay-name': '<name>'} to filter by underlay",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"properties": map[string]interface{}{"type": "object"},
				"limit":      map[string]interface{}{"type": "integer", "default": 100},
				"offset":     map[string]interface{}{"type": "integer", "default": 0},
			},
		},
	},
	{
		Name:        "workspace_get",
		Description: "Get workspace details by ID. workspaceId is the user-facing ID (e.g., 'test-1599'), not the UUID.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"workspaceId": map[string]interface{}{"type": "string", "description": "User-facing workspace ID (e.g., 'test-1599')"},
			},
			Required: []string{"workspaceId"},
		},
	},
	{
		Name:        "workspace_list_resources",
		Description: "List all resources in a workspace including cohorts, buckets, datasets, etc. workspaceId is the user-facing ID (e.g., 'test-1599'), not the UUID.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"workspaceId": map[string]interface{}{"type": "string", "description": "User-facing workspace ID (e.g., 'test-1599')"},
				"offset":      map[string]interface{}{"type": "integer", "default": 0},
				"limit":       map[string]interface{}{"type": "integer", "default": 100},
			},
			Required: []string{"workspaceId"},
		},
	},

	{
		Name:        "underlay_list",
		Description: "List all available underlays",
		InputSchema: InputSchema{Type: "object", Properties: map[string]interface{}{}},
	},
	{
		Name:        "underlay_get_schema",
		Description: "Get complete underlay schema with entities and attributes. This returns the raw schema. For cohort building, use underlay_list_criteria_selectors instead to get available criteria selectors.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"underlayName": map[string]interface{}{"type": "string"},
			},
			Required: []string{"underlayName"},
		},
	},
	{
		Name:        "underlay_list_entities",
		Description: "List all entities in an underlay (e.g., Person, Condition)",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"underlayName": map[string]interface{}{"type": "string"},
			},
			Required: []string{"underlayName"},
		},
	},
	{
		Name:        "underlay_get_entity",
		Description: "Get entity details including attributes and relationships",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"underlayName": map[string]interface{}{"type": "string"},
				"entityName":   map[string]interface{}{"type": "string"},
			},
			Required: []string{"underlayName", "entityName"},
		},
	},
	{
		Name: "underlay_list_criteria_selectors",
		Description: `STEP 1 of cohort creation: Discover available criteria selectors for an underlay.

Returns array of selectors, each with:
- name: Selector name (use in selectorOrModifierName)
- plugin: Plugin type (use in pluginName)
- pluginConfig: JSON string (copy to uiConfig when building criteria)
- category: Display category
- displayName: Human-readable name

EXTRACT from each selector:
1. selector.name → save for selectorOrModifierName
2. selector.plugin → save for pluginName
3. selector.pluginConfig → save as uiConfig (keep as JSON string)

For "entityGroup" plugin selectors:
- Parse pluginConfig to extract classificationEntityGroups[0].id (e.g., "currentDiagnosesPerson")
- This is the entityGroup value needed in selectionData
- Parse columns to find entity's ID field name for data_query_hints

COMPLETE COHORT WORKFLOW:
STEP 1: Call underlay_list_criteria_selectors(underlayName) → get selectors
STEP 2: Call cohort_create_in_workspace(workspaceId, underlayId, underlayName, name) WITHOUT criteriaJson → creates cohort with all participants
STEP 3: Extract studyId and cohortId from response
STEP 4: Call data_query_hints(studyId, cohortId, entityName) → get entity codes/values AND numeric ranges
STEP 5: Build criteriaJson using selector info + codes/ranges from hints
STEP 6: Call cohort_update_criteria(studyId, cohortId, criteriaJson) → apply filters

LEARNING CORRECT FORMATS:
Use study_list_cohorts to examine existing cohorts and see their actual criteriaGroupSections.
This is the BEST way to learn correct selectionData formats for each plugin type.

selectionData format by plugin type (see proto definitions in data-explorer repo):
- "attribute": {"dataRanges":[{"min":<number>,"max":<number>}]} - BOTH min and max required as numbers
- "entityGroup": {"selected": [{"key": {"int64Key": <code>}, "name": "<name>", "entityGroup": "<groupId>"}]}
- "multiAttribute": {"selected": [{"attribute": "<attr>", "dataRanges": [{"min":<number>,"max":<number>}]}]}`,
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"underlayName": map[string]interface{}{"type": "string", "description": "Underlay name"},
			},
			Required: []string{"underlayName"},
		},
	},

	{
		Name: "data_query_hints",
		Description: `STEP 4 of cohort workflow: Discover entity codes, value distributions, and numeric ranges.

Use this to find:
1. Entity codes for entityGroup filters (diagnosis IDs, medication IDs, etc.)
2. Enum values for categorical attributes
3. Numeric ranges (min/max) for numeric attributes like age

INPUT:
- studyId, cohortId: From cohort_create_in_workspace response
- entityName: Entity to query (e.g., "person", "diagnoses", "medications")

RESPONSE STRUCTURE - displayHints array with elements containing:
{
  "attribute": {"name": "<attr_name>", "dataType": "INT64|STRING|..."},
  "displayHint": {
    "numericRangeHint": {"min": <number>, "max": <number>}  // For numeric attributes
    OR
    "enumHint": {"enumHintValues": [...]}  // For categorical attributes
  }
}

CRITICAL: For numeric attributes (like age):
- Response includes "numericRangeHint" with actual data min/max values
- Use these EXACT min/max values in your selectionData dataRanges
- BOTH min and max are REQUIRED in dataRanges (see DataRange proto)
- Adjust min or max to create your filter (e.g., if max=92, use min=66,max=92 for "over 65")

For entityGroup attributes:
- Look for instances with ID fields
- Extract ID value for int64Key and name for display

After getting hints, proceed to STEP 5: Build criteriaJson, then STEP 6: cohort_update_criteria.`,
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"studyId":    map[string]interface{}{"type": "string", "description": "From cohort_create_in_workspace response"},
				"cohortId":   map[string]interface{}{"type": "string", "description": "From cohort_create_in_workspace response"},
				"entityName": map[string]interface{}{"type": "string", "description": "Entity name (e.g., 'diagnoses', 'medications', 'person')"},
			},
			Required: []string{"studyId", "cohortId", "entityName"},
		},
	},
	{
		Name:        "data_sample_instances",
		Description: "Sample actual data from an entity with optional filters",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"studyId":           map[string]interface{}{"type": "string"},
				"cohortId":          map[string]interface{}{"type": "string"},
				"entityName":        map[string]interface{}{"type": "string"},
				"includeAttributes": map[string]interface{}{"type": "array", "items": map[string]interface{}{"type": "string"}},
				"filter":            map[string]interface{}{"type": "object"},
				"limit":             map[string]interface{}{"type": "integer", "default": 50},
			},
			Required: []string{"studyId", "cohortId", "entityName"},
		},
	},
	{
		Name: "study_list",
		Description: `List all Data Explorer studies. Use this to find studyId for existing cohorts.

WHEN TO USE:
- When you need to find studyId/cohortId for an existing cohort
- When you want to see what studies exist in the workspace
- BEFORE calling data_query_hints or cohort_update_criteria on existing cohorts

RESPONSE contains array of studies with:
- id: The studyId (UUID) needed for other API calls
- displayName: Usually "Workspace: <workspace-uuid>"
- properties.externalId: The workspace UUID
- created, createdBy, lastModified, lastModifiedBy

WORKFLOW to find existing cohort IDs:
1. Call study_list to get all studies
2. For each study, call study_list_cohorts(studyId) to list cohorts
3. Find cohort by displayName or underlayName
4. Extract studyId and cohortId for use in other tools`,
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"offset": map[string]interface{}{"type": "integer", "default": 0, "description": "Number of items to skip"},
				"limit":  map[string]interface{}{"type": "integer", "default": 50, "description": "Maximum items to return"},
			},
		},
	},
	{
		Name: "study_list_cohorts",
		Description: `List all cohorts in a Data Explorer study. Use this to find cohortId and view actual criteria.

WHEN TO USE:
- After calling study_list to get a studyId
- When you want to see what cohorts exist in a study
- When you want to examine the actual criteriaGroupSections used in existing cohorts
- To learn correct selectionData formats by looking at working cohorts

RESPONSE contains array of cohorts with:
- id: The cohortId (UUID) needed for data_query_hints, cohort_update_criteria
- underlayName: Which underlay this cohort uses
- displayName: Human-readable cohort name
- description: Cohort description
- criteriaGroupSections: The ACTUAL criteria used (great for learning correct formats!)
- created, createdBy, lastModified, lastModifiedBy

LEARNING FROM EXISTING COHORTS:
The response shows the exact criteriaGroupSections that work. Look at:
- selectionData format for each plugin type
- How selectorOrModifierName is used
- How uiConfig is structured
This is the BEST way to learn correct formats - copy from working cohorts!

WORKFLOW:
1. Call study_list to get studyId
2. Call THIS tool with studyId to list cohorts
3. Extract cohortId for the cohort you want to work with
4. Optionally: Study the criteriaGroupSections to learn correct formats`,
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"studyId": map[string]interface{}{"type": "string", "description": "Study ID from study_list"},
				"offset":  map[string]interface{}{"type": "integer", "default": 0, "description": "Number of items to skip"},
				"limit":   map[string]interface{}{"type": "integer", "default": 50, "description": "Maximum items to return"},
			},
			Required: []string{"studyId"},
		},
	},

	{
		Name: "cohort_create_in_workspace",
		Description: `STEP 2 of cohort workflow: Create cohort in workspace.

TWO MODES:
1. WITHOUT criteriaJson (RECOMMENDED for new underlays): Creates cohort with all participants
   - Use this to create initial cohort for discovering entity codes
   - Then use data_query_hints to get codes
   - Then use cohort_update_criteria to apply filters

2. WITH criteriaJson: Creates cohort with filters already applied
   - Only use if you already know all selector names and entity codes

RESPONSE contains studyId and cohortId at top level:
{
  "studyId": "abc-123",
  "cohortId": "def-456",
  "resourceId": "...",
  ...
}

Extract these for next steps:
- studyId: Needed for data_query_hints and cohort_update_criteria
- cohortId: Needed for data_query_hints and cohort_update_criteria

RECOMMENDED WORKFLOW (for unknown underlay):
1. Call underlay_list_criteria_selectors → get selectors
2. Call THIS tool WITHOUT criteriaJson → creates "all participants" cohort
3. Extract studyId and cohortId from response
4. Call data_query_hints(studyId, cohortId, entityName) → get entity codes
5. Build criteriaJson with discovered selectors and codes
6. Call cohort_update_criteria(studyId, cohortId, criteriaJson) → apply filters

criteriaJson structure (if providing):
{
  "criteriaGroupSections": [{
    "id": "section-id",
    "displayName": "Section Name",
    "disabled": false,
    "operator": "AND",
    "excluded": false,
    "firstBlockReducingOperator": "ANY",
    "secondBlockReducingOperator": "ANY",
    "secondBlockCriteriaGroups": [],
    "criteriaGroups": [{
      "id": "group-id",
      "disabled": false,
      "criteria": [{
        "id": "criteria-id",
        "pluginName": "<from-selector.plugin>",
        "selectorOrModifierName": "<from-selector.name>",
        "selectionData": "<json-string-escaped>",
        "uiConfig": "<from-selector.pluginConfig-escaped>",
        "pluginVersion": 0,
        "tags": {},
        "enabled": true
      }]
    }]
  }]
}

Each criterion in separate criteriaGroup. See underlay_list_criteria_selectors for selectionData formats.
Use study_list_cohorts to examine working cohorts and learn correct formats by example.`,
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"workspaceId":  map[string]interface{}{"type": "string", "description": "User-facing workspace ID (e.g., 'test-1599')"},
				"underlayId":   map[string]interface{}{"type": "string"},
				"underlayName": map[string]interface{}{"type": "string"},
				"name":         map[string]interface{}{"type": "string"},
				"displayName":  map[string]interface{}{"type": "string"},
				"description":  map[string]interface{}{"type": "string"},
				"criteriaJson": map[string]interface{}{"type": "string", "description": "Complete criteriaGroupSections JSON (see tool description for required structure)"},
				"folderId":     map[string]interface{}{"type": "string"},
			},
			Required: []string{"workspaceId", "underlayId", "underlayName", "name"},
		},
	},
	{
		Name: "cohort_update_criteria",
		Description: `STEP 6 of cohort workflow: Apply filter criteria to existing cohort.

This is the final step after discovering selectors, creating initial cohort, and querying entity codes.

INPUT:
- studyId, cohortId: From cohort_create_in_workspace response
- criteriaGroupSections: Array of criteria group sections (see structure below)

BUILD criteriaGroupSections array:
[{
  "id": "section-1",
  "displayName": "Filters",
  "disabled": false,
  "operator": "AND",
  "excluded": false,
  "firstBlockReducingOperator": "ANY",
  "secondBlockReducingOperator": "ANY",
  "secondBlockCriteriaGroups": [],
  "criteriaGroups": [
    {
      "id": "group-1",
      "disabled": false,
      "criteria": [{
        "id": "crit-1",
        "pluginName": "<from-selector.plugin>",
        "selectorOrModifierName": "<from-selector.name>",
        "selectionData": "<escaped-json>",
        "uiConfig": "<from-selector.pluginConfig-escaped>",
        "pluginVersion": 0,
        "tags": {},
        "enabled": true
      }]
    }
  ]
}]

BUILDING selectionData by plugin type:
1. "attribute" plugin (numeric attributes like age):
   - Format: "{\"dataRanges\":[{\"min\":66,\"max\":92}]}"
   - BOTH min and max REQUIRED as numbers (not strings)
   - Get min/max from data_query_hints numericRangeHint response
   - Escape as JSON string when putting in criteria

2. "entityGroup" plugin (diagnoses, medications):
   - Use codes from data_query_hints response
   - Format: "{\"selected\":[{\"key\":{\"int64Key\":CODE},\"name\":\"NAME\",\"entityGroup\":\"GROUP_ID\"}]}"
   - int64Key value must be NUMBER not string
   - entityGroup ID from selector's pluginConfig classificationEntityGroups[0].id

3. "multiAttribute" plugin:
   - Format: "{\"selected\":[{\"attribute\":\"ATTR\",\"dataRanges\":[{\"min\":NUM,\"max\":NUM}]}]}"
   - For categorical: "{\"selected\":[{\"attribute\":\"ATTR\",\"values\":[{\"value\":{\"stringVal\":\"VALUE\"}}]}]}"

CRITICAL:
- Each criterion goes in its own criteriaGroup. Operator "AND" means all groups must match.
- Use study_list_cohorts to examine working cohorts and learn correct formats.`,
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"studyId":               map[string]interface{}{"type": "string", "description": "From cohort_create_in_workspace response"},
				"cohortId":              map[string]interface{}{"type": "string", "description": "From cohort_create_in_workspace response"},
				"criteriaGroupSections": map[string]interface{}{"type": "array", "description": "Array of criteria group sections"},
				"displayName":           map[string]interface{}{"type": "string", "description": "Optional: Update cohort display name"},
				"description":           map[string]interface{}{"type": "string", "description": "Optional: Update cohort description"},
			},
			Required: []string{"studyId", "cohortId"},
		},
	},
	{
		Name:        "cohort_count_instances",
		Description: "Count instances matching cohort criteria",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"studyId":           map[string]interface{}{"type": "string"},
				"cohortId":          map[string]interface{}{"type": "string"},
				"entity":            map[string]interface{}{"type": "string"},
				"groupByAttributes": map[string]interface{}{"type": "array", "items": map[string]interface{}{"type": "string"}},
			},
			Required: []string{"studyId", "cohortId"},
		},
	},

	{
		Name: "export_list_models",
		Description: `List available export models for an underlay.

Export models define how cohort data can be exported to different formats (CSV, IPYNB, etc.).

RESPONSE contains array of export models with:
- name: Export model identifier (use in export_cohort)
- displayName: Human-readable name
- description: What this export model does
- numPrimaryEntityCap: Maximum number of entities that can be exported`,
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"underlayName": map[string]interface{}{"type": "string", "description": "Underlay name"},
			},
			Required: []string{"underlayName"},
		},
	},
	{
		Name: "export_describe",
		Description: `Describe what will be included in a cohort export.

Shows which entities and attributes will be exported based on cohort variable set or all criteria.

INPUT:
- studyId, cohortId: From cohort_create_in_workspace
- allCriteriaFromCohort: If true, exports all criteria; if false (default), exports variable set`,
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"studyId":                map[string]interface{}{"type": "string", "description": "From cohort_create_in_workspace"},
				"cohortId":               map[string]interface{}{"type": "string", "description": "From cohort_create_in_workspace"},
				"allCriteriaFromCohort":  map[string]interface{}{"type": "boolean", "description": "Export all criteria (true) or variable set (false)"},
			},
			Required: []string{"studyId", "cohortId"},
		},
	},
	{
		Name: "export_preview",
		Description: `Preview what data will be exported before running the actual export.

Shows sample instances that will be included in the export.

INPUT:
- studyId, cohortId: From cohort_create_in_workspace
- exportModel: Export model name from export_list_models
- entityName: Entity to preview (e.g., "person", "diagnoses")
- limit: Max instances to preview (default: 20, max: 20)
- inputs: Optional parameters required by export model`,
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"studyId":     map[string]interface{}{"type": "string", "description": "From cohort_create_in_workspace"},
				"cohortId":    map[string]interface{}{"type": "string", "description": "From cohort_create_in_workspace"},
				"exportModel": map[string]interface{}{"type": "string", "description": "Export model name from export_list_models"},
				"entityName":  map[string]interface{}{"type": "string", "description": "Entity to preview"},
				"limit":       map[string]interface{}{"type": "integer", "description": "Max instances (default: 20)", "maximum": 20},
				"inputs":      map[string]interface{}{"type": "object", "description": "Export model input parameters"},
			},
			Required: []string{"studyId", "cohortId"},
		},
	},
	{
		Name: "export_cohort",
		Description: `Export cohort data using specified export model.

Creates downloadable files (CSV, IPYNB, etc.) with cohort data.

INPUT:
- studyId, cohortId: From cohort_create_in_workspace
- exportRequests: Array of export requests, each with:
  - exportModel: Model name from export_list_models (REQUIRED)
  - inputs: Model-specific parameters (optional)
  - includeAnnotations: Include review annotations (default: true)
  - compressFiles: Compress output files (default: true)

RESPONSE contains array of export results with:
- status: "SUCCEEDED" or "FAILED"
- links: Download URLs for exported files
- error: Error message if failed

WORKFLOW:
1. Call export_list_models to see available models
2. Call export_preview to preview what will be exported
3. Call THIS tool to create the export
4. Use links from response to download files`,
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"studyId":        map[string]interface{}{"type": "string", "description": "From cohort_create_in_workspace"},
				"cohortId":       map[string]interface{}{"type": "string", "description": "From cohort_create_in_workspace"},
				"exportRequests": map[string]interface{}{
					"type": "array",
					"description": "Array of export requests",
					"items": map[string]interface{}{
						"type": "object",
						"properties": map[string]interface{}{
							"exportModel":         map[string]interface{}{"type": "string", "description": "Export model name"},
							"inputs":              map[string]interface{}{"type": "object", "description": "Model input parameters"},
							"includeAnnotations":  map[string]interface{}{"type": "boolean", "default": true},
							"compressFiles":       map[string]interface{}{"type": "boolean", "default": true},
						},
						"required": []string{"exportModel"},
					},
				},
			},
			Required: []string{"studyId", "cohortId", "exportRequests"},
		},
	},

	{
		Name:        "filter_build_attribute",
		Description: "Build attribute filter (e.g., age > 65). For cohort creation, use the criteriaGroupSections structure in cohort_create_in_workspace.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"attribute": map[string]interface{}{"type": "string"},
				"operator":  map[string]interface{}{"type": "string", "enum": []string{"EQUALS", "NOT_EQUALS", "LESS_THAN", "GREATER_THAN", "LESS_THAN_OR_EQUAL", "GREATER_THAN_OR_EQUAL", "IN", "NOT_IN", "BETWEEN", "IS_NULL", "IS_NOT_NULL"}},
				"value":     map[string]interface{}{},
				"values":    map[string]interface{}{"type": "array"},
				"dataType":  map[string]interface{}{"type": "string", "enum": []string{"BOOLEAN", "INT64", "STRING", "DATE", "TIMESTAMP", "DOUBLE"}},
			},
			Required: []string{"attribute", "operator", "dataType"},
		},
	},
	{
		Name:        "filter_build_relationship",
		Description: "Build relationship filter (e.g., persons with condition). For cohort creation, use the criteriaGroupSections structure in cohort_create_in_workspace.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"relatedEntity": map[string]interface{}{"type": "string"},
				"subfilter":     map[string]interface{}{"type": "object"},
			},
			Required: []string{"relatedEntity"},
		},
	},
	{
		Name:        "filter_build_boolean_logic",
		Description: "Combine filters with AND/OR/NOT. For cohort creation, use the criteriaGroupSections structure in cohort_create_in_workspace.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"operator":   map[string]interface{}{"type": "string", "enum": []string{"AND", "OR", "NOT"}},
				"subfilters": map[string]interface{}{"type": "array"},
			},
			Required: []string{"operator", "subfilters"},
		},
	},
	{
		Name:        "filter_build_hierarchy",
		Description: "Build hierarchy filter (e.g., all descendants of concept). For cohort creation, use the criteriaGroupSections structure in cohort_create_in_workspace.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"hierarchy": map[string]interface{}{"type": "string"},
				"operator":  map[string]interface{}{"type": "string", "enum": []string{"CHILD_OF", "DESCENDANT_OF_INCLUSIVE", "IS_ROOT", "IS_MEMBER", "IS_LEAF"}},
				"values":    map[string]interface{}{"type": "array"},
			},
			Required: []string{"hierarchy", "operator"},
		},
	},
}

func initializeConfig() error {
	cmd := exec.Command("wb", "status", "--format=json")
	output, err := cmd.CombinedOutput()
	if err != nil {
		// Fallback to production Verily URLs
		workspaceBaseURL = "https://workbench.verily.com/api/wsm"
		dataExplorerURL = "https://workbench.verily.com/api/de"
	} else {
		var status map[string]interface{}
		if err := json.Unmarshal(output, &status); err == nil {
			if server, ok := status["server"].(map[string]interface{}); ok {
				// Get workspaceManagerUri from wb status output
				if wsURL, ok := server["workspaceManagerUri"].(string); ok {
					workspaceBaseURL = wsURL
					// Derive dataExplorerUri from workspaceManagerUri
					// Pattern: replace /api/wsm with /api/de
					dataExplorerURL = strings.Replace(wsURL, "/api/wsm", "/api/de", 1)
				} else {
					// Fallback to production Verily URLs
					workspaceBaseURL = "https://workbench.verily.com/api/wsm"
					dataExplorerURL = "https://workbench.verily.com/api/de"
				}
			}
		}
	}

	fmt.Fprintf(os.Stderr, "Initialized - Workspace: %s, DataExplorer: %s\n", workspaceBaseURL, dataExplorerURL)
	return nil
}

func getToken() (string, error) {
	cmd := exec.Command("wb", "auth", "print-access-token")
	output, err := cmd.CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("failed to get access token: %v", err)
	}
	return strings.TrimSpace(string(output)), nil
}

func resolveWorkspaceId(workspaceId string) (string, error) {
	listUrl := fmt.Sprintf("%s/api/workspaces/v1?offset=0&limit=5000", workspaceBaseURL)
	listResp, apiErr := makeAPIRequest("GET", listUrl, nil)
	if apiErr != nil {
		return "", fmt.Errorf("failed to list workspaces: %w", apiErr)
	}
	var listData map[string]interface{}
	if err := json.Unmarshal(listResp, &listData); err != nil {
		return "", fmt.Errorf("error parsing workspace list: %v", err)
	}
	workspaces, ok := listData["workspaces"].([]interface{})
	if !ok {
		return "", fmt.Errorf("workspaces not found in list response")
	}
	for _, ws := range workspaces {
		wsMap, ok := ws.(map[string]interface{})
		if !ok {
			continue
		}
		if wsMap["userFacingId"].(string) == workspaceId || wsMap["id"].(string) == workspaceId {
			return wsMap["id"].(string), nil
		}
	}
	return "", fmt.Errorf("workspace '%s' not found", workspaceId)
}

func makeAPIRequest(method, url string, body interface{}) ([]byte, error) {
	token, err := getToken()
	if err != nil {
		return nil, err
	}

	var reqBody io.Reader
	if body != nil {
		jsonData, err := json.Marshal(body)
		if err != nil {
			return nil, fmt.Errorf("failed to marshal request: %v", err)
		}
		reqBody = bytes.NewBuffer(jsonData)
	}

	req, err := http.NewRequest(method, url, reqBody)
	if err != nil {
		return nil, err
	}

	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")

	resp, err := httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("API error (%d): %s", resp.StatusCode, string(respBody))
	}

	return respBody, nil
}

func executeWbCommand(args []string) (string, error) {
	cmd := exec.Command("wb", args...)
	output, err := cmd.CombinedOutput()
	return string(output), err
}

func handleCallTool(params CallToolParams) CallToolResult {
	var output string
	var err error

	switch params.Name {
	case "wb_status":
		output, err = executeWbCommand([]string{"status"})
	case "wb_workspace_list":
		args := []string{"workspace", "list"}
		if format, ok := params.Arguments["format"].(string); ok && format == "json" {
			args = append(args, "--format=json")
		}
		output, err = executeWbCommand(args)
	case "wb_execute":
		command, ok := params.Arguments["command"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'command' required"}}, IsError: true}
		}
		output, err = executeWbCommand(strings.Fields(command))

	case "workspace_list_all":
		limit, offset := 100, 0
		if l, ok := params.Arguments["limit"].(float64); ok {
			limit = int(l)
		}
		if o, ok := params.Arguments["offset"].(float64); ok {
			offset = int(o)
		}
		body := map[string]interface{}{"limit": limit, "offset": offset}
		if props, ok := params.Arguments["properties"].(map[string]interface{}); ok {
			// Convert properties from map to array of key-value objects
			var propsArray []map[string]string
			for key, val := range props {
				if strVal, ok := val.(string); ok {
					propsArray = append(propsArray, map[string]string{"key": key, "value": strVal})
				}
			}
			body["properties"] = propsArray
		}
		respBody, apiErr := makeAPIRequest("POST", workspaceBaseURL+"/api/workspaces/v2/filtered", body)
		if apiErr != nil {
			err = apiErr
		} else {
			output = string(respBody)
		}

	case "workspace_get":
		workspaceId, ok := params.Arguments["workspaceId"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'workspaceId' required"}}, IsError: true}
		}
		// Resolve user-facing ID to UUID
		workspaceUuid, err := resolveWorkspaceId(workspaceId)
		if err != nil {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: err.Error()}}, IsError: true}
		}
		url := fmt.Sprintf("%s/api/workspaces/v1/%s", workspaceBaseURL, workspaceUuid)
		respBody, apiErr := makeAPIRequest("GET", url, nil)
		if apiErr != nil {
			err = apiErr
		} else {
			output = string(respBody)
		}

	case "workspace_list_resources":
		workspaceId, ok := params.Arguments["workspaceId"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'workspaceId' required"}}, IsError: true}
		}
		offset := 0
		if val, ok := params.Arguments["offset"].(float64); ok {
			offset = int(val)
		}
		limit := 100
		if val, ok := params.Arguments["limit"].(float64); ok {
			limit = int(val)
		}
		// Resolve user-facing ID to UUID
		workspaceUuid, err := resolveWorkspaceId(workspaceId)
		if err != nil {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: err.Error()}}, IsError: true}
		}
		url := fmt.Sprintf("%s/api/workspaces/v1/%s/resources?offset=%d&limit=%d", workspaceBaseURL, workspaceUuid, offset, limit)
		respBody, apiErr := makeAPIRequest("GET", url, nil)
		if apiErr != nil {
			err = apiErr
		} else {
			output = string(respBody)
		}

	case "underlay_list":
		respBody, apiErr := makeAPIRequest("GET", dataExplorerURL+"/v2/underlays", nil)
		if apiErr != nil {
			err = apiErr
		} else {
			output = string(respBody)
		}

	case "underlay_get_schema":
		underlayName, ok := params.Arguments["underlayName"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'underlayName' required"}}, IsError: true}
		}
		url := fmt.Sprintf("%s/v2/underlays/%s", dataExplorerURL, underlayName)
		respBody, apiErr := makeAPIRequest("GET", url, nil)
		if apiErr != nil {
			err = apiErr
		} else {
			output = string(respBody)
		}

	case "underlay_list_entities":
		underlayName, ok := params.Arguments["underlayName"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'underlayName' required"}}, IsError: true}
		}
		url := fmt.Sprintf("%s/v2/underlays/%s/entities", dataExplorerURL, underlayName)
		respBody, apiErr := makeAPIRequest("GET", url, nil)
		if apiErr != nil {
			err = apiErr
		} else {
			output = string(respBody)
		}

	case "underlay_get_entity":
		underlayName, ok := params.Arguments["underlayName"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'underlayName' required"}}, IsError: true}
		}
		entityName, ok := params.Arguments["entityName"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'entityName' required"}}, IsError: true}
		}
		url := fmt.Sprintf("%s/v2/underlays/%s/entities/%s", dataExplorerURL, underlayName, entityName)
		respBody, apiErr := makeAPIRequest("GET", url, nil)
		if apiErr != nil {
			err = apiErr
		} else {
			output = string(respBody)
		}

	case "underlay_list_criteria_selectors":
		underlayName, ok := params.Arguments["underlayName"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'underlayName' required"}}, IsError: true}
		}
		// Get the schema
		url := fmt.Sprintf("%s/v2/underlays/%s", dataExplorerURL, underlayName)
		respBody, apiErr := makeAPIRequest("GET", url, nil)
		if apiErr != nil {
			err = apiErr
			break
		}

		// Parse the schema
		var schema map[string]interface{}
		if err := json.Unmarshal(respBody, &schema); err != nil {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: fmt.Sprintf("Error parsing schema: %v", err)}}, IsError: true}
		}

		// Extract criteria selectors from serializedConfiguration
		serializedConfig, ok := schema["serializedConfiguration"].(map[string]interface{})
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: serializedConfiguration not found"}}, IsError: true}
		}

		criteriaSelectorsRaw, ok := serializedConfig["criteriaSelectors"].([]interface{})
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: criteriaSelectors not found"}}, IsError: true}
		}

		// Parse each selector (they are JSON strings)
		var selectors []map[string]interface{}
		for _, selectorRaw := range criteriaSelectorsRaw {
			selectorStr, ok := selectorRaw.(string)
			if !ok {
				continue
			}
			var selector map[string]interface{}
			if err := json.Unmarshal([]byte(selectorStr), &selector); err != nil {
				continue
			}

			// Extract useful fields for agents
			result := map[string]interface{}{
				"name":        selector["name"],
				"displayName": selector["displayName"],
				"plugin":      selector["plugin"],
			}

			if pluginConfig, ok := selector["pluginConfig"].(string); ok {
				result["pluginConfig"] = pluginConfig
			}

			if display, ok := selector["display"].(map[string]interface{}); ok {
				if category, ok := display["category"].(string); ok {
					result["category"] = category
				}
			}

			selectors = append(selectors, result)
		}

		outputBytes, _ := json.MarshalIndent(map[string]interface{}{"selectors": selectors}, "", "  ")
		output = string(outputBytes)

	case "data_query_hints":
		studyId, ok := params.Arguments["studyId"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'studyId' required"}}, IsError: true}
		}
		cohortId, ok := params.Arguments["cohortId"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'cohortId' required"}}, IsError: true}
		}
		entityName, ok := params.Arguments["entityName"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'entityName' required"}}, IsError: true}
		}
		url := fmt.Sprintf("%s/v2/studies/%s/cohorts/%s/entities/%s/hints", dataExplorerURL, studyId, cohortId, entityName)
		respBody, apiErr := makeAPIRequest("POST", url, map[string]interface{}{})
		if apiErr != nil {
			err = apiErr
		} else {
			output = string(respBody)
		}

	case "data_sample_instances":
		studyId, ok := params.Arguments["studyId"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'studyId' required"}}, IsError: true}
		}
		cohortId, ok := params.Arguments["cohortId"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'cohortId' required"}}, IsError: true}
		}
		entityName, ok := params.Arguments["entityName"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'entityName' required"}}, IsError: true}
		}
		body := map[string]interface{}{"limit": 50}
		if attrs, ok := params.Arguments["includeAttributes"].([]interface{}); ok {
			body["includeAttributes"] = attrs
		}
		if filter, ok := params.Arguments["filter"].(map[string]interface{}); ok {
			body["filter"] = filter
		}
		if limit, ok := params.Arguments["limit"].(float64); ok {
			body["limit"] = int(limit)
		}
		url := fmt.Sprintf("%s/v2/studies/%s/cohorts/%s/entities/%s/instances", dataExplorerURL, studyId, cohortId, entityName)
		respBody, apiErr := makeAPIRequest("POST", url, body)
		if apiErr != nil {
			err = apiErr
		} else {
			output = string(respBody)
		}

	case "study_list":
		offset, limit := 0, 50
		if o, ok := params.Arguments["offset"].(float64); ok {
			offset = int(o)
		}
		if l, ok := params.Arguments["limit"].(float64); ok {
			limit = int(l)
		}
		url := fmt.Sprintf("%s/v2/studies?offset=%d&limit=%d", dataExplorerURL, offset, limit)
		respBody, apiErr := makeAPIRequest("GET", url, nil)
		if apiErr != nil {
			err = apiErr
		} else {
			output = string(respBody)
		}

	case "study_list_cohorts":
		studyId, ok := params.Arguments["studyId"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'studyId' required"}}, IsError: true}
		}
		offset, limit := 0, 50
		if o, ok := params.Arguments["offset"].(float64); ok {
			offset = int(o)
		}
		if l, ok := params.Arguments["limit"].(float64); ok {
			limit = int(l)
		}
		url := fmt.Sprintf("%s/v2/studies/%s/cohorts?offset=%d&limit=%d", dataExplorerURL, studyId, offset, limit)
		respBody, apiErr := makeAPIRequest("GET", url, nil)
		if apiErr != nil {
			err = apiErr
		} else {
			output = string(respBody)
		}

	case "cohort_create_in_workspace":
		workspaceId, ok := params.Arguments["workspaceId"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'workspaceId' required"}}, IsError: true}
		}
		_, ok = params.Arguments["underlayId"].(string) // underlayId kept for validation but not used
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'underlayId' required"}}, IsError: true}
		}
		underlayName, ok := params.Arguments["underlayName"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'underlayName' required"}}, IsError: true}
		}
		name, ok := params.Arguments["name"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'name' required"}}, IsError: true}
		}
		displayName := name
		if dn, ok := params.Arguments["displayName"].(string); ok {
			displayName = dn
		}
		description := ""
		if desc, ok := params.Arguments["description"].(string); ok {
			description = desc
		}

		// Step 1: Create cohort in Data Explorer
		createBody := map[string]interface{}{
			"studyCreateInfo": map[string]interface{}{
				"displayName": displayName + " Study",
			},
			"cohortCreateInfo": map[string]interface{}{
				"underlayName": underlayName,
				"displayName":  displayName,
				"description":  description,
			},
		}
		createResp, apiErr := makeAPIRequest("POST", dataExplorerURL+"/v2/createCohortInStudy", createBody)
		if apiErr != nil {
			err = fmt.Errorf("Step 1 failed (create cohort): %w", apiErr)
			break
		}

		// Parse response to get studyId and cohortId
		var createResult map[string]interface{}
		if err := json.Unmarshal(createResp, &createResult); err != nil {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: fmt.Sprintf("Error parsing create response: %v", err)}}, IsError: true}
		}
		study, _ := createResult["study"].(map[string]interface{})
		cohort, _ := createResult["cohort"].(map[string]interface{})
		studyId, _ := study["id"].(string)
		cohortId, _ := cohort["id"].(string)

		// Step 2: Update criteria if provided
		if criteriaJson, ok := params.Arguments["criteriaJson"].(string); ok && criteriaJson != "" {
			var updateBody interface{}
			if unmarshalErr := json.Unmarshal([]byte(criteriaJson), &updateBody); unmarshalErr != nil {
				err = fmt.Errorf("Step 2 failed (parse criteria): %w", unmarshalErr)
				break
			}
			_, apiErr = makeAPIRequest("PATCH", fmt.Sprintf("%s/v2/studies/%s/cohorts/%s", dataExplorerURL, studyId, cohortId), updateBody)
			if apiErr != nil {
				err = fmt.Errorf("Step 2 failed (update criteria): %w", apiErr)
				break
			}
		}

		// Step 3: Save cohort to workspace
		// Resolve user-facing ID to UUID
		workspaceUuid, err := resolveWorkspaceId(workspaceId)
		if err != nil {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: fmt.Sprintf("Step 3 failed: %v", err)}}, IsError: true}
		}

		saveBody := map[string]interface{}{
			"common": map[string]interface{}{
				"displayName":         displayName,
				"description":         description,
				"accessScope":         "SHARED_ACCESS",
				"managedBy":           "USER",
				"cloningInstructions": "COPY_RESOURCE",
			},
			"dataExplorerCohort": map[string]interface{}{
				"studyId":  studyId,
				"cohortId": cohortId,
			},
		}
		if folderId, ok := params.Arguments["folderId"].(string); ok {
			saveBody["common"].(map[string]interface{})["folderId"] = folderId
		}
		saveUrl := fmt.Sprintf("%s/api/workspaces/v1/%s/resources/controlled/data-explorer/cohort/save", workspaceBaseURL, workspaceUuid)
		respBody, apiErr := makeAPIRequest("POST", saveUrl, saveBody)
		if apiErr != nil {
			err = fmt.Errorf("Step 3 failed (save to workspace): %w", apiErr)
		} else {
			// Parse workspace response and add studyId/cohortId at top level for easy extraction
			var workspaceResp map[string]interface{}
			if err := json.Unmarshal(respBody, &workspaceResp); err == nil {
				workspaceResp["studyId"] = studyId
				workspaceResp["cohortId"] = cohortId
				if modifiedResp, err := json.Marshal(workspaceResp); err == nil {
					output = string(modifiedResp)
				} else {
					output = string(respBody)
				}
			} else {
				output = string(respBody)
			}
		}

	case "cohort_update_criteria":
		studyId, ok := params.Arguments["studyId"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'studyId' required"}}, IsError: true}
		}
		cohortId, ok := params.Arguments["cohortId"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'cohortId' required"}}, IsError: true}
		}
		body := map[string]interface{}{}
		if criteria, ok := params.Arguments["criteriaGroupSections"]; ok {
			body["criteriaGroupSections"] = criteria
		}
		if displayName, ok := params.Arguments["displayName"].(string); ok {
			body["displayName"] = displayName
		}
		if description, ok := params.Arguments["description"].(string); ok {
			body["description"] = description
		}
		url := fmt.Sprintf("%s/v2/studies/%s/cohorts/%s", dataExplorerURL, studyId, cohortId)
		respBody, apiErr := makeAPIRequest("PATCH", url, body)
		if apiErr != nil {
			err = apiErr
		} else {
			output = string(respBody)
		}

	case "cohort_count_instances":
		studyId, ok := params.Arguments["studyId"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'studyId' required"}}, IsError: true}
		}
		cohortId, ok := params.Arguments["cohortId"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'cohortId' required"}}, IsError: true}
		}
		body := map[string]interface{}{"groupByAttributes": []string{}}
		if entity, ok := params.Arguments["entity"].(string); ok {
			body["entity"] = entity
		}
		if attrs, ok := params.Arguments["groupByAttributes"].([]interface{}); ok {
			body["groupByAttributes"] = attrs
		}
		url := fmt.Sprintf("%s/v2/studies/%s/cohorts/%s/counts", dataExplorerURL, studyId, cohortId)
		respBody, apiErr := makeAPIRequest("POST", url, body)
		if apiErr != nil {
			err = apiErr
		} else {
			output = string(respBody)
		}

	case "export_list_models":
		underlayName, ok := params.Arguments["underlayName"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'underlayName' required"}}, IsError: true}
		}
		url := fmt.Sprintf("%s/v2/underlays/%s/exportModels", dataExplorerURL, underlayName)
		respBody, apiErr := makeAPIRequest("GET", url, nil)
		if apiErr != nil {
			err = apiErr
		} else {
			output = string(respBody)
		}

	case "export_describe":
		studyId, ok := params.Arguments["studyId"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'studyId' required"}}, IsError: true}
		}
		cohortId, ok := params.Arguments["cohortId"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'cohortId' required"}}, IsError: true}
		}
		body := map[string]interface{}{}
		if allCriteria, ok := params.Arguments["allCriteriaFromCohort"].(bool); ok {
			body["allCriteriaFromCohort"] = allCriteria
		}
		url := fmt.Sprintf("%s/v2/studies/%s/cohorts/%s/describeExport", dataExplorerURL, studyId, cohortId)
		respBody, apiErr := makeAPIRequest("POST", url, body)
		if apiErr != nil {
			err = apiErr
		} else {
			output = string(respBody)
		}

	case "export_preview":
		studyId, ok := params.Arguments["studyId"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'studyId' required"}}, IsError: true}
		}
		cohortId, ok := params.Arguments["cohortId"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'cohortId' required"}}, IsError: true}
		}
		body := map[string]interface{}{}
		if exportModel, ok := params.Arguments["exportModel"].(string); ok {
			body["exportModel"] = exportModel
		}
		if entityName, ok := params.Arguments["entityName"].(string); ok {
			body["entityName"] = entityName
		}
		if limit, ok := params.Arguments["limit"].(float64); ok {
			body["limit"] = int(limit)
		} else {
			body["limit"] = 20
		}
		if inputs, ok := params.Arguments["inputs"].(map[string]interface{}); ok {
			body["inputs"] = inputs
		}
		url := fmt.Sprintf("%s/v2/studies/%s/cohorts/%s/previewExport", dataExplorerURL, studyId, cohortId)
		respBody, apiErr := makeAPIRequest("POST", url, body)
		if apiErr != nil {
			err = apiErr
		} else {
			output = string(respBody)
		}

	case "export_cohort":
		studyId, ok := params.Arguments["studyId"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'studyId' required"}}, IsError: true}
		}
		cohortId, ok := params.Arguments["cohortId"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'cohortId' required"}}, IsError: true}
		}
		exportRequests, ok := params.Arguments["exportRequests"].([]interface{})
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'exportRequests' required"}}, IsError: true}
		}
		body := map[string]interface{}{
			"exportRequests": exportRequests,
		}
		url := fmt.Sprintf("%s/v2/studies/%s/cohorts/%s/export", dataExplorerURL, studyId, cohortId)
		respBody, apiErr := makeAPIRequest("POST", url, body)
		if apiErr != nil {
			err = apiErr
		} else {
			output = string(respBody)
		}

	case "filter_build_attribute":
		attribute, ok := params.Arguments["attribute"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'attribute' required"}}, IsError: true}
		}
		operator, ok := params.Arguments["operator"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'operator' required"}}, IsError: true}
		}
		dataType, ok := params.Arguments["dataType"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'dataType' required"}}, IsError: true}
		}
		filter := map[string]interface{}{
			"filterType": "ATTRIBUTE",
			"filterUnion": map[string]interface{}{
				"attributeFilter": map[string]interface{}{
					"attribute": attribute,
					"operator":  operator,
				},
			},
		}
		if operator != "IS_NULL" && operator != "IS_NOT_NULL" {
			values := []interface{}{}
			if val, ok := params.Arguments["value"]; ok {
				values = append(values, buildLiteral(dataType, val))
			}
			if vals, ok := params.Arguments["values"].([]interface{}); ok {
				for _, v := range vals {
					values = append(values, buildLiteral(dataType, v))
				}
			}
			filter["filterUnion"].(map[string]interface{})["attributeFilter"].(map[string]interface{})["values"] = values
		}
		outputBytes, _ := json.MarshalIndent(filter, "", "  ")
		output = string(outputBytes)

	case "filter_build_relationship":
		relatedEntity, ok := params.Arguments["relatedEntity"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'relatedEntity' required"}}, IsError: true}
		}
		filter := map[string]interface{}{
			"filterType": "RELATIONSHIP",
			"filterUnion": map[string]interface{}{
				"relationshipFilter": map[string]interface{}{
					"entity": relatedEntity,
				},
			},
		}
		if subfilter, ok := params.Arguments["subfilter"].(map[string]interface{}); ok {
			filter["filterUnion"].(map[string]interface{})["relationshipFilter"].(map[string]interface{})["subfilter"] = subfilter
		}
		outputBytes, _ := json.MarshalIndent(filter, "", "  ")
		output = string(outputBytes)

	case "filter_build_boolean_logic":
		operator, ok := params.Arguments["operator"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'operator' required"}}, IsError: true}
		}
		subfilters, ok := params.Arguments["subfilters"].([]interface{})
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'subfilters' required"}}, IsError: true}
		}
		filter := map[string]interface{}{
			"filterType": "BOOLEAN_LOGIC",
			"filterUnion": map[string]interface{}{
				"booleanLogicFilter": map[string]interface{}{
					"operator":   operator,
					"subfilters": subfilters,
				},
			},
		}
		outputBytes, _ := json.MarshalIndent(filter, "", "  ")
		output = string(outputBytes)

	case "filter_build_hierarchy":
		hierarchy, ok := params.Arguments["hierarchy"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'hierarchy' required"}}, IsError: true}
		}
		operator, ok := params.Arguments["operator"].(string)
		if !ok {
			return CallToolResult{Content: []ContentItem{{Type: "text", Text: "Error: 'operator' required"}}, IsError: true}
		}
		filter := map[string]interface{}{
			"filterType": "HIERARCHY",
			"filterUnion": map[string]interface{}{
				"hierarchyFilter": map[string]interface{}{
					"hierarchy": hierarchy,
					"operator":  operator,
				},
			},
		}
		if values, ok := params.Arguments["values"].([]interface{}); ok {
			filter["filterUnion"].(map[string]interface{})["hierarchyFilter"].(map[string]interface{})["values"] = values
		}
		outputBytes, _ := json.MarshalIndent(filter, "", "  ")
		output = string(outputBytes)

	case "workspace_create":
		id := params.Arguments["id"].(string)
		podId := params.Arguments["podId"].(string)
		args := []string{"workspace", "create", "--id=" + id, "--pod=" + podId}
		if name, ok := params.Arguments["name"].(string); ok {
			args = append(args, "--name="+name)
		}
		if desc, ok := params.Arguments["description"].(string); ok {
			args = append(args, "--description="+desc)
		}
		if orgId, ok := params.Arguments["organizationId"].(string); ok {
			args = append(args, "--org="+orgId)
		}
		output, err = executeWbCommand(args)

	case "workspace_delete":
		workspaceId := params.Arguments["workspaceId"].(string)
		output, err = executeWbCommand([]string{"workspace", "delete", "--workspace=" + workspaceId})

	case "workspace_update":
		workspaceId := params.Arguments["workspaceId"].(string)
		args := []string{"workspace", "update", "--workspace=" + workspaceId}
		if name, ok := params.Arguments["name"].(string); ok {
			args = append(args, "--name="+name)
		}
		if desc, ok := params.Arguments["description"].(string); ok {
			args = append(args, "--description="+desc)
		}
		output, err = executeWbCommand(args)

	case "workspace_duplicate":
		sourceId := params.Arguments["sourceWorkspaceId"].(string)
		destId := params.Arguments["destWorkspaceId"].(string)
		args := []string{"workspace", "duplicate", "--source-workspace=" + sourceId, "--destination-workspace-id=" + destId}
		if name, ok := params.Arguments["name"].(string); ok {
			args = append(args, "--name="+name)
		}
		output, err = executeWbCommand(args)

	case "workspace_set_property":
		workspaceId := params.Arguments["workspaceId"].(string)
		key := params.Arguments["key"].(string)
		value := params.Arguments["value"].(string)
		output, err = executeWbCommand([]string{"workspace", "set-property", "--workspace=" + workspaceId, "--key=" + key, "--value=" + value})

	case "workspace_delete_property":
		workspaceId := params.Arguments["workspaceId"].(string)
		key := params.Arguments["key"].(string)
		output, err = executeWbCommand([]string{"workspace", "delete-property", "--workspace=" + workspaceId, "--key=" + key})

	case "workspace_add_user":
		workspaceId := params.Arguments["workspaceId"].(string)
		email := params.Arguments["email"].(string)
		role := params.Arguments["role"].(string)
		output, err = executeWbCommand([]string{"workspace", "add-user", "--workspace=" + workspaceId, "--email=" + email, "--role=" + role})

	case "workspace_remove_user":
		workspaceId := params.Arguments["workspaceId"].(string)
		email := params.Arguments["email"].(string)
		output, err = executeWbCommand([]string{"workspace", "remove-user", "--workspace=" + workspaceId, "--email=" + email})

	case "workspace_list_users":
		workspaceId := params.Arguments["workspaceId"].(string)
		output, err = executeWbCommand([]string{"workspace", "list-users", "--workspace=" + workspaceId})

	case "resource_create_bucket":
		resourceId := params.Arguments["resourceId"].(string)
		bucketName := params.Arguments["bucketName"].(string)
		args := []string{"resource", "create", "gcs-bucket", "--id=" + resourceId, "--bucket-name=" + bucketName}
		if desc, ok := params.Arguments["description"].(string); ok {
			args = append(args, "--description="+desc)
		}
		output, err = executeWbCommand(args)

	case "resource_create_bq_dataset":
		resourceId := params.Arguments["resourceId"].(string)
		datasetId := params.Arguments["datasetId"].(string)
		args := []string{"resource", "create", "bq-dataset", "--id=" + resourceId, "--dataset-id=" + datasetId}
		if desc, ok := params.Arguments["description"].(string); ok {
			args = append(args, "--description="+desc)
		}
		output, err = executeWbCommand(args)

	case "resource_delete":
		resourceId := params.Arguments["resourceId"].(string)
		output, err = executeWbCommand([]string{"resource", "delete", "--name=" + resourceId})

	case "resource_update":
		resourceId := params.Arguments["resourceId"].(string)
		args := []string{"resource", "update", "--name=" + resourceId}
		if name, ok := params.Arguments["name"].(string); ok {
			args = append(args, "--new-name="+name)
		}
		if desc, ok := params.Arguments["description"].(string); ok {
			args = append(args, "--description="+desc)
		}
		output, err = executeWbCommand(args)

	case "resource_add_reference":
		resourceId := params.Arguments["resourceId"].(string)
		resourceType := params.Arguments["resourceType"].(string)
		path := params.Arguments["path"].(string)
		args := []string{"resource", "add-ref", resourceType, "--name=" + resourceId, "--path=" + path}
		if desc, ok := params.Arguments["description"].(string); ok {
			args = append(args, "--description="+desc)
		}
		output, err = executeWbCommand(args)

	case "resource_check_access":
		resourceId := params.Arguments["resourceId"].(string)
		output, err = executeWbCommand([]string{"resource", "check-access", "--name=" + resourceId})

	case "resource_move":
		resourceId := params.Arguments["resourceId"].(string)
		folderId := params.Arguments["folderId"].(string)
		output, err = executeWbCommand([]string{"resource", "move", "--name=" + resourceId, "--folder-id=" + folderId})

	case "folder_create":
		folderId := params.Arguments["folderId"].(string)
		displayName := params.Arguments["displayName"].(string)
		args := []string{"folder", "create", "--id=" + folderId, "--display-name=" + displayName}
		if desc, ok := params.Arguments["description"].(string); ok {
			args = append(args, "--description="+desc)
		}
		if parentId, ok := params.Arguments["parentId"].(string); ok {
			args = append(args, "--parent-folder-id="+parentId)
		}
		output, err = executeWbCommand(args)

	case "folder_delete":
		folderId := params.Arguments["folderId"].(string)
		output, err = executeWbCommand([]string{"folder", "delete", "--id=" + folderId})

	case "folder_update":
		folderId := params.Arguments["folderId"].(string)
		args := []string{"folder", "update", "--id=" + folderId}
		if displayName, ok := params.Arguments["displayName"].(string); ok {
			args = append(args, "--display-name="+displayName)
		}
		if desc, ok := params.Arguments["description"].(string); ok {
			args = append(args, "--description="+desc)
		}
		output, err = executeWbCommand(args)

	case "folder_list_tree":
		output, err = executeWbCommand([]string{"folder", "tree"})

	case "workspace_list_data_collections":
		// Get all resources with their metadata (includes sourceWorkspaceId)
		resourcesOutput, resourcesErr := executeWbCommand([]string{"resource", "list", "--format=json"})
		if resourcesErr != nil {
			err = fmt.Errorf("failed to list resources: %w", resourcesErr)
			break
		}

		// Parse resources
		var resources []map[string]interface{}
		if jsonErr := json.Unmarshal([]byte(resourcesOutput), &resources); jsonErr != nil {
			// Try parsing as object with "resources" key
			var resourceResponse map[string]interface{}
			if err2 := json.Unmarshal([]byte(resourcesOutput), &resourceResponse); err2 == nil {
				if r, ok := resourceResponse["resources"].([]interface{}); ok {
					for _, item := range r {
						if m, ok := item.(map[string]interface{}); ok {
							resources = append(resources, m)
						}
					}
				}
			}
		}

		// Collect unique sourceWorkspaceIds
		sourceWorkspaceIds := make(map[string]bool)
		for _, resource := range resources {
			if sourceId, ok := resource["sourceWorkspaceId"].(string); ok && sourceId != "" {
				sourceWorkspaceIds[sourceId] = true
			}
		}

		// Look up each source workspace to get the data collection name
		dataCollectionNames := make(map[string]string) // sourceWorkspaceId -> display name
		for sourceId := range sourceWorkspaceIds {
			wsOutput, wsErr := executeWbCommand([]string{"workspace", "describe", "--workspace=" + sourceId, "--format=json"})
			if wsErr == nil {
				var wsInfo map[string]interface{}
				if json.Unmarshal([]byte(wsOutput), &wsInfo) == nil {
					// Try to get display name, fall back to id
					if displayName, ok := wsInfo["displayName"].(string); ok && displayName != "" {
						dataCollectionNames[sourceId] = displayName
					} else if name, ok := wsInfo["name"].(string); ok && name != "" {
						dataCollectionNames[sourceId] = name
					} else if id, ok := wsInfo["id"].(string); ok {
						dataCollectionNames[sourceId] = id
					} else {
						dataCollectionNames[sourceId] = sourceId
					}
				} else {
					dataCollectionNames[sourceId] = sourceId
				}
			} else {
				// If we can't access the source workspace, use the ID
				dataCollectionNames[sourceId] = sourceId + " (inaccessible)"
			}
		}

		// Group resources by data collection (sourceWorkspaceId)
		dataCollections := make(map[string]map[string]interface{})
		localResources := []map[string]interface{}{}

		for _, resource := range resources {
			resourceInfo := map[string]interface{}{
				"name": resource["name"],
				"type": resource["resourceType"],
			}

			// Add cloud path if available
			if metadata, ok := resource["metadata"].(map[string]interface{}); ok {
				if bucket, ok := metadata["bucketName"].(string); ok {
					resourceInfo["path"] = "gs://" + bucket
				} else if dataset, ok := metadata["datasetId"].(string); ok {
					if project, ok := metadata["projectId"].(string); ok {
						resourceInfo["path"] = project + ":" + dataset
					}
				} else if gcsBucket, ok := metadata["gcsBucketName"].(string); ok {
					resourceInfo["path"] = "gs://" + gcsBucket
				}
			}

			// Check if resource came from a data collection (has sourceWorkspaceId)
			if sourceId, ok := resource["sourceWorkspaceId"].(string); ok && sourceId != "" {
				collectionName := dataCollectionNames[sourceId]
				if dataCollections[collectionName] == nil {
					dataCollections[collectionName] = map[string]interface{}{
						"sourceWorkspaceId": sourceId,
						"resources":         []map[string]interface{}{},
					}
				}
				resources := dataCollections[collectionName]["resources"].([]map[string]interface{})
				dataCollections[collectionName]["resources"] = append(resources, resourceInfo)
			} else {
				localResources = append(localResources, resourceInfo)
			}
		}

		// Count resources in collections
		resourcesInCollections := 0
		for _, dc := range dataCollections {
			if res, ok := dc["resources"].([]map[string]interface{}); ok {
				resourcesInCollections += len(res)
			}
		}

		// Build output
		result := map[string]interface{}{
			"dataCollections": dataCollections,
			"localResources":  localResources,
			"summary": map[string]interface{}{
				"totalDataCollections":   len(dataCollections),
				"totalResources":         len(resources),
				"resourcesFromCollections": resourcesInCollections,
				"resourcesCreatedLocally": len(localResources),
			},
		}

		outputBytes, _ := json.MarshalIndent(result, "", "  ")
		output = string(outputBytes)

	case "group_create":
		groupId := params.Arguments["groupId"].(string)
		name := params.Arguments["name"].(string)
		args := []string{"group", "create", "--id=" + groupId, "--name=" + name}
		if desc, ok := params.Arguments["description"].(string); ok {
			args = append(args, "--description="+desc)
		}
		output, err = executeWbCommand(args)

	case "group_delete":
		groupId := params.Arguments["groupId"].(string)
		output, err = executeWbCommand([]string{"group", "delete", "--id=" + groupId})

	case "group_list":
		output, err = executeWbCommand([]string{"group", "list"})

	case "group_describe":
		groupId := params.Arguments["groupId"].(string)
		output, err = executeWbCommand([]string{"group", "describe", "--id=" + groupId})

	case "group_add_user":
		groupId := params.Arguments["groupId"].(string)
		email := params.Arguments["email"].(string)
		role := params.Arguments["role"].(string)
		output, err = executeWbCommand([]string{"group", "member", "add", "--group-id=" + groupId, "--email=" + email, "--role=" + role})

	case "group_remove_user":
		groupId := params.Arguments["groupId"].(string)
		email := params.Arguments["email"].(string)
		output, err = executeWbCommand([]string{"group", "member", "remove", "--group-id=" + groupId, "--email=" + email})

	case "app_create":
		appId := params.Arguments["appId"].(string)
		appConfig := params.Arguments["appConfig"].(string)
		args := []string{"app", "create", "gcp", "--id=" + appId, "--config=" + appConfig}
		if machineType, ok := params.Arguments["machineType"].(string); ok {
			args = append(args, "--machine-type="+machineType)
		}
		if description, ok := params.Arguments["description"].(string); ok {
			args = append(args, "--description="+description)
		}
		if location, ok := params.Arguments["location"].(string); ok {
			args = append(args, "--location="+location)
		}
		output, err = executeWbCommand(args)

	case "app_delete":
		appId := params.Arguments["appId"].(string)
		output, err = executeWbCommand([]string{"app", "delete", "--id=" + appId, "--quiet"})

	case "app_list":
		output, err = executeWbCommand([]string{"app", "list"})

	case "app_start":
		appId := params.Arguments["appId"].(string)
		output, err = executeWbCommand([]string{"app", "start", "--id=" + appId})

	case "app_stop":
		appId := params.Arguments["appId"].(string)
		output, err = executeWbCommand([]string{"app", "stop", "--id=" + appId})

	case "app_get_url":
		appId := params.Arguments["appId"].(string)
		output, err = executeWbCommand([]string{"app", "launch", "--id=" + appId})

	case "auth_status":
		output, err = executeWbCommand([]string{"auth", "status"})

	case "server_list":
		output, err = executeWbCommand([]string{"server", "list"})

	case "server_set":
		serverName := params.Arguments["serverName"].(string)
		output, err = executeWbCommand([]string{"server", "set", "--name=" + serverName})

	case "server_status":
		output, err = executeWbCommand([]string{"server", "status"})

	case "server_list_regions":
		cloudPlatform := params.Arguments["cloudPlatform"].(string)
		output, err = executeWbCommand([]string{"server", "list-regions", "--platform=" + cloudPlatform})

	case "pod_list":
		output, err = executeWbCommand([]string{"pod", "list"})

	case "pod_describe":
		podId := params.Arguments["podId"].(string)
		output, err = executeWbCommand([]string{"pod", "describe", "--id=" + podId})

	case "pod_role_list":
		organizationId := params.Arguments["organizationId"].(string)
		podId := params.Arguments["podId"].(string)
		output, err = executeWbCommand([]string{"pod", "role", "list", "--organization=" + organizationId, "--pod=" + podId})

	case "pod_role_grant":
		organizationId := params.Arguments["organizationId"].(string)
		podId := params.Arguments["podId"].(string)
		email := params.Arguments["email"].(string)
		role := params.Arguments["role"].(string)
		output, err = executeWbCommand([]string{"pod", "role", "grant", "user", "--organization=" + organizationId, "--pod=" + podId, "--email=" + email, "--role=" + role})

	case "pod_role_revoke":
		organizationId := params.Arguments["organizationId"].(string)
		podId := params.Arguments["podId"].(string)
		email := params.Arguments["email"].(string)
		role := params.Arguments["role"].(string)
		output, err = executeWbCommand([]string{"pod", "role", "revoke", "user", "--organization=" + organizationId, "--pod=" + podId, "--email=" + email, "--role=" + role})

	case "organization_list":
		output, err = executeWbCommand([]string{"organization", "list"})

	case "resource_credentials":
		resourceId := params.Arguments["resourceId"].(string)
		args := []string{"resource", "credentials", "--name=" + resourceId}
		if duration, ok := params.Arguments["duration"].(float64); ok {
			args = append(args, fmt.Sprintf("--duration=%d", int(duration)))
		}
		output, err = executeWbCommand(args)

	case "resource_open_console":
		resourceId := params.Arguments["resourceId"].(string)
		output, err = executeWbCommand([]string{"resource", "open-console", "--name=" + resourceId})

	case "resource_list_tree":
		output, err = executeWbCommand([]string{"resource", "list-tree"})

	case "resource_mount":
		output, err = executeWbCommand([]string{"resource", "mount"})

	case "resource_unmount":
		output, err = executeWbCommand([]string{"resource", "unmount"})

	case "notebook_start":
		notebookId := params.Arguments["notebookId"].(string)
		output, err = executeWbCommand([]string{"notebook", "start", "--id=" + notebookId})

	case "notebook_stop":
		notebookId := params.Arguments["notebookId"].(string)
		output, err = executeWbCommand([]string{"notebook", "stop", "--id=" + notebookId})

	case "notebook_launch":
		notebookId := params.Arguments["notebookId"].(string)
		output, err = executeWbCommand([]string{"notebook", "launch", "--id=" + notebookId})

	case "cluster_start":
		clusterId := params.Arguments["clusterId"].(string)
		output, err = executeWbCommand([]string{"cluster", "start", "--id=" + clusterId})

	case "cluster_stop":
		clusterId := params.Arguments["clusterId"].(string)
		output, err = executeWbCommand([]string{"cluster", "stop", "--id=" + clusterId})

	case "cluster_launch":
		clusterId := params.Arguments["clusterId"].(string)
		output, err = executeWbCommand([]string{"cluster", "launch", "--id=" + clusterId})

	case "workflow_list":
		workspaceId := params.Arguments["workspaceId"].(string)
		output, err = executeWbCommand([]string{"workflow", "list", "--workspace=" + workspaceId})

	case "workflow_create":
		workspaceId := params.Arguments["workspaceId"].(string)
		workflowId := params.Arguments["workflowId"].(string)
		bucketId := params.Arguments["bucketId"].(string)
		path := params.Arguments["path"].(string)
		args := []string{"workflow", "create", "--workspace=" + workspaceId, "--workflow=" + workflowId, "--bucket-id=" + bucketId, "--path=" + path}
		if displayName, ok := params.Arguments["displayName"].(string); ok {
			args = append(args, "--display-name="+displayName)
		}
		if description, ok := params.Arguments["description"].(string); ok {
			args = append(args, "--description="+description)
		}
		output, err = executeWbCommand(args)

	case "workflow_describe":
		workspaceId := params.Arguments["workspaceId"].(string)
		workflowId := params.Arguments["workflowId"].(string)
		output, err = executeWbCommand([]string{"workflow", "describe", "--workspace=" + workspaceId, "--workflow=" + workflowId})

	case "workflow_job_list":
		output, err = executeWbCommand([]string{"workflow", "job", "list"})

	case "workflow_job_describe":
		workspaceId := params.Arguments["workspaceId"].(string)
		jobId := params.Arguments["jobId"].(string)
		output, err = executeWbCommand([]string{"workflow", "job", "describe", "--workspace=" + workspaceId, "--job-id=" + jobId})

	case "workflow_job_run":
		workspaceId := params.Arguments["workspaceId"].(string)
		workflowId := params.Arguments["workflowId"].(string)
		outputBucketId := params.Arguments["outputBucketId"].(string)
		args := []string{"workflow", "job", "run", "--workspace=" + workspaceId, "--workflow=" + workflowId, "--output-bucket-id=" + outputBucketId}
		if jobId, ok := params.Arguments["jobId"].(string); ok {
			args = append(args, "--job-id="+jobId)
		}
		if description, ok := params.Arguments["description"].(string); ok {
			args = append(args, "--description="+description)
		}
		if outputPath, ok := params.Arguments["outputPath"].(string); ok {
			args = append(args, "--output-path="+outputPath)
		}
		if inputs, ok := params.Arguments["inputs"].(map[string]interface{}); ok {
			inputsJSON, _ := json.Marshal(inputs)
			args = append(args, "--inputs="+string(inputsJSON))
		}
		output, err = executeWbCommand(args)

	case "workflow_job_cancel":
		workspaceId := params.Arguments["workspaceId"].(string)
		jobId := params.Arguments["jobId"].(string)
		output, err = executeWbCommand([]string{"workflow", "job", "cancel", "--workspace=" + workspaceId, "--job-id=" + jobId})

	case "cromwell_generate_config":
		path := params.Arguments["path"].(string)
		output, err = executeWbCommand([]string{"cromwell", "generate-config", "--path=" + path})

	case "workspace_configure_aws":
		workspaceId := params.Arguments["workspaceId"].(string)
		output, err = executeWbCommand([]string{"workspace", "configure-aws", "--workspace=" + workspaceId})

	case "resolve":
		resourceId := params.Arguments["resourceId"].(string)
		output, err = executeWbCommand([]string{"resolve", "--name=" + resourceId})

	case "version":
		output, err = executeWbCommand([]string{"version"})

	case "bq_execute":
		command := params.Arguments["command"].(string)
		output, err = executeWbCommand(append([]string{"bq"}, strings.Fields(command)...))

	case "gcloud_execute":
		command := params.Arguments["command"].(string)
		output, err = executeWbCommand(append([]string{"gcloud"}, strings.Fields(command)...))

	case "gsutil_execute":
		command := params.Arguments["command"].(string)
		output, err = executeWbCommand(append([]string{"gsutil"}, strings.Fields(command)...))

	case "git_execute":
		command := params.Arguments["command"].(string)
		output, err = executeWbCommand(append([]string{"git"}, strings.Fields(command)...))

	default:
		return CallToolResult{Content: []ContentItem{{Type: "text", Text: fmt.Sprintf("Unknown tool: %s", params.Name)}}, IsError: true}
	}

	if err != nil {
		return CallToolResult{Content: []ContentItem{{Type: "text", Text: fmt.Sprintf("Error: %s", err.Error())}}, IsError: true}
	}
	return CallToolResult{Content: []ContentItem{{Type: "text", Text: output}}, IsError: false}
}

func buildLiteral(dataType string, value interface{}) map[string]interface{} {
	literal := map[string]interface{}{"dataType": dataType, "valueUnion": map[string]interface{}{}}
	switch dataType {
	case "BOOLEAN":
		literal["valueUnion"].(map[string]interface{})["boolVal"] = value
	case "INT64":
		literal["valueUnion"].(map[string]interface{})["int64Val"] = fmt.Sprintf("%v", value)
	case "STRING":
		literal["valueUnion"].(map[string]interface{})["stringVal"] = fmt.Sprintf("%v", value)
	case "DATE":
		literal["valueUnion"].(map[string]interface{})["dateVal"] = fmt.Sprintf("%v", value)
	case "TIMESTAMP":
		literal["valueUnion"].(map[string]interface{})["timestampVal"] = fmt.Sprintf("%v", value)
	case "DOUBLE":
		literal["valueUnion"].(map[string]interface{})["doubleVal"] = value
	}
	return literal
}

func handleRequest(req JSONRPCRequest) JSONRPCResponse {
	switch req.Method {
	case "initialize":
		return JSONRPCResponse{
			JSONRPC: "2.0",
			ID:      req.ID,
			Result: InitializeResult{
				ProtocolVersion: "2024-11-05",
				Capabilities:    map[string]interface{}{"tools": map[string]interface{}{}},
				ServerInfo:      ServerInfo{Name: "wb-mcp-server", Version: "2.0.0"},
			},
		}
	case "notifications/initialized":
		// Client sends this notification after receiving initialize response
		// No response needed for notifications
		return JSONRPCResponse{}
	case "tools/list":
		return JSONRPCResponse{JSONRPC: "2.0", ID: req.ID, Result: ListToolsResult{Tools: wbTools}}
	case "tools/call":
		var params CallToolParams
		if err := json.Unmarshal(req.Params, &params); err != nil {
			return JSONRPCResponse{JSONRPC: "2.0", ID: req.ID, Error: &RPCError{Code: -32602, Message: "Invalid params"}}
		}
		return JSONRPCResponse{JSONRPC: "2.0", ID: req.ID, Result: handleCallTool(params)}
	default:
		return JSONRPCResponse{JSONRPC: "2.0", ID: req.ID, Error: &RPCError{Code: -32601, Message: "Method not found"}}
	}
}

func main() {
	fmt.Fprintln(os.Stderr, "Workbench MCP Server v2.0 starting...")

	if err := initializeConfig(); err != nil {
		fmt.Fprintf(os.Stderr, "Error initializing: %v\n", err)
		os.Exit(1)
	}

	fmt.Fprintf(os.Stderr, "Ready - %d tools available\n", len(wbTools))

	scanner := bufio.NewScanner(os.Stdin)
	for scanner.Scan() {
		line := scanner.Text()
		if line == "" {
			continue
		}

		var req JSONRPCRequest
		if err := json.Unmarshal([]byte(line), &req); err != nil {
			continue
		}

		response := handleRequest(req)
		// Only send response if there's a result or error (skip empty responses for notifications)
		if response.Result != nil || response.Error != nil {
			responseBytes, _ := json.Marshal(response)
			fmt.Println(string(responseBytes))
		}
	}
}
