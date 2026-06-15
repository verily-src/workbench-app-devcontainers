"""
FHIR Export Module for Glyph Annotation Tool

Converts annotations to FHIR R4 resources:
- Observation: Individual annotated findings
- ImagingStudy: Reference to source medical images
- DiagnosticReport: Aggregated annotation session report
- BodyStructure: Anatomical regions with SNOMED CT codes
"""

from datetime import datetime
from typing import List, Dict, Any
import uuid


def generate_observation(annotation: Dict[str, Any], task: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate a FHIR R4 Observation resource from an annotation.

    Args:
        annotation: Annotation data with bboxes and labels
        task: Task metadata (image path, task_id)

    Returns:
        FHIR Observation resource (dict)
    """
    observation_id = annotation.get('annotation_id', str(uuid.uuid4()))

    # Extract first bbox for demonstration (in production, iterate through all)
    bboxes = annotation.get('annotation_data', {}).get('bboxes', [])
    if not bboxes:
        return None

    bbox = bboxes[0]
    label = bbox.get('label', 'Unknown')

    # Map common labels to SNOMED CT codes (example mapping)
    snomed_mapping = {
        'Batting': {'code': '228557005', 'display': 'Person batting'},
        'Bowling': {'code': '228558000', 'display': 'Person bowling'},
        'Person': {'code': '125676002', 'display': 'Person'},
        'Object': {'code': '260787004', 'display': 'Physical object'},
        'Nodule': {'code': '27925004', 'display': 'Nodule'},
        'Mass': {'code': '300848003', 'display': 'Mass'},
        'Lesion': {'code': '52988006', 'display': 'Lesion'}
    }

    snomed = snomed_mapping.get(label, {'code': '123037004', 'display': 'Body structure'})

    observation = {
        'resourceType': 'Observation',
        'id': observation_id,
        'status': 'final',
        'category': [{
            'coding': [{
                'system': 'http://terminology.hl7.org/CodeSystem/observation-category',
                'code': 'imaging',
                'display': 'Imaging'
            }]
        }],
        'code': {
            'coding': [{
                'system': 'http://snomed.info/sct',
                'code': snomed['code'],
                'display': snomed['display']
            }],
            'text': label
        },
        'subject': {
            'reference': f"Patient/{annotation.get('patient_id', 'unknown')}"
        },
        'effectiveDateTime': annotation.get('created_at', datetime.utcnow().isoformat()),
        'issued': annotation.get('created_at', datetime.utcnow().isoformat()),
        'performer': [{
            'reference': f"Practitioner/{annotation.get('annotator', 'unknown')}",
            'display': annotation.get('annotator', 'Unknown Annotator')
        }],
        'valueCodeableConcept': {
            'coding': [{
                'system': 'http://snomed.info/sct',
                'code': snomed['code'],
                'display': snomed['display']
            }],
            'text': f"{label} detected"
        },
        'component': [
            {
                'code': {
                    'coding': [{
                        'system': 'http://loinc.org',
                        'code': '59776-5',
                        'display': 'Bounding box coordinates'
                    }]
                },
                'valueString': f"x:{bbox['x']}, y:{bbox['y']}, width:{bbox['width']}, height:{bbox['height']}"
            },
            {
                'code': {
                    'coding': [{
                        'system': 'http://loinc.org',
                        'code': '82810-3',
                        'display': 'Confidence score'
                    }]
                },
                'valueQuantity': {
                    'value': bbox.get('confidence', 1.0),
                    'unit': 'probability',
                    'system': 'http://unitsofmeasure.org',
                    'code': '1'
                }
            }
        ],
        'derivedFrom': [{
            'reference': f"ImagingStudy/{task.get('task_id', 'unknown')}"
        }]
    }

    return observation


def generate_imaging_study(task: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate a FHIR R4 ImagingStudy resource from a task.

    Args:
        task: Task metadata (image path, task_id)

    Returns:
        FHIR ImagingStudy resource (dict)
    """
    study_id = task.get('task_id', str(uuid.uuid4()))

    imaging_study = {
        'resourceType': 'ImagingStudy',
        'id': study_id,
        'status': 'available',
        'subject': {
            'reference': f"Patient/{task.get('patient_id', 'unknown')}"
        },
        'started': task.get('created_at', datetime.utcnow().isoformat()),
        'numberOfSeries': 1,
        'numberOfInstances': 1,
        'series': [{
            'uid': f"{study_id}.1",
            'number': 1,
            'modality': {
                'system': 'http://dicom.nema.org/resources/ontology/DCM',
                'code': 'OT',  # Other
                'display': 'Other'
            },
            'numberOfInstances': 1,
            'instance': [{
                'uid': f"{study_id}.1.1",
                'sopClass': {
                    'system': 'urn:ietf:rfc:3986',
                    'code': 'urn:oid:1.2.840.10008.5.1.4.1.1.7'
                },
                'number': 1,
                'title': task.get('image_path', 'Unknown image')
            }]
        }]
    }

    return imaging_study


def generate_diagnostic_report(
    annotations: List[Dict[str, Any]],
    task: Dict[str, Any],
    session_id: str = None
) -> Dict[str, Any]:
    """
    Generate a FHIR R4 DiagnosticReport aggregating all annotations for a task.

    Args:
        annotations: List of annotations for this task
        task: Task metadata
        session_id: Optional session identifier

    Returns:
        FHIR DiagnosticReport resource (dict)
    """
    report_id = session_id or str(uuid.uuid4())

    # Count findings by label
    label_counts = {}
    total_bboxes = 0
    for ann in annotations:
        for bbox in ann.get('annotation_data', {}).get('bboxes', []):
            label = bbox.get('label', 'Unknown')
            label_counts[label] = label_counts.get(label, 0) + 1
            total_bboxes += 1

    # Generate conclusion summary
    conclusion_parts = [f"{count} {label}(s)" for label, count in label_counts.items()]
    conclusion = f"Annotation identified {total_bboxes} total findings: " + ", ".join(conclusion_parts)

    diagnostic_report = {
        'resourceType': 'DiagnosticReport',
        'id': report_id,
        'status': 'final',
        'category': [{
            'coding': [{
                'system': 'http://terminology.hl7.org/CodeSystem/v2-0074',
                'code': 'IMG',
                'display': 'Diagnostic Imaging'
            }]
        }],
        'code': {
            'coding': [{
                'system': 'http://loinc.org',
                'code': '18748-4',
                'display': 'Diagnostic imaging study'
            }],
            'text': 'Annotation Report'
        },
        'subject': {
            'reference': f"Patient/{task.get('patient_id', 'unknown')}"
        },
        'effectiveDateTime': datetime.utcnow().isoformat(),
        'issued': datetime.utcnow().isoformat(),
        'performer': [{
            'reference': f"Practitioner/{annotations[0].get('annotator', 'unknown')}" if annotations else "Practitioner/unknown"
        }],
        'imagingStudy': [{
            'reference': f"ImagingStudy/{task.get('task_id', 'unknown')}"
        }],
        'conclusion': conclusion,
        'conclusionCode': [{
            'coding': [{
                'system': 'http://snomed.info/sct',
                'code': '260413007',
                'display': 'Annotation completed'
            }]
        }]
    }

    # Add references to individual Observations
    diagnostic_report['result'] = [
        {'reference': f"Observation/{ann.get('annotation_id', 'unknown')}"}
        for ann in annotations
    ]

    return diagnostic_report


def generate_body_structure(bbox: Dict[str, Any], annotation_id: str) -> Dict[str, Any]:
    """
    Generate a FHIR R4 BodyStructure resource for an annotated region.

    Args:
        bbox: Bounding box data with label
        annotation_id: Parent annotation ID

    Returns:
        FHIR BodyStructure resource (dict)
    """
    label = bbox.get('label', 'Unknown')

    # Map labels to anatomical structures (SNOMED CT)
    anatomy_mapping = {
        'Head': {'code': '69536005', 'display': 'Head structure'},
        'Chest': {'code': '51185008', 'display': 'Thoracic structure'},
        'Lung': {'code': '39607008', 'display': 'Lung structure'},
        'Heart': {'code': '80891009', 'display': 'Heart structure'},
        'Nodule': {'code': '27925004', 'display': 'Nodule'},
        'Person': {'code': '442083009', 'display': 'Anatomical or acquired body structure'}
    }

    anatomy = anatomy_mapping.get(label, {'code': '123037004', 'display': 'Body structure'})

    body_structure = {
        'resourceType': 'BodyStructure',
        'id': f"{annotation_id}-bodystructure",
        'active': True,
        'morphology': {
            'coding': [{
                'system': 'http://snomed.info/sct',
                'code': anatomy['code'],
                'display': anatomy['display']
            }],
            'text': label
        },
        'location': {
            'coding': [{
                'system': 'http://snomed.info/sct',
                'code': anatomy['code'],
                'display': anatomy['display']
            }]
        },
        'patient': {
            'reference': 'Patient/unknown'
        },
        'extension': [{
            'url': 'http://example.org/fhir/StructureDefinition/bounding-box',
            'extension': [
                {'url': 'x', 'valueDecimal': bbox['x']},
                {'url': 'y', 'valueDecimal': bbox['y']},
                {'url': 'width', 'valueDecimal': bbox['width']},
                {'url': 'height', 'valueDecimal': bbox['height']}
            ]
        }]
    }

    return body_structure


def export_to_fhir_bundle(
    annotations: List[Dict[str, Any]],
    tasks: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Export all annotations as a FHIR Bundle containing multiple resources.

    Args:
        annotations: List of all annotations
        tasks: List of tasks (for context)

    Returns:
        FHIR Bundle resource containing Observations, ImagingStudies, DiagnosticReport
    """
    bundle_id = str(uuid.uuid4())

    entries = []

    # Group annotations by task
    task_annotations = {}
    for ann in annotations:
        task_id = ann.get('task_id')
        if task_id not in task_annotations:
            task_annotations[task_id] = []
        task_annotations[task_id].append(ann)

    # Create resources for each task
    for task in tasks:
        task_id = task.get('task_id')
        task_anns = task_annotations.get(task_id, [])

        if not task_anns:
            continue

        # 1. ImagingStudy
        imaging_study = generate_imaging_study(task)
        entries.append({
            'fullUrl': f"urn:uuid:{imaging_study['id']}",
            'resource': imaging_study,
            'request': {
                'method': 'POST',
                'url': 'ImagingStudy'
            }
        })

        # 2. Observations (one per annotation)
        for ann in task_anns:
            observation = generate_observation(ann, task)
            if observation:
                entries.append({
                    'fullUrl': f"urn:uuid:{observation['id']}",
                    'resource': observation,
                    'request': {
                        'method': 'POST',
                        'url': 'Observation'
                    }
                })

        # 3. DiagnosticReport (aggregates all observations for this task)
        diagnostic_report = generate_diagnostic_report(task_anns, task)
        entries.append({
            'fullUrl': f"urn:uuid:{diagnostic_report['id']}",
            'resource': diagnostic_report,
            'request': {
                'method': 'POST',
                'url': 'DiagnosticReport'
            }
        })

    # Create the Bundle
    bundle = {
        'resourceType': 'Bundle',
        'id': bundle_id,
        'type': 'transaction',
        'timestamp': datetime.utcnow().isoformat(),
        'entry': entries,
        'total': len(entries)
    }

    return bundle


def validate_fhir_resource(resource: Dict[str, Any]) -> bool:
    """
    Basic validation of FHIR resource structure.

    Args:
        resource: FHIR resource to validate

    Returns:
        True if valid, False otherwise
    """
    # Check required fields
    if 'resourceType' not in resource:
        return False

    # Resource-specific validation
    resource_type = resource['resourceType']

    if resource_type == 'Observation':
        required = ['status', 'code']
        return all(field in resource for field in required)

    elif resource_type == 'ImagingStudy':
        required = ['status', 'subject']
        return all(field in resource for field in required)

    elif resource_type == 'DiagnosticReport':
        required = ['status', 'code', 'subject']
        return all(field in resource for field in required)

    elif resource_type == 'Bundle':
        required = ['type', 'entry']
        return all(field in resource for field in required)

    return True
