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
)

// DevcontainerTemplate for generating .devcontainer.json
const DevcontainerTemplate = `{
  "name": "%s",
  "dockerComposeFile": "docker-compose.yaml",
  "service": "app",
  "workspaceFolder": "%s",
  "features": %s,
  "remoteUser": "%s"%s
}`

// WBFeatures defines the devcontainer features required for wb CLI
var WBFeatures = map[string]interface{}{
	"ghcr.io/devcontainers/features/java:1": map[string]string{
		"version": "17",
	},
	"ghcr.io/devcontainers/features/aws-cli:1": map[string]interface{}{},
	"ghcr.io/dhoeric/features/google-cloud-cli:1": map[string]interface{}{},
}

// PostCreateCommandTemplate for wb CLI installation
const PostCreateCommandTemplate = `,
  "postCreateCommand": [
    "/workspace/startupscript/post-startup.sh",
    "%s",
    "%s",
    "gcp",
    "true"
  ]`

// PostStartCommandTemplate for wb CLI on container restart
const PostStartCommandTemplate = `,
  "postStartCommand": [
    "/workspace/startupscript/remount-on-restart.sh",
    "%s",
    "%s",
    "gcp",
    "true"
  ]`
