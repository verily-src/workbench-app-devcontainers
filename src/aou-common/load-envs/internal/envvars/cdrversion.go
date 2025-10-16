package envvars

// AccessTier represents an access tier configuration
type AccessTier struct {
	AccessTierID         int    `json:"accessTierId"`
	ShortName            string `json:"shortName"`
	DisplayName          string `json:"displayName"`
	ServicePerimeter     string `json:"servicePerimeter"`
	AuthDomainName       string `json:"authDomainName"`
	AuthDomainGroupEmail string `json:"authDomainGroupEmail"`
	DatasetsBucket       string `json:"datasetsBucket"`
	EnableUserWorkflows  bool   `json:"enableUserWorkflows"`
	VwbTierGroupName     string `json:"vwbTierGroupName"`
}

// CdrConfig represents the configuration for CDR versions and access tiers
type CdrConfig struct {
	AccessTiers []AccessTier `json:"accessTiers"`
	CdrVersions []CdrVersion `json:"cdrVersions"`
}

// CdrVersion represents a CDR (Curated Data Repository) version with all associated metadata
type CdrVersion struct {
	CdrVersionID                         int64  `json:"cdrVersionId"`
	IsDefault                            *bool  `json:"isDefault"`
	Name                                 string `json:"name"`
	AccessTier                           string `json:"accessTier"`
	ArchivalStatus                       int16  `json:"archivalStatus"`
	BigqueryProject                      string `json:"bigqueryProject"`
	BigqueryDataset                      string `json:"bigqueryDataset"`
	CreationTime                         string `json:"creationTime"`
	NumParticipants                      int    `json:"numParticipants"`
	CdrDbName                            string `json:"cdrDbName"`
	WgsBigqueryDataset                   string `json:"wgsBigqueryDataset"`
	WgsFilterSetName                     string `json:"wgsFilterSetName"`
	HasFitbitData                        *bool  `json:"hasFitbitData"`
	HasCopeSurveyData                    *bool  `json:"hasCopeSurveyData"`
	HasFitbitSleepData                   *bool  `json:"hasFitbitSleepData"`
	HasFitbitDeviceData                  *bool  `json:"hasFitbitDeviceData"`
	HasSurveyConductData                 *bool  `json:"hasSurveyConductData"`
	HasMHWBAndETMData                    *bool  `json:"hasMHWBAndETMData"`
	TanagraEnabled                       *bool  `json:"tanagraEnabled"`
	StorageBasePath                      string `json:"storageBasePath"`
	WgsVcfMergedStoragePath              string `json:"wgsVcfMergedStoragePath"`
	WgsHailStoragePath                   string `json:"wgsHailStoragePath"`
	WgsCramManifestPath                  string `json:"wgsCramManifestPath"`
	MicroarrayHailStoragePath            string `json:"microarrayHailStoragePath"`
	MicroarrayVcfSingleSampleStoragePath string `json:"microarrayVcfSingleSampleStoragePath"`
	MicroarrayVcfManifestPath            string `json:"microarrayVcfManifestPath"`
	MicroarrayIdatManifestPath           string `json:"microarrayIdatManifestPath"`
	WgsVdsPath                           string `json:"wgsVdsPath"`
	WgsExomeMultiHailPath                string `json:"wgsExomeMultiHailPath"`
	WgsExomeSplitHailPath                string `json:"wgsExomeSplitHailPath"`
	WgsExomeVcfPath                      string `json:"wgsExomeVcfPath"`
	WgsAcafThresholdMultiHailPath        string `json:"wgsAcafThresholdMultiHailPath"`
	WgsAcafThresholdSplitHailPath        string `json:"wgsAcafThresholdSplitHailPath"`
	WgsAcafThresholdVcfPath              string `json:"wgsAcafThresholdVcfPath"`
	WgsClinvarMultiHailPath              string `json:"wgsClinvarMultiHailPath"`
	WgsClinvarSplitHailPath              string `json:"wgsClinvarSplitHailPath"`
	WgsClinvarVcfPath                    string `json:"wgsClinvarVcfPath"`
	WgsLongReadsManifestPath             string `json:"wgsLongReadsManifestPath"`
	WgsLongReadsHailGRCh38               string `json:"wgsLongReadsHailGRCh38"`
	WgsLongReadsHailT2T                  string `json:"wgsLongReadsHailT2T"`
	WgsLongReadsJointVcfGRCh38           string `json:"wgsLongReadsJointVcfGRCh38"`
	WgsLongReadsJointVcfT2T              string `json:"wgsLongReadsJointVcfT2T"`
	WgsCMRGVcfPath                       string `json:"wgsCMRGVcfPath"`
	VwbTemplateID                        string `json:"vwbTemplateId"`
	PublicReleaseNumber                  int    `json:"publicReleaseNumber"`
}
