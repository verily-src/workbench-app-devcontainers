# Schema Generation Documentation

## Overview

The `build_schema.py` script consolidates all BigQuery metadata JSON files into a single `schema.json` file following the structure defined in `SPEC.md`.

## Input Files

The script reads the following JSON files from the `docs/` directory:

- `bq_datasets.json` - List of all datasets in the data project
- For each dataset:
  - `bq_{dataset}_tables.json` - Table metadata (row counts, sizes, timestamps)
  - `bq_{dataset}_columns.json` - Column metadata (names, types, positions)
  - `bq_{dataset}_descriptions.json` - Table and column descriptions
  - `bq_{dataset}_partitions.json` - Partition and clustering information

## Output

A single `schema.json` file containing:
- Data project and app project identifiers
- ISO timestamp of extraction
- All datasets with their tables and columns
- Clinical domain classifications
- Clinical labels (plain English names)
- Candidate flags for endpoints, exposures, and confounders

## Clinical Domain Classification

### Dataset-Level Mappings

- **sensordata** → sensor
- **admin** → admin
- **screener** → admin
- **appsurveys** → pro
- **corelabreads** → labs
- **externallab** → labs

### CRF Dataset

Tables in the CRF dataset are classified based on table names:
- Questionnaires/surveys/scores → **pro**
- Medications (CM, etc.) → **medications**
- Adverse events (AE) → **outcomes**
- Vital signs → **ehr**
- Default → **ehr**

### Analysis Dataset

Tables in the analysis dataset are classified based on name patterns:
- Contains "dx", "diag", "icd", "condition" → **diagnoses**
- Contains "med", "drug", "rx", "prescription" → **medications**
- Contains "outcome", "event", "death", "mortality", "hospitalization" → **outcomes**
- Contains "lab", "test", "result" → **labs**
- Default → **other**

### Column-Level Refinement

Individual columns can be reclassified based on column name patterns:
- Lab values (eGFR, creatinine, HbA1c, etc.) → **labs**
- Medications/drugs/doses → **medications**
- ICD codes/diagnoses → **diagnoses**
- Mortality/hospitalization → **outcomes**
- Vital signs (BP, HR, etc.) → **ehr**
- PRO scores → **pro**
- Sensor metrics (steps, sleep, HRV) → **sensor**

## Clinical Label Generation

Raw column names are converted to plain English labels:

### Abbreviation Expansion

Common clinical abbreviations are expanded:
- `sbp` → "systolic BP"
- `dbp` → "diastolic BP"
- `hr` → "heart rate"
- `rhr` → "resting heart rate"
- `hrv` → "HRV"
- `bmi` → "BMI"
- `egfr` → "eGFR"
- `hba1c` → "HbA1c"
- And many more...

### Examples

- `vs_sbp1_mmhg` → "Vs systolic BP 1 (mmHg)"
- `abi_rbs_mmhg` → "ABI right brachial systolic (mmHg)"
- `pulse_rate` → "Pulse Rate"
- `total_sleep_time` → "Total Sleep Time"
- `cohort_eligibility` → "Cohort Eligibility"

## Candidate Flags

### is_candidate_endpoint

Set to `true` when column is a plausible study outcome:
- Domain is "outcomes"
- Numeric lab values
- Sensor metrics (HRV, sleep, steps, pulse)
- PRO scores
- Death/mortality/hospitalization indicators
- Numeric vital signs (BP, HR, BMI, HbA1c, eGFR)

### is_candidate_exposure

Set to `true` when column is a plausible treatment/risk factor:
- Domain is "medications"
- Column name contains: medication, drug, treatment, therapy, intervention, dose
- Risk factors: smoking, alcohol, exercise, diet

### is_candidate_confounder

Set to `true` when column is a standard adjustment variable:
- Demographics: age, sex, gender, race, ethnicity
- Clinical: BMI, weight, comorbidity, Charlson index, severity
- Site and temporal: site, siteid, enrollment year
- Prior treatment: baseline values, prior medications

## Running the Script

```bash
cd /home/jupyter/temp-devcontainers/src/stat-expl/docs
python3 build_schema.py
```

The script will:
1. Load all input JSON files
2. Build the consolidated schema structure
3. Classify all tables and columns
4. Generate clinical labels
5. Set candidate flags
6. Write `schema.json` with ISO timestamp

## Output Summary

After running, the script prints:
- Number of datasets found
- Tables per dataset
- Total columns
- Domain distributions
- Candidate flag counts
- Description coverage
- Partition columns found

## Notes

- All descriptions in the current dataset are empty (NULL)
- No partition columns are currently defined
- The script handles missing/null values gracefully
- Metadata columns (STUDYID, SITEID, etc.) are preserved but not flagged as candidates
