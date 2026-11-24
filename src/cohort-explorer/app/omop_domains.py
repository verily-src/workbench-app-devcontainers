"""The OMOP domains the cohort builder can use.

Plain data only. Do not import anything here, so any file can read this one safely.
To add a domain, add one entry. Each entry names the event table, the concept column and the start date column.
An entry may also name a value column. A "Has" rule on that domain then gets lowest and highest value columns.
"""

OMOP_DOMAINS = {
    "condition": {
        "table": "condition_occurrence",
        "concept_column": "condition_concept_id",
        "date_column": "condition_start_date",
    },
    "drug": {
        "table": "drug_exposure",
        "concept_column": "drug_concept_id",
        "date_column": "drug_exposure_start_date",
    },
    "observation": {
        "table": "observation",
        "concept_column": "observation_concept_id",
        "date_column": "observation_date",
    },
    "procedure": {
        "table": "procedure_occurrence",
        "concept_column": "procedure_concept_id",
        "date_column": "procedure_date",
    },
    "measurement": {
        "table": "measurement",
        "concept_column": "measurement_concept_id",
        "date_column": "measurement_date",
        "value_column": "value_as_number",
    },
}
