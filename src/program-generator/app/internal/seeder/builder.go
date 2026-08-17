package seeder

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"time"

	"gopkg.in/yaml.v3"
)

// ---------------------------------------------------------------------------
// Builder — the main orchestrator
// ---------------------------------------------------------------------------

// Builder creates VerilyMe programs from templates.
type Builder struct {
	fhirClient *FHIRClient
	gcsClient  *GCSClient
	gcsBucket  string
}

// NewBuilder creates a Builder with the given FHIR client and optional GCS client.
// The GCS client and bucket are required for templates with consent steps (regulated
// consents need a PDF uploaded to GCS). Pass nil/empty for templates without consent.
func NewBuilder(fhirClient *FHIRClient, gcsClient *GCSClient, gcsBucket string) *Builder {
	return &Builder{
		fhirClient: fhirClient,
		gcsClient:  gcsClient,
		gcsBucket:  gcsBucket,
	}
}

// LoadTemplate reads and parses a YAML template file.
// It detects the format automatically:
//   - Node-tree format: root has node_type (e.g. ADMIN_PROGRAM). Converted to Template.
//   - Legacy format: root has name/org_id/bundles. Parsed directly into Template.
func LoadTemplate(path string) (*Template, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("reading template %s: %w", path, err)
	}

	// Detect format: node-tree format has `node_type` at the root level.
	var probe struct {
		NodeType string `yaml:"node_type"`
	}
	_ = yaml.Unmarshal(data, &probe) // best-effort; errors handled below

	if probe.NodeType != "" {
		// Node-tree format — unmarshal as a single ContentNode tree,
		// then convert to the internal Template representation.
		var root ContentNode
		if err := yaml.Unmarshal(data, &root); err != nil {
			return nil, fmt.Errorf("parsing node-tree template %s: %w", path, err)
		}
		tmpl, err := convertNodeTreeToTemplate(root)
		if err != nil {
			return nil, fmt.Errorf("converting node-tree template: %w", err)
		}
		if err := validateTemplate(tmpl); err != nil {
			return nil, fmt.Errorf("validating template: %w", err)
		}
		return tmpl, nil
	}

	// Legacy format — parse directly into Template.
	var tmpl Template
	if err := yaml.Unmarshal(data, &tmpl); err != nil {
		return nil, fmt.Errorf("parsing template %s: %w", path, err)
	}
	if err := validateTemplate(&tmpl); err != nil {
		return nil, fmt.Errorf("validating template: %w", err)
	}
	return &tmpl, nil
}

// LoadTemplateFromBytes parses a YAML template from raw bytes.
// Like LoadTemplate, it auto-detects the format (node-tree vs legacy).
func LoadTemplateFromBytes(data []byte) (*Template, error) {
	// Detect format: node-tree format has `node_type` at the root level.
	var probe struct {
		NodeType string `yaml:"node_type"`
	}
	_ = yaml.Unmarshal(data, &probe)

	if probe.NodeType != "" {
		var root ContentNode
		if err := yaml.Unmarshal(data, &root); err != nil {
			return nil, fmt.Errorf("parsing node-tree template: %w", err)
		}
		tmpl, err := convertNodeTreeToTemplate(root)
		if err != nil {
			return nil, fmt.Errorf("converting node-tree template: %w", err)
		}
		if err := validateTemplate(tmpl); err != nil {
			return nil, fmt.Errorf("validating template: %w", err)
		}
		return tmpl, nil
	}

	var tmpl Template
	if err := yaml.Unmarshal(data, &tmpl); err != nil {
		return nil, fmt.Errorf("parsing template: %w", err)
	}
	if err := validateTemplate(&tmpl); err != nil {
		return nil, fmt.Errorf("validating template: %w", err)
	}
	return &tmpl, nil
}

// validateTemplate performs basic validation on a template.
func validateTemplate(tmpl *Template) error {
	if tmpl.Name == "" {
		return fmt.Errorf("name is required")
	}
	if tmpl.OrgID == "" {
		return fmt.Errorf("org_id is required")
	}
	if tmpl.Version == "" {
		tmpl.Version = "v1"
	}
	if tmpl.EnvBaseURL == "" {
		tmpl.EnvBaseURL = "https://dev-stable.one.verily.com"
	}
	if len(tmpl.Bundles) == 0 {
		return fmt.Errorf("at least one bundle is required")
	}
	for i, b := range tmpl.Bundles {
		if b.Name == "" {
			return fmt.Errorf("bundle %d: name is required", i)
		}
		if len(b.Steps) == 0 {
			return fmt.Errorf("bundle %q: at least one step is required", b.Name)
		}
		for j, s := range b.Steps {
			switch s.Type {
			case "info", "survey", "consent":
				// valid
			default:
				return fmt.Errorf("bundle %q step %d: unsupported type %q (supported: info, survey, consent)", b.Name, j, s.Type)
			}
			if s.Type == "info" && s.BodyHTML != "" && len(s.Nodes) > 0 {
				return fmt.Errorf("bundle %q step %d: body_html and nodes are mutually exclusive — use one or the other", b.Name, j)
			}
			if s.Type == "consent" && len(s.Checkboxes) == 0 {
				return fmt.Errorf("bundle %q step %d (consent): at least one checkbox is required", b.Name, j)
			}
		}
	}
	return nil
}

// TemplateHasConsentSteps returns true if any bundle in the template has a consent step.
func TemplateHasConsentSteps(tmpl *Template) bool {
	for _, b := range tmpl.Bundles {
		for _, s := range b.Steps {
			if s.Type == "consent" {
				return true
			}
		}
	}
	return false
}

// Build creates all FHIR resources for the template and returns the program output.
// Each run generates a unique suffix appended to the program name, making the
// canonical URLs unique so the tool can be run multiple times with the same template.
func (b *Builder) Build(ctx context.Context, tmpl *Template) (*ProgramOutput, error) {
	// Append a unique suffix so each run creates distinct FHIR resources.
	// Format: name-YYYYMMDD-HHMMSS (human-readable, sortable, unique per second)
	suffix := time.Now().Format("20060102-150405")
	tmplCopy := *tmpl
	tmplCopy.Name = tmpl.Name + "-" + suffix
	fmt.Printf("Program name (with run suffix): %s\n", tmplCopy.Name)

	bc := newBuildContext(tmplCopy)

	// Phase 1: Build all content resources (DocumentReferences, Questionnaires, etc.)
	childPlanDefs, err := b.buildBundles(ctx, bc)
	if err != nil {
		return nil, fmt.Errorf("building bundles: %w", err)
	}

	// Phase 1.5: Check if the Organization already exists in the FHIR store.
	// If it does, we must NOT include it in the transaction — a PUT would replace
	// the entire resource, destroying its verily-part-of-organization hierarchy
	// that other teams depend on. We only create it in fresh stores (dev-hermetic).
	//
	// Default to true (safe): if the check fails we assume the org exists so we
	// never accidentally overwrite a shared org's hierarchy.  The worst case of a
	// false-positive is that the transaction fails with an org-compartment
	// reference error in a truly fresh store, which is easy to diagnose and retry.
	orgExists := true
	if b.fhirClient != nil {
		exists, err := b.fhirClient.ResourceExists(ctx, "Organization", bc.tmpl.OrgID)
		if err != nil {
			fmt.Fprintf(os.Stderr, "⚠️  Could not check if Organization %s exists (assuming exists to avoid destructive PUT): %v\n", bc.tmpl.OrgID, err)
		} else {
			orgExists = exists
		}
	}

	// Phase 2: Build workflow structure
	b.buildWorkflowStructure(bc, childPlanDefs, orgExists)

	// Phase 3: Post the transaction bundle to FHIR
	fmt.Printf("Posting FHIR transaction bundle with %d entries...\n", len(bc.entries))
	resp, err := b.fhirClient.PostTransaction(ctx, bc.entries)
	if err != nil {
		return nil, fmt.Errorf("posting FHIR transaction: %w", err)
	}

	// Phase 4: Extract IDs from response and build output
	return b.buildOutput(bc, resp)
}

// childPlanDefInfo tracks a child PlanDefinition's canonical URL and temp ID.
type childPlanDefInfo struct {
	canonicalURL string
	tempID       string
}

// buildBundles processes all bundles in the template and returns child PlanDef info.
func (b *Builder) buildBundles(ctx context.Context, bc *buildContext) ([]childPlanDefInfo, error) {
	var childPlanDefs []childPlanDefInfo

	for bundleIdx, bundle := range bc.tmpl.Bundles {
		info, err := b.buildBundle(ctx, bc, bundle, bundleIdx)
		if err != nil {
			return nil, fmt.Errorf("bundle %q: %w", bundle.Name, err)
		}
		childPlanDefs = append(childPlanDefs, *info)
	}

	return childPlanDefs, nil
}

// buildBundle processes a single bundle and returns its child PlanDef info.
func (b *Builder) buildBundle(ctx context.Context, bc *buildContext, bundle Bundle, bundleIdx int) (*childPlanDefInfo, error) {
	// 1. Create the card DocumentReference
	cardTempID, cardRes := buildCardDocumentReference(bc, bundle, bundleIdx)
	bc.addEntry(cardTempID, "DocumentReference", cardRes)
	bc.outputResources = append(bc.outputResources, ResourceRef{
		Type: "DocumentReference",
		Name: fmt.Sprintf("%s-card", bundle.Name),
	})

	// 1b. Create the companion CodeSystem for the card (provides localized title/description)
	cardCSTempID, cardCSRes := buildCardCodeSystem(bc, bundle, bundleIdx)
	bc.addEntry(cardCSTempID, "CodeSystem", cardCSRes)
	bc.outputResources = append(bc.outputResources, ResourceRef{
		Type: "CodeSystem",
		Name: fmt.Sprintf("%s-card-translations", bundle.Name),
	})

	// 2. Process each step
	var stepActions []bundleStepAction
	for stepIdx, step := range bundle.Steps {
		action, err := b.buildStep(ctx, bc, step, stepIdx, bundle.Name)
		if err != nil {
			return nil, fmt.Errorf("step %d (%s): %w", stepIdx, step.Type, err)
		}
		stepActions = append(stepActions, *action)
	}

	// 3. Create the child PlanDefinition
	childTempID, childRes := buildChildPlanDefinition(bc, bundle, bundleIdx, cardTempID, stepActions)
	bc.addEntry(childTempID, "PlanDefinition", childRes)

	childCanonical := canonicalURL("standalone-seeding", "PlanDefinition", fmt.Sprintf("%s-%s", bc.tmpl.Name, bundle.Name))
	bc.outputResources = append(bc.outputResources, ResourceRef{
		Type: "PlanDefinition",
		Name: fmt.Sprintf("%s (bundle)", bundle.Name),
	})

	return &childPlanDefInfo{
		canonicalURL: childCanonical + "|" + bc.tmpl.Version,
		tempID:       childTempID,
	}, nil
}

// buildStep processes a single step and returns the action info for the PlanDefinition.
func (b *Builder) buildStep(ctx context.Context, bc *buildContext, step Step, stepIdx int, bundleName string) (*bundleStepAction, error) {
	switch step.Type {
	case "info":
		return b.buildInfoStep(bc, step, stepIdx, bundleName)
	case "survey":
		return b.buildSurveyStep(bc, step, stepIdx, bundleName)
	case "consent":
		return b.buildConsentStep(ctx, bc, step, stepIdx, bundleName)
	default:
		return nil, fmt.Errorf("unsupported step type: %s", step.Type)
	}
}

// buildInfoStep creates all resources for an info step.
func (b *Builder) buildInfoStep(bc *buildContext, step Step, stepIdx int, bundleName string) (*bundleStepAction, error) {
	// Create DocumentReference with proto-encoded content
	docRefTempID, docRefRes, err := buildInfoDocumentReference(bc, step, stepIdx, bundleName)
	if err != nil {
		return nil, fmt.Errorf("building DocumentReference: %w", err)
	}
	bc.addEntry(docRefTempID, "DocumentReference", docRefRes)

	actionID := fmt.Sprintf("%s-%s-info-%d", bc.tmpl.Name, bundleName, stepIdx)

	// Create ActivityDefinition referencing the DocumentReference
	adTempID, adRes := buildActivityDefinition(bc, actionID, docRefTempID)
	bc.addEntry(adTempID, "ActivityDefinition", adRes)

	adCanonical := canonicalURL("standalone-seeding", "ActivityDefinition", actionID)

	bc.outputResources = append(bc.outputResources, ResourceRef{
		Type: "DocumentReference",
		Name: fmt.Sprintf("%s-info-%d", bundleName, stepIdx),
	})
	bc.outputResources = append(bc.outputResources, ResourceRef{
		Type: "ActivityDefinition",
		Name: fmt.Sprintf("%s-info-%d", bundleName, stepIdx),
	})

	contentOID := fmt.Sprintf("%s-%s-info-%d", bc.tmpl.Name, bundleName, stepIdx)

	return &bundleStepAction{
		StepType:            "info",
		ActionID:            actionID,
		DefinitionCanonical: adCanonical + "|" + bc.tmpl.Version,
		ContentOID:          contentOID,
	}, nil
}

// buildSurveyStep creates all resources for a survey step.
func (b *Builder) buildSurveyStep(bc *buildContext, step Step, stepIdx int, bundleName string) (*bundleStepAction, error) {
	// Build survey FHIR resources
	sr, err := buildSurveyResources(bc, step, stepIdx, bundleName)
	if err != nil {
		return nil, fmt.Errorf("building survey resources: %w", err)
	}

	// Add Questionnaire
	qTempID := newTempID()
	bc.addEntry(qTempID, "Questionnaire", sr.Questionnaire)

	// Add CodeSystem
	csTempID := newTempID()
	bc.addEntry(csTempID, "CodeSystem", sr.CodeSystem)

	// Add ValueSets
	for _, vs := range sr.ValueSets {
		vsTempID := newTempID()
		bc.addEntry(vsTempID, "ValueSet", vs)
	}

	actionID := fmt.Sprintf("%s-%s-survey-%d", bc.tmpl.Name, bundleName, stepIdx)
	contentOID := actionID

	bc.outputResources = append(bc.outputResources, ResourceRef{
		Type: "Questionnaire",
		Name: fmt.Sprintf("%s-survey-%d", bundleName, stepIdx),
	})

	return &bundleStepAction{
		StepType:            "survey",
		ActionID:            actionID,
		DefinitionCanonical: sr.QuestionnaireURL + "|" + bc.tmpl.Version,
		ContentOID:          contentOID,
	}, nil
}

// buildConsentStep creates all resources for a consent step:
// Contract, Questionnaire, Content CodeSystem, Metadata CodeSystem, and ActivityDefinition.
// If a GCS client is configured, it also generates and uploads a consent PDF.
func (b *Builder) buildConsentStep(ctx context.Context, bc *buildContext, step Step, stepIdx int, bundleName string) (*bundleStepAction, error) {
	// Generate and upload consent PDF (if GCS is configured)
	var pdfGCSURL string
	if b.gcsClient != nil && b.gcsBucket != "" {
		// Collect checkbox texts for the PDF
		checkboxTexts := make([]string, len(step.Checkboxes))
		for i, cb := range step.Checkboxes {
			checkboxTexts[i] = cb.Text
		}

		// Generate PDF document
		pdfBytes := generateConsentPDF(step.Title, checkboxTexts)
		fmt.Fprintf(os.Stderr, "  Generated consent PDF (%d bytes)\n", len(pdfBytes))

		// Upload to GCS
		objectPath := fmt.Sprintf("standalone-seeding/%s/%s-consent-%d.pdf", bc.tmpl.Name, bundleName, stepIdx)
		var err error
		pdfGCSURL, err = b.gcsClient.UploadPDF(ctx, b.gcsBucket, objectPath, pdfBytes)
		if err != nil {
			return nil, fmt.Errorf("uploading consent PDF: %w", err)
		}
		fmt.Fprintf(os.Stderr, "  Uploaded consent PDF to %s\n", pdfGCSURL)
	} else {
		// Dry-run or no GCS: use a placeholder URL so the FHIR structure is complete.
		// The consent-be will fail to fetch this at runtime, but the structure is valid.
		pdfGCSURL = "https://storage.googleapis.com/PLACEHOLDER_BUCKET/consent-placeholder.pdf"
		fmt.Fprintf(os.Stderr, "  Using placeholder PDF URL (no GCS bucket configured)\n")
	}

	cr, err := buildConsentResources(bc, step, stepIdx, bundleName, pdfGCSURL)
	if err != nil {
		return nil, fmt.Errorf("building consent resources: %w", err)
	}

	// Add Questionnaire (referenced by Contract.topicReference)
	bc.addEntry(cr.QuestionnaireTempID, "Questionnaire", cr.Questionnaire)

	// Add Content CodeSystem
	bc.addEntry(newTempID(), "CodeSystem", cr.ContentCodeSystem)

	// Add Metadata CodeSystem
	bc.addEntry(newTempID(), "CodeSystem", cr.MetadataCodeSystem)

	// Add Contract (references Questionnaire via topicReference temp ID)
	bc.addEntry(newTempID(), "Contract", cr.Contract)

	actionID := fmt.Sprintf("%s-%s-consent-%d", bc.tmpl.Name, bundleName, stepIdx)

	// Create ActivityDefinition with Contract canonical
	contractCanonical := cr.ContractURL + "|" + consentVersion
	adTempID, adRes := buildConsentActivityDefinition(bc, actionID, contractCanonical)
	bc.addEntry(adTempID, "ActivityDefinition", adRes)

	adCanonical := canonicalURL("standalone-seeding", "ActivityDefinition", actionID)

	bc.outputResources = append(bc.outputResources,
		ResourceRef{Type: "Questionnaire", Name: fmt.Sprintf("%s-consent-%d-questionnaire", bundleName, stepIdx)},
		ResourceRef{Type: "CodeSystem", Name: fmt.Sprintf("%s-consent-%d-content-cs", bundleName, stepIdx)},
		ResourceRef{Type: "CodeSystem", Name: fmt.Sprintf("%s-consent-%d-metadata-cs", bundleName, stepIdx)},
		ResourceRef{Type: "Contract", Name: fmt.Sprintf("%s-consent-%d-contract", bundleName, stepIdx)},
		ResourceRef{Type: "ActivityDefinition", Name: fmt.Sprintf("%s-consent-%d-ad", bundleName, stepIdx)},
	)

	return &bundleStepAction{
		StepType:            "consent",
		ActionID:            actionID,
		DefinitionCanonical: adCanonical + "|" + bc.tmpl.Version,
		ContentOID:          cr.ContentID,
	}, nil
}

// buildWorkflowStructure creates the Organization, Group, root PlanDefinition, and HealthcareService.
// orgExists indicates whether the Organization already exists in the FHIR store (checked
// by the caller via a GET). When true the Organization entry is skipped to avoid
// overwriting its verily-part-of-organization hierarchy.
func (b *Builder) buildWorkflowStructure(bc *buildContext, childPlanDefs []childPlanDefInfo, orgExists bool) {
	// Organization — only include if it doesn't already exist in the FHIR store.
	// Uses PUT Organization/<id> so the org is created at an exact, known ID
	// (required for org-compartment references in other resources).
	// In shared environments (dev-stable) the org already exists with a real
	// verily-part-of-organization hierarchy — a PUT would destroy it.
	if orgExists {
		fmt.Printf("  Organization %s already exists — skipping (preserving existing hierarchy)\n", bc.tmpl.OrgID)
	} else {
		orgRes := buildOrganization(bc)
		orgTempID := newTempID()
		bc.addUpsertEntry(orgTempID, "Organization/"+bc.tmpl.OrgID, orgRes)
		bc.outputResources = append(bc.outputResources, ResourceRef{
			Type: "Organization",
			Name: bc.tmpl.OrgID,
		})
		fmt.Printf("  Organization %s (create via PUT)\n", bc.tmpl.OrgID)
	}

	// Group
	groupRes := buildGroup(bc)
	bc.addEntry(bc.groupTempID, "Group", groupRes)
	bc.outputResources = append(bc.outputResources, ResourceRef{
		Type: "Group",
		Name: "applicability-group",
	})

	// Root PlanDefinition
	childCanonicals := make([]string, len(childPlanDefs))
	for i, cp := range childPlanDefs {
		childCanonicals[i] = cp.canonicalURL
	}
	rootPDRes := buildRootPlanDefinition(bc, childCanonicals)
	bc.addEntry(bc.rootPlanDefTempID, "PlanDefinition", rootPDRes)
	bc.outputResources = append(bc.outputResources, ResourceRef{
		Type: "PlanDefinition",
		Name: "root-care-pathway",
	})

	// HealthcareService
	rootCanonical := canonicalURL("standalone-seeding", "PlanDefinition", bc.tmpl.Name) + "|" + bc.tmpl.Version
	hcsRes := buildHealthcareService(bc, rootCanonical)
	bc.addEntry(bc.hcsTempID, "HealthcareService", hcsRes)
	bc.outputResources = append(bc.outputResources, ResourceRef{
		Type: "HealthcareService",
		Name: bc.tmpl.Name,
	})
}

// buildOutput extracts resource IDs from the transaction response.
func (b *Builder) buildOutput(bc *buildContext, resp *TransactionResponse) (*ProgramOutput, error) {
	output := &ProgramOutput{
		Name:    bc.tmpl.Name,
		OrgID:   bc.tmpl.OrgID,
		Version: bc.tmpl.Version,
	}

	// Map temp IDs to actual IDs using entry order (entries and response are in same order)
	tempToActual := make(map[string]string)
	for i, entry := range bc.entries {
		if i < len(resp.Entries) {
			respEntry := resp.Entries[i]
			if entry.FullURL != "" {
				tempToActual[entry.FullURL] = respEntry.ID
			}
			// Update output resources with actual IDs
			if i < len(bc.outputResources) {
				bc.outputResources[i].ID = respEntry.ID
			}
		}
	}

	// The output resources were collected in order, but we added them during build
	// while entries were also added. We need to match them correctly.
	// Actually, outputResources were appended in non-1:1 correspondence with entries.
	// Let's just use the known temp IDs for the important ones.
	output.PlanDefinitionID = tempToActual[bc.rootPlanDefTempID]
	output.GroupID = tempToActual[bc.groupTempID]
	output.HealthcareServiceID = tempToActual[bc.hcsTempID]

	// Collect all resources from the response
	output.Resources = []ResourceRef{}
	for i, entry := range resp.Entries {
		ref := ResourceRef{
			Type: entry.ResourceType,
			ID:   entry.ID,
		}
		// Try to find the corresponding name from our output resources
		// We need to match by position in the entries list
		for _, or := range bc.outputResources {
			if or.Type == entry.ResourceType && or.ID == "" {
				ref.Name = or.Name
				or.ID = entry.ID // mark as used
				break
			}
		}
		// Fallback: use entry index
		if ref.Name == "" && i < len(bc.entries) {
			ref.Name = fmt.Sprintf("entry-%d", i)
		}
		output.Resources = append(output.Resources, ref)
	}

	return output, nil
}

// LoadPreviousOutput reads a previously saved program config JSON and returns
// the output (if any). Returns nil if the file doesn't exist or can't be parsed.
func LoadPreviousOutput(path string) *ProgramOutput {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var prev ProgramOutput
	if err := json.Unmarshal(data, &prev); err != nil {
		return nil
	}
	return &prev
}

// RetireOldPlanDefinitions patches all PlanDefinitions from a previous run to
// "retired" status via the FHIR API. This is critical because the workflow engine
// applies ALL active PlanDefinitions whose Group applicability matches the patient,
// not just registered ones. Without retirement, every old program run would
// keep applying to new patients.
func (b *Builder) RetireOldPlanDefinitions(ctx context.Context, prev *ProgramOutput) error {
	if b.fhirClient == nil || prev == nil {
		return nil
	}

	planDefIDs := []string{}
	for _, r := range prev.Resources {
		if r.Type == "PlanDefinition" {
			planDefIDs = append(planDefIDs, r.ID)
		}
	}

	if len(planDefIDs) == 0 {
		return nil
	}

	fmt.Fprintf(os.Stderr, "Retiring %d PlanDefinitions from previous run (best-effort, 404s are normal on fresh stores)...\n", len(planDefIDs))
	for _, id := range planDefIDs {
		if err := b.fhirClient.PatchResourceStatus(ctx, "PlanDefinition", id, "retired"); err != nil {
			fmt.Fprintf(os.Stderr, "  ℹ️  PlanDefinition/%s not found (already gone or different store) — skipping\n", id)
			// Non-fatal — resource may not exist on a fresh ephemeral store
		} else {
			fmt.Fprintf(os.Stderr, "  ✅ Retired PlanDefinition/%s\n", id)
		}
	}
	return nil
}

// DryRun builds the FHIR transaction bundle without posting it.
// Returns the bundle as a map suitable for JSON marshaling.
func (b *Builder) DryRun(ctx context.Context, tmpl *Template) (map[string]interface{}, error) {
	bc := newBuildContext(*tmpl)

	// Phase 1: Build all content resources
	childPlanDefs, err := b.buildBundles(ctx, bc)
	if err != nil {
		return nil, fmt.Errorf("building bundles: %w", err)
	}

	// Phase 2: Build workflow structure (dry-run: always include Organization)
	b.buildWorkflowStructure(bc, childPlanDefs, false)

	// Return as transaction bundle
	return map[string]interface{}{
		"resourceType": "Bundle",
		"type":         "transaction",
		"entry":        bc.entries,
	}, nil
}

// SaveOutput writes the program output as JSON to a file.
func SaveOutput(output *ProgramOutput, path string) error {
	data, err := json.MarshalIndent(output, "", "  ")
	if err != nil {
		return fmt.Errorf("marshaling output: %w", err)
	}
	if err := os.WriteFile(path, data, 0644); err != nil {
		return fmt.Errorf("writing output to %s: %w", path, err)
	}
	return nil
}

// ---------------------------------------------------------------------------
// Node-tree format → Template conversion
// ---------------------------------------------------------------------------
//
// When the YAML root is an ADMIN_PROGRAM node, we convert the entire node tree
// into the internal Template/Bundle/Step/Question/ConsentCheckbox structs so
// that the downstream FHIR builders work unchanged. This is the "facade"
// approach: the DSL declares richer structure than the converters consume,
// and the conversion layer bridges the gap.
//
// What IS extracted:
//   - Program metadata (name, org_id, version, env_base_url)
//   - Bundle name and card (title, description)
//   - Info step content nodes (from CMPT_VERTICAL_CONTAINER inside CMPT_BUNDLE_LAYOUT)
//   - Survey questions (CMPT_CHOICE_QUESTION, CMPT_FREE_TEXT_QUESTION with basic props)
//   - Compound numeric questions (CMPT_QUESTION_GROUP > CMPT_HORIZONTAL_CONTAINER)
//   - Numeric constraints (PROP_CONSTRAINTS > PROP_NUMERIC > PROP_MIN_VALUE / PROP_MAX_VALUE)
//   - Unit info (PROP_UNITS > PROP_UNIT > PROP_UNIT_DISPLAY / PROP_UNIT_SYSTEM / PROP_UNIT_CODE)
//   - Consent checkboxes (CMPT_CHOICE_QUESTION with PROP_BOOLEAN in ADMIN_CONSENT_SIGN)
//
// What is DECLARED in the DSL but NOT yet leveraged by the converter:
//   - CMPT_BUNDLE_LAYOUT / CMPT_HEADER / CMPT_FOOTER / CMPT_CTA_BUTTON chrome
//   - CMPT_EXIT_BUTTON / ACTN_ON_CLICK behavior
//   - CMPT_PAGE grouping (page boundaries for navigation)
//   - CMPT_DIALOG content (dialog text is currently hardcoded in consent.go)
//   - ADMIN_CONSENT_REVIEW (the review flow's nodes are declared but not consumed)
//   - CMPT_PDF_VIEWER, CMPT_FREE_TEXT_QUESTION with PROP_SIGNATURE (consent modules)
//   - PROP_ALLOW_DECIMAL / PROP_MAX_DECIMAL_PLACES (decimal/quantity distinction)
//
// These are all faithfully declared in the YAML for when a richer converter is built.

// convertNodeTreeToTemplate converts an ADMIN_PROGRAM root node into a Template.
func convertNodeTreeToTemplate(root ContentNode) (*Template, error) {
	if root.NodeType != "ADMIN_PROGRAM" {
		return nil, fmt.Errorf("root node must be ADMIN_PROGRAM, got %q", root.NodeType)
	}
	tmpl := &Template{
		Name: root.ValueString,
	}
	for _, child := range root.Nodes {
		switch child.NodeType {
		case "PROP_ORG_ID":
			tmpl.OrgID = child.ValueString
		case "PROP_VERSION":
			tmpl.Version = child.ValueString
		case "PROP_ENV_BASE_URL":
			tmpl.EnvBaseURL = child.ValueString
		case "ADMIN_BUNDLE":
			bundle, err := extractBundle(child)
			if err != nil {
				return nil, fmt.Errorf("bundle %q: %w", child.ValueString, err)
			}
			tmpl.Bundles = append(tmpl.Bundles, *bundle)
		}
	}
	return tmpl, nil
}

// extractBundle converts an ADMIN_BUNDLE node into a Bundle.
func extractBundle(node ContentNode) (*Bundle, error) {
	bundle := &Bundle{Name: node.ValueString}
	for _, child := range node.Nodes {
		switch child.NodeType {
		case "ADMIN_CARD":
			bundle.Card = extractCard(child)
		case "ADMIN_INFO_STEP":
			step := extractInfoStep(child)
			bundle.Steps = append(bundle.Steps, *step)
		case "ADMIN_SURVEY_STEP":
			step, err := extractSurveyStep(child)
			if err != nil {
				return nil, err
			}
			bundle.Steps = append(bundle.Steps, *step)
		case "ADMIN_CONSENT_STEP":
			step, err := extractConsentStep(child)
			if err != nil {
				return nil, err
			}
			bundle.Steps = append(bundle.Steps, *step)
		}
	}
	return bundle, nil
}

// extractCard converts an ADMIN_CARD node into a Card.
func extractCard(node ContentNode) Card {
	var card Card
	for _, child := range node.Nodes {
		switch child.NodeType {
		case "PROP_TITLE":
			card.Title = child.ValueString
		case "PROP_DESCRIPTION":
			card.Description = child.ValueString
		}
	}
	return card
}

// extractInfoStep converts an ADMIN_INFO_STEP node into an info Step.
// It finds the CMPT_VERTICAL_CONTAINER inside CMPT_BUNDLE_LAYOUT and
// extracts its children as the content nodes for the DocumentReference.
//
// NOTE: CMPT_BUNDLE_LAYOUT, CMPT_HEADER, CMPT_FOOTER, CMPT_EXIT_BUTTON,
// CMPT_CTA_BUTTON, and ACTN_ON_CLICK are declared in the DSL but not
// stored in the DocumentReference. The MFE handles these at runtime via
// the template/route system described in the design doc.
func extractInfoStep(node ContentNode) *Step {
	step := &Step{
		Type:  "info",
		Title: node.ValueString,
	}
	// Find CMPT_BUNDLE_LAYOUT > CMPT_VERTICAL_CONTAINER and extract its children.
	bl := findChild(node, "CMPT_BUNDLE_LAYOUT")
	if bl != nil {
		vc := findChild(*bl, "CMPT_VERTICAL_CONTAINER")
		if vc != nil {
			step.Nodes = vc.Nodes
		}
	}
	return step
}

// extractSurveyStep converts an ADMIN_SURVEY_STEP node into a survey Step.
// It recursively walks the tree and collects all CMPT_CHOICE_QUESTION and
// CMPT_FREE_TEXT_QUESTION nodes into flat Question structs.
//
// NOTE: The tree structure (CMPT_SURVEY_CONTEXT, CMPT_BUNDLE_LAYOUT,
// CMPT_PAGE, CMPT_QUESTION_GROUP, CMPT_HORIZONTAL_CONTAINER, CMPT_TITLE,
// CMPT_HEADER, CMPT_FOOTER, CMPT_CTA_BUTTON, ACTN_ON_CLICK) is declared
// in the DSL but the converter flattens all questions into a linear
// Questionnaire.item[]. A richer converter could use page/group structure
// for nested items and PROP_CONSTRAINTS for FHIR extensions.
func extractSurveyStep(node ContentNode) (*Step, error) {
	step := &Step{
		Type:  "survey",
		Title: node.ValueString,
	}
	step.Questions = collectQuestions(node)
	if len(step.Questions) == 0 {
		return nil, fmt.Errorf("survey step %q has no questions in node tree", node.ValueString)
	}
	return step, nil
}

// extractConsentStep converts an ADMIN_CONSENT_STEP node into a consent Step.
// It finds ADMIN_CONSENT_SIGN and collects CMPT_CHOICE_QUESTION nodes with
// PROP_BOOLEAN children as consent checkboxes.
//
// NOTE: The DSL also declares ADMIN_CONSENT_REVIEW (withdraw flow),
// CMPT_DIALOG (dialog text/buttons), CMPT_PDF_VIEWER, CMPT_FREE_TEXT_QUESTION
// with PROP_SIGNATURE (signature module), and CMPT_HEADER/CMPT_FOOTER chrome.
// These are not yet consumed — the consent builder uses hardcoded defaults for
// dialog text, and the signature/PDF modules are generated automatically.
// A richer converter could read dialog text from CMPT_DIALOG nodes to customize
// the FHIR CodeSystem concepts.
func extractConsentStep(node ContentNode) (*Step, error) {
	step := &Step{
		Type:  "consent",
		Title: node.ValueString,
	}
	// Find ADMIN_CONSENT_SIGN and collect boolean choice questions as checkboxes.
	sign := findChild(node, "ADMIN_CONSENT_SIGN")
	if sign != nil {
		step.Checkboxes = collectCheckboxes(*sign)
	}
	if len(step.Checkboxes) == 0 {
		return nil, fmt.Errorf("consent step %q: no checkboxes found in ADMIN_CONSENT_SIGN", node.ValueString)
	}
	return step, nil
}

// ---------------------------------------------------------------------------
// Node-tree traversal helpers
// ---------------------------------------------------------------------------

// collectQuestions recursively collects all question nodes from a tree,
// converting each CMPT_CHOICE_QUESTION or CMPT_FREE_TEXT_QUESTION into
// a Question struct. CMPT_QUESTION_GROUP nodes are inspected to detect
// compound questions (multiple sub-questions inside a CMPT_HORIZONTAL_CONTAINER).
//
// Compound numeric detection: when a CMPT_QUESTION_GROUP contains a
// CMPT_HORIZONTAL_CONTAINER with exactly 2 CMPT_FREE_TEXT_QUESTION children
// that have numeric constraints, the group is emitted as a single Question
// with Type "compound_numeric" and SubQuestions. This matches the survey-be's
// QuestionnaireItemTypeCode_QUESTION structure with /field1 and /field2 linkIds.
func collectQuestions(node ContentNode) []Question {
	var questions []Question
	for _, child := range node.Nodes {
		switch child.NodeType {
		case "CMPT_QUESTION_GROUP":
			// Check for compound question: a group containing a CMPT_HORIZONTAL_CONTAINER
			// with multiple question children.
			if compound := tryExtractCompoundNumeric(child); compound != nil {
				questions = append(questions, *compound)
			} else {
				// Single-question group or unknown layout — recurse.
				questions = append(questions, collectQuestions(child)...)
			}
		case "CMPT_CHOICE_QUESTION":
			questions = append(questions, extractChoiceQuestion(child))
		case "CMPT_FREE_TEXT_QUESTION":
			// Skip signature questions (those are consent, not survey).
			if !hasChild(child, "PROP_SIGNATURE") {
				questions = append(questions, extractFreeTextQuestion(child))
			}
		default:
			// Recurse into structural nodes: CMPT_SURVEY_CONTEXT,
			// CMPT_BUNDLE_LAYOUT, CMPT_PAGE, CMPT_HEADER, CMPT_FOOTER, etc.
			questions = append(questions, collectQuestions(child)...)
		}
	}
	return questions
}

// tryExtractCompoundNumeric checks if a CMPT_QUESTION_GROUP represents a
// compound numeric question (e.g., blood pressure with systolic/diastolic).
//
// It returns a compound Question if the group has:
//   - A CMPT_HORIZONTAL_CONTAINER with 2+ CMPT_FREE_TEXT_QUESTION children
//   - At least one sub-question has numeric constraints (PROP_CONSTRAINTS > PROP_NUMERIC)
//
// Returns nil if this is a regular single-question group.
func tryExtractCompoundNumeric(group ContentNode) *Question {
	// Find CMPT_HORIZONTAL_CONTAINER in the group.
	hc := findChild(group, "CMPT_HORIZONTAL_CONTAINER")
	if hc == nil {
		return nil
	}

	// Collect free-text questions from the horizontal container.
	var subs []Question
	for _, child := range hc.Nodes {
		if child.NodeType == "CMPT_FREE_TEXT_QUESTION" && !hasChild(child, "PROP_SIGNATURE") {
			subs = append(subs, extractFreeTextQuestion(child))
		}
	}
	if len(subs) < 2 {
		return nil
	}

	// Extract group title from CMPT_TITLE > CMPT_RICH_TEXT.
	var groupTitle string
	title := findChild(group, "CMPT_TITLE")
	if title != nil {
		rt := findChild(*title, "CMPT_RICH_TEXT")
		if rt != nil {
			groupTitle = rt.ValueString
		}
	}

	// Derive parent linkId from the first sub-question's linkId.
	// Convention: if sub has "q4-systolic", parent is "q4".
	parentLinkID := ""
	if subs[0].LinkID != "" {
		if idx := strings.LastIndex(subs[0].LinkID, "-"); idx != -1 {
			parentLinkID = subs[0].LinkID[:idx]
		}
	}

	// Determine if any sub-question is required — the parent inherits it.
	anyRequired := false
	for _, s := range subs {
		if s.Required {
			anyRequired = true
			break
		}
	}

	return &Question{
		Text:         groupTitle,
		Type:         "compound_numeric",
		LinkID:       parentLinkID,
		Required:     anyRequired,
		SubQuestions: subs,
	}
}

// extractChoiceQuestion converts a CMPT_CHOICE_QUESTION node into a Question.
func extractChoiceQuestion(node ContentNode) Question {
	q := Question{Type: "choice"}
	for _, child := range node.Nodes {
		switch child.NodeType {
		case "PROP_LINK_ID":
			q.LinkID = child.ValueString
		case "PROP_LABEL":
			q.Text = child.ValueString
		case "PROP_BOOLEAN":
			q.Type = "boolean"
		case "PROP_OPTION":
			q.Options = append(q.Options, child.ValueString)
			q.OptionsMarkdown = append(q.OptionsMarkdown, child.HTML)
		case "PROP_REQUIRED":
			q.Required = true
		}
	}
	return q
}

// extractFreeTextQuestion converts a CMPT_FREE_TEXT_QUESTION node into a Question.
// It examines PROP_CONSTRAINTS for numeric type/min/max and PROP_UNITS for unit info.
func extractFreeTextQuestion(node ContentNode) Question {
	q := Question{Type: "text"}
	for _, child := range node.Nodes {
		switch child.NodeType {
		case "PROP_LINK_ID":
			q.LinkID = child.ValueString
		case "PROP_LABEL":
			q.Text = child.ValueString
		case "PROP_REQUIRED":
			q.Required = true
		case "PROP_CONSTRAINTS":
			numNode := findChild(child, "PROP_NUMERIC")
			if numNode != nil {
				q.Type = "integer"
				if hasChild(*numNode, "PROP_ALLOW_DECIMAL") {
					q.Type = "decimal"
				}
				// Extract min/max values for FHIR extensions.
				minNode := findChild(*numNode, "PROP_MIN_VALUE")
				if minNode != nil {
					q.MinValue = minNode.ValueString
				}
				maxNode := findChild(*numNode, "PROP_MAX_VALUE")
				if maxNode != nil {
					q.MaxValue = maxNode.ValueString
				}
			}
		case "PROP_UNITS":
			// Extract unit options for FHIR questionnaire-unit extensions.
			// When units are present, the FHIR type becomes "quantity".
			for _, unitChild := range child.Nodes {
				if unitChild.NodeType == "PROP_UNIT" {
					unit := QuestionUnit{}
					for _, prop := range unitChild.Nodes {
						switch prop.NodeType {
						case "PROP_UNIT_DISPLAY":
							unit.Display = prop.ValueString
						case "PROP_UNIT_SYSTEM":
							unit.System = prop.ValueString
						case "PROP_UNIT_CODE":
							unit.Code = prop.ValueString
						}
					}
					q.Units = append(q.Units, unit)
				}
			}
		}
	}
	// NOTE: We intentionally keep q.Type as "integer" or "decimal" even when
	// units are present. The FHIR type override to "quantity" happens at output
	// time in mapQuestionType (survey.go), so that buildNumericExtensions can
	// still use the underlying integer/decimal type for valueInteger vs valueDecimal.
	return q
}

// collectCheckboxes recursively collects consent checkboxes from a node tree.
// A checkbox is a CMPT_CHOICE_QUESTION with a PROP_BOOLEAN child.
func collectCheckboxes(node ContentNode) []ConsentCheckbox {
	var checkboxes []ConsentCheckbox
	for _, child := range node.Nodes {
		if child.NodeType == "CMPT_CHOICE_QUESTION" && hasChild(child, "PROP_BOOLEAN") {
			cb := ConsentCheckbox{}
			for _, prop := range child.Nodes {
				switch prop.NodeType {
				case "PROP_LABEL":
					cb.Text = prop.ValueString
				case "PROP_REQUIRED":
					cb.Required = true
				}
			}
			checkboxes = append(checkboxes, cb)
		} else {
			// Recurse into structural nodes.
			checkboxes = append(checkboxes, collectCheckboxes(child)...)
		}
	}
	return checkboxes
}

// findChild returns a pointer to the first child with the given node type, or nil.
func findChild(node ContentNode, nodeType string) *ContentNode {
	for i := range node.Nodes {
		if node.Nodes[i].NodeType == nodeType {
			return &node.Nodes[i]
		}
	}
	return nil
}

// hasChild returns true if any direct child has the given node type.
func hasChild(node ContentNode, nodeType string) bool {
	return findChild(node, nodeType) != nil
}
