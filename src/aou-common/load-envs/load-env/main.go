package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"

	"github.com/deepmap/oapi-codegen/pkg/securityprovider"
	"github.com/google/uuid"
	"github.com/verily-src/workbench-app-devcontainers/src/aou-common/load-envs/load-env/internal/wsm"
)

var (
	workspaceId         = flag.String("workspace", "", "Workspace user-facing ID or UUID")
	workspaceManagerURL = flag.String("wsm-url", "", "Base Workspace Manager URL")
	envsDir             = flag.String("envs", "/.envs", "Directory containing environment variables")
)

func main() {
	flag.Parse()

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if *workspaceId == "" {
		log.Fatal("Workspace UfID must be specified via flag '-workspace'")
	}

	if *workspaceManagerURL == "" {
		log.Fatal("Workspace manager URL must be specified via flag '-wsm-url'")
	}

	authToken := os.Getenv("AUTH_TOKEN")
	if authToken == "" {
		log.Fatal("Bearer token must be specified via environment variable 'AUTH_TOKEN'")
	}

	workspaceUxid := *workspaceId
	_, err := uuid.Parse(*workspaceId)
	if err != nil {
		workspaceUxid = "~" + *workspaceId
	}

	version, err := GetAoUVersion(ctx, workspaceUxid, authToken)
	if err != nil {
		log.Fatalf("Failed to get AoU version: %v", err)
	}

	fmt.Println(filepath.Join(*envsDir, version.DataCollectionId.String(), version.Version+".env"))
}

type AoUVersion struct {
	DataCollectionId uuid.UUID
	Version          string
}

func GetAoUVersion(ctx context.Context, workspaceUxid string, authToken string) (AoUVersion, error) {
	client, err := GetWsmClient(authToken)
	if err != nil {
		return AoUVersion{}, err
	}

	resources, err := ListWsmResources(ctx, client, workspaceUxid)
	if err != nil {
		return AoUVersion{}, err
	}

	sourceResourceLineage, err := FirstAoUResource(resources)
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

func FirstAoUResource(resources *wsm.ResourceList) (wsm.ResourceLineageEntry, error) {
	files, err := os.ReadDir(*envsDir)
	if err != nil {
		return wsm.ResourceLineageEntry{}, fmt.Errorf("failed to read envs directory: %v", err)
	}

	// Pre-allocate the map with the number of children in the envs directory.
	// There shouldn't really be any that aren't valid UUIDs, so setting the
	// initial capacity to the number of children should eliminate
	// re-allocations.
	aouDataCollectionIds := make(map[uuid.UUID]struct{}, len(files))
	for _, file := range files {
		if !file.IsDir() {
			continue
		}
		if id, err := uuid.Parse(file.Name()); err == nil {
			aouDataCollectionIds[id] = struct{}{}
		}
	}

	for _, resource := range resources.Resources {
		lineage := resource.Metadata.ResourceLineage

		for _, lineageEntry := range *lineage {
			// Return the first lineage entry whose source workspace ID is
			// present in the aouDataCollectionIds map. There should not be
			// multiple versions of the AoU data collection in the same
			// workspace.
			if _, ok := aouDataCollectionIds[lineageEntry.SourceWorkspaceId]; ok {
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

func ListWsmFolders(
	ctx context.Context,
	client *wsm.ClientWithResponses,
	workspaceId string,
) (*wsm.FolderList, error) {
	wsmRsp, err := client.ListFoldersWithResponse(ctx, workspaceId)
	if err != nil {
		return nil, fmt.Errorf("getting folders from WSM: %v", err)
	}
	log.Printf("query to WSM service returned %v for workspace ID %v", wsmRsp.Status(), workspaceId)

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
	wsmRsp, err := client.EnumerateResourcesWithResponse(ctx, workspaceId, nil)
	if err != nil {
		return nil, fmt.Errorf("getting resources from WSM: %v", err)
	}
	log.Printf("query to WSM service returned %v for workspace ID %v", wsmRsp.Status(), workspaceId)

	if statusCode := wsmRsp.StatusCode(); statusCode != http.StatusOK {
		log.Printf("call to GET resource list for %v from WSM returned: %v", workspaceId, statusCode)
		return nil, fmt.Errorf("request to WSM failed with status: %v", statusCode)
	}

	return wsmRsp.JSON200, nil
}
