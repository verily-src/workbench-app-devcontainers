package main

import (
	"context"
	"database/sql"
	"fmt"
	"log"
)

// CaddyService handles Caddy operations and status updates
type CaddyService struct {
	caddy *CaddyClient
	db    *sql.DB
}

// NewCaddyService creates a new Caddy service
func NewCaddyService(caddy *CaddyClient, db *sql.DB) *CaddyService {
	return &CaddyService{caddy: caddy, db: db}
}

// SyncAllApps syncs all apps from database to Caddy on startup
func (s *CaddyService) SyncAllApps(ctx context.Context) error {
	// Clear all Caddy routes
	if err := s.caddy.DeleteAllRoutes(ctx); err != nil {
		return fmt.Errorf("failed to clear Caddy routes: %w", err)
	}
	log.Println("Cleared all Caddy routes")

	// Get all apps from database
	query := `SELECT id, app_name, port FROM apps ORDER BY id`
	rows, err := s.db.QueryContext(ctx, query)
	if err != nil {
		return fmt.Errorf("failed to query apps: %w", err)
	}
	defer rows.Close()

	var syncedCount, errorCount int

	// Add app routes first (so they are evaluated before default routes)
	for rows.Next() {
		var appID, port int
		var appName string

		if err := rows.Scan(&appID, &appName, &port); err != nil {
			log.Printf("Error scanning app row: %v", err)
			continue
		}

		// Add route to Caddy
		if err := s.caddy.AddRoute(ctx, appID, appName, port); err != nil {
			log.Printf("Error adding route for app %d (%s): %v", appID, appName, err)
			s.updateStatus(ctx, appID, "failed")
			errorCount++
			continue
		}

		// Update status to active
		if err := s.updateStatus(ctx, appID, "active"); err != nil {
			log.Printf("Warning: Failed to update status for app %d: %v", appID, err)
		}
		syncedCount++
	}

	if err = rows.Err(); err != nil {
		return fmt.Errorf("error iterating rows: %w", err)
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

// updateStatus updates app status in database
func (s *CaddyService) updateStatus(ctx context.Context, appID int, status string) error {
	query := `UPDATE apps SET status = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2`
	_, err := s.db.ExecContext(ctx, query, status, appID)
	return err
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
