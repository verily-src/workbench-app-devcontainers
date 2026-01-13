package main

import (
	"context"
	"fmt"
	"log"
	"sync"
)

type DockerService struct {
	docker          *DockerClient
	db              *DB
	cancelFuncsLock sync.RWMutex
	cancelFuncs     map[int]context.CancelFunc
}

func NewDockerService(docker *DockerClient, db *DB) *DockerService {
	return &DockerService{
		docker:      docker,
		db:          db,
		cancelFuncs: make(map[int]context.CancelFunc),
	}
}

// CancelAndRegisterBuild cancels any ongoing build for the app and registers the new cancel function
func (s *DockerService) CancelAndRegisterBuild(appID int, newCancelFunc context.CancelFunc) {
	s.cancelFuncsLock.Lock()
	defer s.cancelFuncsLock.Unlock()

	// Cancel previous build if one exists
	if oldCancel, exists := s.cancelFuncs[appID]; exists {
		log.Printf("Cancelling previous build for app %d", appID)
		oldCancel()
	}

	// Register new cancel function
	s.cancelFuncs[appID] = newCancelFunc
}

// RemoveCancelFunc removes the cancel function after build completes or fails
func (s *DockerService) RemoveCancelFunc(appID int) {
	s.cancelFuncsLock.Lock()
	delete(s.cancelFuncs, appID)
	s.cancelFuncsLock.Unlock()
}

// BuildContainer generates devcontainer configuration and builds the container
// This is a synchronous operation that should be called from an async context
// stopExisting: if true, stops the existing container before rebuilding
func (s *DockerService) BuildContainer(ctx context.Context, app *App, stopExisting bool) error {
	appDir := fmt.Sprintf("%s/app-%d", s.docker.appsBaseDir, app.ID)

	// Stop existing container if requested (for updates)
	if stopExisting {
		if err := s.docker.Stop(ctx, app.ID, appDir); err != nil {
			log.Printf("Warning: Failed to stop container for app %d: %v", app.ID, err)
		}
	}

	// Generate .devcontainer.json
	generatedDir, err := s.docker.GenerateDevcontainerConfig(
		app.ID,
		app.AppName,
		app.Username,
		app.UserHomeDirectory,
		app.OptionalFeatures,
	)
	if err != nil {
		return fmt.Errorf("failed to generate devcontainer config: %w", err)
	}

	// Generate docker-compose.yaml and Dockerfile
	if err := s.docker.GenerateDockerCompose(ctx, generatedDir, app.AppName, app.Port, app.ID, app.Dockerfile); err != nil {
		return fmt.Errorf("failed to generate docker-compose: %w", err)
	}

	// Build and start container (long-running operation)
	if err := s.docker.BuildAndStart(ctx, generatedDir); err != nil {
		return fmt.Errorf("failed to build and start container: %w", err)
	}

	log.Printf("Container created and started for app %d (%s)", app.ID, app.AppName)
	return nil
}

// UpdateStatus updates app status in database (delegates to DB layer)
func (s *DockerService) UpdateStatus(ctx context.Context, appID int, status string) error {
	if err := s.db.UpdateAppStatus(ctx, appID, status); err != nil {
		log.Printf("Error updating status for app %d: %v", appID, err)
		return err
	}
	return nil
}


// RemoveContainer stops and removes container
func (s *DockerService) RemoveContainer(ctx context.Context, appID int) error {
	if err := s.docker.Cleanup(ctx, appID); err != nil {
		return fmt.Errorf("failed to cleanup container: %w", err)
	}

	// Cleanup the cancel function to prevent memory leak
	s.RemoveCancelFunc(appID)

	log.Printf("Container removed for app %d", appID)
	return nil
}

// StartContainer starts a stopped container
func (s *DockerService) StartContainer(ctx context.Context, appID int) error {
	if err := s.docker.Start(ctx, appID); err != nil {
		return fmt.Errorf("failed to start container: %w", err)
	}

	log.Printf("Container started for app %d", appID)
	return nil
}

// StopContainer stops a running container
func (s *DockerService) StopContainer(ctx context.Context, appID int) error {
	if err := s.docker.StopContainer(ctx, appID); err != nil {
		return fmt.Errorf("failed to stop container: %w", err)
	}

	log.Printf("Container stopped for app %d", appID)
	return nil
}

// EnrichWithContainerStatus adds container status to an app
func (s *DockerService) EnrichWithContainerStatus(ctx context.Context, app *App) {
	status, err := s.docker.GetContainerStatus(ctx, app.ID)
	if err != nil {
		log.Printf("Warning: Failed to get container status for app %d: %v", app.ID, err)
		app.ContainerStatus = "unknown"
		return
	}
	app.ContainerStatus = status
}

// EnrichWithContainerStatuses adds container status to multiple apps
func (s *DockerService) EnrichWithContainerStatuses(ctx context.Context, apps []*App) {
	for _, app := range apps {
		s.EnrichWithContainerStatus(ctx, app)
	}
}
