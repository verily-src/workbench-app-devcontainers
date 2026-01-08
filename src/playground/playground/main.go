package main

import (
	"fmt"
	"log"
	"net/http"
	"os"
)

func helloHandler(w http.ResponseWriter, r *http.Request) {
	// Write the response body
	fmt.Fprintf(w, "Hello, World!")
}

func helloHandler2(w http.ResponseWriter, r *http.Request) {
	// Write the response body
	fmt.Fprintf(w, "Hello, World 2!")
}

func main() {
	// Get configuration from environment variables
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	// Capture environment variables from docker-compose
	dbHost := os.Getenv("DB_HOST")
	dbPort := os.Getenv("DB_PORT")
	dbName := os.Getenv("DB_NAME")
	dbUser := os.Getenv("DB_USER")
	dbPassword := os.Getenv("DB_PASSWORD")
	caddyHost := os.Getenv("CADDY_HOST")
	caddyPort := os.Getenv("CADDY_PORT")

	// Log the configuration
	log.Printf("Configuration loaded:")
	log.Printf("  PORT: %s", port)
	log.Printf("  DB_HOST: %s", dbHost)
	log.Printf("  DB_PORT: %s", dbPort)
	log.Printf("  DB_NAME: %s", dbName)
	log.Printf("  DB_USER: %s", dbUser)
	log.Printf("  DB_PASSWORD: %s", dbPassword)
	log.Printf("  CADDY_HOST: %s", caddyHost)
	log.Printf("  CADDY_PORT: %s", caddyPort)

	// Register the handler function for the "/" path
	http.HandleFunc("/_app", helloHandler)
	http.HandleFunc("/_app/asdf", helloHandler2)

	// Start the HTTP server on the configured port
	log.Printf("Server starting on port %s...", port)
	if err := http.ListenAndServe(":"+port, nil); err != nil {
		log.Fatal(err)
	}
}
