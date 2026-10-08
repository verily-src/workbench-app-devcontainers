package seeder

import "fmt"

// ---------------------------------------------------------------------------
// Consent resource builders (Contract + Questionnaire + 2 CodeSystems)
//
// A **regulated** consent in the VerilyMe system is stored as 4 FHIR resources:
//
//   Contract          — the legal agreement (type="consent", references Questionnaire)
//   Questionnaire     — the UI layout (PDF + checkbox + signature + dialog modules)
//   Content CodeSystem — localized text for all UI elements + PDF GCS URL
//   Metadata CodeSystem — minimal metadata (title, supported languages)
//
// The consent-be dispatches to the regulated converter when
//   Contract.type.coding[0].code == "consent"
// and validates the Questionnaire profile is
//   verily-questionnaire-regulated-contract.
//
// The regulated consent renders (via SignView in the consent MFE):
//   1. PDF document (scrollable; gates viewConsent lifecycle RPC via pdfLoaded)
//   2. Checkbox reasons (agreement items the participant must check)
//   3. Full legal name text field + handwritten signature pad
//   4. Submit / Decline buttons
//   5. Disagree dialog  — shown when user taps "Decline"
//   6. Withdraw dialog  — shown when user taps "Withdraw" post-signing
// ---------------------------------------------------------------------------

const (
	consentVersion = "1"

	// FHIR profiles
	contractProfile               = "http://fhir.verily.com/StructureDefinition/verily-contract-definition"
	regulatedQuestionnaireProfile = "http://fhir.verily.com/StructureDefinition/verily-questionnaire-regulated-contract"
	consentContentCSProfile       = "http://fhir.verily.com/StructureDefinition/verily-consent-content-code-system"
	consentMetadataCSProfile      = "http://fhir.verily.com/StructureDefinition/verily-consent-metadata-code-system"

	// URL prefixes — consent-be searches by these + version
	contractURLPrefix          = "http://fhir.verily.com/Contract"
	consentQuestionnaireURLPfx = "http://fhir.verily.com/Questionnaire"
	consentContentCSURLPrefix  = "http://fhir.verily.com/CodeSystem/ConsentContent"
	consentMetadataCSURLPrefix = "http://fhir.verily.com/CodeSystem/ConsentMetadata"

	// NamingSystem identifiers
	contractIDSystem          = "http://fhir.verily.com/NamingSystem/consent-contract-id"
	consentQIDSystem          = "http://fhir.verily.com/NamingSystem/consent-questionnaire-id"
	consentContentCSIDSystem  = "http://fhir.verily.com/NamingSystem/consent-content-code-system-id"
	consentMetadataCSIDSystem = "http://fhir.verily.com/NamingSystem/consent-metadata-code-system-id"

	// Code systems used by the consent backend to identify module types
	consentRenderingTypeSystem = "http://fhir.verily.com/CodeSystem/consent-item-rendering-type"
	dialogRenderingTypeSystem  = "http://fhir.verily.com/CodeSystem/consent-dialog-rendering-type"
	contractTypeSystem         = "http://terminology.hl7.org/CodeSystem/contract-type"
	contractTermTypeSystem     = "http://fhir.verily.com/CodeSystem/verily-contract-term-type"
	contractActionTypeSystem   = "http://terminology.hl7.org/CodeSystem/contractaction"
	contractActionStatusSystem = "http://terminology.hl7.org/CodeSystem/contract-actionstatus"
	purposeOfUseSystem         = "http://terminology.hl7.org/ValueSet/v3-GeneralPurposeOfUse"

	// Fixed concept code for consent title
	consentTitleCode = "consent-title"
)

// consentResources holds all FHIR resources for a single consent step.
type consentResources struct {
	Contract           map[string]interface{}
	Questionnaire      map[string]interface{}
	ContentCodeSystem  map[string]interface{}
	MetadataCodeSystem map[string]interface{}

	ContentID           string // e.g. "my-program-20260227-welcome-consent-0"
	ContractURL         string // e.g. "http://fhir.verily.com/Contract/{ContentID}"
	QuestionnaireTempID string // urn:uuid:... (used for Contract.topicReference)
}

// buildConsentResources creates the 4 FHIR resources for a regulated consent step.
//
// pdfGCSURL is the GCS URL of the uploaded consent PDF document. When non-empty,
// a pdf-module is added to the Questionnaire (required for the consent MFE to
// render the consent and trigger the viewConsent lifecycle RPC).
//
// Questionnaire layout (with PDF):
//
//	cg0          group  pdf-module           — consent document PDF
//	  cg0-pa     attach                       └── PDF attachment (GCS URL in CodeSystem)
//	cg1          group  checkbox-module       — agreement checkboxes
//	  cg1-r1     bool                          ├── checkbox 1
//	  cg1-r2     bool                          └── checkbox 2
//	cg2          group  signature-module      — handwritten signature
//	  cg2-hw     attach                        └── signature pad (required=true)
//	dlg-disagree group  dialog-disagree-module — decline confirmation
//	  title / confirm-button / cancel-button
//	dlg-withdraw group  dialog-withdraw-module — post-sign withdrawal
//	  title / body / confirm-button / cancel-button
func buildConsentResources(bc *buildContext, step Step, stepIdx int, bundleName string, pdfGCSURL string) (*consentResources, error) {
	contentID := fmt.Sprintf("%s-%s-consent-%d", bc.tmpl.Name, bundleName, stepIdx)
	contentCSURL := fmt.Sprintf("%s/%s", consentContentCSURLPrefix, contentID)
	idValue := fmt.Sprintf("%s:%s", contentID, consentVersion)

	// --------------- Content CodeSystem concepts ---------------
	concepts := []map[string]interface{}{
		designationConcept(consentTitleCode, step.Title),
	}

	// --------------- Questionnaire items ---------------
	items := []map[string]interface{}{}
	moduleIdx := 0

	// ── PDF module (cg0) ── only when a PDF URL is provided
	if pdfGCSURL != "" {
		pdfGroupLinkID := fmt.Sprintf("cg%d", moduleIdx)
		pdfAttLinkID := fmt.Sprintf("%s-pa", pdfGroupLinkID)

		// The consent-be looks up the GCS URL via CodeSystem designation
		concepts = append(concepts, designationConcept(pdfAttLinkID, pdfGCSURL))

		items = append(items, map[string]interface{}{
			"type":   "group",
			"linkId": pdfGroupLinkID,
			"code": []map[string]interface{}{
				{"system": consentRenderingTypeSystem, "code": "pdf-module"},
			},
			"item": []map[string]interface{}{
				{
					"type":   "attachment",
					"linkId": pdfAttLinkID,
					"code": []map[string]interface{}{
						{"system": contentCSURL, "code": pdfAttLinkID, "version": consentVersion},
					},
				},
			},
		})
		moduleIdx++
	}

	// ── Checkbox module (cg1 when PDF present, cg0 otherwise) ──
	cbGroupLinkID := fmt.Sprintf("cg%d", moduleIdx)
	cbItems := []map[string]interface{}{}
	for i, cb := range step.Checkboxes {
		reasonLinkID := fmt.Sprintf("%s-r%d", cbGroupLinkID, i+1)
		concepts = append(concepts, designationConcept(reasonLinkID, cb.Text))
		cbItems = append(cbItems, map[string]interface{}{
			"type":     "boolean",
			"linkId":   reasonLinkID,
			"required": cb.Required,
			"code": []map[string]interface{}{
				{"system": contentCSURL, "code": reasonLinkID, "version": consentVersion},
			},
		})
	}
	items = append(items, map[string]interface{}{
		"type":   "group",
		"linkId": cbGroupLinkID,
		"code": []map[string]interface{}{
			{"system": consentRenderingTypeSystem, "code": "checkbox-module"},
		},
		"item": cbItems,
	})
	moduleIdx++

	// ── Signature module (cg2 when PDF present, cg1 otherwise) ──
	sigGroupLinkID := fmt.Sprintf("cg%d", moduleIdx)
	sigHWLinkID := fmt.Sprintf("%s-hw", sigGroupLinkID)
	items = append(items, map[string]interface{}{
		"type":   "group",
		"linkId": sigGroupLinkID,
		"code": []map[string]interface{}{
			{"system": consentRenderingTypeSystem, "code": "signature-module"},
		},
		"item": []map[string]interface{}{
			{
				"type":     "attachment",
				"linkId":   sigHWLinkID,
				"required": true, // enables handwritten signature in the renderer
			},
		},
	})
	moduleIdx++

	// ── Disagree dialog module ──
	concepts = append(concepts,
		designationConcept("dlg-disagree-title", "Are you sure?"),
		designationConcept("dlg-disagree-cfmbtn", "Yes, decline"),
		designationConcept("dlg-disagree-cxlbtn", "Go back"),
	)
	items = append(items, dialogModuleItem(
		"dlg-disagree",
		"dialog-disagree-module",
		contentCSURL,
		[]dialogNestedItem{
			{linkID: "dlg-disagree-title", dialogType: "title"},
			{linkID: "dlg-disagree-cfmbtn", dialogType: "confirm-button"},
			{linkID: "dlg-disagree-cxlbtn", dialogType: "cancel-button"},
		},
	))

	// ── Withdraw dialog module ──
	concepts = append(concepts,
		designationConcept("dlg-withdraw-title", "Withdraw Consent?"),
		designationConcept("dlg-withdraw-body", "If you withdraw, your previous responses will no longer be used."),
		designationConcept("dlg-withdraw-cfmbtn", "Withdraw"),
		designationConcept("dlg-withdraw-cxlbtn", "Cancel"),
	)
	items = append(items, dialogModuleItem(
		"dlg-withdraw",
		"dialog-withdraw-module",
		contentCSURL,
		[]dialogNestedItem{
			{linkID: "dlg-withdraw-title", dialogType: "title"},
			{linkID: "dlg-withdraw-body", dialogType: "body"},
			{linkID: "dlg-withdraw-cfmbtn", dialogType: "confirm-button"},
			{linkID: "dlg-withdraw-cxlbtn", dialogType: "cancel-button"},
		},
	))

	// --------------- Questionnaire ---------------
	qTempID := newTempID()
	questionnaire := map[string]interface{}{
		"resourceType": "Questionnaire",
		"meta":         buildOrgCompartmentMeta(bc, regulatedQuestionnaireProfile),
		"identifier": []map[string]interface{}{
			{"system": consentQIDSystem, "value": idValue},
		},
		"url":     fmt.Sprintf("%s/%s", consentQuestionnaireURLPfx, contentID),
		"version": consentVersion,
		"status":  "active",
		"code": []map[string]interface{}{
			{"system": contentCSURL, "code": consentTitleCode, "version": consentVersion},
		},
		"item": items,
	}

	// --------------- Content CodeSystem ---------------
	contentCS := map[string]interface{}{
		"resourceType": "CodeSystem",
		"meta":         buildOrgCompartmentMeta(bc, consentContentCSProfile),
		"identifier": []map[string]interface{}{
			{"system": consentContentCSIDSystem, "value": idValue},
		},
		"url":           contentCSURL,
		"version":       consentVersion,
		"status":        "active",
		"content":       "complete",
		"caseSensitive": true,
		"concept":       concepts,
	}

	// --------------- Metadata CodeSystem ---------------
	metadataCS := map[string]interface{}{
		"resourceType": "CodeSystem",
		"meta":         buildOrgCompartmentMeta(bc, consentMetadataCSProfile),
		"identifier": []map[string]interface{}{
			{"system": consentMetadataCSIDSystem, "value": idValue},
		},
		"url":           fmt.Sprintf("%s/%s", consentMetadataCSURLPrefix, contentID),
		"version":       consentVersion,
		"status":        "active",
		"content":       "complete",
		"caseSensitive": true,
		"concept": []map[string]interface{}{
			// The consent-be requires a "supported-languages" concept whose
			// designations enumerate the supported locales.  Without this,
			// getSupportedLanguagesFromConceptList returns an error and
			// ListConsentMetadata fails at runtime.
			supportedLanguagesConcept(),
			designationConcept(consentTitleCode, step.Title),
		},
	}

	// --------------- Contract ---------------
	terms := buildConsentTerms(step.Checkboxes, cbGroupLinkID)

	contract := map[string]interface{}{
		"resourceType": "Contract",
		"meta":         buildContractMeta(bc, contentID),
		"identifier": []map[string]interface{}{
			{"system": contractIDSystem, "value": idValue},
		},
		"url":     fmt.Sprintf("%s/%s", contractURLPrefix, contentID),
		"version": consentVersion,
		"name":    contentID,
		"type": map[string]interface{}{
			"coding": []map[string]interface{}{
				// "consent" routes to the regulated converter in consent-be.
				// ("privacy" would route to the agreement converter.)
				{"system": contractTypeSystem, "code": "consent"},
			},
		},
		"topicReference": map[string]interface{}{
			"reference": qTempID,
		},
		"term": terms,
	}

	return &consentResources{
		Contract:            contract,
		Questionnaire:       questionnaire,
		ContentCodeSystem:   contentCS,
		MetadataCodeSystem:  metadataCS,
		ContentID:           contentID,
		ContractURL:         fmt.Sprintf("%s/%s", contractURLPrefix, contentID),
		QuestionnaireTempID: qTempID,
	}, nil
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// buildContractMeta creates the meta block for a Contract.
// It adds both the org compartment extension AND the metadata identifier
// extension that links the Contract to its metadata CodeSystem.
func buildContractMeta(bc *buildContext, contentID string) map[string]interface{} {
	return map[string]interface{}{
		"profile": []string{contractProfile},
		"extension": []map[string]interface{}{
			{
				"url": orgCompartmentExtURL,
				"valueReference": map[string]interface{}{
					"reference": bc.orgCompartmentRef(),
				},
			},
			{
				"url":         consentMetadataCSIDSystem,
				"valueString": fmt.Sprintf("%s:%s", contentID, consentVersion),
			},
		},
	}
}

// dialogNestedItem defines a single nested item in a dialog module.
type dialogNestedItem struct {
	linkID     string // e.g. "dlg-disagree-title"
	dialogType string // e.g. "title", "body", "confirm-button", "cancel-button"
}

// dialogModuleItem creates a Questionnaire group item for a dialog module.
// The consent-be identifies dialog modules by the itemrenderingtype.System code,
// and looks up localized text for each nested item via its dialogrenderingtype.System
// code + Content CodeSystem code.
func dialogModuleItem(groupLinkID, renderingCode, contentCSURL string, nested []dialogNestedItem) map[string]interface{} {
	nestedItems := []map[string]interface{}{}
	for _, n := range nested {
		nestedItems = append(nestedItems, map[string]interface{}{
			"type":   "string",
			"linkId": n.linkID,
			"code": []map[string]interface{}{
				// First code: identifies the dialog rendering type (title, body, etc.)
				{"system": dialogRenderingTypeSystem, "code": n.dialogType},
				// Second code: references the Content CodeSystem for localized text lookup
				{"system": contentCSURL, "code": n.linkID, "version": consentVersion},
			},
		})
	}
	return map[string]interface{}{
		"type":   "group",
		"linkId": groupLinkID,
		"code": []map[string]interface{}{
			{"system": consentRenderingTypeSystem, "code": renderingCode},
		},
		"item": nestedItems,
	}
}

// supportedLanguagesConcept creates the "supported-languages" concept required
// by the consent-be's getLocaleMetadataFromConcept / getSupportedLanguagesFromConceptList.
// Each designation's language field declares a supported locale.  The value is
// the human-readable name (not used by code, but useful for debugging).
func supportedLanguagesConcept() map[string]interface{} {
	return map[string]interface{}{
		"code": "supported-languages",
		"designation": []map[string]interface{}{
			{"language": "en", "value": "English"},
			{"language": "en-US", "value": "English (US)"},
		},
	}
}

// designationConcept creates a CodeSystem concept with an English designation.
// The consent-be looks up designations by exact locale match (e.g. "en-US"),
// so we include both "en" and "en-US" to cover all lookup paths.
func designationConcept(code, text string) map[string]interface{} {
	return map[string]interface{}{
		"code": code,
		"designation": []map[string]interface{}{
			{"language": "en", "value": text},
			{"language": "en-US", "value": text},
		},
	}
}

// buildConsentTerms creates Contract.term entries from checkboxes.
// Each term maps 1:1 with a checkbox and uses the same linkId as the
// Questionnaire item so the consent-be can correlate them.
func buildConsentTerms(checkboxes []ConsentCheckbox, cbGroupLinkID string) []map[string]interface{} {
	terms := []map[string]interface{}{}
	for i, cb := range checkboxes {
		reasonLinkID := fmt.Sprintf("%s-r%d", cbGroupLinkID, i+1)
		terms = append(terms, map[string]interface{}{
			"identifier": map[string]interface{}{
				"value": reasonLinkID,
			},
			"text": cb.Text,
			// offer is required (1..1) by FHIR R4 Contract.term — empty object suffices.
			"offer": map[string]interface{}{},
			"type": map[string]interface{}{
				"coding": []map[string]interface{}{
					{"system": contractTermTypeSystem, "code": "participation"},
				},
			},
			"action": []map[string]interface{}{
				{
					"intent": map[string]interface{}{
						"coding": []map[string]interface{}{
							{"system": purposeOfUseSystem, "code": "TREAT"},
						},
					},
					"status": map[string]interface{}{
						"coding": []map[string]interface{}{
							{"system": contractActionStatusSystem, "code": "complete"},
						},
					},
					"type": map[string]interface{}{
						"coding": []map[string]interface{}{
							{"system": contractActionTypeSystem, "code": "action-a"},
						},
					},
				},
			},
		})
	}
	return terms
}
