package seeder

import (
	"fmt"
	"strconv"

	"github.com/google/uuid"
)

// ---------------------------------------------------------------------------
// Survey resource builders (Questionnaire + CodeSystem + ValueSet)
// ---------------------------------------------------------------------------

const (
	questionnaireProfile  = "http://fhir.verily.com/StructureDefinition/verily-questionnaire"
	codeSystemProfile     = "http://fhir.verily.com/StructureDefinition/verily-code-system"
	valueSetProfile       = "http://fhir.verily.com/StructureDefinition/verily-value-set"
	surveyOIDNamingSystem = "http://fhir.verily.com/NamingSystem/survey-content-object-identifier"
)

// surveyResources holds the FHIR resources generated for a single survey step.
type surveyResources struct {
	// Questionnaire is the main survey resource (referenced by definitionCanonical).
	Questionnaire    map[string]interface{}
	QuestionnaireURL string // Canonical URL for the Questionnaire

	// CodeSystem defines the question/answer codes.
	CodeSystem map[string]interface{}

	// ValueSets define the answer options for choice questions.
	ValueSets []map[string]interface{}
}

// buildSurveyResources creates all FHIR resources for a survey step.
func buildSurveyResources(bc *buildContext, step Step, stepIdx int, bundleName string) (*surveyResources, error) {
	if len(step.Questions) == 0 {
		return nil, fmt.Errorf("survey step %d in bundle %q has no questions", stepIdx, bundleName)
	}

	contentUID := fmt.Sprintf("%s-%s-survey-%d", bc.tmpl.Name, bundleName, stepIdx)
	oid := contentUID
	qURL := fmt.Sprintf("http://fhir.verily.com/Questionnaire/%s", contentUID)
	csURL := fmt.Sprintf("http://fhir.verily.com/CodeSystem/%s", contentUID)

	// Build CodeSystem concepts and Questionnaire items
	csConcepts := []map[string]interface{}{}
	qItems := []map[string]interface{}{}
	valueSets := []map[string]interface{}{}

	// Add title concept to CodeSystem
	csConcepts = append(csConcepts, map[string]interface{}{
		"code":    "title",
		"display": step.Title,
	})

	for qIdx, question := range step.Questions {
		// Use the explicit LinkID from the node tree (PROP_LINK_ID) if provided;
		// fall back to the auto-generated code (q1, q2, ...) for legacy templates.
		questionCode := fmt.Sprintf("q%d", qIdx+1)
		if question.LinkID != "" {
			questionCode = question.LinkID
		}

		if question.Type == "compound_numeric" {
			// Compound numeric: emit a parent item with type "question" (FHIR code 3)
			// and two sub-items with linkIds "{parent}/field1" and "{parent}/field2".
			// This is the exact structure the survey-be expects for QUESTION_TYPE_COMPOUND_NUMERIC.
			item, subConcepts := buildCompoundNumericItem(bc, question, questionCode, contentUID)
			qItems = append(qItems, item)
			csConcepts = append(csConcepts, map[string]interface{}{
				"code":    questionCode,
				"display": question.Text,
			})
			csConcepts = append(csConcepts, subConcepts...)
			continue
		}

		// The survey-be does not support the FHIR "boolean" question type.
		// Convert boolean questions to choice questions with Yes/No options,
		// which is how VCMS handles them.
		q := question
		if q.Type == "boolean" {
			q.Type = "choice"
			if len(q.Options) == 0 {
				q.Options = []string{"Yes", "No"}
			}
		}

		// Add question concept to CodeSystem
		csConcepts = append(csConcepts, map[string]interface{}{
			"code":    questionCode,
			"display": q.Text,
		})

		// Build Questionnaire item
		item := buildQuestionnaireItem(bc, q, questionCode, contentUID, qIdx)
		qItems = append(qItems, item)

		// Build ValueSet for choice questions
		if q.Type == "choice" && len(q.Options) > 0 {
			vs := buildValueSet(bc, q, questionCode, contentUID, oid)
			valueSets = append(valueSets, vs)

			// Add answer option concepts to CodeSystem
			for optIdx, opt := range q.Options {
				optCode := fmt.Sprintf("%s-a%d", questionCode, optIdx+1)
				concept := map[string]interface{}{
					"code":    optCode,
					"display": opt,
				}
				// Add rendering-markdown extension if markdown formatting exists.
				if optIdx < len(q.OptionsMarkdown) && q.OptionsMarkdown[optIdx] != "" {
					concept["extension"] = []map[string]interface{}{
						{
							"url":           "http://hl7.org/fhir/extensions/StructureDefinition/rendering-markdown",
							"valueMarkdown": q.OptionsMarkdown[optIdx],
						},
					}
				}
				csConcepts = append(csConcepts, concept)
			}
		}
	}

	// Build the Questionnaire
	// The survey-be requires a `code` field on the Questionnaire root that maps
	// to a concept in the CodeSystem (used for title/description lookup in basicView).
	questionnaire := map[string]interface{}{
		"resourceType": "Questionnaire",
		"meta":         buildOrgCompartmentMeta(bc, questionnaireProfile),
		"url":          qURL,
		"version":      bc.tmpl.Version,
		"title":        step.Title,
		"status":       "active",
		"code": []map[string]interface{}{
			{
				"system": csURL,
				"code":   "title",
			},
		},
		"identifier": []map[string]interface{}{
			{"system": surveyOIDNamingSystem, "value": oid},
		},
		"item": qItems,
	}

	// Build the CodeSystem
	codeSystem := map[string]interface{}{
		"resourceType":  "CodeSystem",
		"meta":          buildOrgCompartmentMeta(bc, codeSystemProfile),
		"url":           csURL,
		"version":       bc.tmpl.Version,
		"title":         step.Title,
		"status":        "active",
		"content":       "complete",
		"caseSensitive": true,
		"concept":       csConcepts,
		"identifier": []map[string]interface{}{
			{"system": contentOIDSystem, "value": oid},
		},
	}

	return &surveyResources{
		Questionnaire:    questionnaire,
		QuestionnaireURL: qURL,
		CodeSystem:       codeSystem,
		ValueSets:        valueSets,
	}, nil
}

// buildQuestionnaireItem creates a single Questionnaire.item for a question.
// Each item needs a `code` field that references the question concept in the
// CodeSystem — the survey-be uses item.Code[0] for question type mapping.
// For choice questions, the survey-be expects `answerValueSet` (a reference to
// an external ValueSet), NOT inline `answerOption`.
func buildQuestionnaireItem(bc *buildContext, q Question, questionCode, contentUID string, qIdx int) map[string]interface{} {
	csURL := fmt.Sprintf("http://fhir.verily.com/CodeSystem/%s", contentUID)
	item := map[string]interface{}{
		"linkId":   questionCode,
		"text":     q.Text,
		"type":     mapQuestionType(q),
		"required": q.Required,
		"code": []map[string]interface{}{
			{
				"system": csURL,
				"code":   questionCode,
			},
		},
	}

	// For choice questions:
	// 1. Reference the ValueSet via answerValueSet (the survey-be's optionsFromItem
	//    requires this, not inline answerOption).
	// 2. Add the questionnaire-itemControl extension so the survey-be sets the
	//    ChoiceConfig.Type field. Without it, the frontend's ChoiceQuestion component
	//    renders null (the default case returns nothing).
	//    VCMS uses "radio-button" or "drop-down"; we default to "radio-button".
	if q.Type == "choice" && len(q.Options) > 0 {
		vsCanonical := fmt.Sprintf("http://fhir.verily.com/ValueSet/%s/%s|%s", contentUID, questionCode, bc.tmpl.Version)
		item["answerValueSet"] = vsCanonical
		item["extension"] = []map[string]interface{}{
			{
				"url": "http://hl7.org/fhir/StructureDefinition/questionnaire-itemControl",
				"valueCodeableConcept": map[string]interface{}{
					"text": "radio-button",
				},
			},
		}
	}

	return item
}

// buildValueSet creates a ValueSet for a choice question's answer options.
func buildValueSet(bc *buildContext, q Question, questionCode, contentUID, surveyOID string) map[string]interface{} {
	csURL := fmt.Sprintf("http://fhir.verily.com/CodeSystem/%s", contentUID)

	concepts := []map[string]interface{}{}
	for optIdx, opt := range q.Options {
		optCode := fmt.Sprintf("%s-a%d", questionCode, optIdx+1)
		concepts = append(concepts, map[string]interface{}{
			"code":    optCode,
			"display": opt,
		})
	}

	return map[string]interface{}{
		"resourceType": "ValueSet",
		"meta":         buildOrgCompartmentMeta(bc, valueSetProfile),
		"url":          fmt.Sprintf("http://fhir.verily.com/ValueSet/%s/%s", contentUID, questionCode),
		"version":      bc.tmpl.Version,
		"status":       "active",
		"identifier": []map[string]interface{}{
			{"system": surveyOIDNamingSystem, "value": fmt.Sprintf("%s/%s", surveyOID, questionCode)},
		},
		"compose": map[string]interface{}{
			"include": []map[string]interface{}{
				{
					"system":  csURL,
					"version": bc.tmpl.Version,
					"concept": concepts,
				},
			},
		},
	}
}

// buildCompoundNumericItem creates a FHIR Questionnaire.item for a compound numeric
// question. The structure matches exactly what the survey-be expects:
//
//	Parent item:
//	  linkId: "{questionCode}"
//	  type: "question"   (QuestionnaireItemTypeCode_QUESTION = 3)
//	  repeats: true
//	  item[]:
//	    [0] linkId: "{questionCode}/field1", type: integer/decimal/quantity
//	    [1] linkId: "{questionCode}/field2", type: integer/decimal/quantity
//
// The survey-be's mapToQuestionType dispatches "question" → COMPOUND_NUMERIC,
// and compoundNumericConfigFromItem reads item.Item[0] and item.Item[1].
// Sub-item linkIds MUST use the "/{fieldN}" suffix because the response
// serializer hardcodes "field1" / "field2" as lookup keys.
func buildCompoundNumericItem(bc *buildContext, q Question, questionCode, contentUID string) (map[string]interface{}, []map[string]interface{}) {
	csURL := fmt.Sprintf("http://fhir.verily.com/CodeSystem/%s", contentUID)

	var subItems []map[string]interface{}
	var subConcepts []map[string]interface{}

	for i, sub := range q.SubQuestions {
		fieldKey := fmt.Sprintf("field%d", i+1)
		subLinkID := fmt.Sprintf("%s/%s", questionCode, fieldKey)
		subCode := subLinkID // CodeSystem code matches linkId

		subItem := map[string]interface{}{
			"linkId":   subLinkID,
			"text":     sub.Text,
			"type":     mapQuestionType(sub),
			"required": sub.Required,
			"code": []map[string]interface{}{
				{
					"system":  csURL,
					"version": bc.tmpl.Version,
					"code":    subCode,
				},
			},
		}

		// Add numeric constraint extensions (minValue, maxValue, maxDecimalPlaces).
		exts := buildNumericExtensions(sub)
		if len(exts) > 0 {
			subItem["extension"] = exts
		}

		subItems = append(subItems, subItem)
		subConcepts = append(subConcepts, map[string]interface{}{
			"code":    subCode,
			"display": sub.Text,
		})
	}

	parentItem := map[string]interface{}{
		"linkId":   questionCode,
		"text":     q.Text,
		"type":     "question", // FHIR QuestionnaireItemTypeCode_QUESTION
		"repeats":  true,       // Required by the survey-be for compound numerics
		"required": q.Required,
		"code": []map[string]interface{}{
			{
				"system": csURL,
				"code":   questionCode,
			},
		},
		"item": subItems,
	}

	return parentItem, subConcepts
}

// buildNumericExtensions creates FHIR extensions for numeric constraints on a question.
// The extensions follow the same structure that the survey-be's extension parser expects:
//   - minValue: http://hl7.org/fhir/StructureDefinition/minValue
//   - maxValue: http://hl7.org/fhir/StructureDefinition/maxValue
//   - maxDecimalPlaces: http://hl7.org/fhir/StructureDefinition/maxDecimalPlaces
//   - questionnaire-unit: http://hl7.org/fhir/StructureDefinition/questionnaire-unit
func buildNumericExtensions(q Question) []map[string]interface{} {
	var exts []map[string]interface{}

	isInteger := q.Type == "integer"
	// isDecimalOrQuantity := q.Type == "decimal" || q.Type == "quantity"

	// For integer questions, force maxDecimalPlaces to 0 (the survey-be extension
	// parser expects this to distinguish integers from decimals).
	if isInteger {
		exts = append(exts, map[string]interface{}{
			"url":          "http://hl7.org/fhir/StructureDefinition/maxDecimalPlaces",
			"valueInteger": 0,
		})
	}

	if q.MinValue != "" {
		if isInteger {
			if v, err := strconv.Atoi(q.MinValue); err == nil {
				exts = append(exts, map[string]interface{}{
					"url":          "http://hl7.org/fhir/StructureDefinition/minValue",
					"valueInteger": v,
				})
			}
		} else {
			if v, err := strconv.ParseFloat(q.MinValue, 64); err == nil {
				exts = append(exts, map[string]interface{}{
					"url":          "http://hl7.org/fhir/StructureDefinition/minValue",
					"valueDecimal": v,
				})
			}
		}
	}

	if q.MaxValue != "" {
		if isInteger {
			if v, err := strconv.Atoi(q.MaxValue); err == nil {
				exts = append(exts, map[string]interface{}{
					"url":          "http://hl7.org/fhir/StructureDefinition/maxValue",
					"valueInteger": v,
				})
			}
		} else {
			if v, err := strconv.ParseFloat(q.MaxValue, 64); err == nil {
				exts = append(exts, map[string]interface{}{
					"url":          "http://hl7.org/fhir/StructureDefinition/maxValue",
					"valueDecimal": v,
				})
			}
		}
	}

	for _, unit := range q.Units {
		exts = append(exts, map[string]interface{}{
			"url": "http://hl7.org/fhir/StructureDefinition/questionnaire-unit",
			"valueCoding": map[string]interface{}{
				"system":  unit.System,
				"code":    unit.Code,
				"display": unit.Display,
			},
		})
	}

	return exts
}

// mapQuestionType maps our simple type names to FHIR Questionnaire item types.
// Note: "boolean" is NOT a supported FHIR type in the survey-be. Boolean
// questions should be converted to "choice" with Yes/No options before
// reaching this function (see buildSurveyResources).
func mapQuestionType(q Question) string {
	// When units are present, the FHIR type is "quantity" regardless of
	// the underlying integer/decimal distinction. The survey-be dispatches
	// QUANTITY items to the numeric renderer with unit support.
	if len(q.Units) > 0 && (q.Type == "integer" || q.Type == "decimal") {
		return "quantity"
	}
	switch q.Type {
	case "choice":
		return "choice"
	case "text":
		return "string"
	case "integer":
		return "integer"
	case "decimal":
		return "decimal"
	default:
		return "string"
	}
}

// newTempID generates a new urn:uuid temporary ID for transaction bundle references.
func newTempID() string {
	return "urn:uuid:" + uuid.New().String()
}
