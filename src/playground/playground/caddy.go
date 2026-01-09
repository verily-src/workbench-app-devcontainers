package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
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
func (c *CaddyClient) doRequest(ctx context.Context, method, path string, payload interface{}) error {
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

// CaddyHandler represents the reverse proxy handler
type CaddyHandler struct {
	Handler   string          `json:"handler"`
	Upstreams []CaddyUpstream `json:"upstreams"`
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

// AddRoute adds a new route to Caddy for an app using subdomain
func (c *CaddyClient) AddRoute(ctx context.Context, appID int, appName string, port int) error {
	containerName := fmt.Sprintf("app-%d", appID)
	route := CaddyRoute{
		Handle: []CaddyHandler{
			{
				Handler: "reverse_proxy",
				Upstreams: []CaddyUpstream{
					{Dial: fmt.Sprintf("%s:%d", containerName, port)},
				},
			},
		},
		Match: []CaddyMatcher{
			{
				Host: []string{
					fmt.Sprintf("%s.localhost", appName),
					fmt.Sprintf("%s.localhost:%s", appName, c.publicPort),
				},
			},
		},
	}

	return c.doRequest(ctx, "POST", "/config/apps/http/servers/srv0/routes/1/handle/0/routes", route)
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
	path := fmt.Sprintf("/config/apps/http/servers/srv0/routes/1/handle/0/routes/%d", routeIndex)
	return c.doRequest(ctx, "DELETE", path, nil)
}

// findRouteIndex searches for a route by app name and returns its index
func (c *CaddyClient) findRouteIndex(ctx context.Context, appName string) (int, error) {
	url := fmt.Sprintf("%s/config/apps/http/servers/srv0/routes/1/handle/0/routes", c.baseURL)

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

	// Search for the route matching this app name (by subdomain)
	hostPattern1 := fmt.Sprintf("%s.localhost", appName)
	hostPattern2 := fmt.Sprintf("%s.localhost:%s", appName, c.publicPort)
	for i, route := range routes {
		if len(route.Match) > 0 && len(route.Match[0].Host) > 0 {
			if route.Match[0].Host[0] == hostPattern1 || route.Match[0].Host[0] == hostPattern2 {
				return i, nil
			}
		}
	}

	return -1, nil // Not found
}

// UpdateRoute updates a route (delete old, add new)
func (c *CaddyClient) UpdateRoute(ctx context.Context, appID int, oldAppName, newAppName string, newPort int) error {
	// Delete old route first to avoid duplicates
	if err := c.DeleteRoute(ctx, oldAppName); err != nil {
		return fmt.Errorf("failed to delete old route: %w", err)
	}

	// Add new route
	if err := c.AddRoute(ctx, appID, newAppName, newPort); err != nil {
		return fmt.Errorf("failed to add new route: %w", err)
	}

	return nil
}

// DeleteAllRoutes clears all Caddy routes
func (c *CaddyClient) DeleteAllRoutes(ctx context.Context) error {
	routes := []CaddyRoute{}
	return c.doRequest(ctx, "PATCH", "/config/apps/http/servers/srv0/routes/1/handle/0/routes", routes)
}

// HealthCheck verifies Caddy API is accessible
func (c *CaddyClient) HealthCheck(ctx context.Context) error {
	return c.doRequest(ctx, "GET", "/config/", nil)
}
