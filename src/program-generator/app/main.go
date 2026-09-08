package main

import (
	"context"
	"embed"
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
	"log"
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/verily-src/workbench-app-devcontainers/src/program-generator/app/internal/ai"
	"github.com/verily-src/workbench-app-devcontainers/src/program-generator/app/internal/db"
	"github.com/verily-src/workbench-app-devcontainers/src/program-generator/app/internal/seeder"
)

//go:embed static/*
var staticFiles embed.FS

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	// Database
	connStr := fmt.Sprintf("host=%s port=%s user=%s password=%s dbname=%s sslmode=disable",
		envOrDefault("DB_HOST", "localhost"),
		envOrDefault("DB_PORT", "5432"),
		envOrDefault("DB_USER", "pguser"),
		envOrDefault("DB_PASSWORD", "pgpass"),
		envOrDefault("DB_NAME", "program_generator"),
	)

	dbClient, err := db.NewClient(connStr)
	if err != nil {
		log.Fatalf("Failed to connect to database: %v", err)
	}
	defer dbClient.Close()

	if err := dbClient.InitSchema(); err != nil {
		log.Fatalf("Failed to init schema: %v", err)
	}
	log.Println("Database connected and schema initialized")

	// Vertex AI
	ctx := context.Background()
	vertexProject := envOrDefault("VERTEX_PROJECT", "wb-agile-aubergine-8187")
	vertexRegion := envOrDefault("VERTEX_REGION", "us-east5")
	aiModel := envOrDefault("AI_MODEL", "gemini-2.5-pro")

	aiClient, err := ai.NewClient(ctx, vertexProject, vertexRegion, aiModel)
	if err != nil {
		log.Printf("Warning: AI client init failed (generation won't work): %v", err)
		aiClient = nil
	} else {
		defer aiClient.Close()
		log.Printf("AI client initialized (project=%s, region=%s, model=%s)", vertexProject, vertexRegion, aiModel)
	}

	// FHIR/seeder config
	fhirStore := os.Getenv("FHIR_STORE")
	gcsBucket := os.Getenv("GCS_BUCKET")

	// HTTP routes
	mux := http.NewServeMux()

	// Static frontend
	staticFS, err := fs.Sub(staticFiles, "static")
	if err != nil {
		log.Fatal(err)
	}
	mux.Handle("GET /static/", http.StripPrefix("/static/", http.FileServer(http.FS(staticFS))))
	mux.HandleFunc("GET /", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/" {
			data, err := staticFiles.ReadFile("static/index.html")
			if err != nil {
				http.Error(w, "Not found", http.StatusNotFound)
				return
			}
			w.Header().Set("Content-Type", "text/html; charset=utf-8")
			w.Write(data)
			return
		}
		// Serve other static files (JS, CSS)
		http.FileServer(http.FS(staticFS)).ServeHTTP(w, r)
	})

	// Health
	mux.HandleFunc("GET /api/health", func(w http.ResponseWriter, r *http.Request) {
		if err := dbClient.Ping(); err != nil {
			http.Error(w, "db unhealthy", http.StatusServiceUnavailable)
			return
		}
		writeJSON(w, map[string]string{"status": "ok"})
	})

	// Generate program via AI
	mux.HandleFunc("POST /api/generate", func(w http.ResponseWriter, r *http.Request) {
		if aiClient == nil {
			http.Error(w, "AI client not available", http.StatusServiceUnavailable)
			return
		}

		var req struct {
			Prompt string `json:"prompt"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "invalid request body", http.StatusBadRequest)
			return
		}
		if req.Prompt == "" {
			http.Error(w, "prompt is required", http.StatusBadRequest)
			return
		}

		ctx, cancel := context.WithTimeout(r.Context(), 2*time.Minute)
		defer cancel()

		yaml, err := aiClient.GenerateProgram(ctx, req.Prompt)
		if err != nil {
			log.Printf("Generation error: %v", err)
			http.Error(w, fmt.Sprintf("generation failed: %v", err), http.StatusInternalServerError)
			return
		}

		writeJSON(w, map[string]string{"yaml": yaml})
	})

	// Validate template (dry-run)
	mux.HandleFunc("POST /api/validate", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Yaml string `json:"yaml"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "invalid request body", http.StatusBadRequest)
			return
		}

		tmpl, err := seeder.LoadTemplateFromBytes([]byte(req.Yaml))
		if err != nil {
			writeJSON(w, map[string]interface{}{
				"valid": false,
				"error": err.Error(),
			})
			return
		}

		// Dry-run: build the FHIR bundle without posting
		builder := seeder.NewBuilder(nil, nil, "")
		bundle, err := builder.DryRun(r.Context(), tmpl)
		if err != nil {
			writeJSON(w, map[string]interface{}{
				"valid": false,
				"error": err.Error(),
			})
			return
		}

		writeJSON(w, map[string]interface{}{
			"valid":       true,
			"bundle":      bundle,
			"name":        tmpl.Name,
			"bundleCount": len(tmpl.Bundles),
		})
	})

	// Seed program to FHIR
	mux.HandleFunc("POST /api/seed", func(w http.ResponseWriter, r *http.Request) {
		if fhirStore == "" {
			http.Error(w, "FHIR_STORE not configured", http.StatusServiceUnavailable)
			return
		}

		var req struct {
			Yaml string `json:"yaml"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "invalid request body", http.StatusBadRequest)
			return
		}

		tmpl, err := seeder.LoadTemplateFromBytes([]byte(req.Yaml))
		if err != nil {
			http.Error(w, fmt.Sprintf("invalid template: %v", err), http.StatusBadRequest)
			return
		}

		ctx := r.Context()

		fhirClient, err := seeder.NewFHIRClient(ctx, fhirStore)
		if err != nil {
			http.Error(w, fmt.Sprintf("FHIR client error: %v", err), http.StatusInternalServerError)
			return
		}

		var gcsClient *seeder.GCSClient
		if gcsBucket != "" && seeder.TemplateHasConsentSteps(tmpl) {
			gcsClient, err = seeder.NewGCSClient(ctx)
			if err != nil {
				http.Error(w, fmt.Sprintf("GCS client error: %v", err), http.StatusInternalServerError)
				return
			}
			defer gcsClient.Close()
		}

		builder := seeder.NewBuilder(fhirClient, gcsClient, gcsBucket)
		output, err := builder.Build(ctx, tmpl)
		if err != nil {
			http.Error(w, fmt.Sprintf("seed failed: %v", err), http.StatusInternalServerError)
			return
		}

		writeJSON(w, output)
	})

	// Template CRUD
	mux.HandleFunc("GET /api/templates", func(w http.ResponseWriter, r *http.Request) {
		templates, err := dbClient.ListTemplates()
		if err != nil {
			http.Error(w, "failed to list templates", http.StatusInternalServerError)
			return
		}
		if templates == nil {
			templates = []db.Template{}
		}
		writeJSON(w, templates)
	})

	mux.HandleFunc("GET /api/templates/{id}", func(w http.ResponseWriter, r *http.Request) {
		id, err := strconv.Atoi(r.PathValue("id"))
		if err != nil {
			http.Error(w, "invalid id", http.StatusBadRequest)
			return
		}
		t, err := dbClient.GetTemplate(id)
		if err != nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		writeJSON(w, t)
	})

	mux.HandleFunc("POST /api/templates", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Name string `json:"name"`
			Yaml string `json:"yaml"`
		}
		body, _ := io.ReadAll(r.Body)
		if err := json.Unmarshal(body, &req); err != nil {
			http.Error(w, "invalid body", http.StatusBadRequest)
			return
		}
		if req.Name == "" || req.Yaml == "" {
			http.Error(w, "name and yaml are required", http.StatusBadRequest)
			return
		}
		t, err := dbClient.SaveTemplate(req.Name, req.Yaml)
		if err != nil {
			http.Error(w, "save failed", http.StatusInternalServerError)
			return
		}
		w.WriteHeader(http.StatusCreated)
		writeJSON(w, t)
	})

	log.Printf("Server starting on port %s", port)
	if err := http.ListenAndServe(":"+port, mux); err != nil {
		log.Fatal(err)
	}
}

func writeJSON(w http.ResponseWriter, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(v)
}

func envOrDefault(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}
