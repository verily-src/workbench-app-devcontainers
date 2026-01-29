package docker

import (
	"bytes"
	"context"
	"fmt"
	"log"
	"sync"
	"text/template"

	"github.com/verily-src/workbench-app-devcontainers/src/playground/playground/internal/models"
)

// Service handles Docker operations and orchestration
type Service struct {
	client          *Client
	cancelFuncsLock sync.Mutex
	cancelFuncs     map[int]context.CancelFunc
}

// NewService creates a new Docker service
func NewService(client *Client) *Service {
	return &Service{
		client:      client,
		cancelFuncs: make(map[int]context.CancelFunc),
	}
}

// replaceCancelFunc sets the cancel function for an app and returns the old
// one if it exists
func (s *Service) replaceCancelFunc(appID int, newCancelFunc context.CancelFunc) (oldCancelFunc context.CancelFunc, exists bool) {
	s.cancelFuncsLock.Lock()
	defer s.cancelFuncsLock.Unlock()

	oldCancel, exists := s.cancelFuncs[appID]
	s.cancelFuncs[appID] = newCancelFunc

	return oldCancel, exists
}

// CancelAndRegisterBuild cancels any ongoing build for the app and registers the new cancel function
func (s *Service) CancelAndRegisterBuild(appID int, newCancelFunc context.CancelFunc) {
	// Cancel previous build if one exists
	if oldCancel, exists := s.replaceCancelFunc(appID, newCancelFunc); exists {
		log.Printf("Cancelling previous build for app %d", appID)
		oldCancel()
	}
}

// RemoveCancelFunc removes the cancel function after build completes or fails
func (s *Service) RemoveCancelFunc(appID int) {
	s.cancelFuncsLock.Lock()
	defer s.cancelFuncsLock.Unlock()
	delete(s.cancelFuncs, appID)
}

// renderDockerfileTemplate renders the Dockerfile template with variables
func (s *Service) renderDockerfileTemplate(dockerfileTemplate string, appID int, appName string, port int) (string, error) {
	// Prepare template variables
	vars := TemplateVars{
		AppName:       appName,
		ContainerName: fmt.Sprintf("app-%d", appID),
		Port:          port,
	}

	// Parse and execute template
	tmpl, err := template.New("dockerfile").Parse(dockerfileTemplate)
	if err != nil {
		return "", fmt.Errorf("failed to parse Dockerfile template: %w", err)
	}

	var buf bytes.Buffer
	if err := tmpl.Execute(&buf, vars); err != nil {
		return "", fmt.Errorf("failed to execute Dockerfile template: %w", err)
	}

	return buf.String(), nil
}

// BuildContainer generates devcontainer configuration and builds the container
// This is a synchronous operation that should be called from an async context
// stopExisting: if true, stops the existing container before rebuilding
func (s *Service) BuildContainer(ctx context.Context, app *models.App, stopExisting bool) error {
	appDir := fmt.Sprintf("%s/app-%d", s.client.getAppsBaseDir(), app.ID)

	// Stop existing container if requested (for updates)
	if stopExisting {
		if err := s.client.stop(ctx, app.ID, appDir); err != nil {
			log.Printf("Warning: Failed to stop container for app %d: %v", app.ID, err)
		}
	}

	// Generate .devcontainer.json
	generatedDir, err := s.client.generateDevcontainerConfig(
		app.ID,
		app.AppName,
		app.Username,
		app.UserHomeDirectory,
		app.OptionalFeatures,
	)
	if err != nil {
		return fmt.Errorf("failed to generate devcontainer config: %w", err)
	}

	// Render Dockerfile template
	renderedDockerfile, err := s.renderDockerfileTemplate(app.Dockerfile, app.ID, app.AppName, app.Port)
	if err != nil {
		return fmt.Errorf("failed to render Dockerfile template: %w", err)
	}

	// Generate docker-compose.yaml and Dockerfile
	if err := s.client.generateDockerCompose(ctx, generatedDir, app.AppName, app.Port, app.ID, renderedDockerfile); err != nil {
		return fmt.Errorf("failed to generate docker-compose: %w", err)
	}

	// Build and start container (long-running operation)
	if err := s.client.buildAndStart(ctx, generatedDir); err != nil {
		return fmt.Errorf("failed to build and start container: %w", err)
	}

	log.Printf("Container created and started for app %d (%s)", app.ID, app.AppName)
	return nil
}

// RemoveContainer stops and removes container
func (s *Service) RemoveContainer(ctx context.Context, appID int) error {
	if err := s.client.cleanup(ctx, appID); err != nil {
		return fmt.Errorf("failed to cleanup container: %w", err)
	}

	// Cleanup the cancel function to prevent memory leak
	s.RemoveCancelFunc(appID)

	log.Printf("Container removed for app %d", appID)
	return nil
}

// StartContainer starts a stopped container
func (s *Service) StartContainer(ctx context.Context, appID int) error {
	if err := s.client.start(ctx, appID); err != nil {
		return fmt.Errorf("failed to start container: %w", err)
	}

	log.Printf("Container started for app %d", appID)
	return nil
}

// StopContainer stops a running container
func (s *Service) StopContainer(ctx context.Context, appID int) error {
	if err := s.client.stopContainer(ctx, appID); err != nil {
		return fmt.Errorf("failed to stop container: %w", err)
	}

	log.Printf("Container stopped for app %d", appID)
	return nil
}

// EnrichWithContainerStatus adds container status to an app
func (s *Service) EnrichWithContainerStatus(ctx context.Context, app *models.App) {
	status, err := s.client.getContainerStatus(ctx, app.ID)
	if err != nil {
		log.Printf("Warning: Failed to get container status for app %d: %v", app.ID, err)
		app.ContainerStatus = ContainerStatusUnknown
		return
	}
	app.ContainerStatus = status
}

// EnrichWithContainerStatuses adds container status to multiple apps
func (s *Service) EnrichWithContainerStatuses(ctx context.Context, apps []*models.App) {
	for _, app := range apps {
		s.EnrichWithContainerStatus(ctx, app)
	}
}

// GetContainerStatus returns the container status for an app
func (s *Service) GetContainerStatus(ctx context.Context, appID int) (string, error) {
	return s.client.getContainerStatus(ctx, appID)
}

// GetContainerLogs returns the logs for an app container
func (s *Service) GetContainerLogs(ctx context.Context, appID int, tail int) (string, error) {
	return s.client.getContainerLogs(ctx, appID, tail)
}

// GetPlaygroundLogs returns logs from the playground container
func (s *Service) GetPlaygroundLogs(ctx context.Context, tail int) (string, error) {
	return s.client.getPlaygroundLogs(ctx, tail)
}

// HealthCheck verifies Docker is accessible
func (s *Service) HealthCheck(ctx context.Context) error {
	return s.client.healthCheck(ctx)
}
