package seeder

import (
	"fmt"
)

// ---------------------------------------------------------------------------
// Workflow structure builders
// ---------------------------------------------------------------------------

const (
	planDefProfile       = "http://fhir.verily.com/StructureDefinition/verily-workflow-plandefinition"
	actDefProfile        = "http://fhir.verily.com/StructureDefinition/verily-workflow-activitydefinition"
	contentExtURL        = "http://fhir.verily.com/StructureDefinition/content"
	bundleCardTypeExtURL = "http://fhir.verily.com/StructureDefinition/bundle-card-type"
	lastStepExtURL       = "http://fhir.verily.com/StructureDefinition/last-step-in-bundle"

	bundleStepSystem      = "http://fhir.verily.com/CodeSystem/bundle-step"
	bundleStepTypeSystem  = "http://fhir.verily.com/CodeSystem/bundle-step-type"
	actionCategorySystem  = "http://fhir.verily.com/CodeSystem/action-category"
	actionActivityType    = "http://fhir.verily.com/CodeSystem/action-activity-type"
	activitySystem        = "http://fhir.verily.com/CodeSystem/activity"
	bundleCardVCMSContent = "http://fhir.verily.com/CodeSystem/bundle-card-vcms-content"
	bundleStepVCMSContent = "http://fhir.verily.com/CodeSystem/bundle-step-vcms-content"

	carePathwayExtURL = "http://fhir.verily.com/StructureDefinition/care-program-care-pathway"
	enrolledExtURL    = "http://fhir.verily.com/StructureDefinition/care-program-enrolled"
	hcsProfile        = "http://fhir.verily.com/StructureDefinition/verily-care-program"
)

// ---------------------------------------------------------------------------
// Organization (prerequisite for org-compartment validation)
// ---------------------------------------------------------------------------

const (
	orgProfile          = "http://fhir.verily.com/StructureDefinition/verily-organization"
	orgIdentifierSystem = "http://fhir.verily.com/NamingSystem/verily-organization-identifier"
	orgTypeSystem       = "http://fhir.verily.com/CodeSystem/verily-organization-type"
	partOfOrgExtURL     = "http://fhir.verily.com/StructureDefinition/verily-part-of-organization"

	// cortexBootstrapOrgID is the Organization that cortex bootstraps into every
	// FHIR store (including ephemeral ones).  We use it as the parent for newly
	// seeded organizations.
	// See cortex/internal/hermetic/bootstraporg.go.
	cortexBootstrapOrgID = "c19068d3-f31f-46d8-93f9-74bac897dcad"
)

// buildOrganization creates a minimal FHIR Organization resource that satisfies
// the cortex-fhir-proxy's org-compartment validation.  Without this resource in
// the FHIR store, enrollment (which routes through cortex-fhir-proxy) fails with
// "organization-compartment URL is invalid".
//
// IMPORTANT: The caller (buildWorkflowStructure) only includes this resource in
// the transaction when the Organization does not already exist (checked via GET).
// In shared environments (dev-stable) the Organization has a real
// verily-part-of-organization hierarchy managed by other teams — a PUT would
// replace the entire resource and destroy that hierarchy.  The seed-program tool
// writes directly to the GCP Healthcare API (bypassing cortex-fhir-proxy), so
// the proxy's validatePartOfOrganization guard does not protect against this.
func buildOrganization(bc *buildContext) map[string]interface{} {
	return map[string]interface{}{
		"resourceType": "Organization",
		"id":           bc.tmpl.OrgID,
		"meta": map[string]interface{}{
			"profile": []string{orgProfile},
			"extension": []map[string]interface{}{
				{
					"url": orgCompartmentExtURL,
					"valueReference": map[string]interface{}{
						"reference": "Organization/" + bc.tmpl.OrgID,
					},
				},
			},
		},
		"active": true,
		"name":   fmt.Sprintf("Standalone Seeding Org (%s)", bc.tmpl.OrgID),
		"identifier": []map[string]interface{}{
			{
				"system": orgIdentifierSystem,
				"value":  bc.tmpl.OrgID,
			},
		},
		"type": []map[string]interface{}{
			{
				"coding": []map[string]interface{}{
					{
						"system": orgTypeSystem,
						"code":   "CareDeliveryOrganization",
					},
				},
			},
		},
		"extension": []map[string]interface{}{
			{
				"url": partOfOrgExtURL,
				"valueReference": map[string]interface{}{
					"reference": "Organization/" + cortexBootstrapOrgID,
					"type":      "Organization",
				},
			},
		},
	}
}

// ---------------------------------------------------------------------------
// Group (applicability)
// ---------------------------------------------------------------------------

// buildGroup creates a FHIR Group resource for PlanDefinition applicability.
// Characteristics: org match + care-program-enrolled.
// The profile is required for workflow-be to read the Group (Data Contract).
func buildGroup(bc *buildContext) map[string]interface{} {
	return map[string]interface{}{
		"resourceType": "Group",
		"meta":         buildOrgCompartmentMeta(bc, "http://fhir.verily.com/StructureDefinition/verily-workflow-group"),
		"type":         "person",
		"actual":       false,
		"name":         fmt.Sprintf("%s Applicability Group", bc.tmpl.Name),
		// The characteristic uses a FHIRPath expression that the workflow engine
		// evaluates for applicability. It checks:
		//   1. Patient's managingOrganization matches the program's org
		//   2. Patient has the care-program-enrolled extension
		"characteristic": []map[string]interface{}{
			{
				"code": map[string]interface{}{
					"text": fmt.Sprintf(
						"Patient.managingOrganization.reference='Organization/%s' and "+
							"Patient.extension.where(url='%s').exists()",
						bc.tmpl.OrgID,
						enrolledExtURL,
					),
				},
				"valueBoolean": true,
				"exclude":      false,
			},
		},
	}
}

// ---------------------------------------------------------------------------
// ActivityDefinition (for info steps)
// ---------------------------------------------------------------------------

// buildActivityDefinition creates a FHIR ActivityDefinition that references
// a DocumentReference for an info step.
func buildActivityDefinition(bc *buildContext, actionID string, docRefTempID string) (tempID string, resource map[string]interface{}) {
	adURL := canonicalURL("standalone-seeding", "ActivityDefinition", actionID)
	tempID = newTempID()

	resource = map[string]interface{}{
		"resourceType": "ActivityDefinition",
		"meta":         buildOrgCompartmentMeta(bc, actDefProfile),
		"status":       "active",
		"url":          adURL,
		"version":      bc.tmpl.Version,
		"kind":         "Task",
		"extension": []map[string]interface{}{
			{
				"url": contentExtURL,
				"valueReference": map[string]interface{}{
					"reference": docRefTempID,
					"type":      "DocumentReference",
				},
			},
		},
		"dynamicValue": []map[string]interface{}{
			{
				"path": "input[0].value as Reference",
				"expression": map[string]interface{}{
					"expression": "%activity_definition.extension[0].value as Reference",
					"language":   "text/fhirpath",
				},
			},
		},
	}
	return tempID, resource
}

// ---------------------------------------------------------------------------
// ActivityDefinition (for consent steps)
// ---------------------------------------------------------------------------

// buildConsentActivityDefinition creates a FHIR ActivityDefinition for a consent step.
// Unlike info steps (which use valueReference → DocumentReference), consent steps
// use valueCanonical → Contract canonical URL. The workflow engine copies this
// canonical into the Task's input, which the action service's consent module reads
// to look up the Contract + Questionnaire + CodeSystems.
func buildConsentActivityDefinition(bc *buildContext, actionID string, contractCanonical string) (tempID string, resource map[string]interface{}) {
	adURL := canonicalURL("standalone-seeding", "ActivityDefinition", actionID)
	tempID = newTempID()

	resource = map[string]interface{}{
		"resourceType": "ActivityDefinition",
		"meta":         buildOrgCompartmentMeta(bc, actDefProfile),
		"status":       "active",
		"url":          adURL,
		"version":      bc.tmpl.Version,
		"kind":         "Task",
		"extension": []map[string]interface{}{
			{
				"url":            contentExtURL,
				"valueCanonical": contractCanonical,
			},
		},
		"dynamicValue": []map[string]interface{}{
			{
				"path": "input[0].value as canonical",
				"expression": map[string]interface{}{
					"expression": "%activity_definition.extension[0].value as canonical",
					"language":   "text/fhirpath",
				},
			},
		},
	}
	return tempID, resource
}

// ---------------------------------------------------------------------------
// Child PlanDefinition (bundle / mission)
// ---------------------------------------------------------------------------

// bundleStepAction holds the data needed to create a PlanDefinition action for a bundle step.
type bundleStepAction struct {
	StepType            string // "info", "survey", or "consent"
	ActionID            string
	DefinitionCanonical string // ActivityDefinition URL|version for info/consent; Questionnaire URL|version for survey
	ContentOID          string
}

// buildChildPlanDefinition creates a child PlanDefinition (one per bundle/mission).
func buildChildPlanDefinition(bc *buildContext, bundle Bundle, bundleIdx int, cardDocRefTempID string, steps []bundleStepAction) (tempID string, resource map[string]interface{}) {
	planDefURL := canonicalURL("standalone-seeding", "PlanDefinition", fmt.Sprintf("%s-%s", bc.tmpl.Name, bundle.Name))
	tempID = newTempID()

	// Build step actions
	stepActions := []interface{}{}
	for i, step := range steps {
		action := buildStepAction(step)
		// Mark the last step
		if i == len(steps)-1 {
			addLastStepExtension(action)
		}
		stepActions = append(stepActions, action)
	}

	// Build the bundle action (wrapper)
	activityID := fmt.Sprintf("%s-%s", bc.tmpl.Name, bundle.Name)
	bundleAction := map[string]interface{}{
		"id":     activityID,
		"title":  bundle.Card.Title,
		"action": stepActions,
		"code": []map[string]interface{}{
			{
				"coding": []map[string]interface{}{
					{"system": actionActivityType, "code": "bundle"},
					{"system": actionCategorySystem, "code": "participant"},
					{"system": activitySystem, "code": activityID},
				},
			},
		},
		"extension": []map[string]interface{}{
			{
				"url": contentExtURL,
				"valueReference": map[string]interface{}{
					"reference": cardDocRefTempID,
					"type":      "DocumentReference",
				},
			},
			{
				"url":       bundleCardTypeExtURL,
				"valueCode": "task",
			},
		},
		"dynamicValue": []map[string]interface{}{
			{
				"path": "extension",
				"expression": map[string]interface{}{
					"expression": "%action.extension[0]",
					"language":   "text/fhirpath",
				},
			},
			{
				"path": "extension",
				"expression": map[string]interface{}{
					"expression": "%action.extension[1]",
					"language":   "text/fhirpath",
				},
			},
		},
	}

	resource = map[string]interface{}{
		"resourceType": "PlanDefinition",
		"meta":         buildOrgCompartmentMeta(bc, planDefProfile),
		"status":       "active",
		"name":         bundle.Name,
		"url":          planDefURL,
		"version":      bc.tmpl.Version,
		"action":       []interface{}{bundleAction},
	}
	return tempID, resource
}

// buildStepAction creates a PlanDefinition.action for a single bundle step.
func buildStepAction(step bundleStepAction) map[string]interface{} {
	codings := []map[string]interface{}{
		{"system": bundleStepSystem, "code": step.ActionID},
		{"system": bundleStepTypeSystem, "code": step.StepType},
		{"system": actionCategorySystem, "code": "participant"},
	}

	action := map[string]interface{}{
		"id": step.ActionID,
		"code": []map[string]interface{}{
			{"coding": codings},
		},
		"dynamicValue": []map[string]interface{}{
			{
				"path": "input[0].type.coding",
				"expression": map[string]interface{}{
					"expression": "%action.code[0].coding[0]",
					"language":   "text/fhirpath",
				},
			},
			{
				"path": "input[0].type.coding",
				"expression": map[string]interface{}{
					"expression": "%action.code[0].coding[1]",
					"language":   "text/fhirpath",
				},
			},
		},
	}

	// Info steps use definitionCanonical pointing to ActivityDefinition
	// Survey steps use definitionCanonical pointing to Questionnaire
	if step.DefinitionCanonical != "" {
		action["definitionCanonical"] = step.DefinitionCanonical
	}

	return action
}

// addLastStepExtension adds the last-step-in-bundle extension to an action.
func addLastStepExtension(action map[string]interface{}) {
	ext, ok := action["extension"].([]map[string]interface{})
	if !ok {
		ext = []map[string]interface{}{}
	}
	ext = append(ext, map[string]interface{}{
		"url":          lastStepExtURL,
		"valueBoolean": true,
	})
	action["extension"] = ext
}

// ---------------------------------------------------------------------------
// Root PlanDefinition (care pathway)
// ---------------------------------------------------------------------------

// buildRootPlanDefinition creates the top-level care pathway PlanDefinition.
func buildRootPlanDefinition(bc *buildContext, childPlanDefCanonicals []string) map[string]interface{} {
	rootURL := canonicalURL("standalone-seeding", "PlanDefinition", bc.tmpl.Name)

	actions := []map[string]interface{}{}
	for i, canonical := range childPlanDefCanonicals {
		actions = append(actions, map[string]interface{}{
			"id":                  fmt.Sprintf("bundle-%d", i),
			"definitionCanonical": canonical,
		})
	}

	return map[string]interface{}{
		"resourceType": "PlanDefinition",
		"meta":         buildOrgCompartmentMeta(bc, planDefProfile),
		"status":       "active",
		"name":         bc.tmpl.Name,
		"url":          rootURL,
		"version":      bc.tmpl.Version,
		"subjectReference": map[string]interface{}{
			"reference": bc.groupTempID,
		},
		"action": actions,
	}
}

// ---------------------------------------------------------------------------
// HealthcareService (program entry point)
// ---------------------------------------------------------------------------

// buildHealthcareService creates a HealthcareService with a care-pathway extension.
func buildHealthcareService(bc *buildContext, rootPlanDefCanonical string) map[string]interface{} {
	return map[string]interface{}{
		"resourceType": "HealthcareService",
		"meta":         buildOrgCompartmentMeta(bc, hcsProfile),
		"active":       true,
		"name":         bc.tmpl.Name,
		"extension": []map[string]interface{}{
			{
				"url":            carePathwayExtURL,
				"valueCanonical": rootPlanDefCanonical,
			},
		},
	}
}
