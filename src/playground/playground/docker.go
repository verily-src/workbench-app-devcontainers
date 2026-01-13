package main

import (
	"context"
	"encoding/json"
	"fmt"
	"maps"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
)

type DockerClient struct {
	appsBaseDir        string
	startupScriptMount string
}

func NewDockerClient(baseDir string) *DockerClient {
	return &DockerClient{
		appsBaseDir: baseDir,
	}
}

// GetStartupScriptMount inspects the playground container to find the startupscript mount
func (d *DockerClient) GetStartupScriptMount(ctx context.Context) (string, error) {
	// If already cached, return it
	if d.startupScriptMount != "" {
		return d.startupScriptMount, nil
	}

	// Inspect the playground container to find mounts
	cmd := exec.CommandContext(ctx, "docker", "inspect", "-f", "{{json .Mounts}}", "playground")
	output, err := cmd.CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("failed to inspect playground container: %w, output: %s", err, string(output))
	}

	// Parse mounts
	var mounts []struct {
		Type        string `json:"Type"`
		Source      string `json:"Source"`
		Destination string `json:"Destination"`
	}

	if err := json.Unmarshal(output, &mounts); err != nil {
		return "", fmt.Errorf("failed to parse mounts: %w", err)
	}

	// Find the startupscript mount
	for _, mount := range mounts {
		if mount.Destination == "/workspace/startupscript" {
			d.startupScriptMount = mount.Source
			return mount.Source, nil
		}
	}

	return "", fmt.Errorf("startupscript mount not found in playground container")
}

// GenerateDevcontainerConfig creates .devcontainer.json for an app
func (d *DockerClient) GenerateDevcontainerConfig(appID int, appName, username, userHomeDir string, optionalFeatures []string) (string, error) {
	appDir := filepath.Join(d.appsBaseDir, fmt.Sprintf("app-%d", appID))

	// Create app directory
	if err := os.MkdirAll(appDir, 0755); err != nil {
		return "", fmt.Errorf("failed to create app directory: %w", err)
	}

	// Check which features are requested
	hasWB := slices.Contains(optionalFeatures, FeatureWB)
	hasWorkbenchTools := slices.Contains(optionalFeatures, FeatureWorkbenchTools)

	// Build features object
	features := make(map[string]any)
	var optionalCommands string

	if hasWB {
		// Add WB features (includes java, aws-cli, gcloud)
		maps.Copy(features, WBFeatures)

		// Add postCreateCommand and postStartCommand
		postCreate := fmt.Sprintf(PostCreateCommandTemplate, username, userHomeDir)
		postStart := fmt.Sprintf(PostStartCommandTemplate, username, userHomeDir)
		optionalCommands = postCreate + postStart
	}

	if hasWorkbenchTools {
		// Copy workbench-tools feature to app directory
		featuresDestDir := filepath.Join(appDir, ".devcontainer", "features")
		workbenchToolsDest := filepath.Join(featuresDestDir, "workbench-tools")

		// Remove destination if it already exists (CopyFS fails if dest exists)
		if err := os.RemoveAll(workbenchToolsDest); err != nil {
			return "", fmt.Errorf("failed to remove existing workbench-tools directory: %w", err)
		}

		// Ensure parent directory exists
		if err := os.MkdirAll(featuresDestDir, 0755); err != nil {
			return "", fmt.Errorf("failed to create features directory: %w", err)
		}

		// Copy workbench-tools feature files using os.CopyFS
		workbenchToolsFS := os.DirFS(WorkbenchToolsFeaturePath)
		if err := os.CopyFS(workbenchToolsDest, workbenchToolsFS); err != nil {
			return "", fmt.Errorf("failed to copy workbench-tools feature: %w", err)
		}

		// Add workbench-tools feature to features map with relative path
		features["./.devcontainer/features/workbench-tools"] = map[string]string{
			"cloud":       "gcp",
			"username":    username,
			"userHomeDir": userHomeDir,
		}
	}

	featuresJSON, err := json.MarshalIndent(features, "  ", "  ")
	if err != nil {
		return "", fmt.Errorf("failed to marshal features: %w", err)
	}

	// Generate .devcontainer.json
	devcontainerContent := fmt.Sprintf(
		DevcontainerTemplate,
		appName,
		userHomeDir,
		string(featuresJSON),
		optionalCommands,
	)

	devcontainerPath := filepath.Join(appDir, ".devcontainer.json")
	if err := os.WriteFile(devcontainerPath, []byte(devcontainerContent), 0644); err != nil {
		return "", fmt.Errorf("failed to write .devcontainer.json: %w", err)
	}

	return appDir, nil
}

// GenerateDockerCompose creates docker-compose.yaml for an app
func (d *DockerClient) GenerateDockerCompose(ctx context.Context, appDir, appName string, port, appID int, dockerfile string) error {
	// Write Dockerfile
	dockerfilePath := filepath.Join(appDir, "Dockerfile")
	if err := os.WriteFile(dockerfilePath, []byte(dockerfile), 0644); err != nil {
		return fmt.Errorf("failed to write Dockerfile: %w", err)
	}

	// Get startup script mount from playground container
	startupScriptMount, err := d.GetStartupScriptMount(ctx)
	if err != nil {
		return fmt.Errorf("failed to get startup script mount: %w", err)
	}

	// Generate docker-compose.yaml (minimal - devcontainer will handle the rest)
	// Use unique container name per app to avoid conflicts
	containerName := fmt.Sprintf("app-%d", appID)
	composeContent := fmt.Sprintf(DockerComposeTemplate, containerName, appName, startupScriptMount)

	composePath := filepath.Join(appDir, "docker-compose.yaml")
	if err := os.WriteFile(composePath, []byte(composeContent), 0644); err != nil {
		return fmt.Errorf("failed to write docker-compose.yaml: %w", err)
	}

	return nil
}

// BuildAndStart builds the devcontainer and starts the container
func (d *DockerClient) BuildAndStart(ctx context.Context, appDir string) error {
	// Build with devcontainer CLI
	buildCmd := exec.CommandContext(ctx, "devcontainer", "build", "--workspace-folder", appDir)
	buildCmd.Dir = appDir
	buildCmd.Stdout = os.Stdout
	buildCmd.Stderr = os.Stderr

	if err := buildCmd.Run(); err != nil {
		return fmt.Errorf("devcontainer build failed: %w", err)
	}

	// Start container with devcontainer CLI
	upCmd := exec.CommandContext(ctx, "devcontainer", "up", "--workspace-folder", appDir)
	upCmd.Dir = appDir
	upCmd.Stdout = os.Stdout
	upCmd.Stderr = os.Stderr

	if err := upCmd.Run(); err != nil {
		return fmt.Errorf("devcontainer up failed: %w", err)
	}

	return nil
}

// Start starts an existing stopped container
func (d *DockerClient) Start(ctx context.Context, appID int) error {
	containerName := fmt.Sprintf("app-%d", appID)

	// Start container using docker CLI
	startCmd := exec.CommandContext(ctx, "docker", "start", containerName)

	output, err := startCmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("docker start failed: %w, output: %s", err, string(output))
	}

	return nil
}

// StopContainer stops the container without removing it
func (d *DockerClient) StopContainer(ctx context.Context, appID int) error {
	containerName := fmt.Sprintf("app-%d", appID)

	// Stop container using docker CLI
	stopCmd := exec.CommandContext(ctx, "docker", "stop", containerName)

	output, err := stopCmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("docker stop failed: %w, output: %s", err, string(output))
	}

	return nil
}

// GetContainerStatus returns the status of a container (running, exited, etc.)
func (d *DockerClient) GetContainerStatus(ctx context.Context, appID int) (string, error) {
	containerName := fmt.Sprintf("app-%d", appID)

	// Get container status using docker inspect
	inspectCmd := exec.CommandContext(ctx, "docker", "inspect", "-f", "{{.State.Status}}", containerName)

	output, err := inspectCmd.CombinedOutput()
	if err != nil {
		// Container doesn't exist
		return "not_found", nil
	}

	status := string(output)
	status = status[:len(status)-1] // Remove trailing newline
	return status, nil
}

// Stop stops the container and removes it
func (d *DockerClient) Stop(ctx context.Context, appID int, appDir string) error {
	containerName := fmt.Sprintf("app-%d", appID)

	// Stop container using docker CLI
	stopCmd := exec.CommandContext(ctx, "docker", "stop", containerName)
	stopCmd.Dir = appDir

	output, err := stopCmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("docker stop failed: %w, output: %s", err, string(output))
	}

	// Remove container
	rmCmd := exec.CommandContext(ctx, "docker", "rm", containerName)
	rmCmd.Dir = appDir

	output, err = rmCmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("docker rm failed: %w, output: %s", err, string(output))
	}

	return nil
}

// Cleanup removes app directory and associated resources
func (d *DockerClient) Cleanup(ctx context.Context, appID int) error {
	appDir := filepath.Join(d.appsBaseDir, fmt.Sprintf("app-%d", appID))

	// Stop container first (best effort)
	_ = d.Stop(ctx, appID, appDir)

	// Remove directory
	if err := os.RemoveAll(appDir); err != nil {
		return fmt.Errorf("failed to remove app directory: %w", err)
	}

	return nil
}

// HealthCheck verifies Docker is accessible
func (d *DockerClient) HealthCheck(ctx context.Context) error {
	cmd := exec.CommandContext(ctx, "docker", "info")
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("docker not accessible: %w", err)
	}
	return nil
}

// GetLogs retrieves logs from a container
func (d *DockerClient) GetLogs(ctx context.Context, containerName string, tail int) (string, error) {
	args := []string{"logs", "--tail", fmt.Sprintf("%d", tail), containerName}
	cmd := exec.CommandContext(ctx, "docker", args...)

	output, err := cmd.CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("failed to get logs for %s: %w", containerName, err)
	}

	return string(output), nil
}

// GetContainerLogs retrieves logs from an app container
func (d *DockerClient) GetContainerLogs(ctx context.Context, appID int, tail int) (string, error) {
	containerName := fmt.Sprintf("app-%d", appID)
	return d.GetLogs(ctx, containerName, tail)
}

// GetPlaygroundLogs retrieves logs from the playground container
func (d *DockerClient) GetPlaygroundLogs(ctx context.Context, tail int) (string, error) {
	return d.GetLogs(ctx, "playground", tail)
}
