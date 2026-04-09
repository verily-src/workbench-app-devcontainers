package envvars

// AccessTier represents an access tier configuration
type AccessTier struct {
	ShortName            string `json:"shortName"`
	DatasetsBucket       string `json:"datasetsBucket"`
	ArtifactRegistryRepo string `json:"artifactRegistryRepo"`
}

// CdrConfig represents the configuration for CDR versions and access tiers
type CdrConfig struct {
	AccessTiers []AccessTier `json:"accessTiers"`
	CdrVersions []CdrVersion `json:"cdrVersions"`
}

// CdrVersion represents a CDR (Curated Data Repository) version with all associated metadata
type CdrVersion struct {
	Name                                 string `json:"name"`
	AccessTier                           string `json:"accessTier"`
	BigqueryProject                      string `json:"bigqueryProject"`
	BigqueryDataset                      string `json:"bigqueryDataset"`
	DCVersionName                        string `json:"dcVersionName"`
	StorageBasePath                      string `json:"storageBasePath"`
	WgsVcfMergedStoragePath              string `json:"wgsVcfMergedStoragePath" env:"WGS_VCF_MERGED_STORAGE_PATH"`
	WgsHailStoragePath                   string `json:"wgsHailStoragePath" env:"WGS_HAIL_STORAGE_PATH"`
	WgsCramManifestPath                  string `json:"wgsCramManifestPath" env:"WGS_CRAM_MANIFEST_PATH"`
	MicroarrayHailStoragePath            string `json:"microarrayHailStoragePath" env:"MICROARRAY_HAIL_STORAGE_PATH"`
	MicroarrayVcfSingleSampleStoragePath string `json:"microarrayVcfSingleSampleStoragePath" env:"MICROARRAY_VCF_SINGLE_SAMPLE_STORAGE_PATH"`
	MicroarrayVcfManifestPath            string `json:"microarrayVcfManifestPath" env:"MICROARRAY_VCF_MANIFEST_PATH"`
	MicroarrayIdatManifestPath           string `json:"microarrayIdatManifestPath" env:"MICROARRAY_IDAT_MANIFEST_PATH"`
	WgsVdsPath                           string `json:"wgsVdsPath" env:"WGS_VDS_PATH"`
	WgsExomeMultiHailPath                string `json:"wgsExomeMultiHailPath" env:"WGS_EXOME_MULTI_HAIL_PATH"`
	WgsExomeSplitHailPath                string `json:"wgsExomeSplitHailPath" env:"WGS_EXOME_SPLIT_HAIL_PATH"`
	WgsExomeVcfPath                      string `json:"wgsExomeVcfPath" env:"WGS_EXOME_VCF_PATH"`
	WgsAcafThresholdMultiHailPath        string `json:"wgsAcafThresholdMultiHailPath" env:"WGS_ACAF_THRESHOLD_MULTI_HAIL_PATH"`
	WgsAcafThresholdSplitHailPath        string `json:"wgsAcafThresholdSplitHailPath" env:"WGS_ACAF_THRESHOLD_SPLIT_HAIL_PATH"`
	WgsAcafThresholdVcfPath              string `json:"wgsAcafThresholdVcfPath" env:"WGS_ACAF_THRESHOLD_VCF_PATH"`
	WgsClinvarMultiHailPath              string `json:"wgsClinvarMultiHailPath" env:"WGS_CLINVAR_MULTI_HAIL_PATH"`
	WgsClinvarSplitHailPath              string `json:"wgsClinvarSplitHailPath" env:"WGS_CLINVAR_SPLIT_HAIL_PATH"`
	WgsClinvarVcfPath                    string `json:"wgsClinvarVcfPath" env:"WGS_CLINVAR_VCF_PATH"`
	WgsLongReadsManifestPath             string `json:"wgsLongReadsManifestPath" env:"LONG_READS_MANIFEST_PATH"`
	WgsLongReadsHailGRCh38               string `json:"wgsLongReadsHailGRCh38" env:"WGS_LONGREADS_HAIL_GRCH38_PATH"`
	WgsLongReadsHailT2T                  string `json:"wgsLongReadsHailT2T" env:"WGS_LONGREADS_HAIL_T2T_PATH"`
	WgsLongReadsJointVcfGRCh38           string `json:"wgsLongReadsJointVcfGRCh38" env:"WGS_LONGREADS_JOINT_SNP_INDEL_VCF_GRCH38_PATH"`
	WgsLongReadsJointVcfT2T              string `json:"wgsLongReadsJointVcfT2T" env:"WGS_LONGREADS_JOINT_SNP_INDEL_VCF_T2T_PATH"`
	WgsCMRGVcfPath                       string `json:"wgsCMRGVcfPath" env:"WGS_CMRG_VCF_PATH"`
}
