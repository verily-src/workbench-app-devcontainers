package main

import "time"

// App represents an application in the database
type App struct {
	ID                int       `json:"id"`
	AppName           string    `json:"app_name"`
	Username          string    `json:"username"`
	UserHomeDirectory string    `json:"user_home_directory"`
	Dockerfile        string    `json:"dockerfile"`
	Port              int       `json:"port"`
	OptionalFeatures  []string  `json:"optional_features"`
	CaddyConfig       string    `json:"caddy_config"`      // Caddyfile template for routing
	Status            string    `json:"status"`            // pending, active, or failed
	ContainerStatus   string    `json:"container_status"`  // running, exited, stopped, not_found
	CreatedAt         time.Time `json:"created_at"`
	UpdatedAt         time.Time `json:"updated_at"`
}

// AppCreateRequest represents the request body for creating an app
type AppCreateRequest struct {
	AppName           string   `json:"app_name"`
	Username          string   `json:"username"`
	UserHomeDirectory string   `json:"user_home_directory"`
	Dockerfile        string   `json:"dockerfile,omitempty"`
	DockerImage       string   `json:"docker_image,omitempty"`
	Port              int      `json:"port"`
	OptionalFeatures  []string `json:"optional_features"`
	CaddyConfig       string   `json:"caddy_config"`
}

// AppListResponse represents the response for listing apps
type AppListResponse struct {
	Apps  []*App `json:"apps"`
	Total int    `json:"total"`
}

// ErrorResponse represents an error response
type ErrorResponse struct {
	Error string `json:"error"`
}
