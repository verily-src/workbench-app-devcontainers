package seeder

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"

	"golang.org/x/oauth2/google"
)

const (
	healthcareScope = "https://www.googleapis.com/auth/cloud-healthcare"
	fhirAPIBase     = "https://healthcare.googleapis.com/v1"
)

// FHIRClient communicates with the Google Healthcare FHIR API.
type FHIRClient struct {
	httpClient *http.Client
	storePath  string // e.g. "projects/<GCP_PROJECT>/locations/<REGION>/datasets/<DATASET>/fhirStores/<STORE>"
}

// NewFHIRClient creates an authenticated FHIR client using application-default credentials.
func NewFHIRClient(ctx context.Context, fhirStorePath string) (*FHIRClient, error) {
	client, err := google.DefaultClient(ctx, healthcareScope)
	if err != nil {
		return nil, fmt.Errorf("creating authenticated client: %w", err)
	}
	return &FHIRClient{
		httpClient: client,
		storePath:  fhirStorePath,
	}, nil
}

// fhirURL constructs the full FHIR endpoint URL.
func (c *FHIRClient) fhirURL(path string) string {
	return fmt.Sprintf("%s/%s/fhir/%s", fhirAPIBase, c.storePath, path)
}

// TransactionResponse holds the parsed response from a FHIR transaction bundle.
type TransactionResponse struct {
	Entries []TransactionResponseEntry
}

// TransactionResponseEntry holds one entry from the transaction response.
type TransactionResponseEntry struct {
	ResourceType string
	ID           string
	Location     string
}

// PostTransaction posts a FHIR transaction bundle and returns the created resource IDs.
func (c *FHIRClient) PostTransaction(ctx context.Context, entries []bundleEntry) (*TransactionResponse, error) {
	bundle := map[string]interface{}{
		"resourceType": "Bundle",
		"type":         "transaction",
		"entry":        entries,
	}

	body, err := json.Marshal(bundle)
	if err != nil {
		return nil, fmt.Errorf("marshaling transaction bundle: %w", err)
	}

	url := fmt.Sprintf("%s/%s/fhir", fhirAPIBase, c.storePath)
	req, err := http.NewRequestWithContext(ctx, "POST", url, bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("creating request: %w", err)
	}
	req.Header.Set("Content-Type", "application/fhir+json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("executing request: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("reading response: %w", err)
	}

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("FHIR transaction failed (HTTP %d): %s", resp.StatusCode, string(respBody))
	}

	return parseTransactionResponse(respBody)
}

// parseTransactionResponse extracts resource IDs from a FHIR transaction response.
func parseTransactionResponse(body []byte) (*TransactionResponse, error) {
	var raw struct {
		Entry []struct {
			Response struct {
				Location string `json:"location"`
				Status   string `json:"status"`
			} `json:"response"`
		} `json:"entry"`
	}
	if err := json.Unmarshal(body, &raw); err != nil {
		return nil, fmt.Errorf("parsing transaction response: %w", err)
	}

	result := &TransactionResponse{}
	for _, e := range raw.Entry {
		entry := TransactionResponseEntry{Location: e.Response.Location}
		// Location is like "ResourceType/id/_history/version"
		if entry.Location != "" {
			entry.ResourceType, entry.ID = parseLocation(entry.Location)
		}
		result.Entries = append(result.Entries, entry)
	}
	return result, nil
}

// PatchResourceStatus patches a FHIR resource's status field via JSON Patch.
func (c *FHIRClient) PatchResourceStatus(ctx context.Context, resourceType, id, newStatus string) error {
	patch := []map[string]interface{}{
		{"op": "replace", "path": "/status", "value": newStatus},
	}
	body, _ := json.Marshal(patch)

	url := c.fhirURL(fmt.Sprintf("%s/%s", resourceType, id))
	req, err := http.NewRequestWithContext(ctx, "PATCH", url, bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("creating PATCH request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json-patch+json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("executing PATCH: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		respBody, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("PATCH failed (HTTP %d): %s", resp.StatusCode, string(respBody))
	}
	return nil
}

// ResourceExists checks whether a FHIR resource exists by ID.
// Returns true if the resource exists (HTTP 200), false if not found (HTTP 404).
func (c *FHIRClient) ResourceExists(ctx context.Context, resourceType, id string) (bool, error) {
	url := c.fhirURL(fmt.Sprintf("%s/%s", resourceType, id))
	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return false, fmt.Errorf("creating request: %w", err)
	}
	req.Header.Set("Accept", "application/fhir+json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return false, fmt.Errorf("checking resource existence: %w", err)
	}
	defer resp.Body.Close()
	io.ReadAll(resp.Body) // drain body

	return resp.StatusCode == http.StatusOK, nil
}

// parseLocation extracts ResourceType and ID from a FHIR location URL.
// Location can be:
//   - "PlanDefinition/abc-123/_history/1"  (relative)
//   - "https://healthcare.googleapis.com/v1/.../fhir/PlanDefinition/abc-123/_history/1"  (absolute)
func parseLocation(location string) (resourceType, id string) {
	// Find the "/fhir/" marker to handle absolute URLs
	fhirIdx := strings.Index(location, "/fhir/")
	if fhirIdx >= 0 {
		location = location[fhirIdx+len("/fhir/"):]
	}

	// Now split "ResourceType/id/..." on "/"
	parts := strings.SplitN(location, "/", 3)
	if len(parts) >= 2 {
		return parts[0], parts[1]
	}
	return "", ""
}
