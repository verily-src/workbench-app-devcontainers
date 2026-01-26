package main

import (
	"errors"
	"regexp"
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

	if strings.TrimSpace(req.Dockerfile) == "" {
		return errors.New("dockerfile is required")
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

// validAppNamePattern matches only ASCII letters, digits, hyphens, and underscores
var validAppNamePattern = regexp.MustCompile(`^[a-zA-Z0-9_-]+$`)

// isValidAppName checks if app name contains only valid characters
func isValidAppName(name string) bool {
	return validAppNamePattern.MatchString(name)
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
