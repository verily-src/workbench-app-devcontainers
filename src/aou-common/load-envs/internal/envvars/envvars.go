package envvars

import (
	"maps"
	"strings"
)

// Environment variable keys
const (
	workspaceNameEnvKey = "WORKSPACE_NAME"
	googleProjectEnvKey = "GOOGLE_PROJECT"
	ownerEmailEnvKey    = "OWNER_EMAIL"

	microarrayHailStoragePathKey = "MICROARRAY_HAIL_STORAGE_PATH"
	workspaceCDREnvKey           = "WORKSPACE_CDR"

	bigQueryStorageAPIEnabledEnvKey = "BIGQUERY_STORAGE_API_ENABLED"

	workspaceUfidKey           = "WORKSPACE_UFID"
	workspaceBucketKey         = "WORKSPACE_BUCKET"
	cdrStoragePathKey          = "CDR_STORAGE_PATH"
	wgsVCFMergedStoragePathKey = "WGS_VCF_MERGED_STORAGE_PATH"
	wgsHailStoragePathKey      = "WGS_HAIL_STORAGE_PATH"

	wgsCramManifestPathKey = "WGS_CRAM_MANIFEST_PATH"

	microarrayVCFSingleSampleStoragePathKey = "MICROARRAY_VCF_SINGLE_SAMPLE_STORAGE_PATH"
	microarrayVCFManifestPathKey            = "MICROARRAY_VCF_MANIFEST_PATH"
	microarrayIdatManifestPathKey           = "MICROARRAY_IDAT_MANIFEST_PATH"

	// CDR V7, Q12023
	wgsVDSStoragePathKey = "WGS_VDS_PATH"
	// Exome
	wgsExomeMultiHailPathKey = "WGS_EXOME_MULTI_HAIL_PATH"
	wgsExomeSplitHailPathKey = "WGS_EXOME_SPLIT_HAIL_PATH"
	wgsExomeVCFPathKey       = "WGS_EXOME_VCF_PATH"
	// ACAF Threshold
	wgsAcafThresholdMultiHailPathKey = "WGS_ACAF_THRESHOLD_MULTI_HAIL_PATH"
	wgsAcafThresholdSplitHailPathKey = "WGS_ACAF_THRESHOLD_SPLIT_HAIL_PATH"
	wgsAcafThresholdVCFPathKey       = "WGS_ACAF_THRESHOLD_VCF_PATH"

	// Clinvar
	wgsClinvarMultiHailPathKey = "WGS_CLINVAR_MULTI_HAIL_PATH"
	wgsClinvarSplitHailPathKey = "WGS_CLINVAR_SPLIT_HAIL_PATH"
	wgsClinvarVCFPathKey       = "WGS_CLINVAR_VCF_PATH"

	// Long reads
	longReadsManifestPathKey                  = "LONG_READS_MANIFEST_PATH"
	wgsLongReadsHailGRCh38PathKey             = "WGS_LONGREADS_HAIL_GRCH38_PATH"
	wgsLongReadsHailT2TPathKey                = "WGS_LONGREADS_HAIL_T2T_PATH"
	wgsLongReadsJointSNPIndelVCFGRCh38PathKey = "WGS_LONGREADS_JOINT_SNP_INDEL_VCF_GRCH38_PATH"
	wgsLongReadsJointSNPIndelVCFT2TPathKey    = "WGS_LONGREADS_JOINT_SNP_INDEL_VCF_T2T_PATH"
	wgsCMRGVCFPathKey                         = "WGS_CMRG_VCF_PATH"

	artifactRegistryDockerRepoKey = "ARTIFACT_REGISTRY_DOCKER_REPO"
	artifactRegistryDockerRepo    = "us-central1-docker.pkg.dev/all-of-us-rw-prod/aou-rw-gar-remote-repo-docker-prod"
)

// FASTA reference environment variables
var fastaReferenceEnvVarMap = map[string]string{
	"HG38_REFERENCE_FASTA": "gs://genomics-public-data/references/hg38/v0/Homo_sapiens_assembly38.fasta",
	"HG38_REFERENCE_FAI":   "gs://genomics-public-data/references/hg38/v0/Homo_sapiens_assembly38.fasta.fai",
	"HG38_REFERENCE_DICT":  "gs://genomics-public-data/references/hg38/v0/Homo_sapiens_assembly38.dict",
}

// buildCdrEnvVars builds environment variables for a CDR version
func buildCdrEnvVars(cdrVersion *CdrVersion, datasetsBucket string) map[string]string {
	vars := make(map[string]string)

	vars[workspaceCDREnvKey] = cdrVersion.BigqueryProject + "." + cdrVersion.BigqueryDataset

	if datasetsBucket != "" && cdrVersion.StorageBasePath != "" {
		basePath := joinStoragePaths(datasetsBucket, cdrVersion.StorageBasePath)

		// Map of environment variable keys to optional storage paths
		partialStoragePaths := map[string]string{
			cdrStoragePathKey:                         "/",
			wgsVCFMergedStoragePathKey:                cdrVersion.WgsVcfMergedStoragePath,
			wgsHailStoragePathKey:                     cdrVersion.WgsHailStoragePath,
			wgsCramManifestPathKey:                    cdrVersion.WgsCramManifestPath,
			microarrayHailStoragePathKey:              cdrVersion.MicroarrayHailStoragePath,
			microarrayVCFSingleSampleStoragePathKey:   cdrVersion.MicroarrayVcfSingleSampleStoragePath,
			microarrayVCFManifestPathKey:              cdrVersion.MicroarrayVcfManifestPath,
			microarrayIdatManifestPathKey:             cdrVersion.MicroarrayIdatManifestPath,
			wgsVDSStoragePathKey:                      cdrVersion.WgsVdsPath,
			wgsExomeMultiHailPathKey:                  cdrVersion.WgsExomeMultiHailPath,
			wgsExomeSplitHailPathKey:                  cdrVersion.WgsExomeSplitHailPath,
			wgsExomeVCFPathKey:                        cdrVersion.WgsExomeVcfPath,
			wgsAcafThresholdMultiHailPathKey:          cdrVersion.WgsAcafThresholdMultiHailPath,
			wgsAcafThresholdSplitHailPathKey:          cdrVersion.WgsAcafThresholdSplitHailPath,
			wgsAcafThresholdVCFPathKey:                cdrVersion.WgsAcafThresholdVcfPath,
			wgsClinvarMultiHailPathKey:                cdrVersion.WgsClinvarMultiHailPath,
			wgsClinvarSplitHailPathKey:                cdrVersion.WgsClinvarSplitHailPath,
			wgsClinvarVCFPathKey:                      cdrVersion.WgsClinvarVcfPath,
			longReadsManifestPathKey:                  cdrVersion.WgsLongReadsManifestPath,
			wgsLongReadsHailGRCh38PathKey:             cdrVersion.WgsLongReadsHailGRCh38,
			wgsLongReadsHailT2TPathKey:                cdrVersion.WgsLongReadsHailT2T,
			wgsLongReadsJointSNPIndelVCFGRCh38PathKey: cdrVersion.WgsLongReadsJointVcfGRCh38,
			wgsLongReadsJointSNPIndelVCFT2TPathKey:    cdrVersion.WgsLongReadsJointVcfT2T,
			wgsCMRGVCFPathKey:                         cdrVersion.WgsCMRGVcfPath,
		}

		// Only add non-empty paths
		for key, partialPath := range partialStoragePaths {
			if partialPath != "" {
				vars[key] = joinStoragePaths(basePath, partialPath)
			}
		}
	}

	return vars
}

// GetBaseEnvironmentVariables returns the base environment variables for a workspace
func GetBaseEnvironmentVariables(
	workspaceUfid string,
	workspaceBucket string,
	cdrVersion *CdrVersion,
	datasetsBucket string,
) map[string]string {
	customEnvironmentVariables := make(map[string]string)

	customEnvironmentVariables[workspaceUfidKey] = workspaceUfid

	// This variable is already made available by Leonardo, but it's only exported in certain
	// notebooks contexts; this ensures it is always exported. See RW-7096.
	customEnvironmentVariables[workspaceBucketKey] = "gs://" + workspaceBucket

	customEnvironmentVariables[bigQueryStorageAPIEnabledEnvKey] = "true"

	// Add CDR environment variables
	maps.Copy(customEnvironmentVariables, buildCdrEnvVars(cdrVersion, datasetsBucket))

	// Add FASTA reference environment variables
	maps.Copy(customEnvironmentVariables, fastaReferenceEnvVarMap)

	customEnvironmentVariables[artifactRegistryDockerRepoKey] = artifactRegistryDockerRepo

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
