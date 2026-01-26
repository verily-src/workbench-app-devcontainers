package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"

	"github.com/deepmap/oapi-codegen/pkg/securityprovider"
	"github.com/google/uuid"
	"github.com/verily-src/workbench-app-devcontainers/src/aou-common/load-envs/configs"
	"github.com/verily-src/workbench-app-devcontainers/src/aou-common/load-envs/internal/envvars"
	"github.com/verily-src/workbench-app-devcontainers/src/aou-common/load-envs/internal/wsm"
)

var (
	workspaceUfid       = flag.String("workspace", "", "Workspace user-facing ID")
	workspaceManagerURL = flag.String("wsm-url", "", "Base Workspace Manager URL")
)

// DataCollectionMapping defines the mapping from AoU data collection UUIDs to
// CDR environments and access tiers
type DataCollectionMapping struct {
	// The UUID of the AoU data collection
	DataCollectionUUID string `json:"dataCollectionUuid"`
	// The CDR environment (test, stable, prod) for this data collection
	CdrEnv string `json:"cdrEnv"`
	// The access tier short name (registered, controlled) for this data collection
	AccessTier string `json:"accessTier"`
}

func main() {
	flag.Parse()

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if *workspaceUfid == "" {
		log.Fatal("Workspace user-facing ID must be specified via flag '-workspace'")
	}

	if *workspaceManagerURL == "" {
		log.Fatal("Workspace manager URL must be specified via flag '-wsm-url'")
	}

	authToken := os.Getenv("AUTH_TOKEN")
	if authToken == "" {
		log.Fatal("Bearer token must be specified via environment variable 'AUTH_TOKEN'")
	}

	// Load data collection mappings once
	mappings, err := LoadDataCollectionMappings()
	if err != nil {
		log.Fatalf("Failed to load data collection mappings: %v", err)
	}

	client, err := GetWsmClient(authToken)
	if err != nil {
		log.Fatalf("Failed to create WSM client: %v", err)
	}

	gcpProject, err := GetGcpProject(ctx, client)
	if err != nil {
		log.Fatalf("Failed to get GCP project: %v", err)
	}

	aouVersion, err := GetAoUVersion(ctx, client, mappings)
	if err != nil {
		log.Fatalf("Failed to get AoU version: %v", err)
	}

	// Get CDR configuration (access tier and version)
	accessTier, cdrVersion, err := GetCdrConfiguration(mappings, aouVersion)
	if err != nil {
		log.Fatalf("Failed to get CDR configuration: %v", err)
	}

	log.Printf("Using CDR version: %s (env: %s, version: %s, access tier: %s)", cdrVersion.Name, mappings[aouVersion.DataCollectionId].CdrEnv, cdrVersion.DCVersionName, accessTier.ShortName)

	// Build and print environment variables
	PrintEnvironmentVariables(gcpProject, cdrVersion, accessTier)
}

// LoadDataCollectionMappings loads and parses the data collection mappings into a map
func LoadDataCollectionMappings() (map[uuid.UUID]DataCollectionMapping, error) {
	var mappingsList []DataCollectionMapping
	if err := json.Unmarshal(configs.DatacollectionMapping, &mappingsList); err != nil {
		return nil, fmt.Errorf("failed to parse data collection mapping: %v", err)
	}

	mappings := make(map[uuid.UUID]DataCollectionMapping, len(mappingsList))
	for _, mapping := range mappingsList {
		id, err := uuid.Parse(mapping.DataCollectionUUID)
		if err != nil {
			return nil, fmt.Errorf("invalid UUID in data collection mapping: %s", mapping.DataCollectionUUID)
		}
		mappings[id] = mapping
	}

	return mappings, nil
}

// GetCdrConfiguration loads the CDR config and finds the matching access tier and version.
// Returns the access tier and CDR version for the given data collection mapping and AoU version.
func GetCdrConfiguration(mappings map[uuid.UUID]DataCollectionMapping, aouVersion AoUVersion) (*envvars.AccessTier, *envvars.CdrVersion, error) {
	mapping := mappings[aouVersion.DataCollectionId]

	// Load the appropriate CDR config based on the environment
	var cdrConfigData []byte
	switch mapping.CdrEnv {
	case "test":
		cdrConfigData = configs.CdrConfigTest
	case "stable":
		cdrConfigData = configs.CdrConfigStable
	case "prod":
		cdrConfigData = configs.CdrConfigProd
	default:
		return nil, nil, fmt.Errorf("unknown CDR environment: %s", mapping.CdrEnv)
	}

	var cdrConfig envvars.CdrConfig
	if err := json.Unmarshal(cdrConfigData, &cdrConfig); err != nil {
		return nil, nil, fmt.Errorf("failed to parse CDR config: %v", err)
	}

	// Find the access tier
	var accessTier *envvars.AccessTier
	for _, at := range cdrConfig.AccessTiers {
		if at.ShortName == mapping.AccessTier {
			accessTier = &at
			break
		}
	}
	if accessTier == nil {
		return nil, nil, fmt.Errorf("access tier not found: %s", mapping.AccessTier)
	}

	// Find the CDR version by public release number and access tier
	for _, v := range cdrConfig.CdrVersions {
		if v.AccessTier == mapping.AccessTier && v.DCVersionName == aouVersion.Version {
			return accessTier, &v, nil
		}
	}

	return nil, nil, fmt.Errorf("CDR version not found: %s (env: %s, access tier: %s)", aouVersion.Version, mapping.CdrEnv, mapping.AccessTier)
}

// PrintEnvironmentVariables builds and prints environment variables in .env format
func PrintEnvironmentVariables(gcpProject string, cdrVersion *envvars.CdrVersion, accessTier *envvars.AccessTier) {
	envVars := envvars.GetBaseEnvironmentVariables(
		*workspaceUfid,
		gcpProject,
		accessTier,
		cdrVersion,
	)

	for key, value := range envVars {
		fmt.Printf("export %s=%s\n", key, value)
	}
}

type AoUVersion struct {
	DataCollectionId uuid.UUID
	Version          string
}

// GetGcpProject retrieves the GCP project associated with the specified
// workspace
func GetGcpProject(ctx context.Context, client *wsm.ClientWithResponses) (string, error) {
	workspace, err := DescribeWsmWorkspace(ctx, client, "~"+*workspaceUfid)
	if err != nil {
		return "", err
	}

	return workspace.GcpContext.ProjectId, nil
}

// GetAoUVersion retrieves the AoU data collection version by inspecting the
// lineage of resources in the specified workspace and comparing them to the
// known AoU data collection UUIDs.
func GetAoUVersion(ctx context.Context, client *wsm.ClientWithResponses, mappings map[uuid.UUID]DataCollectionMapping) (AoUVersion, error) {
	resources, err := ListWsmResources(ctx, client, "~"+*workspaceUfid)
	if err != nil {
		return AoUVersion{}, err
	}

	sourceResourceLineage, err := FirstAoUResource(resources, mappings)
	if err != nil {
		return AoUVersion{}, err
	}

	version, err := GetVersionForResource(
		ctx,
		client,
		sourceResourceLineage.SourceResourceId,
		sourceResourceLineage.SourceWorkspaceId.String())
	if err != nil {
		return AoUVersion{}, err
	}

	aouVersion := AoUVersion{
		DataCollectionId: sourceResourceLineage.SourceWorkspaceId,
		Version:          version,
	}
	return aouVersion, nil
}

// GetVersionForResource retrieves the version string for a given resource by
// traversing its folder hierarchy to find the root folder, whose name is used
// as the version string.
func GetVersionForResource(
	ctx context.Context,
	client *wsm.ClientWithResponses,
	sourceResourceId uuid.UUID,
	sourceDataCollectionId string,
) (string, error) {
	sourceFolders, err := ListWsmFolders(ctx, client, sourceDataCollectionId)
	if err != nil {
		return "", err
	}

	sourceResources, err := ListWsmResources(ctx, client, sourceDataCollectionId)
	if err != nil {
		return "", err
	}

	folders := make(map[uuid.UUID]*wsm.Folder, len(sourceFolders.Folders))
	for _, folder := range sourceFolders.Folders {
		folders[folder.Id] = &folder
	}

	var folder *wsm.Folder
	for _, resource := range sourceResources.Resources {
		if resource.Metadata.ResourceId != sourceResourceId {
			continue
		}

		if resource.Metadata.FolderId == nil {
			continue
		}

		folder, err = GetRootFolder(*resource.Metadata.FolderId, folders)
		if err != nil {
			return "", fmt.Errorf("failed to get root folder: %v", err)
		}
		break
	}

	if folder == nil {
		return "", fmt.Errorf("no folder found for resource %v", sourceResourceId)
	}

	return folder.DisplayName, nil
}

// GetRootFolder recursively walks up the parent folders given a leaf folder ID
func GetRootFolder(leafFolderId uuid.UUID, folders map[uuid.UUID]*wsm.Folder) (*wsm.Folder, error) {
	folder, ok := folders[leafFolderId]
	if !ok {
		return nil, fmt.Errorf("Folder not found: %v", leafFolderId)
	}

	if folder.ParentFolderId != nil {
		return GetRootFolder(*folder.ParentFolderId, folders)
	}

	return folder, nil
}

func FirstAoUResource(resources *wsm.ResourceList, mappings map[uuid.UUID]DataCollectionMapping) (wsm.ResourceLineageEntry, error) {
	for _, resource := range resources.Resources {
		lineage := resource.Metadata.ResourceLineage

		for _, lineageEntry := range *lineage {
			// Return the first lineage entry whose source workspace ID is
			// present in the mappings. There should not be multiple versions
			// of the AoU data collection in the same workspace.
			if _, ok := mappings[lineageEntry.SourceWorkspaceId]; ok {
				return lineageEntry, nil
			}
		}
	}

	return wsm.ResourceLineageEntry{}, fmt.Errorf("no AoU resources in workspace")
}

func GetWsmClient(authToken string) (*wsm.ClientWithResponses, error) {
	bearerTokenProvider, err := securityprovider.NewSecurityProviderBearerToken(authToken)
	if err != nil {
		return nil, fmt.Errorf("creating bearer token: %v", err)
	}

	client, err := wsm.NewClientWithResponses(*workspaceManagerURL, wsm.WithRequestEditorFn(bearerTokenProvider.Intercept))
	if err != nil {
		return nil, fmt.Errorf("creating WSM client: %v", err)
	}

	return client, nil
}

func DescribeWsmWorkspace(
	ctx context.Context,
	client *wsm.ClientWithResponses,
	workspaceId string,
) (*wsm.WorkspaceDescription, error) {
	wsmRsp, err := client.DescribeWorkspaceWithResponse(ctx, workspaceId)
	if err != nil {
		return nil, fmt.Errorf("describing workspace from WSM: %v", err)
	}

	if statusCode := wsmRsp.StatusCode(); statusCode != http.StatusOK {
		log.Printf("call to GET workspace %v from WSM returned: %v", workspaceId, statusCode)
		return nil, fmt.Errorf("request to WSM failed with status: %v", statusCode)
	}

	return wsmRsp.JSON200, nil
}

func ListWsmFolders(
	ctx context.Context,
	client *wsm.ClientWithResponses,
	workspaceId string,
) (*wsm.FolderList, error) {
	wsmRsp, err := client.ListFoldersWithResponse(ctx, workspaceId)
	if err != nil {
		return nil, fmt.Errorf("getting folders from WSM: %v", err)
	}

	if statusCode := wsmRsp.StatusCode(); statusCode != http.StatusOK {
		log.Printf("call to GET folder list for %v from WSM returned: %v", workspaceId, statusCode)
		return nil, fmt.Errorf("request to WSM failed with status: %v", statusCode)
	}

	return wsmRsp.JSON200, nil
}

func ListWsmResources(
	ctx context.Context,
	client *wsm.ClientWithResponses,
	workspaceId string,
) (*wsm.ResourceList, error) {
	wsmRsp, err := client.EnumerateResourcesWithResponse(ctx, workspaceId, &wsm.EnumerateResourcesParams{
		LimitParam: ptr(1000),
	})
	if err != nil {
		return nil, fmt.Errorf("getting resources from WSM: %v", err)
	}

	if statusCode := wsmRsp.StatusCode(); statusCode != http.StatusOK {
		log.Printf("call to GET resource list for %v from WSM returned: %v", workspaceId, statusCode)
		return nil, fmt.Errorf("request to WSM failed with status: %v", statusCode)
	}

	return wsmRsp.JSON200, nil
}

func ptr[T any](v T) *T {
	return &v
}
