package main

import (
	"context"
	"fmt"
	"log"
)

// CaddyService handles Caddy operations and status updates
type CaddyService struct {
	caddy *CaddyClient
	db    *DB
}

// NewCaddyService creates a new Caddy service
func NewCaddyService(caddy *CaddyClient, db *DB) *CaddyService {
	return &CaddyService{caddy: caddy, db: db}
}

// SyncAllApps syncs all apps from database to Caddy on startup
func (s *CaddyService) SyncAllApps(ctx context.Context) error {
	// Reset Caddy routes to default (clears all and adds back playground UI route)
	if err := s.caddy.ResetRoutes(ctx); err != nil {
		return fmt.Errorf("failed to reset Caddy routes: %w", err)
	}
	log.Println("Reset Caddy routes to default")

	// Get all apps from database using DB layer
	apps, err := s.db.GetAppsForCaddySync(ctx)
	if err != nil {
		return fmt.Errorf("failed to get apps for sync: %w", err)
	}

	var syncedCount, errorCount int

	// Add app routes first (so they are evaluated before default routes)
	for _, app := range apps {
		// Add route to Caddy
		if err := s.caddy.AddRoute(ctx, app.ID, app.AppName, app.Port); err != nil {
			log.Printf("Error adding route for app %d (%s): %v", app.ID, app.AppName, err)
			s.updateStatus(ctx, app.ID, "failed")
			errorCount++
			continue
		}

		// Update status to active
		if err := s.updateStatus(ctx, app.ID, "active"); err != nil {
			log.Printf("Warning: Failed to update status for app %d: %v", app.ID, err)
		}
		syncedCount++
	}

	log.Printf("Startup sync complete: %d apps synced, %d errors", syncedCount, errorCount)
	return nil
}

// SyncApp synchronizes an app with Caddy and updates status
func (s *CaddyService) SyncApp(ctx context.Context, appID int, appName string, port int) error {
	// Add route to Caddy
	if err := s.caddy.AddRoute(ctx, appID, appName, port); err != nil {
		// Update status to 'failed'
		if updateErr := s.updateStatus(ctx, appID, "failed"); updateErr != nil {
			log.Printf("Warning: Failed to update status to 'failed' for app %d: %v", appID, updateErr)
		}
		return fmt.Errorf("failed to add Caddy route: %w", err)
	}

	// Update status to 'active'
	if err := s.updateStatus(ctx, appID, "active"); err != nil {
		// Caddy route was added but status update failed
		// Log error but don't fail the operation
		log.Printf("Warning: Caddy route added but status update failed for app %d: %v", appID, err)
	}

	return nil
}

// updateStatus updates app status in database (delegates to DB layer)
func (s *CaddyService) updateStatus(ctx context.Context, appID int, status string) error {
	return s.db.UpdateAppStatus(ctx, appID, status)
}

// RemoveApp removes Caddy route for an app
func (s *CaddyService) RemoveApp(ctx context.Context, appName string) error {
	return s.caddy.DeleteRoute(ctx, appName)
}

// UpdateApp updates Caddy route when app changes
func (s *CaddyService) UpdateApp(ctx context.Context, appID int, oldName, newName string, oldPort, newPort int) error {
	// If nothing changed, no need to update
	if oldName == newName && oldPort == newPort {
		return nil
	}

	// Update status to pending during update
	if err := s.updateStatus(ctx, appID, "pending"); err != nil {
		log.Printf("Warning: Failed to update status to 'pending' for app %d: %v", appID, err)
	}

	// Update Caddy route (delete old, add new)
	if err := s.caddy.UpdateRoute(ctx, appID, oldName, newName, newPort); err != nil {
		if updateErr := s.updateStatus(ctx, appID, "failed"); updateErr != nil {
			log.Printf("Warning: Failed to update status to 'failed' for app %d: %v", appID, updateErr)
		}
		return err
	}

	// Update status to active
	if err := s.updateStatus(ctx, appID, "active"); err != nil {
		log.Printf("Warning: Caddy route updated but status update failed for app %d: %v", appID, err)
	}

	return nil
}
