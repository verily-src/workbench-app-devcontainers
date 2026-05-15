package seeder

import (
	"encoding/base64"
	"fmt"
	"strings"

	"github.com/google/uuid"
	componentspb "github.com/verily-src/workbench-app-devcontainers/src/program-generator/app/internal/contentpb"
	"google.golang.org/protobuf/proto"
)

// ---------------------------------------------------------------------------
// Content / DocumentReference builder
// ---------------------------------------------------------------------------

const (
	docRefProfile          = "http://fhir.verily.com/StructureDefinition/verily-document-reference-content"
	cardCodeSystemProfile  = "http://fhir.verily.com/StructureDefinition/verily-code-system-content"
	orgCompartmentExtURL   = "http://fhir.verily.com/StructureDefinition/verily-organization-compartment"
	vcmsMetadataExtURL     = "http://fhir.verily.com/StructureDefinition/vcms-content-metadata"
	vcmsContentTemplateURL = "http://fhir.verily.com/StructureDefinition/vcms-content-templates"
	contentOIDSystem       = "http://fhir.verily.com/NamingSystem/vcms-content-object-identifier"
	contentVersionIDSystem = "http://fhir.verily.com/NamingSystem/vcms-version-specific-content-id"
)

// buildInfoDocumentReference creates a FHIR DocumentReference for an info step.
// It encodes the step's body_html as a proto Node tree and embeds it as base64.
func buildInfoDocumentReference(bc *buildContext, step Step, stepIdx int, bundleName string) (tempID string, resource map[string]interface{}, error error) {
	contentUID := fmt.Sprintf("%s-%s-info-%d", bc.tmpl.Name, bundleName, stepIdx)
	oid := contentUID // Use contentUID as the OID for simplicity
	versionedID := fmt.Sprintf("%s-%s", contentUID, bc.tmpl.Version)

	// Build the proto Node tree for the content
	node, err := buildInfoNode(step)
	if err != nil {
		return "", nil, fmt.Errorf("building node tree: %w", err)
	}

	// Encode to base64
	encodedData, err := encodeNodeToBase64(node)
	if err != nil {
		return "", nil, fmt.Errorf("encoding content node: %w", err)
	}

	tempID = "urn:uuid:" + uuid.New().String()
	resource = map[string]interface{}{
		"resourceType": "DocumentReference",
		"meta":         buildDocRefMeta(bc),
		"status":       "current",
		"type":         map[string]interface{}{"text": "ActivityPage"},
		"description":  step.Title,
		"identifier": []map[string]interface{}{
			{"system": contentOIDSystem, "value": oid},
			{"system": contentVersionIDSystem, "value": versionedID},
		},
		"content": []map[string]interface{}{
			{"attachment": map[string]interface{}{}},
		},
		"extension": []interface{}{
			buildVCMSMetadataExtension(contentUID, oid, "activity-page"),
			buildContentTemplateExtension(encodedData),
		},
	}
	return tempID, resource, nil
}

// buildCardDocumentReference creates a FHIR DocumentReference for a bundle card.
func buildCardDocumentReference(bc *buildContext, bundle Bundle, bundleIdx int) (tempID string, resource map[string]interface{}) {
	contentUID := fmt.Sprintf("%s-%s-card", bc.tmpl.Name, bundle.Name)
	oid := contentUID
	versionedID := fmt.Sprintf("%s-%s", contentUID, bc.tmpl.Version)

	// Build a simple card node with title + description
	node := buildCardNode(bundle.Card)
	encodedData, err := encodeNodeToBase64(node)
	if err != nil {
		// Cards are non-critical; use empty data if encoding fails
		encodedData = ""
	}

	tempID = "urn:uuid:" + uuid.New().String()
	resource = map[string]interface{}{
		"resourceType": "DocumentReference",
		"meta":         buildDocRefMeta(bc),
		"status":       "current",
		"type":         map[string]interface{}{"text": "ActivityCard"},
		"description":  bundle.Card.Title,
		"identifier": []map[string]interface{}{
			{"system": contentOIDSystem, "value": oid},
			{"system": contentVersionIDSystem, "value": versionedID},
		},
		"content": []map[string]interface{}{
			{"attachment": map[string]interface{}{}},
		},
		"extension": []interface{}{
			buildVCMSMetadataExtension(contentUID, oid, "activity-card"),
			buildContentTemplateExtension(encodedData),
		},
	}
	return tempID, resource
}

// buildCardCodeSystem creates a companion CodeSystem for a card DocumentReference.
// The Content BE uses this CodeSystem to get localized title/description for ActivityCard
// type DocumentReferences. It links them via the vcms-version-specific-content-id identifier.
func buildCardCodeSystem(bc *buildContext, bundle Bundle, bundleIdx int) (tempID string, resource map[string]interface{}) {
	contentUID := fmt.Sprintf("%s-%s-card", bc.tmpl.Name, bundle.Name)
	versionedID := fmt.Sprintf("%s-%s", contentUID, bc.tmpl.Version)

	concepts := []map[string]interface{}{
		{
			"code": "title",
			"designation": []map[string]interface{}{
				{
					"language": "en-US",
					"value":    bundle.Card.Title,
				},
			},
		},
		{
			"code": "description",
			"designation": []map[string]interface{}{
				{
					"language": "en-US",
					"value":    bundle.Card.Description,
					"extension": []map[string]interface{}{
						{
							"url":           "http://hl7.org/fhir/extensions/StructureDefinition/rendering-markdown",
							"valueMarkdown": bundle.Card.Description,
						},
					},
				},
			},
		},
	}

	tempID = "urn:uuid:" + uuid.New().String()
	resource = map[string]interface{}{
		"resourceType": "CodeSystem",
		"meta":         buildOrgCompartmentMeta(bc, cardCodeSystemProfile),
		"url":          fmt.Sprintf("%s/cortex-fhir-proxy/operational/fhir/CodeSystem/%s", bc.tmpl.EnvBaseURL, contentUID),
		"version":      bc.tmpl.Version,
		"name":         contentUID,
		"title":        fmt.Sprintf("%s Card Translations", bundle.Card.Title),
		"status":       "active",
		"content":      "complete",
		"identifier": []map[string]interface{}{
			{"system": contentVersionIDSystem, "value": versionedID},
		},
		"concept": concepts,
	}
	return tempID, resource
}

// ---------------------------------------------------------------------------
// Node proto tree builders
// ---------------------------------------------------------------------------

// buildInfoNode constructs a Node proto tree for an info step.
//
// Two modes:
//   - body_html (sugar): VerticalContainer > [RichText(title), RichText(body)]
//   - nodes (full power): VerticalContainer > [...converted nodes]
//     In full-power mode the content tree is self-contained (title is already
//     a CMPT_RICH_TEXT node), so we do NOT prepend step.Title as a heading.
func buildInfoNode(step Step) (*componentspb.Node, error) {
	// Full node tree mode — convert each ContentNode to proto.
	if len(step.Nodes) > 0 {
		children := make([]*componentspb.Node, 0, len(step.Nodes))

		for i, cn := range step.Nodes {
			converted, err := convertContentNode(cn)
			if err != nil {
				return nil, fmt.Errorf("nodes[%d]: %w", i, err)
			}
			children = append(children, converted)
		}

		return &componentspb.Node{
			NodeType: componentspb.NodeType_CMPT_VERTICAL_CONTAINER,
			Nodes:    children,
		}, nil
	}

	// Sugar mode — simple body_html.
	children := []*componentspb.Node{}

	if step.Title != "" {
		titleHTML := fmt.Sprintf("<h1>%s</h1>", step.Title)
		titleMD := "# " + step.Title
		children = append(children, &componentspb.Node{
			NodeType:    componentspb.NodeType_CMPT_RICH_TEXT,
			ValueString: &titleMD,
			Html:        &titleHTML,
		})
	}

	if step.BodyHTML != "" {
		bodyMD := step.BodyHTML // Simplification; real impl would convert HTML→markdown
		children = append(children, &componentspb.Node{
			NodeType:    componentspb.NodeType_CMPT_RICH_TEXT,
			ValueString: &bodyMD,
			Html:        &step.BodyHTML,
		})
	}

	return &componentspb.Node{
		NodeType: componentspb.NodeType_CMPT_VERTICAL_CONTAINER,
		Nodes:    children,
	}, nil
}

// ---------------------------------------------------------------------------
// ContentNode → proto Node conversion
// ---------------------------------------------------------------------------

// nodeTypeMap maps YAML node type names to proto NodeType values.
// It accepts both SCREAMING_SNAKE_CASE proto enum names (new node-tree format)
// and lowercase snake_case names (legacy format) for backward compatibility.
var nodeTypeMap = map[string]componentspb.NodeType{
	// SCREAMING_SNAKE_CASE — proto enum names (node-tree format)
	"CMPT_VERTICAL_CONTAINER":   componentspb.NodeType_CMPT_VERTICAL_CONTAINER,
	"CMPT_HORIZONTAL_CONTAINER": componentspb.NodeType_CMPT_HORIZONTAL_CONTAINER,
	"CMPT_RICH_TEXT":            componentspb.NodeType_CMPT_RICH_TEXT,
	"CMPT_IMAGE":                componentspb.NodeType_CMPT_IMAGE,
	"CMPT_HIGHLIGHT_CARD":       componentspb.NodeType_CMPT_HIGHLIGHT_CARD,
	"CMPT_ICON_LIST":            componentspb.NodeType_CMPT_ICON_LIST,
	"CMPT_ICON":                 componentspb.NodeType_CMPT_ICON,
	"CMPT_ACCORDION_GROUP":      componentspb.NodeType_CMPT_ACCORDION_GROUP,
	"CMPT_ACCORDION_ROW":        componentspb.NodeType_CMPT_ACCORDION_ROW,
	"CMPT_ACCORDION_SUMMARY":    componentspb.NodeType_CMPT_ACCORDION_SUMMARY,
	"CMPT_ACCORDION_DETAILS":    componentspb.NodeType_CMPT_ACCORDION_DETAILS,
	"CMPT_SECTION_DIVIDER":      componentspb.NodeType_CMPT_SECTION_DIVIDER,
	"PROP_ALT_TEXT":             componentspb.NodeType_PROP_ALT_TEXT,
	"PROP_DARK_MODE":            componentspb.NodeType_PROP_DARK_MODE,
	"PROP_COLOR":                componentspb.NodeType_PROP_COLOR,
	"PROP_MIME_TYPE":            componentspb.NodeType_PROP_MIME_TYPE,
	"PROP_BLOB_KEY":             componentspb.NodeType_PROP_BLOB_KEY,

	// Lowercase — legacy YAML format (snake_case without CMPT_/PROP_ prefix)
	"vertical_container":   componentspb.NodeType_CMPT_VERTICAL_CONTAINER,
	"horizontal_container": componentspb.NodeType_CMPT_HORIZONTAL_CONTAINER,
	"rich_text":            componentspb.NodeType_CMPT_RICH_TEXT,
	"image":                componentspb.NodeType_CMPT_IMAGE,
	"highlight_card":       componentspb.NodeType_CMPT_HIGHLIGHT_CARD,
	"icon_list":            componentspb.NodeType_CMPT_ICON_LIST,
	"icon":                 componentspb.NodeType_CMPT_ICON,
	"accordion_group":      componentspb.NodeType_CMPT_ACCORDION_GROUP,
	"accordion_row":        componentspb.NodeType_CMPT_ACCORDION_ROW,
	"accordion_summary":    componentspb.NodeType_CMPT_ACCORDION_SUMMARY,
	"accordion_details":    componentspb.NodeType_CMPT_ACCORDION_DETAILS,
	"section_divider":      componentspb.NodeType_CMPT_SECTION_DIVIDER,
	"alt_text":             componentspb.NodeType_PROP_ALT_TEXT,
	"dark_mode":            componentspb.NodeType_PROP_DARK_MODE,
	"color":                componentspb.NodeType_PROP_COLOR,
	"mime_type":            componentspb.NodeType_PROP_MIME_TYPE,
	"blob_key":             componentspb.NodeType_PROP_BLOB_KEY,
}

// convertContentNode recursively converts a YAML ContentNode to a proto Node.
func convertContentNode(cn ContentNode) (*componentspb.Node, error) {
	nt, ok := nodeTypeMap[cn.NodeType]
	if !ok {
		return nil, fmt.Errorf("unknown node type %q (valid types: %s)", cn.NodeType, validNodeTypes())
	}

	node := &componentspb.Node{
		NodeType: nt,
	}

	if cn.ValueString != "" {
		node.ValueString = &cn.ValueString
	}
	if cn.HTML != "" {
		node.Html = &cn.HTML
	}
	if cn.URI != "" {
		node.Uri = &cn.URI
	}
	if cn.Data != "" {
		node.ValueBytes = []byte(cn.Data)
	}
	if cn.ID != "" {
		node.Id = &cn.ID
	}

	for i, child := range cn.Nodes {
		converted, err := convertContentNode(child)
		if err != nil {
			return nil, fmt.Errorf("nodes[%d]: %w", i, err)
		}
		node.Nodes = append(node.Nodes, converted)
	}

	return node, nil
}

// validNodeTypes returns a comma-separated list of valid YAML node type names.
func validNodeTypes() string {
	types := make([]string, 0, len(nodeTypeMap))
	for k := range nodeTypeMap {
		types = append(types, k)
	}
	return strings.Join(types, ", ")
}

// buildCardNode constructs a Node proto tree for a bundle card.
func buildCardNode(card Card) *componentspb.Node {
	children := []*componentspb.Node{}

	if card.Title != "" {
		titleHTML := fmt.Sprintf("<strong>%s</strong>", card.Title)
		titleMD := "**" + card.Title + "**"
		children = append(children, &componentspb.Node{
			NodeType:    componentspb.NodeType_CMPT_RICH_TEXT,
			ValueString: &titleMD,
			Html:        &titleHTML,
		})
	}

	if card.Description != "" {
		descHTML := fmt.Sprintf("<p>%s</p>", card.Description)
		children = append(children, &componentspb.Node{
			NodeType:    componentspb.NodeType_CMPT_RICH_TEXT,
			ValueString: &card.Description,
			Html:        &descHTML,
		})
	}

	return &componentspb.Node{
		NodeType: componentspb.NodeType_CMPT_VERTICAL_CONTAINER,
		Nodes:    children,
	}
}

// ---------------------------------------------------------------------------
// Proto encoding
// ---------------------------------------------------------------------------

// encodeNodeToBase64 marshals a Node proto and returns a double-base64-encoded string.
//
// Why double-encode? The FHIR `data` field is type base64Binary, so the FHIR
// client automatically decodes the outer layer when reading. VCMS stores data
// as proto → base64 → base64 so that after the automatic outer decode, the
// content-be still receives a base64 string it can decode to get the raw proto.
func encodeNodeToBase64(node *componentspb.Node) (string, error) {
	data, err := proto.Marshal(node)
	if err != nil {
		return "", fmt.Errorf("proto marshal: %w", err)
	}
	inner := base64.StdEncoding.EncodeToString(data)
	return base64.StdEncoding.EncodeToString([]byte(inner)), nil
}

// ---------------------------------------------------------------------------
// FHIR extension helpers
// ---------------------------------------------------------------------------

// buildDocRefMeta creates the meta block for a DocumentReference with org compartment.
func buildDocRefMeta(bc *buildContext) map[string]interface{} {
	return map[string]interface{}{
		"profile": []string{docRefProfile},
		"extension": []map[string]interface{}{
			{
				"url": orgCompartmentExtURL,
				"valueReference": map[string]interface{}{
					"reference": bc.orgCompartmentRef(),
				},
			},
		},
	}
}

// buildOrgCompartmentMeta creates a meta block with org compartment for any resource.
func buildOrgCompartmentMeta(bc *buildContext, profiles ...string) map[string]interface{} {
	meta := map[string]interface{}{
		"extension": []map[string]interface{}{
			{
				"url": orgCompartmentExtURL,
				"valueReference": map[string]interface{}{
					"reference": bc.orgCompartmentRef(),
				},
			},
		},
	}
	if len(profiles) > 0 {
		meta["profile"] = profiles
	}
	return meta
}

// buildVCMSMetadataExtension creates the vcms-content-metadata extension.
// The semanticVersion and version fields are hardcoded: semver is decorative
// vCMS metadata that nothing resolves by, and the integer version is always "1"
// for freshly-seeded content.
func buildVCMSMetadataExtension(contentUID, oid, contentType string) map[string]interface{} {
	return map[string]interface{}{
		"url": vcmsMetadataExtURL,
		"extension": []map[string]interface{}{
			{"url": "semanticVersion", "valueString": "1.0.0"},
			{"url": "contentUID", "valueString": contentUID},
			{"url": "objectIdentifier", "valueString": oid},
			{"url": "version", "valueString": "1"},
			{
				"url": "locale",
				"valueCoding": map[string]interface{}{
					"system":  "urn:ietf:bcp:47",
					"code":    "en-US",
					"display": "English (United States)",
				},
			},
			{"url": "contentId", "valueString": "1"},
			{
				"url": "contentType",
				"valueCoding": map[string]interface{}{
					"system": "http://fhir.verily.com/CodeSystem/vcms-content-type",
					"code":   contentType,
				},
			},
			{"url": "publishedBy", "valueString": "Standalone Seeding Tool"},
		},
	}
}

// buildContentTemplateExtension creates the vcms-content-templates extension
// with the base64-encoded proto Node data.
func buildContentTemplateExtension(encodedData string) map[string]interface{} {
	return map[string]interface{}{
		"url": vcmsContentTemplateURL,
		"extension": []map[string]interface{}{
			{
				"url": "componentData",
				"valueAttachment": map[string]interface{}{
					"contentType": "application/x-protobuf",
					"language":    "en-US",
					"data":        encodedData,
				},
			},
		},
	}
}
