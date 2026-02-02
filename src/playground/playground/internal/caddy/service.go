package caddy

import (
	"context"
	"fmt"
	"log"

	"github.com/verily-src/workbench-app-devcontainers/src/playground/playground/internal/db"
	"github.com/verily-src/workbench-app-devcontainers/src/playground/playground/internal/models"
)

// Service handles Caddy operations and status updates
type Service struct {
	client *Client
	db     *db.Client
}

// NewService creates a new Caddy service
func NewService(client *Client, dbClient *db.Client) *Service {
	return &Service{client: client, db: dbClient}
}

// SyncAllApps syncs all apps from database to Caddy on startup
func (s *Service) SyncAllApps(ctx context.Context) error {
	// Reset Caddy routes to default (clears all and adds back playground UI route)
	if err := s.client.resetRoutes(ctx); err != nil {
		return fmt.Errorf("failed to reset Caddy routes: %w", err)
	}
	log.Println("Reset Caddy routes to default")

	// Get all apps from database using DB layer
	apps, err := s.db.ListApps(ctx)
	if err != nil {
		return fmt.Errorf("failed to get apps for sync: %w", err)
	}

	var syncedCount, errorCount int

	// Add app routes first (so they are evaluated before default routes)
	for _, app := range apps {
		// Add route to Caddy
		if err := s.client.addRoute(ctx, app.ID, app.AppName, app.Port, app.CaddyConfig); err != nil {
			log.Printf("Error adding route for app %d (%s): %v", app.ID, app.AppName, err)
			s.db.UpdateAppStatus(ctx, app.ID, "failed")
			errorCount++
			continue
		}

		// Update status to active
		if err := s.db.UpdateAppStatus(ctx, app.ID, "active"); err != nil {
			log.Printf("Warning: Failed to update status for app %d: %v", app.ID, err)
		}
		syncedCount++
	}

	log.Printf("Startup sync complete: %d apps synced, %d errors", syncedCount, errorCount)
	return nil
}

// SyncApp synchronizes an app with Caddy and updates status
func (s *Service) SyncApp(ctx context.Context, appID int, appName string, port int, caddyConfig string) error {
	// Add route to Caddy
	if err := s.client.addRoute(ctx, appID, appName, port, caddyConfig); err != nil {
		// Update status to 'failed'
		if updateErr := s.db.UpdateAppStatus(ctx, appID, "failed"); updateErr != nil {
			log.Printf("Warning: Failed to update status to 'failed' for app %d: %v", appID, updateErr)
		}
		return fmt.Errorf("failed to add Caddy route: %w", err)
	}

	// Update status to 'active'
	if err := s.db.UpdateAppStatus(ctx, appID, "active"); err != nil {
		// Caddy route was added but status update failed
		// Log error but don't fail the operation
		log.Printf("Warning: Caddy route added but status update failed for app %d: %v", appID, err)
	}

	return nil
}

// RemoveApp removes Caddy route for an app
func (s *Service) RemoveApp(ctx context.Context, appName string) error {
	return s.client.deleteRoute(ctx, appName)
}

// UpdateApp updates Caddy route when app changes
func (s *Service) UpdateApp(ctx context.Context, oldApp, newApp *models.App) error {
	// If nothing changed, no need to update
	if oldApp.AppName == newApp.AppName && oldApp.Port == newApp.Port && oldApp.CaddyConfig == newApp.CaddyConfig {
		return nil
	}

	// Update status to pending during update
	if err := s.db.UpdateAppStatus(ctx, newApp.ID, "pending"); err != nil {
		log.Printf("Warning: Failed to update status to 'pending' for app %d: %v", newApp.ID, err)
	}

	// Update Caddy route (delete old, add new)
	if err := s.client.updateRoute(ctx, newApp.ID, oldApp.AppName, newApp.AppName, newApp.Port, newApp.CaddyConfig); err != nil {
		if updateErr := s.db.UpdateAppStatus(ctx, newApp.ID, "failed"); updateErr != nil {
			log.Printf("Warning: Failed to update status to 'failed' for app %d: %v", newApp.ID, updateErr)
		}
		return err
	}

	// Update status to active
	if err := s.db.UpdateAppStatus(ctx, newApp.ID, "active"); err != nil {
		log.Printf("Warning: Caddy route updated but status update failed for app %d: %v", newApp.ID, err)
	}

	return nil
}

// HealthCheck verifies Caddy API is accessible
func (s *Service) HealthCheck(ctx context.Context) error {
	return s.client.healthCheck(ctx)
}
