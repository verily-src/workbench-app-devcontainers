// Package seeder provides the core logic for creating VerilyMe programs
// from YAML templates. It constructs all necessary FHIR resources (content,
// surveys, workflow definitions) and posts them to the Healthcare API.
package seeder

import (
	"github.com/google/uuid"
	"gopkg.in/yaml.v3"
)

// ---------------------------------------------------------------------------
// Template types — read from YAML
// ---------------------------------------------------------------------------

// Template is the top-level YAML structure for a program definition.
// In the node-tree format, this is derived from an ADMIN_PROGRAM root node
// via convertNodeTreeToTemplate (see builder.go).
type Template struct {
	// Name is a human-readable name for the program (e.g. "my-test-program").
	// Used to generate FHIR resource names/URLs.
	Name string `yaml:"name"`

	// OrgID is the FHIR Organization ID that owns all resources.
	// Must match the enrollment profile's organization.
	OrgID string `yaml:"org_id"`

	// Version is the semantic version for all FHIR resources (e.g. "1.0.0").
	Version string `yaml:"version"`

	// EnvBaseURL is the environment base URL (e.g. "https://dev-stable.one.verily.com").
	// Used to construct org compartment references.
	EnvBaseURL string `yaml:"env_base_url"`

	// Bundles defines the missions/bundles in the program.
	// Each bundle appears as a card on the VerilyMe home screen.
	Bundles []Bundle `yaml:"bundles"`
}

// Bundle represents a mission bundle — a collection of steps shown as a single
// card on the VerilyMe home screen.
type Bundle struct {
	// Name is the internal name for the bundle (e.g. "welcome-mission").
	Name string `yaml:"name"`

	// Card defines the home-screen card content.
	Card Card `yaml:"card"`

	// Steps defines the ordered steps within the bundle.
	// Supported step types: "info", "survey".
	Steps []Step `yaml:"steps"`
}

// Card defines the content shown on the VerilyMe home-screen card for a bundle.
type Card struct {
	Title       string `yaml:"title"`
	Description string `yaml:"description"`
}

// Step is a single step within a bundle. The Type field determines which
// sub-fields are relevant.
type Step struct {
	// Type is the step type: "info", "survey", or "consent".
	Type string `yaml:"type"`

	// Title is displayed at the top of the step.
	Title string `yaml:"title"`

	// BodyHTML is the rich-text HTML content for "info" steps.
	// Sugar for a simple vertical container with title + body rich text.
	// Mutually exclusive with Nodes — use one or the other.
	// Note: not used by "consent" steps (regulated consent has no HTML module).
	BodyHTML string `yaml:"body_html,omitempty"`

	// Nodes is the full component node tree for "info" steps.
	// When set, this gives full control over the content layout (images,
	// accordions, highlight cards, etc.). The nodes are wrapped in an implicit
	// CMPT_VERTICAL_CONTAINER root.
	// Mutually exclusive with BodyHTML — use one or the other.
	Nodes []ContentNode `yaml:"nodes,omitempty"`

	// Questions are the survey questions for "survey" steps.
	Questions []Question `yaml:"questions,omitempty"`

	// Checkboxes are the agreement checkboxes for "consent" steps.
	// At least one is required.
	Checkboxes []ConsentCheckbox `yaml:"checkboxes,omitempty"`
}

// ContentNode represents a single node in the component tree.
// It mirrors the proto Node message (components_common.proto) with
// proto-native field names for zero-translation YAML↔proto mapping.
//
// The custom UnmarshalYAML accepts both proto-native field names (new format)
// and legacy snake_case names (old format) for backward compatibility:
//
//	New format: node_type, value_string (proto-native)
//	Old format: type, value (legacy)
//
// Node types use SCREAMING_SNAKE_CASE matching the proto NodeType enum:
//
//	CMPT_RICH_TEXT, CMPT_IMAGE, CMPT_VERTICAL_CONTAINER, etc.
//
// The legacy format's lowercase names (rich_text, image, etc.) are also accepted.
type ContentNode struct {
	// NodeType is the node type (e.g. "CMPT_RICH_TEXT", "CMPT_IMAGE").
	// Maps to proto Node.node_type. Legacy: "type" field with lowercase names.
	NodeType string

	// ValueString maps to proto Node.value_string (text content, color values, icon IDs).
	// Legacy: "value" field.
	ValueString string

	// HTML maps to proto Node.html (rich text HTML content).
	HTML string

	// URI maps to proto Node.uri (URL for images or linked content).
	URI string

	// Data maps to proto Node.value_bytes as base64 (binary data, data URIs).
	Data string

	// ID maps to proto Node.id (unique identifier for the node).
	ID string

	// Nodes are nested child nodes. Maps to proto Node.nodes.
	Nodes []ContentNode
}

// UnmarshalYAML implements yaml.Unmarshaler for ContentNode.
// It accepts both proto-native field names (node_type, value_string) and
// legacy YAML field names (type, value), preferring the proto-native names.
func (cn *ContentNode) UnmarshalYAML(value *yaml.Node) error {
	// Use an auxiliary struct to avoid infinite recursion while still
	// triggering ContentNode.UnmarshalYAML for nested children.
	type raw struct {
		// Proto-native names (new format)
		NodeType    string `yaml:"node_type"`
		ValueString string `yaml:"value_string"`
		// Legacy names (old format)
		Type  string `yaml:"type"`
		Value string `yaml:"value"`
		// Common fields (same name in both formats)
		HTML  string        `yaml:"html"`
		URI   string        `yaml:"uri"`
		Data  string        `yaml:"data"`
		ID    string        `yaml:"id"`
		Nodes []ContentNode `yaml:"nodes"`
	}
	var r raw
	if err := value.Decode(&r); err != nil {
		return err
	}
	// Prefer proto-native names; fall back to legacy.
	cn.NodeType = r.NodeType
	if cn.NodeType == "" {
		cn.NodeType = r.Type
	}
	cn.ValueString = r.ValueString
	if cn.ValueString == "" {
		cn.ValueString = r.Value
	}
	cn.HTML = r.HTML
	cn.URI = r.URI
	cn.Data = r.Data
	cn.ID = r.ID
	cn.Nodes = r.Nodes
	return nil
}

// Question defines a single survey question.
// It can also represent a compound question (e.g., blood pressure with systolic/diastolic)
// when Type is "compound_numeric" and SubQuestions holds the individual fields.
type Question struct {
	// Text is the question prompt (or group title for compound questions).
	Text string `yaml:"text"`

	// Type is the answer type: "choice", "boolean", "text", "integer", "decimal",
	// "quantity", or "compound_numeric" (for compound questions with sub-fields).
	Type string `yaml:"type"`

	// LinkID is the optional Questionnaire.item[].linkId for this question.
	// If empty, the builder auto-generates one from the question index.
	LinkID string `yaml:"link_id,omitempty"`

	// Options lists the answer choices for "choice" type questions.
	Options []string `yaml:"options,omitempty"`

	// OptionsMarkdown holds optional markdown-formatted versions of Options.
	// When present, the builder adds a rendering-markdown FHIR extension to
	// the CodeSystem concept so the survey-be renders bold/italic/etc.
	// Parallel to Options: OptionsMarkdown[i] corresponds to Options[i].
	// Empty strings mean "no markdown for this option".
	OptionsMarkdown []string `yaml:"-"`

	// Required indicates whether the question must be answered.
	Required bool `yaml:"required,omitempty"`

	// SubQuestions holds the individual fields of a compound question.
	// Only used when Type is "compound_numeric" — the survey-be expects exactly
	// two sub-fields with linkIds "{parent}/field1" and "{parent}/field2".
	SubQuestions []Question `yaml:"-"`

	// MinValue and MaxValue hold numeric constraints extracted from
	// PROP_CONSTRAINTS > PROP_NUMERIC > PROP_MIN_VALUE / PROP_MAX_VALUE.
	MinValue string `yaml:"-"`
	MaxValue string `yaml:"-"`

	// Units holds unit information from PROP_UNITS > PROP_UNIT.
	// When present, the FHIR item type becomes "quantity" instead of "integer".
	Units []QuestionUnit `yaml:"-"`
}

// QuestionUnit holds a single unit option for a numeric question.
// Maps to the FHIR questionnaire-unit extension.
type QuestionUnit struct {
	Display string // PROP_UNIT_DISPLAY
	System  string // PROP_UNIT_SYSTEM
	Code    string // PROP_UNIT_CODE
}

// ConsentCheckbox defines a single agreement checkbox in a consent step.
type ConsentCheckbox struct {
	// Text is the label shown next to the checkbox.
	Text string `yaml:"text"`

	// Required indicates whether the checkbox must be checked to proceed.
	Required bool `yaml:"required"`
}

// ---------------------------------------------------------------------------
// Output types — written as JSON after program creation
// ---------------------------------------------------------------------------

// ProgramOutput contains all IDs produced by creating a program.
// This is saved as JSON and can be consumed by the enrollment script.
type ProgramOutput struct {
	Name                string        `json:"name"`
	HealthcareServiceID string        `json:"healthcare_service_id"`
	PlanDefinitionID    string        `json:"plan_definition_id"`
	GroupID             string        `json:"group_id"`
	OrgID               string        `json:"org_id"`
	Version             string        `json:"version"`
	Resources           []ResourceRef `json:"resources"`
}

// ResourceRef records a single created FHIR resource.
type ResourceRef struct {
	Type string `json:"type"`
	ID   string `json:"id"`
	Name string `json:"name,omitempty"`
}

// ---------------------------------------------------------------------------
// Internal build-time types — used to wire resources together
// ---------------------------------------------------------------------------

// buildContext holds all state accumulated while building a program.
// It is used to track temp UUIDs and the final FHIR transaction entries.
type buildContext struct {
	tmpl    Template
	entries []bundleEntry

	// ID maps: tempUUID → assigned during build, resolved by FHIR server
	rootPlanDefTempID string
	groupTempID       string
	hcsTempID         string

	// Collected output refs
	outputResources []ResourceRef
}

// bundleEntry is one entry in the FHIR transaction bundle.
type bundleEntry struct {
	FullURL  string                 `json:"fullUrl,omitempty"`
	Resource map[string]interface{} `json:"resource"`
	Request  bundleRequest          `json:"request"`
}

// bundleRequest is the request portion of a transaction bundle entry.
type bundleRequest struct {
	Method string `json:"method"`
	URL    string `json:"url"`
}

// newBuildContext initializes a build context from a template.
func newBuildContext(tmpl Template) *buildContext {
	return &buildContext{
		tmpl:              tmpl,
		rootPlanDefTempID: "urn:uuid:" + uuid.New().String(),
		groupTempID:       "urn:uuid:" + uuid.New().String(),
		hcsTempID:         "urn:uuid:" + uuid.New().String(),
	}
}

// addEntry adds a resource to the transaction bundle.
func (bc *buildContext) addEntry(tempID string, resourceType string, resource map[string]interface{}) {
	entry := bundleEntry{
		FullURL:  tempID,
		Resource: resource,
		Request: bundleRequest{
			Method: "POST",
			URL:    resourceType,
		},
	}
	bc.entries = append(bc.entries, entry)
}

// addUpsertEntry adds a resource with PUT (create-or-update) semantics.
// The URL should include the resource ID, e.g. "Organization/abc-123".
// This ensures the resource exists at a known ID and that other bundle entries
// can reference it within the same transaction.
func (bc *buildContext) addUpsertEntry(tempID string, resourceURL string, resource map[string]interface{}) {
	entry := bundleEntry{
		FullURL:  tempID,
		Resource: resource,
		Request: bundleRequest{
			Method: "PUT",
			URL:    resourceURL,
		},
	}
	bc.entries = append(bc.entries, entry)
}

// orgCompartmentRef returns the full org compartment reference URL.
func (bc *buildContext) orgCompartmentRef() string {
	return bc.tmpl.EnvBaseURL + "/cortex-fhir-proxy/operational/fhir/Organization/" + bc.tmpl.OrgID
}

// canonicalURL creates a canonical URL for a resource.
func canonicalURL(namespace, resourceType, name string) string {
	return "http://fhir.verily.com/NamingSystem/" + namespace + "/" + resourceType + "/" + name
}
