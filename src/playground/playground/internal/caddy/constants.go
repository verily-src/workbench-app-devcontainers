package caddy

// templateVars holds variables for rendering Caddy templates
type templateVars struct {
	AppName       string
	ContainerName string
	Port          int
}
