package main

import "time"

// Context timeout durations for different operation types
const (
	HealthCheckTimeout = 2 * time.Second
	ReadTimeout        = 5 * time.Second
	WriteTimeout       = 10 * time.Second
	DockerTimeout      = 30 * time.Second // Timeout for Docker start/stop operations

	// Docker configuration
	DockerBuildTimeout = 30 * time.Minute // 30 minute timeout for async build operations
	AppsBaseDir        = "/workspace/apps"

	// Optional feature names
	FeatureWB             = "wb"
	FeatureWorkbenchTools = "workbench-tools"

	// Container status values
	ContainerStatusNotFound = "not_found"
	ContainerStatusUnknown  = "unknown"
)

// CaddyTemplateVars holds variables for rendering Caddy templates
type CaddyTemplateVars struct {
	AppName       string
	ContainerName string
	Port          int
}

// DevcontainerTemplate for generating .devcontainer.json
const DevcontainerTemplate = `{
  "name": "%s",
  "dockerComposeFile": "docker-compose.yaml",
  "service": "app",
  "workspaceFolder": "%s",
  "features": %s,
  "remoteUser": "root"%s
}`

// WBFeatures defines the devcontainer features required for wb CLI
var WBFeatures = map[string]any{
	"ghcr.io/devcontainers/features/java:1": map[string]string{
		"version": "17",
	},
	"ghcr.io/devcontainers/features/aws-cli:1":    map[string]any{},
	"ghcr.io/dhoeric/features/google-cloud-cli:1": map[string]any{},
}

// WorkbenchToolsFeaturePath is the source path for the workbench-tools feature
const WorkbenchToolsFeaturePath = "/workspace/features/src/workbench-tools"

// DockerComposeTemplate for generating docker-compose.yaml for apps
const DockerComposeTemplate = `services:
  app:
    platform: linux/amd64
    build:
      context: .
      dockerfile: Dockerfile
    container_name: %s
    networks:
      - playground_playground-apps
    cap_add:
      - SYS_ADMIN
    devices:
      - /dev/fuse
    security_opt:
      - apparmor:unconfined
    volumes:
      - %s:/workspace/startupscript:ro

networks:
  playground_playground-apps:
    external: true
`

// PostCreateCommandTemplate for wb CLI installation
const PostCreateCommandTemplate = `,
  "postCreateCommand": [
    "/workspace/startupscript/post-startup.sh",
    "%s",
    "%s",
    "%s",
    "true"
  ]`

// PostStartCommandTemplate for wb CLI on container restart
const PostStartCommandTemplate = `,
  "postStartCommand": [
    "/workspace/startupscript/remount-on-restart.sh",
    "%s",
    "%s",
    "%s",
    "true"
  ]`
