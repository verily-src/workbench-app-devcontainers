package caddy

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

// Client handles interactions with Caddy Admin API
type Client struct {
	baseURL    string
	publicPort string
	client     *http.Client
}

// NewClient creates a new Caddy client
func NewClient(host, adminPort, publicPort string) *Client {
	return &Client{
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
func (c *Client) doRequest(ctx context.Context, method, path string, payload any) error {
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

// route represents a Caddy route configuration
type route struct {
	Handle []handler `json:"handle"`
	Match  []matcher `json:"match"`
}

// handler represents a handler (reverse_proxy, rewrite, etc)
type handler struct {
	Handler         string     `json:"handler"`
	Upstreams       []upstream `json:"upstreams,omitempty"`
	StripPathPrefix string     `json:"strip_path_prefix,omitempty"`
}

// upstream represents an upstream server
type upstream struct {
	Dial string `json:"dial"`
}

// matcher represents path and host matching rules
type matcher struct {
	Path []string `json:"path,omitempty"`
	Host []string `json:"host,omitempty"`
}

// adaptResponse represents the response from the /adapt endpoint
type adaptResponse struct {
	Result json.RawMessage `json:"result,omitempty"`
	Error  string          `json:"error,omitempty"`
}

// caddyConfig represents the full Caddy configuration returned by /adapt
type caddyConfig struct {
	Apps caddyApps `json:"apps"`
}

// caddyApps represents the apps section of Caddy config
type caddyApps struct {
	HTTP httpApp `json:"http"`
}

// httpApp represents the HTTP app configuration
type httpApp struct {
	Servers map[string]server `json:"servers"`
}

// server represents a server configuration
type server struct {
	Routes []json.RawMessage `json:"routes"`
}

// renderTemplate renders a Caddyfile template with the given variables
func renderTemplate(templateStr string, vars templateVars) (string, error) {
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
func (c *Client) adaptCaddyfile(ctx context.Context, caddyfile string) (json.RawMessage, error) {
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
	var adaptResp adaptResponse
	if err := json.Unmarshal(body, &adaptResp); err != nil {
		return nil, fmt.Errorf("failed to parse adapt response: %w", err)
	}

	// Check for errors
	if adaptResp.Error != "" {
		return nil, fmt.Errorf("caddyfile configuration error: %s", adaptResp.Error)
	}

	// Parse the result
	var config caddyConfig
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

// addRoute adds a new route to Caddy for an app using Caddyfile template
// Routes are inserted at the beginning (index 0) so they're evaluated before the default UI route
func (c *Client) addRoute(ctx context.Context, appID int, appName string, port int, caddyConfigStr string) error {
	containerName := fmt.Sprintf("app-%d", appID)

	// Prepare template variables
	vars := templateVars{
		AppName:       appName,
		ContainerName: containerName,
		Port:          port,
	}

	// Render the template
	renderedCaddyfile, err := renderTemplate(caddyConfigStr, vars)
	if err != nil {
		return fmt.Errorf("failed to render Caddyfile template: %w", err)
	}

	// Adapt Caddyfile to Caddy JSON
	r, err := c.adaptCaddyfile(ctx, renderedCaddyfile)
	if err != nil {
		return fmt.Errorf("failed to adapt Caddyfile: %w", err)
	}

	// PUT the route to Caddy
	return c.doRequest(ctx, "PUT", "/config/apps/http/servers/srv0/routes/0/handle/0/routes/0", r)
}

// deleteRoute removes a route from Caddy by app name
func (c *Client) deleteRoute(ctx context.Context, appName string) error {
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
func (c *Client) findRouteIndex(ctx context.Context, appName string) (int, error) {
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

	var routes []route
	if err := json.NewDecoder(resp.Body).Decode(&routes); err != nil {
		return -1, fmt.Errorf("failed to decode routes: %w", err)
	}

	// Search for the route matching this app name (by path)
	pathPattern := fmt.Sprintf("/%s", appName)
	for i, r := range routes {
		if len(r.Match) > 0 && len(r.Match[0].Path) > 0 {
			if r.Match[0].Path[0] == pathPattern {
				return i, nil
			}
		}
	}

	return -1, nil // Not found
}

// updateRoute updates a route (delete old, add new)
func (c *Client) updateRoute(ctx context.Context, appID int, oldAppName, newAppName string, newPort int, caddyConfigStr string) error {
	// Delete old route first to avoid duplicates
	if err := c.deleteRoute(ctx, oldAppName); err != nil {
		return fmt.Errorf("failed to delete old route: %w", err)
	}

	// Add new route
	if err := c.addRoute(ctx, appID, newAppName, newPort, caddyConfigStr); err != nil {
		return fmt.Errorf("failed to add new route: %w", err)
	}

	return nil
}

// resetRoutes clears all Caddy routes and adds back the shell and default playground UI routes
func (c *Client) resetRoutes(ctx context.Context) error {
	routes := []route{
		// Create shell route for playground ttyd
		{
			Handle: []handler{
				{
					Handler: "reverse_proxy",
					Upstreams: []upstream{
						{Dial: "playground:7681"},
					},
				},
			},
			Match: []matcher{
				{
					Path: []string{"/_shell", "/_shell/*"},
				},
			},
		},

		// Create default route for playground UI
		{
			Handle: []handler{
				{
					Handler: "reverse_proxy",
					Upstreams: []upstream{
						{Dial: "playground:8080"},
					},
				},
			},
		},
	}

	return c.doRequest(ctx, "PATCH", "/config/apps/http/servers/srv0/routes/0/handle/0/routes", routes)
}

// healthCheck verifies Caddy API is accessible
func (c *Client) healthCheck(ctx context.Context) error {
	return c.doRequest(ctx, "GET", "/config/", nil)
}
