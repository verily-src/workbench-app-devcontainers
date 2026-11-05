"""OMOP CDM event domains: their tables, concept and date columns.

Dependency-free so the standalone loader (omop_load.py) can import it.
"""

DOMAINS = {
    "condition": {"table": "condition_occurrence", "concept": "condition_concept_id",
                  "date": "condition_start_date"},
    "drug": {"table": "drug_exposure", "concept": "drug_concept_id",
             "date": "drug_exposure_start_date"},
    "procedure": {"table": "procedure_occurrence", "concept": "procedure_concept_id",
                  "date": "procedure_date"},
    "measurement": {"table": "measurement", "concept": "measurement_concept_id",
                    "date": "measurement_date", "value": "value_as_number"},
    "observation": {"table": "observation", "concept": "observation_concept_id",
                    "date": "observation_date"},
    "visit": {"table": "visit_occurrence", "concept": "visit_concept_id",
              "date": "visit_start_date"},
    "device": {"table": "device_exposure", "concept": "device_concept_id",
               "date": "device_exposure_start_date"},
    "death": {"table": "death", "concept": "cause_concept_id", "date": "death_date"},
}
