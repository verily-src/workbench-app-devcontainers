package seeder

import (
	"bufio"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// EnvConfig holds environment-specific values loaded from an env profile file.
// These can override template defaults for FHIR store, GCS bucket, and base URL.
type EnvConfig struct {
	FHIRStore  string // e.g. "projects/<GCP_PROJECT>/locations/<REGION>/datasets/<DATASET>/fhirStores/<STORE>"
	GCSBucket  string // e.g. "econsent-pdf-pilot-dev-oneverily-<GCP_PROJECT>"
	EnvBaseURL string // e.g. "https://dev-stable.one.verily.com"
	EnvName    string // e.g. "dev-stable"
}

// LoadEnvConfig reads an environment profile from the envs/ directory relative
// to the given base directory (typically the standalone/ directory). Returns nil
// if envName is empty (no override requested).
func LoadEnvConfig(baseDir, envName string) (*EnvConfig, error) {
	if envName == "" {
		return nil, nil
	}

	envFile := filepath.Join(baseDir, "envs", envName+".env")
	if _, err := os.Stat(envFile); os.IsNotExist(err) {
		return nil, fmt.Errorf("environment profile not found: %s (available: dev-stable, dev-hermetic)", envFile)
	}

	vars, err := parseEnvFile(envFile)
	if err != nil {
		return nil, fmt.Errorf("parsing env profile %s: %w", envFile, err)
	}

	// Load .local.env overlay (written by hermetic-create.sh, git-ignored).
	// Values in the local file take precedence over the base env file.
	localEnvFile := filepath.Join(baseDir, "envs", envName+".local.env")
	if _, err := os.Stat(localEnvFile); err == nil {
		localVars, err := parseEnvFile(localEnvFile)
		if err != nil {
			return nil, fmt.Errorf("parsing local env overlay %s: %w", localEnvFile, err)
		}
		for k, v := range localVars {
			vars[k] = v
		}
	}

	cfg := &EnvConfig{
		EnvName: envName,
	}

	// Extract values we care about.
	if v, ok := vars["FHIR_STORE"]; ok && v != "" {
		cfg.FHIRStore = v
	}
	if v, ok := vars["GCS_BUCKET"]; ok && v != "" {
		cfg.GCSBucket = v
	}
	if v, ok := vars["ENV_BASE_URL"]; ok && v != "" {
		cfg.EnvBaseURL = v
	}

	return cfg, nil
}

// parseEnvFile reads a shell-style env file and returns a map of KEY=VALUE pairs.
// It handles:
//   - Comments (lines starting with #)
//   - Empty lines
//   - ${VAR:-default} patterns (extracts the default value)
//   - Quoted values ("value" or 'value')
//
// It does NOT handle complex shell expansions or ${VAR} references to other vars.
func parseEnvFile(path string) (map[string]string, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	vars := make(map[string]string)
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		// Skip comments and empty lines
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}

		// Find KEY=VALUE
		eqIdx := strings.Index(line, "=")
		if eqIdx < 0 {
			continue
		}
		key := strings.TrimSpace(line[:eqIdx])
		val := strings.TrimSpace(line[eqIdx+1:])

		// Strip quotes
		val = stripQuotes(val)

		// Handle ${VAR:-default} pattern — extract the default value
		if strings.HasPrefix(val, "${") && strings.HasSuffix(val, "}") {
			inner := val[2 : len(val)-1]
			if dashIdx := strings.Index(inner, ":-"); dashIdx >= 0 {
				val = inner[dashIdx+2:]
			} else {
				// ${VAR} without default — skip (value comes from environment)
				continue
			}
		}

		// Strip quotes from extracted default
		val = stripQuotes(val)

		// Handle ${FHIR_STORE} reference in FHIR_STORE_BASE — skip these,
		// we'll compose the URL from FHIR_STORE ourselves.
		if strings.Contains(val, "${") {
			continue
		}

		vars[key] = val
	}

	return vars, scanner.Err()
}

// stripQuotes removes surrounding double or single quotes from a string.
func stripQuotes(s string) string {
	if len(s) >= 2 {
		if (s[0] == '"' && s[len(s)-1] == '"') || (s[0] == '\'' && s[len(s)-1] == '\'') {
			return s[1 : len(s)-1]
		}
	}
	return s
}
