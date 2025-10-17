package envvars

import (
	"fmt"
	"maps"
	"reflect"
	"strings"
)

// Environment variable keys
const (
	workspaceCDREnvKey = "WORKSPACE_CDR"

	workspaceUfidKey        = "WORKSPACE_UFID"
	workspaceBucketKey      = "WORKSPACE_BUCKET"
	cdrStoragePathKey       = "CDR_STORAGE_PATH"
	artifactRegistryRepoKey = "ARTIFACT_REGISTRY_DOCKER_REPO"
)

var staticEnvVars = map[string]string{
	"BIGQUERY_STORAGE_API_ENABLED": "true",

	// FASTA reference environment variables
	"HG38_REFERENCE_FASTA": "gs://genomics-public-data/references/hg38/v0/Homo_sapiens_assembly38.fasta",
	"HG38_REFERENCE_FAI":   "gs://genomics-public-data/references/hg38/v0/Homo_sapiens_assembly38.fasta.fai",
	"HG38_REFERENCE_DICT":  "gs://genomics-public-data/references/hg38/v0/Homo_sapiens_assembly38.dict",
}

// buildCdrEnvVars builds environment variables for a CDR version
func buildCdrEnvVars(cdrVersion *CdrVersion, basePath string) map[string]string {
	vars := make(map[string]string)

	// Use reflection to iterate over struct fields with env tags
	val := reflect.ValueOf(cdrVersion).Elem()
	typ := val.Type()

	for i := 0; i < val.NumField(); i++ {
		field := typ.Field(i)
		envTag := field.Tag.Get("env")
		if envTag == "" {
			continue
		}

		// Get field value
		fieldValue := val.Field(i)
		if fieldValue.Kind() != reflect.String {
			continue
		}

		partialPath := fieldValue.String()

		// Only add non-empty paths
		if partialPath != "" {
			vars[envTag] = joinStoragePaths(basePath, partialPath)
		}
	}

	return vars
}

// GetBaseEnvironmentVariables returns the base environment variables for a workspace
func GetBaseEnvironmentVariables(
	workspaceUfid, gcpProject string,
	accessTier *AccessTier,
	cdrVersion *CdrVersion,
) map[string]string {
	customEnvironmentVariables := make(map[string]string)

	customEnvironmentVariables[workspaceUfidKey] = workspaceUfid
	customEnvironmentVariables[workspaceBucketKey] = fmt.Sprintf("gs://cloned-%s-%s", "mybucket", gcpProject)
	customEnvironmentVariables[artifactRegistryRepoKey] = accessTier.ArtifactRegistryRepo

	// Add CDR environment variables
	customEnvironmentVariables[workspaceCDREnvKey] = cdrVersion.BigqueryProject + "." + cdrVersion.BigqueryDataset
	if accessTier.DatasetsBucket != "" && cdrVersion.StorageBasePath != "" {
		basePath := joinStoragePaths(accessTier.DatasetsBucket, cdrVersion.StorageBasePath)

		customEnvironmentVariables[cdrStoragePathKey] = joinStoragePaths(basePath, "/")
		maps.Copy(customEnvironmentVariables, buildCdrEnvVars(cdrVersion, basePath))
	}

	maps.Copy(customEnvironmentVariables, staticEnvVars)

	return customEnvironmentVariables
}

// joinStoragePaths joins storage path segments, trimming leading/trailing slashes
func joinStoragePaths(paths ...string) string {
	var cleaned []string
	for _, p := range paths {
		trimmed := strings.Trim(p, "/")
		if trimmed != "" {
			cleaned = append(cleaned, trimmed)
		}
	}
	return strings.Join(cleaned, "/")
}
