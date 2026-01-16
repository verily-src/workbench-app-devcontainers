package main

import (
	"errors"
	"strings"
	"text/template"
)

// ValidateAppCreate validates the request to create an app
func ValidateAppCreate(req *AppCreateRequest) error {
	appName := strings.TrimSpace(req.AppName)

	if appName == "" {
		return errors.New("app_name is required")
	}

	// Validate app_name format for Caddy routing
	// Only allow alphanumeric, hyphens, and underscores
	if !isValidAppName(appName) {
		return errors.New("app_name must contain only letters, numbers, hyphens, and underscores")
	}

	// Prevent reserved paths
	if appName == "_app" || appName == "health" {
		return errors.New("app_name cannot be a reserved path")
	}

	if strings.TrimSpace(req.Username) == "" {
		return errors.New("username is required")
	}
	if strings.TrimSpace(req.UserHomeDirectory) == "" {
		return errors.New("user_home_directory is required")
	}

	// Validate that either dockerfile or docker_image is provided (but not both)
	hasDockerfile := strings.TrimSpace(req.Dockerfile) != ""
	hasDockerImage := strings.TrimSpace(req.DockerImage) != ""

	if !hasDockerfile && !hasDockerImage {
		return errors.New("either dockerfile or docker_image is required")
	}

	if hasDockerfile && hasDockerImage {
		return errors.New("provide either dockerfile or docker_image, not both")
	}

	// If docker_image is provided, convert to dockerfile format
	if hasDockerImage {
		req.Dockerfile = "FROM " + strings.TrimSpace(req.DockerImage)
		req.DockerImage = "" // Clear docker_image after conversion
	}

	if req.Port < 1 || req.Port > 65535 {
		return errors.New("port must be between 1 and 65535")
	}

	// Validate optional features
	validFeatures := map[string]bool{
		FeatureWB:             true,
		FeatureWorkbenchTools: true,
	}
	for _, feature := range req.OptionalFeatures {
		if !validFeatures[feature] {
			return errors.New("invalid optional feature: " + feature)
		}
	}

	// Validate caddy_config
	if err := validateAppTemplate(req.CaddyConfig); err != nil {
		return err
	}

	// Validate dockerfile as template
	if err := validateAppTemplate(req.Dockerfile); err != nil {
		return err
	}

	return nil
}

// isValidAppName checks if app name contains only valid characters
func isValidAppName(name string) bool {
	for _, char := range name {
		if !((char >= 'a' && char <= 'z') ||
			(char >= 'A' && char <= 'Z') ||
			(char >= '0' && char <= '9') ||
			char == '-' || char == '_') {
			return false
		}
	}
	return len(name) > 0
}

func validateAppTemplate(templateStr string) error {
	// Validate template syntax by parsing it
	tmpl, err := template.New("app_template").Parse(templateStr)
	if err != nil {
		return errors.New("template has invalid template syntax: " + err.Error())
	}

	// Verify template can execute with dummy data
	vars := CaddyTemplateVars{
		AppName:       "test",
		ContainerName: "test-container",
		Port:          8080,
	}

	var buf strings.Builder
	if err := tmpl.Execute(&buf, vars); err != nil {
		return errors.New("template execution failed: " + err.Error())
	}

	return nil
}
