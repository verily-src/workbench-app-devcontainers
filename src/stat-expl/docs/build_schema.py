#!/usr/bin/env python3
"""
Parse all bq_*.json files and consolidate into schema.json following SPEC.md structure.
Applies clinical domain classification and generates clinical labels from raw column names.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


# Clinical domain mapping rules
DATASET_TO_DOMAIN = {
    'sensordata': 'sensor',
    'admin': 'admin',
    'screener': 'admin',
    'appsurveys': 'pro',
    'corelabreads': 'labs',
    'externallab': 'labs',
}

# CRF domain classification based on table names
CRF_TABLE_TO_DOMAIN = {
    # PRO tables (patient-reported outcomes)
    'ACE': 'pro',  # ACE questionnaire
    'DEMOG': 'ehr',  # Demographics
    'MH': 'ehr',  # Medical history
    'CM': 'medications',  # Concomitant medications
    'AE': 'outcomes',  # Adverse events
    # Default for most CRF tables is EHR
}

# Analysis domain classification based on table/column patterns
ANALYSIS_TABLE_PATTERNS = {
    'diagnoses': ['dx', 'diag', 'icd', 'condition'],
    'medications': ['med', 'drug', 'rx', 'prescription'],
    'outcomes': ['outcome', 'event', 'death', 'mortality', 'hospitalization'],
    'labs': ['lab', 'test', 'result'],
}


def clean_column_name_for_label(name: str) -> str:
    """Convert raw column name to clinical label (plain English)."""
    # Skip standard metadata columns
    metadata_cols = {'STUDYID', 'SITEID', 'SUBJID', 'USUBJID', 'VISIT', 'VISITNUM',
                     'DeviceID', 'timezone', 'study_day', 'study_day_int',
                     'questionnaire_version', 'algorithm_name', 'algorithm_version',
                     'ordinal_position', 'milliseconds_from_midnight_utc'}

    if name in metadata_cols:
        return name

    # Common abbreviation expansions
    replacements = {
        'sbp': 'systolic BP',
        'dbp': 'diastolic BP',
        'hr': 'heart rate',
        'rhr': 'resting heart rate',
        'hrv': 'HRV',
        'rmssd': 'RMSSD',
        'sdnn': 'SDNN',
        'bmi': 'BMI',
        'egfr': 'eGFR',
        'hba1c': 'HbA1c',
        'ldl': 'LDL',
        'hdl': 'HDL',
        'trig': 'triglycerides',
        'mmhg': '(mmHg)',
        'mg_dl': '(mg/dL)',
        'mmol': '(mmol/L)',
        'bpm': '(bpm)',
        'kg': '(kg)',
        'cm': '(cm)',
        'lbs': 'brachial systolic',
        'ldp': 'dorsalis pedis',
        'lpt': 'posterior tibial',
        'rbs': 'right brachial systolic',
        'rdp': 'right dorsalis pedis',
        'rpt': 'right posterior tibial',
        'abi': 'ABI',
        'perf': 'performed',
        'yn': 'yes/no',
        'num': 'number',
        'tot': 'total',
        'avg': 'average',
        'med': 'median',
        'min': 'minimum',
        'max': 'maximum',
        'waso': 'WASO',
        'rem': 'REM',
        'nrem': 'NREM',
    }

    # Convert to lowercase, split on underscores
    parts = name.lower().split('_')

    # Replace known abbreviations
    result_parts = []
    for part in parts:
        if part in replacements:
            result_parts.append(replacements[part])
        else:
            result_parts.append(part)

    # Join and capitalize
    label = ' '.join(result_parts)

    # Capitalize first letter of each sentence/major word
    label = label.replace('  ', ' ').strip()

    # Special case handling for measurements with units
    if '(' in label and ')' in label:
        # Keep units in parentheses as-is
        pass
    else:
        # Title case for normal labels
        label = ' '.join(word.capitalize() if len(word) > 2 else word for word in label.split())

    return label if label != name.lower() else name


def classify_table_domain(dataset: str, table_name: str) -> str:
    """Determine clinical domain for a table based on dataset and table name."""
    # Check dataset-level mapping first
    if dataset in DATASET_TO_DOMAIN:
        return DATASET_TO_DOMAIN[dataset]

    # CRF dataset special handling
    if dataset == 'crf':
        # Check CRF table-specific mappings
        if table_name in CRF_TABLE_TO_DOMAIN:
            return CRF_TABLE_TO_DOMAIN[table_name]

        # Check for common patterns in table name
        table_lower = table_name.lower()
        if 'med' in table_lower or 'cm' in table_lower:
            return 'medications'
        if 'vs' in table_lower or 'vital' in table_lower:
            return 'ehr'
        if 'ae' in table_lower or 'adverse' in table_lower:
            return 'outcomes'
        if any(x in table_lower for x in ['questionnaire', 'survey', 'score', 'scale']):
            return 'pro'

        # Default CRF is EHR
        return 'ehr'

    # Analysis dataset special handling
    if dataset == 'analysis':
        table_lower = table_name.lower()
        for domain, patterns in ANALYSIS_TABLE_PATTERNS.items():
            if any(pattern in table_lower for pattern in patterns):
                return domain
        # Default analysis is other
        return 'other'

    # Default fallback
    return 'other'


def classify_column_domain(dataset: str, table_name: str, column_name: str, data_type: str) -> str:
    """Determine clinical domain for a specific column."""
    # Start with table-level domain
    table_domain = classify_table_domain(dataset, table_name)

    # Refine based on column name if needed
    col_lower = column_name.lower()

    # Lab values
    if any(x in col_lower for x in ['egfr', 'creatinine', 'glucose', 'hba1c', 'ldl', 'hdl', 'trig']):
        return 'labs'

    # Medications
    if any(x in col_lower for x in ['medication', 'drug', 'dose', 'dosage']):
        return 'medications'

    # Diagnoses
    if any(x in col_lower for x in ['icd', 'diagnosis', 'condition', 'disease']):
        return 'diagnoses'

    # Outcomes
    if any(x in col_lower for x in ['death', 'mortality', 'hospitalization', 'adverse', 'event']):
        return 'outcomes'

    # Vitals/measurements
    if any(x in col_lower for x in ['sbp', 'dbp', 'hr', 'bp', 'weight', 'height', 'bmi', 'temp']):
        return 'ehr'

    # PRO
    if any(x in col_lower for x in ['score', 'questionnaire', 'survey', 'reported']):
        return 'pro'

    # Sensor
    if any(x in col_lower for x in ['step', 'sleep', 'hrv', 'activity', 'wear', 'pulse']):
        return 'sensor'

    # Otherwise use table domain
    return table_domain


def is_candidate_endpoint(column_name: str, data_type: str, domain: str) -> bool:
    """Determine if column is a plausible study endpoint."""
    col_lower = column_name.lower()

    # Outcomes domain is likely endpoint
    if domain == 'outcomes':
        return True

    # Lab values can be endpoints
    if domain == 'labs' and data_type in ['FLOAT64', 'INT64', 'NUMERIC']:
        return True

    # Sensor metrics can be endpoints
    if domain == 'sensor' and any(x in col_lower for x in ['hrv', 'sleep', 'step', 'pulse', 'rhr']):
        return True

    # PRO scores can be endpoints
    if domain == 'pro' and 'score' in col_lower:
        return True

    # Specific endpoint indicators
    if any(x in col_lower for x in ['death', 'mortality', 'hospitalization', 'event', 'outcome']):
        return True

    # Vital sign changes can be endpoints
    if any(x in col_lower for x in ['sbp', 'dbp', 'hr', 'bmi', 'weight', 'hba1c', 'egfr']):
        if data_type in ['FLOAT64', 'INT64', 'NUMERIC']:
            return True

    return False


def is_candidate_exposure(column_name: str, data_type: str, domain: str) -> bool:
    """Determine if column is a plausible exposure/treatment."""
    col_lower = column_name.lower()

    # Medications domain
    if domain == 'medications':
        return True

    # Specific exposure indicators
    if any(x in col_lower for x in ['medication', 'drug', 'treatment', 'therapy', 'intervention', 'dose']):
        return True

    # Risk factors
    if any(x in col_lower for x in ['smoking', 'alcohol', 'exercise', 'diet']):
        return True

    return False


def is_candidate_confounder(column_name: str, data_type: str, domain: str) -> bool:
    """Determine if column is a plausible confounder for adjustment."""
    col_lower = column_name.lower()

    # Standard demographic adjusters
    if any(x in col_lower for x in ['age', 'sex', 'gender', 'race', 'ethnicity']):
        return True

    # Clinical confounders
    if any(x in col_lower for x in ['bmi', 'weight', 'comorbid', 'charlson', 'severity']):
        return True

    # Site and temporal confounders
    if any(x in col_lower for x in ['site', 'siteid', 'enrollment', 'year']):
        return True

    # Prior treatment
    if 'prior' in col_lower or 'baseline' in col_lower:
        return True

    return False


def load_json(filepath: Path) -> List[Dict]:
    """Load JSON file, return empty list if error."""
    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
            # Handle empty or null results
            if data is None:
                return []
            return data if isinstance(data, list) else [data]
    except Exception as e:
        print(f"Warning: Could not load {filepath}: {e}")
        return []


def main():
    docs_dir = Path(__file__).parent

    # Load datasets list
    datasets_data = load_json(docs_dir / 'bq_datasets.json')
    dataset_names = [d['datasetReference']['datasetId'] for d in datasets_data]

    print(f"Found {len(dataset_names)} datasets: {', '.join(dataset_names)}")

    # Build consolidated schema
    schema = {
        "data_project": "wb-spotless-eggplant-4340",
        "app_project": "wb-rapid-apricot-2196",
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "datasets": []
    }

    for dataset_name in dataset_names:
        print(f"\nProcessing dataset: {dataset_name}")

        # Load dataset-specific files
        tables_data = load_json(docs_dir / f'bq_{dataset_name}_tables.json')
        columns_data = load_json(docs_dir / f'bq_{dataset_name}_columns.json')
        descriptions_data = load_json(docs_dir / f'bq_{dataset_name}_descriptions.json')
        partitions_data = load_json(docs_dir / f'bq_{dataset_name}_partitions.json')

        # Build lookup dictionaries
        table_info = {t['table_id']: t for t in tables_data}

        # Build column lookup by table
        columns_by_table = {}
        for col in columns_data:
            table_name = col['table_name']
            if table_name not in columns_by_table:
                columns_by_table[table_name] = []
            columns_by_table[table_name].append(col)

        # Build description lookup
        desc_lookup = {}
        for desc in descriptions_data:
            key = (desc['table_name'], desc['column_name'])
            desc_lookup[key] = {
                'column_description': desc.get('column_description') or '',
                'table_description': desc.get('table_description') or ''
            }

        # Build partition column lookup
        partition_lookup = {}
        for part in partitions_data:
            table_name = part['table_name']
            if part.get('is_partitioning_column') == 'YES':
                partition_lookup[table_name] = part['column_name']

        # Build tables list
        tables = []
        for table_name, columns in columns_by_table.items():
            info = table_info.get(table_name, {})

            # Get table description from any column in this table
            table_desc = ''
            for col in columns:
                key = (table_name, col['column_name'])
                if key in desc_lookup:
                    table_desc = desc_lookup[key]['table_description']
                    if table_desc:
                        break

            # Determine domain for this table
            table_domain = classify_table_domain(dataset_name, table_name)

            # Build columns list
            column_list = []
            for col in columns:
                col_name = col['column_name']
                col_type = col['data_type']

                # Get column description
                key = (table_name, col_name)
                col_desc = desc_lookup.get(key, {}).get('column_description', '')

                # Generate clinical label
                clinical_label = clean_column_name_for_label(col_name)

                # Determine column domain
                col_domain = classify_column_domain(dataset_name, table_name, col_name, col_type)

                # Determine flags
                is_endpoint = is_candidate_endpoint(col_name, col_type, col_domain)
                is_exposure = is_candidate_exposure(col_name, col_type, col_domain)
                is_confounder = is_candidate_confounder(col_name, col_type, col_domain)

                column_list.append({
                    "name": col_name,
                    "type": col_type,
                    "nullable": col['is_nullable'] == 'YES',
                    "ordinal_position": int(col['ordinal_position']),
                    "clinical_label": clinical_label,
                    "clinical_domain": col_domain,
                    "description": col_desc,
                    "is_candidate_endpoint": is_endpoint,
                    "is_candidate_exposure": is_exposure,
                    "is_candidate_confounder": is_confounder
                })

            # Sort columns by ordinal position
            column_list.sort(key=lambda x: x['ordinal_position'])

            # Build table object
            table_obj = {
                "name": table_name,
                "dataset": dataset_name,
                "domain": table_domain,
                "row_count": int(info.get('row_count', 0)),
                "size_mb": float(info.get('size_mb', 0)),
                "last_modified": info.get('last_modified', ''),
                "description": table_desc,
                "partition_column": partition_lookup.get(table_name),
                "columns": column_list
            }

            tables.append(table_obj)

        # Sort tables by row count descending
        tables.sort(key=lambda x: x['row_count'], reverse=True)

        # Add dataset to schema
        schema['datasets'].append({
            "name": dataset_name,
            "tables": tables
        })

        print(f"  - {len(tables)} tables, {sum(len(t['columns']) for t in tables)} columns")

    # Write schema.json
    output_path = docs_dir / 'schema.json'
    with open(output_path, 'w') as f:
        json.dump(schema, f, indent=2)

    print(f"\n✓ Schema written to {output_path}")
    print(f"  Total datasets: {len(schema['datasets'])}")
    print(f"  Total tables: {sum(len(d['tables']) for d in schema['datasets'])}")
    print(f"  Total columns: {sum(sum(len(t['columns']) for t in d['tables']) for d in schema['datasets'])}")


if __name__ == '__main__':
    main()
