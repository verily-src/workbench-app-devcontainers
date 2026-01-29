package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strconv"
	"strings"

	"github.com/verily-src/workbench-app-devcontainers/src/playground/playground/internal/caddy"
	"github.com/verily-src/workbench-app-devcontainers/src/playground/playground/internal/db"
	"github.com/verily-src/workbench-app-devcontainers/src/playground/playground/internal/docker"
	"github.com/verily-src/workbench-app-devcontainers/src/playground/playground/internal/models"
)

// setupContainer creates devcontainer configuration and builds the container
// Should be called with 'go' to run asynchronously
// If a build is already in progress for this app, it will be cancelled
func setupContainer(app *models.App, dbClient *db.Client, dockerService *docker.Service, caddyService *caddy.Service) {
	// Create context with 30 minute timeout
	ctx, cancel := context.WithTimeout(context.Background(), docker.BuildTimeout)
	defer cancel()

	// Cancel any previous build and register this one
	dockerService.CancelAndRegisterBuild(app.ID, cancel)
	defer dockerService.RemoveCancelFunc(app.ID)

	// Build container (common Docker operations)
	if err := dockerService.BuildContainer(ctx, app, false); err != nil {
		log.Printf("Error building container for app %d: %v", app.ID, err)
		dbClient.UpdateAppStatus(ctx, app.ID, "failed")
		return
	}

	// Sync with Caddy
	if err := caddyService.SyncApp(ctx, app.ID, app.AppName, app.Port, app.CaddyConfig); err != nil {
		log.Printf("Error syncing app %d with Caddy: %v", app.ID, err)
		dbClient.UpdateAppStatus(ctx, app.ID, "failed")
		return
	}

	// Success - status is already set to 'active' by SyncApp
	log.Printf("App %d (%s) fully provisioned and active", app.ID, app.AppName)
}

// updateContainer rebuilds container when app is updated
// Should be called with 'go' to run asynchronously
// If a build is already in progress for this app, it will be cancelled
func updateContainer(oldApp, newApp *models.App, dbClient *db.Client, dockerService *docker.Service, caddyService *caddy.Service) {
	// Create context with 30 minute timeout
	ctx, cancel := context.WithTimeout(context.Background(), docker.BuildTimeout)
	defer cancel()

	// Cancel any previous build and register this one
	dockerService.CancelAndRegisterBuild(newApp.ID, cancel)
	defer dockerService.RemoveCancelFunc(newApp.ID)

	// Update status to pending
	dbClient.UpdateAppStatus(ctx, newApp.ID, "pending")

	// Build container (common Docker operations, including stopping existing container)
	if err := dockerService.BuildContainer(ctx, newApp, true); err != nil {
		log.Printf("Error rebuilding container for app %d: %v", newApp.ID, err)
		dbClient.UpdateAppStatus(ctx, newApp.ID, "failed")
		return
	}

	log.Printf("Container updated for app %d (%s)", newApp.ID, newApp.AppName)

	// Sync with Caddy if name, port, or stripPrefix changed
	if err := caddyService.UpdateApp(ctx, oldApp, newApp); err != nil {
		log.Printf("Error syncing app %d with Caddy: %v", newApp.ID, err)
		dbClient.UpdateAppStatus(ctx, newApp.ID, "failed")
		return
	}
	dbClient.UpdateAppStatus(ctx, newApp.ID, "active")

	log.Printf("App %d (%s) fully updated and active", newApp.ID, newApp.AppName)
}

// writeJSON writes a JSON response
func writeJSON(w http.ResponseWriter, status int, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(v); err != nil {
		log.Printf("Error encoding JSON: %v", err)
	}
}

// getAppIDFromPath extracts and validates app ID from path parameter
func getAppIDFromPath(r *http.Request) (int, error) {
	idStr := r.PathValue("id")
	if idStr == "" {
		return 0, fmt.Errorf("missing app ID")
	}

	id, err := strconv.Atoi(idStr)
	if err != nil {
		return 0, fmt.Errorf("invalid app ID format")
	}

	return id, nil
}

// writeError writes an error response
func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, models.ErrorResponse{Error: message})
}

// handleDBError handles common database errors and writes appropriate HTTP responses
// Returns true if the error was handled, false otherwise
func handleDBError(w http.ResponseWriter, err error, operation string) bool {
	if err == nil {
		return false
	}

	errMsg := err.Error()

	// Check for not found errors
	if strings.Contains(errMsg, "not found") {
		writeError(w, http.StatusNotFound, "App not found")
		return true
	}

	// Check for duplicate/conflict errors
	if strings.Contains(errMsg, "already exists") || strings.Contains(errMsg, "duplicate key") || strings.Contains(errMsg, "unique constraint") {
		writeError(w, http.StatusConflict, errMsg)
		return true
	}

	// Generic internal server error
	log.Printf("Error %s: %v", operation, err)
	writeError(w, http.StatusInternalServerError, fmt.Sprintf("Failed to %s", operation))
	return true
}

// healthHandler handles health check requests
func healthHandler(dbClient *db.Client) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), HealthCheckTimeout)
		defer cancel()

		if err := dbClient.Ping(ctx); err != nil {
			log.Printf("Health check failed: %v", err)
			writeJSON(w, http.StatusServiceUnavailable, map[string]string{
				"status": "unhealthy",
				"error":  "database unavailable",
			})
			return
		}

		writeJSON(w, http.StatusOK, map[string]string{"status": "healthy"})
	}
}

// createAppHandler handles POST /_app
func createAppHandler(dbClient *db.Client, dockerService *docker.Service, caddyService *caddy.Service) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var req models.AppCreateRequest

		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeError(w, http.StatusBadRequest, "Invalid JSON format")
			return
		}

		if err := ValidateAppCreate(&req); err != nil {
			writeError(w, http.StatusBadRequest, err.Error())
			return
		}

		ctx, cancel := context.WithTimeout(r.Context(), WriteTimeout)
		defer cancel()

		// Create app in DB with status='pending'
		app, err := dbClient.CreateApp(ctx, &req)
		if handleDBError(w, err, "create app") {
			return
		}

		// Start async container build (30 minute timeout handled internally)
		// This returns immediately - container builds in background
		go setupContainer(app, dbClient, dockerService, caddyService)

		// Return app immediately with status='pending'
		// Client can poll GET /_app/{id} to check when status becomes 'active' or 'failed'
		writeJSON(w, http.StatusCreated, app)
	}
}

// getAppHandler handles GET /_app/{id}
func getAppHandler(dbClient *db.Client, dockerService *docker.Service) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := getAppIDFromPath(r)
		if err != nil {
			writeError(w, http.StatusBadRequest, err.Error())
			return
		}

		ctx, cancel := context.WithTimeout(r.Context(), ReadTimeout)
		defer cancel()

		app, err := dbClient.GetApp(ctx, id)
		if handleDBError(w, err, "get app") {
			return
		}

		// Enrich with container status
		dockerService.EnrichWithContainerStatus(ctx, app)

		writeJSON(w, http.StatusOK, app)
	}
}

// listAppsHandler handles GET /_app
func listAppsHandler(dbClient *db.Client, dockerService *docker.Service) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), ReadTimeout)
		defer cancel()

		apps, err := dbClient.ListApps(ctx)
		if handleDBError(w, err, "list apps") {
			return
		}

		// Handle empty list
		if apps == nil {
			apps = []*models.App{}
		}

		// Enrich with container statuses
		dockerService.EnrichWithContainerStatuses(ctx, apps)

		response := models.AppListResponse{
			Apps:  apps,
			Total: len(apps),
		}

		writeJSON(w, http.StatusOK, response)
	}
}

// updateAppHandler handles PUT /_app/{id}
func updateAppHandler(dbClient *db.Client, dockerService *docker.Service, caddyService *caddy.Service) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := getAppIDFromPath(r)
		if err != nil {
			writeError(w, http.StatusBadRequest, err.Error())
			return
		}

		var req models.AppCreateRequest

		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeError(w, http.StatusBadRequest, "Invalid JSON format")
			return
		}

		if err := ValidateAppCreate(&req); err != nil {
			writeError(w, http.StatusBadRequest, err.Error())
			return
		}

		ctx, cancel := context.WithTimeout(r.Context(), WriteTimeout)
		defer cancel()

		// Get old app to compare
		oldApp, err := dbClient.GetApp(ctx, id)
		if handleDBError(w, err, "get app") {
			return
		}

		// Update app in DB
		app, err := dbClient.UpdateApp(ctx, id, &req)
		if handleDBError(w, err, "update app") {
			return
		}

		// Start async container rebuild (30 minute timeout handled internally)
		// This returns immediately - container rebuilds in background
		go updateContainer(oldApp, app, dbClient, dockerService, caddyService)

		// Return app immediately with status='pending'
		// Status will be updated to 'active' or 'failed' when rebuild completes
		app.Status = "pending"
		writeJSON(w, http.StatusOK, app)
	}
}

// deleteAppHandler handles DELETE /_app/{id}
func deleteAppHandler(dbClient *db.Client, dockerService *docker.Service, caddyService *caddy.Service) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := getAppIDFromPath(r)
		if err != nil {
			writeError(w, http.StatusBadRequest, err.Error())
			return
		}

		ctx, cancel := context.WithTimeout(r.Context(), WriteTimeout)
		defer cancel()

		// Get app first
		app, err := dbClient.GetApp(ctx, id)
		if handleDBError(w, err, "get app") {
			return
		}

		// Remove from Caddy first (best effort)
		if err := caddyService.RemoveApp(ctx, app.AppName); err != nil {
			log.Printf("Warning: Failed to remove Caddy route: %v", err)
			// Continue with DB delete anyway
		}

		// Stop and remove container (best effort)
		if err := dockerService.RemoveContainer(ctx, app.ID); err != nil {
			log.Printf("Warning: Failed to remove container: %v", err)
		}

		// Delete from database
		err = dbClient.DeleteApp(ctx, id)
		if handleDBError(w, err, "delete app") {
			return
		}

		w.WriteHeader(http.StatusNoContent)
	}
}

// startAppHandler starts a stopped container, or creates it if it doesn't exist
func startAppHandler(dbClient *db.Client, dockerService *docker.Service, caddyService *caddy.Service) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := getAppIDFromPath(r)
		if err != nil {
			writeError(w, http.StatusBadRequest, err.Error())
			return
		}

		ctx, cancel := context.WithTimeout(r.Context(), DockerTimeout)
		defer cancel()

		// Get app from database
		app, err := dbClient.GetApp(ctx, id)
		if handleDBError(w, err, "get app") {
			return
		}

		// Check container status
		status, err := dockerService.GetContainerStatus(ctx, id)
		if err != nil {
			writeError(w, http.StatusInternalServerError, fmt.Sprintf("Failed to check container status: %v", err))
			return
		}

		// If container doesn't exist, create it
		if status == docker.ContainerStatusNotFound {
			log.Printf("Container not found for app %d, creating...", id)

			// Update status to pending in DB
			if err := dbClient.UpdateAppStatus(ctx, id, "pending"); err != nil {
				log.Printf("Warning: Failed to update status to pending: %v", err)
			}

			// Trigger async container creation
			go setupContainer(app, dbClient, dockerService, caddyService)

			writeJSON(w, http.StatusAccepted, map[string]string{
				"status":  "creating",
				"message": "Container is being created in the background",
			})
			return
		}

		// If container is already running, return success
		if status == "running" {
			writeJSON(w, http.StatusOK, map[string]string{
				"status":  "already_running",
				"message": "Container is already running",
			})
			return
		}

		// Otherwise, start the stopped container
		if err := dockerService.StartContainer(ctx, id); err != nil {
			writeError(w, http.StatusInternalServerError, fmt.Sprintf("Failed to start container: %v", err))
			return
		}

		writeJSON(w, http.StatusOK, map[string]string{"status": "started"})
	}
}

// stopAppHandler stops a running container
func stopAppHandler(dockerService *docker.Service) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := getAppIDFromPath(r)
		if err != nil {
			writeError(w, http.StatusBadRequest, err.Error())
			return
		}

		ctx, cancel := context.WithTimeout(r.Context(), DockerTimeout)
		defer cancel()

		if err := dockerService.StopContainer(ctx, id); err != nil {
			writeError(w, http.StatusInternalServerError, fmt.Sprintf("Failed to stop container: %v", err))
			return
		}

		writeJSON(w, http.StatusOK, map[string]string{"status": "stopped"})
	}
}

// appLogsHandler retrieves logs from an app container
func appLogsHandler(dockerService *docker.Service) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, err := getAppIDFromPath(r)
		if err != nil {
			writeError(w, http.StatusBadRequest, err.Error())
			return
		}

		// Get tail parameter (default 100 lines)
		tail := 100
		if tailStr := r.URL.Query().Get("tail"); tailStr != "" {
			if t, err := strconv.Atoi(tailStr); err == nil && t > 0 {
				tail = t
			}
		}

		ctx, cancel := context.WithTimeout(r.Context(), ReadTimeout)
		defer cancel()

		logs, err := dockerService.GetContainerLogs(ctx, id, tail)
		if err != nil {
			writeError(w, http.StatusInternalServerError, fmt.Sprintf("Failed to get logs: %v", err))
			return
		}

		writeJSON(w, http.StatusOK, map[string]string{"logs": logs})
	}
}

// playgroundLogsHandler retrieves logs from the playground container
func playgroundLogsHandler(dockerService *docker.Service) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		// Get tail parameter (default 100 lines)
		tail := 100
		if tailStr := r.URL.Query().Get("tail"); tailStr != "" {
			if t, err := strconv.Atoi(tailStr); err == nil && t > 0 {
				tail = t
			}
		}

		ctx, cancel := context.WithTimeout(r.Context(), ReadTimeout)
		defer cancel()

		logs, err := dockerService.GetPlaygroundLogs(ctx, tail)
		if err != nil {
			writeError(w, http.StatusInternalServerError, fmt.Sprintf("Failed to get playground logs: %v", err))
			return
		}

		writeJSON(w, http.StatusOK, map[string]string{"logs": logs})
	}
}
