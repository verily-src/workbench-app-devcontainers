package main

import (
	"context"
	"embed"
	"fmt"
	"io/fs"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/verily-src/workbench-app-devcontainers/src/playground/playground/internal/caddy"
	"github.com/verily-src/workbench-app-devcontainers/src/playground/playground/internal/db"
	"github.com/verily-src/workbench-app-devcontainers/src/playground/playground/internal/docker"
)

// Timeout constants for different operation types
const (
	HealthCheckTimeout = 2 * time.Second
	ReadTimeout        = 5 * time.Second
	WriteTimeout       = 10 * time.Second
	DockerTimeout      = 30 * time.Second
)

//go:embed static/*
var staticFiles embed.FS

func main() {
	// Get configuration from environment variables
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	// Capture database environment variables from docker-compose
	dbHost := os.Getenv("DB_HOST")
	dbPort := os.Getenv("DB_PORT")
	dbName := os.Getenv("DB_NAME")
	dbUser := os.Getenv("DB_USER")
	dbPassword := os.Getenv("DB_PASSWORD")

	// Caddy configuration
	caddyHost := os.Getenv("CADDY_HOST")
	caddyPort := os.Getenv("CADDY_PORT")
	if caddyHost == "" {
		caddyHost = "app"
	}
	if caddyPort == "" {
		caddyPort = "2019"
	}

	// Cloud environment
	cloud := os.Getenv("CLOUD")
	if cloud == "" {
		cloud = "gcp"
	}

	// Log the configuration
	log.Printf("Configuration loaded:")
	log.Printf("  PORT: %s", port)
	log.Printf("  DB_HOST: %s", dbHost)
	log.Printf("  DB_PORT: %s", dbPort)
	log.Printf("  DB_NAME: %s", dbName)
	log.Printf("  DB_USER: %s", dbUser)
	log.Printf("  CADDY_HOST: %s", caddyHost)
	log.Printf("  CADDY_PORT: %s", caddyPort)
	log.Printf("  CLOUD: %s", cloud)

	// Build PostgreSQL connection string
	connStr := fmt.Sprintf(
		"host=%s port=%s user=%s password=%s dbname=%s sslmode=disable",
		dbHost, dbPort, dbUser, dbPassword, dbName,
	)

	// Initialize database connection
	dbClient, err := db.NewClient(connStr)
	if err != nil {
		log.Fatalf("Failed to initialize database: %v", err)
	}
	defer dbClient.Close()

	// Initialize database schema
	if err := dbClient.InitSchema(); err != nil {
		log.Fatalf("Failed to initialize schema: %v", err)
	}

	// Ensure apps base directory exists
	if err := os.MkdirAll(docker.AppsBaseDir, 0755); err != nil {
		log.Fatalf("Failed to create apps directory: %v", err)
	}

	// Initialize Docker service
	dockerClient := docker.NewClient(docker.AppsBaseDir, cloud)
	dockerService := docker.NewService(dockerClient)

	// Health check Docker
	ctx, cancel := context.WithTimeout(context.Background(), HealthCheckTimeout)
	if err := dockerService.HealthCheck(ctx); err != nil {
		log.Fatalf("Docker not accessible: %v", err)
	}
	log.Println("Docker connection verified")
	cancel()

	// Initialize Caddy service
	caddyClient := caddy.NewClient(caddyHost, caddyPort, port)
	caddyService := caddy.NewService(caddyClient, dbClient)

	// Health check Caddy
	ctx, cancel = context.WithTimeout(context.Background(), ReadTimeout)
	if err := caddyService.HealthCheck(ctx); err != nil {
		log.Printf("Warning: Caddy unreachable: %v", err)
		log.Println("Apps will be created with status='failed'")
	} else {
		log.Println("Caddy connection verified")
	}
	cancel()

	// Sync all apps from database to Caddy on startup
	syncCtx, syncCancel := context.WithTimeout(context.Background(), WriteTimeout)
	if err := caddyService.SyncAllApps(syncCtx); err != nil {
		log.Printf("Warning: Failed to sync apps to Caddy: %v", err)
	}
	syncCancel()

	// Setup HTTP router with CRUD endpoints
	mux := http.NewServeMux()

	// Serve static files (UI) from embedded filesystem
	staticFS, err := fs.Sub(staticFiles, "static")
	if err != nil {
		log.Fatal(err)
	}
	mux.Handle("GET /static/", http.StripPrefix("/static/", http.FileServer(http.FS(staticFS))))
	mux.HandleFunc("GET /", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/" {
			data, err := staticFiles.ReadFile("static/index.html")
			if err != nil {
				http.Error(w, "File not found", http.StatusNotFound)
				return
			}
			w.Header().Set("Content-Type", "text/html; charset=utf-8")
			w.Write(data)
			return
		}
		http.NotFound(w, r)
	})

	// Health check endpoint
	mux.HandleFunc("GET /_app/health", healthHandler(dbClient))

	// CRUD endpoints
	mux.HandleFunc("POST /_app", createAppHandler(dbClient, dockerService, caddyService))
	mux.HandleFunc("GET /_app/{id}", getAppHandler(dbClient, dockerService))
	mux.HandleFunc("GET /_app", listAppsHandler(dbClient, dockerService))
	mux.HandleFunc("PUT /_app/{id}", updateAppHandler(dbClient, dockerService, caddyService))
	mux.HandleFunc("DELETE /_app/{id}", deleteAppHandler(dbClient, dockerService, caddyService))

	// Container control endpoints
	mux.HandleFunc("POST /_app/{id}/start", startAppHandler(dbClient, dockerService, caddyService))
	mux.HandleFunc("POST /_app/{id}/stop", stopAppHandler(dockerService))

	// Logs endpoints
	mux.HandleFunc("GET /_app/{id}/logs", appLogsHandler(dockerService))
	mux.HandleFunc("GET /_app/logs", playgroundLogsHandler(dockerService))

	// Start the HTTP server on the configured port
	log.Printf("Server starting on port %s...", port)
	if err := http.ListenAndServe(":"+port, mux); err != nil {
		log.Fatal(err)
	}
}
