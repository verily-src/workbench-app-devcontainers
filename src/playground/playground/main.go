package main

import (
	"context"
	"embed"
	"fmt"
	"io/fs"
	"log"
	"net/http"
	"os"
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
	db, err := InitDB(connStr)
	if err != nil {
		log.Fatalf("Failed to initialize database: %v", err)
	}
	defer db.Close()

	// Initialize database schema
	if err := InitSchema(db); err != nil {
		log.Fatalf("Failed to initialize schema: %v", err)
	}

	// Initialize Docker client
	dockerClient := NewDockerClient(AppsBaseDir, cloud)

	// Health check Docker
	ctx, cancel := context.WithTimeout(context.Background(), HealthCheckTimeout)
	if err := dockerClient.HealthCheck(ctx); err != nil {
		log.Fatalf("Docker not accessible: %v", err)
	}
	log.Println("Docker connection verified")
	cancel()

	// Ensure apps base directory exists
	if err := os.MkdirAll(AppsBaseDir, 0755); err != nil {
		log.Fatalf("Failed to create apps directory: %v", err)
	}

	// Initialize Caddy client
	caddyClient := NewCaddyClient(caddyHost, caddyPort, port)

	// Health check Caddy
	ctx, cancel = context.WithTimeout(context.Background(), ReadTimeout)
	if err := caddyClient.HealthCheck(ctx); err != nil {
		log.Printf("Warning: Caddy unreachable: %v", err)
		log.Println("Apps will be created with status='failed'")
	} else {
		log.Println("Caddy connection verified")
	}
	cancel()

	// Initialize services
	dockerService := NewDockerService(dockerClient, db)
	caddyService := NewCaddyService(caddyClient, db)

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
	mux.HandleFunc("GET /_app/health", healthHandler(db))

	// CRUD endpoints
	mux.HandleFunc("POST /_app", createAppHandler(db, dockerService, caddyService))
	mux.HandleFunc("GET /_app/{id}", getAppHandler(db, dockerService))
	mux.HandleFunc("GET /_app", listAppsHandler(db, dockerService))
	mux.HandleFunc("PUT /_app/{id}", updateAppHandler(db, dockerService, caddyService))
	mux.HandleFunc("DELETE /_app/{id}", deleteAppHandler(db, dockerService, caddyService))

	// Container control endpoints
	mux.HandleFunc("POST /_app/{id}/start", startAppHandler(db, dockerService, caddyService))
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
