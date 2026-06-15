# FHIR Export Guide for Glyph

## Overview

Glyph now supports exporting annotations as **FHIR R4** resources, enabling integration with Electronic Health Records (EHRs), PACS/RIS systems, and healthcare data platforms.

## Supported FHIR Resources

### 1. Observation
Individual annotated findings (bounding boxes, labels) represented as FHIR Observations.

**Includes:**
- SNOMED CT coded labels
- Bounding box coordinates in components
- Confidence scores
- Reference to ImagingStudy
- Annotator (Practitioner) reference

### 2. ImagingStudy
Links annotations to source medical images (DICOM studies).

**Includes:**
- Study/Series/Instance UIDs
- Image metadata
- Modality information

### 3. DiagnosticReport
Aggregates all findings from an annotation session into a cohesive report.

**Includes:**
- Summary/conclusion of findings
- References to all Observations
- Performer (annotator)
- Status (final, preliminary, amended)

### 4. Bundle
Transaction bundle containing all resources for batch upload to FHIR server.

---

## API Endpoints

### Export All Annotations as FHIR Bundle

```bash
GET /api/export/fhir
```

**Response**: FHIR Bundle (transaction type) with all Observations, ImagingStudies, and DiagnosticReports

**Example**:
```bash
curl http://localhost:8080/api/export/fhir > annotations_fhir.json
```

---

### Export Observations for Specific Task

```bash
GET /api/export/fhir/observation/<task_id>
```

**Response**: FHIR Bundle (collection type) with Observations for one task

**Example**:
```bash
curl http://localhost:8080/api/export/fhir/observation/task_001
```

---

### Export DiagnosticReport for Specific Task

```bash
GET /api/export/fhir/report/<task_id>
```

**Response**: FHIR DiagnosticReport summarizing annotations for one task

**Example**:
```bash
curl http://localhost:8080/api/export/fhir/report/task_001
```

---

## FHIR Output Examples

### Observation Example

```json
{
  "resourceType": "Observation",
  "id": "annotation-12345",
  "status": "final",
  "category": [{
    "coding": [{
      "system": "http://terminology.hl7.org/CodeSystem/observation-category",
      "code": "imaging",
      "display": "Imaging"
    }]
  }],
  "code": {
    "coding": [{
      "system": "http://snomed.info/sct",
      "code": "27925004",
      "display": "Nodule"
    }],
    "text": "Nodule"
  },
  "subject": {
    "reference": "Patient/unknown"
  },
  "effectiveDateTime": "2026-06-15T10:30:00Z",
  "performer": [{
    "reference": "Practitioner/annotator-123",
    "display": "Dr. Radiologist"
  }],
  "valueCodeableConcept": {
    "coding": [{
      "system": "http://snomed.info/sct",
      "code": "27925004",
      "display": "Nodule"
    }],
    "text": "Nodule detected"
  },
  "component": [
    {
      "code": {
        "coding": [{
          "system": "http://loinc.org",
          "code": "59776-5",
          "display": "Bounding box coordinates"
        }]
      },
      "valueString": "x:150, y:200, width:80, height:100"
    },
    {
      "code": {
        "coding": [{
          "system": "http://loinc.org",
          "code": "82810-3",
          "display": "Confidence score"
        }]
      },
      "valueQuantity": {
        "value": 0.95,
        "unit": "probability",
        "system": "http://unitsofmeasure.org",
        "code": "1"
      }
    }
  ],
  "derivedFrom": [{
    "reference": "ImagingStudy/task_001"
  }]
}
```

### DiagnosticReport Example

```json
{
  "resourceType": "DiagnosticReport",
  "id": "report-session-123",
  "status": "final",
  "category": [{
    "coding": [{
      "system": "http://terminology.hl7.org/CodeSystem/v2-0074",
      "code": "IMG",
      "display": "Diagnostic Imaging"
    }]
  }],
  "code": {
    "coding": [{
      "system": "http://loinc.org",
      "code": "18748-4",
      "display": "Diagnostic imaging study"
    }],
    "text": "Annotation Report"
  },
  "subject": {
    "reference": "Patient/unknown"
  },
  "effectiveDateTime": "2026-06-15T10:30:00Z",
  "issued": "2026-06-15T10:30:00Z",
  "performer": [{
    "reference": "Practitioner/annotator-123"
  }],
  "imagingStudy": [{
    "reference": "ImagingStudy/task_001"
  }],
  "conclusion": "Annotation identified 3 total findings: 2 Nodule(s), 1 Mass(es)",
  "result": [
    {"reference": "Observation/annotation-12345"},
    {"reference": "Observation/annotation-12346"}
  ]
}
```

---

## SNOMED CT Coding

Glyph automatically maps common labels to SNOMED CT codes:

| Label | SNOMED CT Code | Display |
|-------|----------------|---------|
| Nodule | 27925004 | Nodule |
| Mass | 300848003 | Mass |
| Lesion | 52988006 | Lesion |
| Person | 125676002 | Person |
| Lung | 39607008 | Lung structure |
| Heart | 80891009 | Heart structure |
| Head | 69536005 | Head structure |

**Custom Mappings**: Edit `fhir_export.py` → `snomed_mapping` dict to add your own label-to-SNOMED mappings.

---

## Integration with FHIR Servers

### Upload to HAPI FHIR Server

```bash
# Export bundle
curl http://localhost:8080/api/export/fhir > bundle.json

# Upload to FHIR server (transaction bundle)
curl -X POST \
  http://your-fhir-server:8080/fhir \
  -H "Content-Type: application/fhir+json" \
  -d @bundle.json
```

### Upload to Google Cloud Healthcare API

```bash
# Export bundle
curl http://localhost:8080/api/export/fhir > bundle.json

# Upload via gcloud
PROJECT_ID="your-project"
LOCATION="us-central1"
DATASET="your-dataset"
FHIR_STORE="your-fhir-store"

curl -X POST \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/fhir+json" \
  https://healthcare.googleapis.com/v1/projects/$PROJECT_ID/locations/$LOCATION/datasets/$DATASET/fhirStores/$FHIR_STORE/fhir \
  -d @bundle.json
```

---

## Validation

### Validate FHIR Resources

Use the official FHIR validator:

```bash
# Download validator
wget https://github.com/hapifhir/org.hl7.fhir.core/releases/download/6.0.11/validator_cli.jar

# Validate exported FHIR
java -jar validator_cli.jar annotations_fhir.json -version 4.0
```

---

## Extending FHIR Export

### Add Custom SNOMED CT Codes

Edit `fhir_export.py`:

```python
snomed_mapping = {
    'Your Label': {'code': 'SNOMED_CODE', 'display': 'Display Text'},
    'Tumor': {'code': '108369006', 'display': 'Tumor'},
    # Add more...
}
```

### Add Patient Context

Modify annotation data to include patient ID:

```python
annotation = {
    'task_id': 'task_001',
    'patient_id': 'patient-123',  # Add this
    'annotation_data': {...}
}
```

FHIR export will then reference:
```json
"subject": {
  "reference": "Patient/patient-123"
}
```

### Add BodyStructure Resources

Uncomment BodyStructure generation in `fhir_export.py`:

```python
from fhir_export import generate_body_structure

# In your export function:
for bbox in annotation_data['bboxes']:
    body_structure = generate_body_structure(bbox, annotation_id)
    entries.append({
        'fullUrl': f"urn:uuid:{body_structure['id']}",
        'resource': body_structure,
        'request': {'method': 'POST', 'url': 'BodyStructure'}
    })
```

---

## Use Cases

### 1. Radiology Workflow Integration
- Annotate chest X-rays in Glyph
- Export FHIR Observations
- Upload to PACS via FHIR
- Radiologist reviews findings in RIS

### 2. Clinical Decision Support
- ML model annotates CT scans
- Export as FHIR DiagnosticReport
- CDS system queries FHIR server
- Alerts clinician to critical findings

### 3. Research Data Sharing
- Multi-site study annotates pathology slides
- Export FHIR Bundles
- Share via FHIR server
- Standardized, interoperable dataset

### 4. FDA Submission
- Annotation pipeline for device validation
- FHIR Provenance tracks all changes
- Audit trail for regulatory compliance
- Submit FHIR-compliant annotations with 510(k)

---

## Troubleshooting

### FHIR Validation Errors

**Problem**: "Missing required field: status"

**Solution**: Ensure all annotations have required metadata. Check `fhir_export.py` for required fields.

---

### SNOMED CT Code Not Found

**Problem**: Label doesn't map to SNOMED CT

**Solution**: Add custom mapping in `fhir_export.py` → `snomed_mapping`

---

### Bundle Upload Fails

**Problem**: FHIR server rejects bundle

**Solution**: 
1. Validate bundle locally first (see Validation section)
2. Check FHIR server logs for specific error
3. Ensure FHIR server supports R4 (not DSTU2/STU3)

---

## References

- **FHIR R4 Spec**: http://hl7.org/fhir/R4/
- **Observation Resource**: http://hl7.org/fhir/R4/observation.html
- **DiagnosticReport Resource**: http://hl7.org/fhir/R4/diagnosticreport.html
- **ImagingStudy Resource**: http://hl7.org/fhir/R4/imagingstudy.html
- **SNOMED CT**: https://www.snomed.org/
- **LOINC**: https://loinc.org/
- **Google Cloud Healthcare API**: https://cloud.google.com/healthcare-api/docs/how-tos/fhir

---

**Last Updated**: June 2026  
**FHIR Version**: R4  
**Module**: `fhir_export.py`
