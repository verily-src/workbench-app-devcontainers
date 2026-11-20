package main

import (
	"fmt"
	"sort"
	"strings"
)

// Guides for wb_help. These used to be part of the tool descriptions, which are
// sent with every model request; here they cost tokens only when a model asks.
var helpTopics = map[string]string{
	"cohorts": `BUILDING A COHORT (tools in the "dataexplorer" group)

WORKFLOW
1. underlay_list_criteria_selectors(underlayName) -> selectors.
2. cohort_create_in_workspace(workspaceId, underlayId, underlayName, name) WITHOUT criteriaJson
   -> a cohort with all participants. Its response has studyId and cohortId at the top level:
   {"studyId": "abc-123", "cohortId": "def-456", "resourceId": "...", ...}
3. Keep studyId and cohortId; data_query_hints and cohort_update_criteria need both.
4. data_query_hints(studyId, cohortId, entityName) -> entity codes, enum values and numeric ranges.
5. Build criteria from the selectors and hints (formats below).
6. cohort_update_criteria(studyId, cohortId, criteriaGroupSections) -> applies the filters.
Only pass criteriaJson to cohort_create_in_workspace if you already know every selector name and code.

To find an existing cohort: study_list -> study_list_cohorts(studyId) -> match on displayName or
underlayName. study_list_cohorts also returns each cohort's actual criteriaGroupSections. Copying from
working cohorts is the most reliable way to get selectionData, selectorOrModifierName and uiConfig right.

SELECTORS (underlay_list_criteria_selectors)
Each selector has name, plugin, pluginConfig, category and displayName. Use:
- selector.name -> selectorOrModifierName
- selector.plugin -> pluginName
- selector.pluginConfig -> uiConfig (keep it as a JSON string)
For "entityGroup" selectors, parse pluginConfig: classificationEntityGroups[0].id (e.g.
"currentDiagnosesPerson") is the entityGroup value for selectionData, and its columns give the
entity's ID field for data_query_hints.

HINTS (data_query_hints)
entityName is e.g. "person", "diagnoses" or "medications". The response's displayHints array holds:
{"attribute": {"name": "<attr>", "dataType": "INT64|STRING|..."},
 "displayHint": {"numericRangeHint": {"min": <n>, "max": <n>}}   // numeric attributes
            or  {"enumHint": {"enumHintValues": [...]}}}          // categorical attributes
For numeric attributes such as age, start from the exact min/max in numericRangeHint and adjust one end
(e.g. if max=92, use min=66,max=92 for "over 65"). For entityGroup attributes, take the ID value for
int64Key and the name for display.

CRITERIA (criteriaGroupSections; also the criteriaJson shape {"criteriaGroupSections": [...]})
[{
  "id": "section-1", "displayName": "Filters", "disabled": false, "operator": "AND", "excluded": false,
  "firstBlockReducingOperator": "ANY", "secondBlockReducingOperator": "ANY",
  "secondBlockCriteriaGroups": [],
  "criteriaGroups": [{
    "id": "group-1", "disabled": false,
    "criteria": [{
      "id": "crit-1",
      "pluginName": "<selector.plugin>",
      "selectorOrModifierName": "<selector.name>",
      "selectionData": "<JSON, escaped as a string>",
      "uiConfig": "<selector.pluginConfig, escaped as a string>",
      "pluginVersion": 0, "tags": {}, "enabled": true
    }]
  }]
}]
Put each criterion in its own criteriaGroup. Operator "AND" means every group must match.

selectionData BY PLUGIN (a JSON string inside the criterion)
- "attribute" (numeric, e.g. age): "{\"dataRanges\":[{\"min\":66,\"max\":92}]}"
  Both min and max are required, as numbers, not strings.
- "entityGroup" (diagnoses, medications): "{\"selected\":[{\"key\":{\"int64Key\":CODE},\"name\":\"NAME\",\"entityGroup\":\"GROUP_ID\"}]}"
  int64Key must be a number. GROUP_ID comes from the selector's pluginConfig.
- "multiAttribute", numeric: "{\"selected\":[{\"attribute\":\"ATTR\",\"dataRanges\":[{\"min\":NUM,\"max\":NUM}]}]}"
- "multiAttribute", categorical: "{\"selected\":[{\"attribute\":\"ATTR\",\"values\":[{\"value\":{\"stringVal\":\"VALUE\"}}]}]}"

The filter_build_* tools build Data Explorer filter JSON (attribute, relationship, boolean logic,
hierarchy) for tools that take filters.`,

	"export": `EXPORTING A COHORT (tools in the "dataexplorer" group)

1. export_list_models(underlayName) -> export models. Each has name (use it as exportModel),
   displayName, description and numPrimaryEntityCap (the most entities it can export).
2. export_describe(studyId, cohortId) -> the entities and attributes the export will include: the
   cohort's variable set, or every criterion with allCriteriaFromCohort=true.
3. export_preview(studyId, cohortId, exportModel, entityName) -> up to 20 sample instances.
4. export_cohort(studyId, cohortId, exportRequests) -> one result per request, with status
   ("SUCCEEDED" or "FAILED"), links (download URLs for the CSV, IPYNB, ... files) and error.
   Each request has exportModel (required), inputs (model-specific, optional), includeAnnotations
   (default true) and compressFiles (default true).
studyId and cohortId come from cohort_create_in_workspace, or from study_list and study_list_cohorts.`,

	"data-collections": `FINDING DATA COLLECTIONS

- workspace_list_data_collections: collections already added to the current workspace, with their
  resources grouped by source collection (via each resource's lineage), plus resources created locally.
- platform_list_data_collections: every collection the user can read across all of Workbench, attached
  or not. Tell the user this is a platform-wide search, not just their workspace.
  The query argument matches name, description, data modality tags, therapeutic area tags and data
  model type, so "imaging", "genomics" or "oncology" work.
  Each result can include: shortDescription, description, organization, availability, isFree,
  isInstantlyAccessible, patientCount, timeFrame, geographicCoverage, dataModel, dataModalityTags,
  therapeuticTags, underlayName (for schema exploration), dataDictionary, usageExamples (sample use
  cases and SQL), accessGroupName, supportEmail, dataPublished, metadataLastUpdated and
  externalDocumentation.
  Summarize results by relevance, highlighting the fields that matter for the question (e.g. patient
  count and modality for clinical searches, underlayName for schema exploration).`,
}

// helpTopicNames returns the topics accepted by wb_help, including "toolsets".
func helpTopicNames() []string {
	names := []string{"toolsets"}
	for name := range helpTopics {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

func wbHelp(topic string, enabled map[string]bool, cloud string) (string, error) {
	topic = strings.ToLower(strings.TrimSpace(topic))
	if topic == "toolsets" {
		return toolsetsHelp(enabled, cloud), nil
	}
	if text, ok := helpTopics[topic]; ok {
		return text, nil
	}
	return "", fmt.Errorf("unknown topic %q; topics: %s", topic, strings.Join(helpTopicNames(), ", "))
}
