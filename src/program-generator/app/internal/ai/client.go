package ai

import (
	"context"
	_ "embed"
	"fmt"
	"strings"

	"cloud.google.com/go/vertexai/genai"
)

//go:embed prompts/system.md
var systemPrompt string

//go:embed prompts/reference-template.yaml
var referenceTemplate string

type Client struct {
	client *genai.Client
	model  string
}

func NewClient(ctx context.Context, projectID, region, model string) (*Client, error) {
	client, err := genai.NewClient(ctx, projectID, region)
	if err != nil {
		return nil, fmt.Errorf("creating Vertex AI client: %w", err)
	}
	if model == "" {
		model = "gemini-2.5-pro"
	}
	return &Client{client: client, model: model}, nil
}

func (c *Client) GenerateProgram(ctx context.Context, userRequest string) (string, error) {
	model := c.client.GenerativeModel(c.model)

	// Build system instruction with embedded reference template
	fullSystemPrompt := systemPrompt + "\n\n## Reference Template\n\n```yaml\n" + referenceTemplate + "\n```"

	model.SystemInstruction = &genai.Content{
		Parts: []genai.Part{genai.Text(fullSystemPrompt)},
	}
	model.SetTemperature(0.3)

	resp, err := model.GenerateContent(ctx, genai.Text(userRequest))
	if err != nil {
		return "", fmt.Errorf("generating content: %w", err)
	}

	if len(resp.Candidates) == 0 || len(resp.Candidates[0].Content.Parts) == 0 {
		return "", fmt.Errorf("no content returned from model")
	}

	text, ok := resp.Candidates[0].Content.Parts[0].(genai.Text)
	if !ok {
		return "", fmt.Errorf("unexpected response type from model")
	}

	yaml := string(text)
	yaml = stripCodeFences(yaml)
	return yaml, nil
}

func (c *Client) Close() {
	c.client.Close()
}

// stripCodeFences removes markdown code fences if the model wraps the YAML in them.
func stripCodeFences(s string) string {
	s = strings.TrimSpace(s)
	if strings.HasPrefix(s, "```yaml") {
		s = strings.TrimPrefix(s, "```yaml")
		s = strings.TrimSuffix(s, "```")
		s = strings.TrimSpace(s)
	} else if strings.HasPrefix(s, "```") {
		s = strings.TrimPrefix(s, "```")
		s = strings.TrimSuffix(s, "```")
		s = strings.TrimSpace(s)
	}
	return s
}
