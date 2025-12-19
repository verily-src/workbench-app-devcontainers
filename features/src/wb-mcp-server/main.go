package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"strings"
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

var wbTools = []Tool{
	{
		Name:        "wb_status",
		Description: "Get the current workspace and server status",
		InputSchema: InputSchema{
			Type:       "object",
			Properties: map[string]interface{}{},
		},
	},
	{
		Name:        "wb_workspace_list",
		Description: "List all Workbench workspaces",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"format": map[string]interface{}{
					"type":        "string",
					"description": "Output format (json, text)",
					"enum":        []string{"json", "text"},
				},
			},
		},
	},
	{
		Name:        "wb_resource_list",
		Description: "List resources in the current workspace",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"type": map[string]interface{}{
					"type":        "string",
					"description": "Resource type to filter by",
				},
				"format": map[string]interface{}{
					"type":        "string",
					"description": "Output format (json, text)",
					"enum":        []string{"json", "text"},
				},
			},
		},
	},
	{
		Name:        "wb_resource_describe",
		Description: "Describe a specific resource in the workspace",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"name": map[string]interface{}{
					"type":        "string",
					"description": "Name or ID of the resource",
				},
				"format": map[string]interface{}{
					"type":        "string",
					"description": "Output format (json, text)",
					"enum":        []string{"json", "text"},
				},
			},
			Required: []string{"name"},
		},
	},
	{
		Name:        "wb_folder_tree",
		Description: "Display folder structure as a tree",
		InputSchema: InputSchema{
			Type:       "object",
			Properties: map[string]interface{}{},
		},
	},
	{
		Name:        "wb_app_list",
		Description: "List all applications in the workspace",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"format": map[string]interface{}{
					"type":        "string",
					"description": "Output format (json, text)",
					"enum":        []string{"json", "text"},
				},
			},
		},
	},
	{
		Name:        "wb_app_describe",
		Description: "Describe a specific application",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"name": map[string]interface{}{
					"type":        "string",
					"description": "Name or ID of the application",
				},
			},
			Required: []string{"name"},
		},
	},
	{
		Name:        "wb_execute",
		Description: "Execute a custom wb command. Use this for commands not covered by other tools. Provide the full command without 'wb' prefix (e.g., 'workspace describe --id=123' not 'wb workspace describe --id=123')",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"command": map[string]interface{}{
					"type":        "string",
					"description": "The wb command to execute (without 'wb' prefix)",
				},
			},
			Required: []string{"command"},
		},
	},
}

func executeWbCommand(args []string) (string, error) {
	cmd := exec.Command("wb", args...)
	output, err := cmd.CombinedOutput()
	return string(output), err
}

func handleCallTool(params CallToolParams) CallToolResult {
	var args []string
	var output string
	var err error

	switch params.Name {
	case "wb_status":
		args = []string{"status"}
		output, err = executeWbCommand(args)

	case "wb_workspace_list":
		args = []string{"workspace", "list"}
		if format, ok := params.Arguments["format"].(string); ok && format == "json" {
			args = append(args, "--format=json")
		}
		output, err = executeWbCommand(args)

	case "wb_resource_list":
		args = []string{"resource", "list"}
		if resourceType, ok := params.Arguments["type"].(string); ok && resourceType != "" {
			args = append(args, "--type="+resourceType)
		}
		if format, ok := params.Arguments["format"].(string); ok && format == "json" {
			args = append(args, "--format=json")
		}
		output, err = executeWbCommand(args)

	case "wb_resource_describe":
		name, ok := params.Arguments["name"].(string)
		if !ok {
			return CallToolResult{
				Content: []ContentItem{{Type: "text", Text: "Error: 'name' parameter is required"}},
				IsError: true,
			}
		}
		args = []string{"resource", "describe", "--name=" + name}
		if format, ok := params.Arguments["format"].(string); ok && format == "json" {
			args = append(args, "--format=json")
		}
		output, err = executeWbCommand(args)

	case "wb_folder_tree":
		args = []string{"folder", "tree"}
		output, err = executeWbCommand(args)

	case "wb_app_list":
		args = []string{"app", "list"}
		if format, ok := params.Arguments["format"].(string); ok && format == "json" {
			args = append(args, "--format=json")
		}
		output, err = executeWbCommand(args)

	case "wb_app_describe":
		name, ok := params.Arguments["name"].(string)
		if !ok {
			return CallToolResult{
				Content: []ContentItem{{Type: "text", Text: "Error: 'name' parameter is required"}},
				IsError: true,
			}
		}
		args = []string{"app", "describe", "--name=" + name}
		output, err = executeWbCommand(args)

	case "wb_execute":
		command, ok := params.Arguments["command"].(string)
		if !ok {
			return CallToolResult{
				Content: []ContentItem{{Type: "text", Text: "Error: 'command' parameter is required"}},
				IsError: true,
			}
		}
		args = strings.Fields(command)
		output, err = executeWbCommand(args)

	default:
		return CallToolResult{
			Content: []ContentItem{{Type: "text", Text: fmt.Sprintf("Unknown tool: %s", params.Name)}},
			IsError: true,
		}
	}

	if err != nil {
		return CallToolResult{
			Content: []ContentItem{{Type: "text", Text: fmt.Sprintf("Command failed: %s\nOutput: %s", err.Error(), output)}},
			IsError: true,
		}
	}

	return CallToolResult{
		Content: []ContentItem{{Type: "text", Text: output}},
		IsError: false,
	}
}

func handleRequest(req JSONRPCRequest) JSONRPCResponse {
	switch req.Method {
	case "initialize":
		var params InitializeParams
		if req.Params != nil {
			json.Unmarshal(req.Params, &params)
		}

		return JSONRPCResponse{
			JSONRPC: "2.0",
			ID:      req.ID,
			Result: InitializeResult{
				ProtocolVersion: "2024-11-05",
				Capabilities: map[string]interface{}{
					"tools": map[string]interface{}{},
				},
				ServerInfo: ServerInfo{
					Name:    "wb-mcp-server",
					Version: "1.0.0",
				},
			},
		}

	case "tools/list":
		return JSONRPCResponse{
			JSONRPC: "2.0",
			ID:      req.ID,
			Result: ListToolsResult{
				Tools: wbTools,
			},
		}

	case "tools/call":
		var params CallToolParams
		if err := json.Unmarshal(req.Params, &params); err != nil {
			return JSONRPCResponse{
				JSONRPC: "2.0",
				ID:      req.ID,
				Error: &RPCError{
					Code:    -32602,
					Message: "Invalid params: " + err.Error(),
				},
			}
		}

		result := handleCallTool(params)
		return JSONRPCResponse{
			JSONRPC: "2.0",
			ID:      req.ID,
			Result:  result,
		}

	default:
		return JSONRPCResponse{
			JSONRPC: "2.0",
			ID:      req.ID,
			Error: &RPCError{
				Code:    -32601,
				Message: "Method not found: " + req.Method,
			},
		}
	}
}

func main() {
	fmt.Fprintln(os.Stderr, "Workbench MCP Server v1.0.0 starting...")
	fmt.Fprintln(os.Stderr, "Reading from stdin, writing to stdout")

	scanner := bufio.NewScanner(os.Stdin)
	for scanner.Scan() {
		line := scanner.Text()
		if line == "" {
			continue
		}

		var req JSONRPCRequest
		if err := json.Unmarshal([]byte(line), &req); err != nil {
			fmt.Fprintln(os.Stderr, "Error parsing request:", err)
			continue
		}

		response := handleRequest(req)
		responseBytes, err := json.Marshal(response)
		if err != nil {
			fmt.Fprintln(os.Stderr, "Error marshaling response:", err)
			continue
		}

		fmt.Println(string(responseBytes))
	}

	if err := scanner.Err(); err != nil {
		fmt.Fprintln(os.Stderr, "Error reading input:", err)
	}
}
