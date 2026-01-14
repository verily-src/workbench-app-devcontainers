package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"text/template"
	"time"
)

// CaddyClient handles interactions with Caddy Admin API
type CaddyClient struct {
	baseURL    string
	publicPort string
	client     *http.Client
}

// NewCaddyClient creates a new Caddy client
func NewCaddyClient(host, adminPort, publicPort string) *CaddyClient {
	return &CaddyClient{
		baseURL:    fmt.Sprintf("http://%s:%s", host, adminPort),
		publicPort: publicPort,
		client: &http.Client{
			Timeout: 10 * time.Second,
			Transport: &http.Transport{
				MaxIdleConns:        10,
				MaxIdleConnsPerHost: 5,
				IdleConnTimeout:     30 * time.Second,
			},
		},
	}
}

// doRequest executes a Caddy API request and handles errors
func (c *CaddyClient) doRequest(ctx context.Context, method, path string, payload any) error {
	url := fmt.Sprintf("%s%s", c.baseURL, path)

	var body io.Reader
	if payload != nil {
		jsonData, err := json.Marshal(payload)
		if err != nil {
			return fmt.Errorf("failed to marshal payload: %w", err)
		}
		body = bytes.NewBuffer(jsonData)
	}

	req, err := http.NewRequestWithContext(ctx, method, url, body)
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}

	if payload != nil {
		req.Header.Set("Content-Type", "application/json")
	}

	resp, err := c.client.Do(req)
	if err != nil {
		return fmt.Errorf("caddy API request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		bodyBytes, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("caddy API returned status %d: %s", resp.StatusCode, string(bodyBytes))
	}

	return nil
}

// CaddyRoute represents a Caddy route configuration
type CaddyRoute struct {
	Handle []CaddyHandler `json:"handle"`
	Match  []CaddyMatcher `json:"match"`
}

// CaddyHandler represents a handler (reverse_proxy, rewrite, etc)
type CaddyHandler struct {
	Handler         string          `json:"handler"`
	Upstreams       []CaddyUpstream `json:"upstreams,omitempty"`
	StripPathPrefix string          `json:"strip_path_prefix,omitempty"`
}

// CaddyUpstream represents an upstream server
type CaddyUpstream struct {
	Dial string `json:"dial"`
}

// CaddyMatcher represents path and host matching rules
type CaddyMatcher struct {
	Path []string `json:"path,omitempty"`
	Host []string `json:"host,omitempty"`
}

// CaddyAdaptResponse represents the response from the /adapt endpoint
type CaddyAdaptResponse struct {
	Result json.RawMessage `json:"result,omitempty"`
	Error  string          `json:"error,omitempty"`
}

// CaddyConfig represents the full Caddy configuration returned by /adapt
type CaddyConfig struct {
	Apps CaddyApps `json:"apps"`
}

// CaddyApps represents the apps section of Caddy config
type CaddyApps struct {
	HTTP CaddyHTTP `json:"http"`
}

// CaddyHTTP represents the HTTP app configuration
type CaddyHTTP struct {
	Servers map[string]CaddyServer `json:"servers"`
}

// CaddyServer represents a server configuration
type CaddyServer struct {
	Routes []json.RawMessage `json:"routes"`
}

// renderCaddyTemplate renders a Caddyfile template with the given variables
func renderCaddyTemplate(templateStr string, vars CaddyTemplateVars) (string, error) {
	tmpl, err := template.New("caddy").Parse(templateStr)
	if err != nil {
		return "", fmt.Errorf("failed to parse template: %w", err)
	}

	var buf strings.Builder
	if err := tmpl.Execute(&buf, vars); err != nil {
		return "", fmt.Errorf("failed to execute template: %w", err)
	}

	return buf.String(), nil
}

// adaptCaddyfile converts a Caddyfile to Caddy JSON using the /adapt endpoint
func (c *CaddyClient) adaptCaddyfile(ctx context.Context, caddyfile string) (json.RawMessage, error) {
	// Wrap the Caddyfile in a site block
	wrappedCaddyfile := fmt.Sprintf(":80 {\n%s\n}", caddyfile)

	url := fmt.Sprintf("%s/adapt", c.baseURL)

	req, err := http.NewRequestWithContext(ctx, "POST", url, strings.NewReader(wrappedCaddyfile))
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	req.Header.Set("Content-Type", "text/caddyfile")

	resp, err := c.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("caddy adapt request failed: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response: %w", err)
	}

	// Parse the response
	var adaptResp CaddyAdaptResponse
	if err := json.Unmarshal(body, &adaptResp); err != nil {
		return nil, fmt.Errorf("failed to parse adapt response: %w", err)
	}

	// Check for errors
	if adaptResp.Error != "" {
		return nil, fmt.Errorf("caddyfile configuration error: %s", adaptResp.Error)
	}

	// Parse the result
	var config CaddyConfig
	if err := json.Unmarshal(adaptResp.Result, &config); err != nil {
		return nil, fmt.Errorf("failed to parse caddy config: %w", err)
	}

	// Extract the first route from srv0
	if servers, ok := config.Apps.HTTP.Servers["srv0"]; ok {
		if len(servers.Routes) > 0 {
			return servers.Routes[0], nil
		}
	}

	return nil, fmt.Errorf("no routes found in adapted configuration")
}

// AddRoute adds a new route to Caddy for an app using Caddyfile template
// Routes are inserted at the beginning (index 0) so they're evaluated before the default UI route
func (c *CaddyClient) AddRoute(ctx context.Context, appID int, appName string, port int, caddyConfig string) error {
	containerName := fmt.Sprintf("app-%d", appID)

	// Prepare template variables
	vars := CaddyTemplateVars{
		AppName:       appName,
		ContainerName: containerName,
		Port:          port,
	}

	// Render the template
	renderedCaddyfile, err := renderCaddyTemplate(caddyConfig, vars)
	if err != nil {
		return fmt.Errorf("failed to render Caddyfile template: %w", err)
	}

	// Adapt Caddyfile to Caddy JSON
	route, err := c.adaptCaddyfile(ctx, renderedCaddyfile)
	if err != nil {
		return fmt.Errorf("failed to adapt Caddyfile: %w", err)
	}

	// PUT the route to Caddy
	return c.doRequest(ctx, "PUT", "/config/apps/http/servers/srv0/routes/0/handle/0/routes/0", route)
}

// DeleteRoute removes a route from Caddy by app name
func (c *CaddyClient) DeleteRoute(ctx context.Context, appName string) error {
	// First, find the route index by getting current config
	routeIndex, err := c.findRouteIndex(ctx, appName)
	if err != nil {
		return fmt.Errorf("failed to find route: %w", err)
	}

	if routeIndex == -1 {
		// Route doesn't exist, consider this success (idempotent)
		return nil
	}

	// Delete the route at the found index
	path := fmt.Sprintf("/config/apps/http/servers/srv0/routes/0/handle/0/routes/%d", routeIndex)
	return c.doRequest(ctx, "DELETE", path, nil)
}

// findRouteIndex searches for a route by app name and returns its index
func (c *CaddyClient) findRouteIndex(ctx context.Context, appName string) (int, error) {
	url := fmt.Sprintf("%s/config/apps/http/servers/srv0/routes/0/handle/0/routes", c.baseURL)

	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return -1, fmt.Errorf("failed to create request: %w", err)
	}

	resp, err := c.client.Do(req)
	if err != nil {
		return -1, fmt.Errorf("caddy API request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return -1, fmt.Errorf("caddy API returned status %d: %s", resp.StatusCode, string(body))
	}

	var routes []CaddyRoute
	if err := json.NewDecoder(resp.Body).Decode(&routes); err != nil {
		return -1, fmt.Errorf("failed to decode routes: %w", err)
	}

	// Search for the route matching this app name (by path)
	pathPattern := fmt.Sprintf("/%s", appName)
	for i, route := range routes {
		if len(route.Match) > 0 && len(route.Match[0].Path) > 0 {
			if route.Match[0].Path[0] == pathPattern {
				return i, nil
			}
		}
	}

	return -1, nil // Not found
}

// UpdateRoute updates a route (delete old, add new)
func (c *CaddyClient) UpdateRoute(ctx context.Context, appID int, oldAppName, newAppName string, newPort int, caddyConfig string) error {
	// Delete old route first to avoid duplicates
	if err := c.DeleteRoute(ctx, oldAppName); err != nil {
		return fmt.Errorf("failed to delete old route: %w", err)
	}

	// Add new route
	if err := c.AddRoute(ctx, appID, newAppName, newPort, caddyConfig); err != nil {
		return fmt.Errorf("failed to add new route: %w", err)
	}

	return nil
}

// ResetRoutes clears all Caddy routes and adds back the shell and default playground UI routes
func (c *CaddyClient) ResetRoutes(ctx context.Context) error {
	routes := []CaddyRoute{
		// Create shell route for playground ttyd
		{
			Handle: []CaddyHandler{
				{
					Handler: "reverse_proxy",
					Upstreams: []CaddyUpstream{
						{Dial: "playground:7681"},
					},
				},
			},
			Match: []CaddyMatcher{
				{
					Path: []string{"/_shell", "/_shell/*"},
				},
			},
		},

		// Create default route for playground UI
		{
			Handle: []CaddyHandler{
				{
					Handler: "reverse_proxy",
					Upstreams: []CaddyUpstream{
						{Dial: "playground:8080"},
					},
				},
			},
		},
	}

	return c.doRequest(ctx, "PATCH", "/config/apps/http/servers/srv0/routes/0/handle/0/routes", routes)
}

// HealthCheck verifies Caddy API is accessible
func (c *CaddyClient) HealthCheck(ctx context.Context) error {
	return c.doRequest(ctx, "GET", "/config/", nil)
}
