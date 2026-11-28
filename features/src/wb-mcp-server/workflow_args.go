package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"os/exec"
	"strings"
)

// optionalString returns the argument when it is a non-empty string.
func optionalString(arguments map[string]interface{}, key string) (string, bool) {
	v, ok := arguments[key].(string)
	return v, ok && v != ""
}

// workflowCreateArgs builds the `wb workflow create` command line.
func workflowCreateArgs(arguments map[string]interface{}) ([]string, error) {
	vals, err := requireStrings(arguments, "workspaceId", "workflowId", "bucketId", "path")
	if err != nil {
		return nil, err
	}
	args := []string{"workflow", "create", "--workspace=" + vals[0], "--workflow=" + vals[1], "--bucket-id=" + vals[2], "--path=" + vals[3]}
	if v, ok := arguments["displayName"].(string); ok {
		args = append(args, "--display-name="+v)
	}
	if v, ok := arguments["description"].(string); ok {
		args = append(args, "--description="+v)
	}
	if v, ok := optionalString(arguments, "workflowType"); ok {
		args = append(args, "--workflow-type="+v)
	}
	return args, nil
}

// workflowInputsObject returns the inputs argument as an object. A string holding a JSON object
// is parsed, since models often send inputs that way. An absent argument or "" means no inputs;
// any other value (null, an array, a number) is an error.
func workflowInputsObject(arguments map[string]interface{}) (map[string]interface{}, bool, error) {
	v, present := arguments["inputs"]
	if !present {
		return nil, false, nil
	}
	switch inputs := v.(type) {
	case map[string]interface{}:
		return inputs, true, nil
	case string:
		if strings.TrimSpace(inputs) == "" {
			return nil, false, nil
		}
		var parsed map[string]interface{}
		if json.Unmarshal([]byte(inputs), &parsed) == nil && parsed != nil {
			return parsed, true, nil
		}
	}
	return nil, false, errors.New("inputs must be a JSON object of workflow input names to values")
}

// workflowJobRunArgs builds the `wb workflow job run` command line.
func workflowJobRunArgs(arguments map[string]interface{}) ([]string, error) {
	vals, err := requireStrings(arguments, "workspaceId", "workflowId", "outputBucketId")
	if err != nil {
		return nil, err
	}
	bucket, hasBucket := optionalString(arguments, "paramsFileBucketId")
	path, hasPath := optionalString(arguments, "paramsFilePath")
	if hasBucket != hasPath {
		return nil, errors.New("paramsFileBucketId and paramsFilePath are both needed for a params file")
	}
	for _, key := range []string{"inputsUri", "jobId", "outputPath", "description"} {
		if v, present := arguments[key]; present {
			if _, isString := v.(string); !isString {
				return nil, fmt.Errorf("%s must be a string", key)
			}
		}
	}
	inputs, hasInputs, err := workflowInputsObject(arguments)
	if err != nil {
		return nil, err
	}
	// An empty inputs object is no inputs: models send {} for "none", and the CLI refuses
	// --inputs for a Nextflow workflow even when it is empty. (An empty inputsUri is absent already.)
	if hasInputs && len(inputs) == 0 {
		hasInputs = false
	}
	inputsURI, hasInputsURI := optionalString(arguments, "inputsUri")
	if hasInputs && hasInputsURI {
		return nil, errors.New("give inputs or inputsUri, not both")
	}
	args := []string{"workflow", "job", "run", "--workspace=" + vals[0], "--workflow=" + vals[1], "--output-bucket-id=" + vals[2]}
	if v, ok := optionalString(arguments, "jobId"); ok {
		args = append(args, "--job-id="+v)
	}
	if v, ok := optionalString(arguments, "description"); ok {
		args = append(args, "--description="+v)
	}
	if v, ok := optionalString(arguments, "outputPath"); ok {
		args = append(args, "--output-path="+v)
	}
	if hasInputs {
		inputsJSON, _ := json.Marshal(inputs)
		args = append(args, "--inputs="+string(inputsJSON))
	}
	if hasInputsURI {
		args = append(args, "--inputs-uri="+inputsURI)
	}
	if v, ok := optionalString(arguments, "profile"); ok {
		args = append(args, "--profile="+v)
	}
	if hasBucket {
		args = append(args, "--params-file-bucket-id="+bucket, "--params-file-path="+path)
	}
	return args, nil
}

// cliWorkspaceID returns the workspace ID that the wb CLI's --workspace takes, given a workspace's
// ID or UUID: the CLI finds no workspace by its UUID, and other tools (workflow_inputs_get) need
// the UUID, so a model passes either. A UUID not seen in `wb status` is returned as given.
func cliWorkspaceID(workspace string) string {
	if !isUUID(workspace) {
		return workspace
	}
	lookup := func() string {
		cacheMu.Lock()
		defer cacheMu.Unlock()
		for id, uuid := range workspaceIdCache {
			if strings.EqualFold(uuid, workspace) {
				return id
			}
		}
		return ""
	}
	if id := lookup(); id != "" {
		return id
	}
	if _, err := refreshStatus(); err == nil {
		if id := lookup(); id != "" {
			return id
		}
	}
	return workspace
}

// cliResourceID returns the resource ID that the wb CLI's --*-bucket-id flags take (the `id` of
// `wb resource list`, such as "output"), given a resource's ID, its UUID, or its cloud bucket name
// (with or without gs://): workspace_list_resources shows the first two, the sandboxed agent knows
// the bucket names, and the CLI finds a resource only by its ID. A value it cannot match is
// returned as given.
func cliResourceID(workspace, resource string) string {
	bucketName := strings.TrimSuffix(strings.TrimPrefix(resource, "gs://"), "/")
	if !isUUID(resource) && !strings.HasPrefix(resource, "gs://") && !strings.ContainsAny(resource, "-.") {
		return resource // a plain resource ID; anything that may be a UUID or a bucket name is looked up
	}
	out, err := exec.Command("wb", "resource", "list", "--workspace="+workspace, "--format=json").Output()
	if err != nil {
		return resource
	}
	var listed []struct {
		ID         string `json:"id"`
		UUID       string `json:"uuid"`
		BucketName string `json:"bucketName"`
	}
	if json.Unmarshal(out, &listed) != nil {
		return resource
	}
	for _, r := range listed {
		if r.ID != "" && (strings.EqualFold(r.UUID, resource) || (r.BucketName != "" && r.BucketName == bucketName)) {
			return r.ID
		}
	}
	return resource
}

// withCLIIDs returns a copy of a workflow tool's arguments with the workspace and any bucket
// resource named by UUID rewritten to the IDs the wb CLI takes. Every workflow tool that runs the
// CLI with --workspace calls it; the ones that call the Workflow API resolve the UUID instead
// (resolveWorkspaceId).
func withCLIIDs(arguments map[string]interface{}, bucketKeys ...string) map[string]interface{} {
	out := make(map[string]interface{}, len(arguments))
	for k, v := range arguments {
		out[k] = v
	}
	workspace, ok := optionalString(out, "workspaceId")
	if !ok {
		return out
	}
	workspace = cliWorkspaceID(workspace)
	out["workspaceId"] = workspace
	for _, key := range bucketKeys {
		if v, ok := optionalString(out, key); ok {
			out[key] = cliResourceID(workspace, v)
		}
	}
	return out
}
