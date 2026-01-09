package main

import (
	"context"
	"database/sql"
	"fmt"
	"log"
	"sync"
)

type DockerService struct {
	docker          *DockerClient
	db              *sql.DB
	cancelFuncsLock sync.RWMutex
	cancelFuncs     map[int]context.CancelFunc
}

func NewDockerService(docker *DockerClient, db *sql.DB) *DockerService {
	return &DockerService{
		docker:      docker,
		db:          db,
		cancelFuncs: make(map[int]context.CancelFunc),
	}
}

// cancelAndRegisterBuild cancels any ongoing build for the app and registers the new cancel function
func (s *DockerService) cancelAndRegisterBuild(appID int, newCancelFunc context.CancelFunc) {
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

// removeCancelFunc removes the cancel function after build completes or fails
func (s *DockerService) removeCancelFunc(appID int) {
	s.cancelFuncsLock.Lock()
	delete(s.cancelFuncs, appID)
	s.cancelFuncsLock.Unlock()
}

// SetupContainerAsync creates devcontainer configuration and builds the container asynchronously
// Returns immediately - container build happens in background with 30 minute timeout
// If a build is already in progress for this app, it will be cancelled
func (s *DockerService) SetupContainerAsync(app *App, caddyService *CaddyService) {
	go func() {
		// Create context with 30 minute timeout
		ctx, cancel := context.WithTimeout(context.Background(), DockerBuildTimeout)
		defer cancel()

		// Cancel any previous build and register this one
		s.cancelAndRegisterBuild(app.ID, cancel)
		defer s.removeCancelFunc(app.ID)

		// Generate .devcontainer.json
		appDir, err := s.docker.GenerateDevcontainerConfig(
			app.ID,
			app.AppName,
			app.Username,
			app.UserHomeDirectory,
			app.OptionalFeatures,
		)
		if err != nil {
			log.Printf("Error generating devcontainer config for app %d: %v", app.ID, err)
			s.UpdateStatus(ctx, app.ID, "failed")
			return
		}

		// Generate docker-compose.yaml and Dockerfile
		if err := s.docker.GenerateDockerCompose(appDir, app.AppName, app.Port, app.ID, app.Dockerfile); err != nil {
			log.Printf("Error generating docker-compose for app %d: %v", app.ID, err)
			s.UpdateStatus(ctx, app.ID, "failed")
			return
		}

		// Build and start container (long-running operation)
		if err := s.docker.BuildAndStart(ctx, appDir); err != nil {
			log.Printf("Error building and starting container for app %d: %v", app.ID, err)
			s.UpdateStatus(ctx, app.ID, "failed")
			return
		}

		log.Printf("Container created and started for app %d (%s)", app.ID, app.AppName)

		// Sync with Caddy
		if err := caddyService.SyncApp(ctx, app.ID, app.AppName, app.Port); err != nil {
			log.Printf("Error syncing app %d with Caddy: %v", app.ID, err)
			s.UpdateStatus(ctx, app.ID, "failed")
			return
		}

		// Success - status is already set to 'active' by SyncApp
		log.Printf("App %d (%s) fully provisioned and active", app.ID, app.AppName)
	}()
}

// UpdateStatus updates app status in database
func (s *DockerService) UpdateStatus(ctx context.Context, appID int, status string) error {
	query := `UPDATE apps SET status = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2`
	_, err := s.db.ExecContext(ctx, query, status, appID)
	if err != nil {
		log.Printf("Error updating status for app %d: %v", appID, err)
	}
	return err
}

// UpdateContainerAsync rebuilds container when app is updated (asynchronously)
// Returns immediately - container rebuild happens in background with 30 minute timeout
// If a build is already in progress for this app, it will be cancelled
func (s *DockerService) UpdateContainerAsync(app *App, oldAppName string, oldPort int, caddyService *CaddyService) {
	go func() {
		// Create context with 30 minute timeout
		ctx, cancel := context.WithTimeout(context.Background(), DockerBuildTimeout)
		defer cancel()

		// Cancel any previous build and register this one
		s.cancelAndRegisterBuild(app.ID, cancel)
		defer s.removeCancelFunc(app.ID)

		// Update status to pending
		s.UpdateStatus(ctx, app.ID, "pending")

		appDir := fmt.Sprintf("%s/app-%d", s.docker.appsBaseDir, app.ID)

		// Stop existing container
		if err := s.docker.Stop(ctx, app.ID, appDir); err != nil {
			log.Printf("Warning: Failed to stop container for app %d: %v", app.ID, err)
		}

		// Regenerate configuration
		if _, err := s.docker.GenerateDevcontainerConfig(
			app.ID,
			app.AppName,
			app.Username,
			app.UserHomeDirectory,
			app.OptionalFeatures,
		); err != nil {
			log.Printf("Error regenerating devcontainer config for app %d: %v", app.ID, err)
			s.UpdateStatus(ctx, app.ID, "failed")
			return
		}

		if err := s.docker.GenerateDockerCompose(appDir, app.AppName, app.Port, app.ID, app.Dockerfile); err != nil {
			log.Printf("Error regenerating docker-compose for app %d: %v", app.ID, err)
			s.UpdateStatus(ctx, app.ID, "failed")
			return
		}

		// Rebuild and restart (long-running operation)
		if err := s.docker.BuildAndStart(ctx, appDir); err != nil {
			log.Printf("Error rebuilding and starting container for app %d: %v", app.ID, err)
			s.UpdateStatus(ctx, app.ID, "failed")
			return
		}

		log.Printf("Container updated for app %d (%s)", app.ID, app.AppName)

		// Sync with Caddy if name or port changed
		if oldAppName != app.AppName || oldPort != app.Port {
			if err := caddyService.UpdateApp(ctx, app.ID, oldAppName, app.AppName, oldPort, app.Port); err != nil {
				log.Printf("Error syncing app %d with Caddy: %v", app.ID, err)
				s.UpdateStatus(ctx, app.ID, "failed")
				return
			}
		} else {
			// No Caddy update needed, just update status to active
			s.UpdateStatus(ctx, app.ID, "active")
		}

		log.Printf("App %d (%s) fully updated and active", app.ID, app.AppName)
	}()
}

// RemoveContainer stops and removes container
func (s *DockerService) RemoveContainer(ctx context.Context, appID int) error {
	if err := s.docker.Cleanup(ctx, appID); err != nil {
		return fmt.Errorf("failed to cleanup container: %w", err)
	}

	// Cleanup the cancel function to prevent memory leak
	s.removeCancelFunc(appID)

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
