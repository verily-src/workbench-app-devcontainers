"""The small OMOP test database from section 4.2 of omop-poc-spec.md.

The schema is called "omop". The concept IDs and names are test values. The tests write the
expected results by hand, so they never depend on the code under test.
Concept 99999999 has no row in "concept", on purpose.
"""

OMOP_SCHEMA = "omop"

OMOP_FIXTURE_STATEMENTS = [
    "CREATE SCHEMA omop",
    """CREATE TABLE omop.person (
        person_id integer PRIMARY KEY,
        gender_concept_id integer,
        race_concept_id integer,
        ethnicity_concept_id integer,
        year_of_birth integer
    )""",
    """CREATE TABLE omop.concept (
        concept_id integer PRIMARY KEY,
        concept_name text,
        domain_id text,
        vocabulary_id text
    )""",
    "CREATE TABLE omop.condition_occurrence (person_id integer, condition_concept_id integer, condition_start_date date)",
    "CREATE TABLE omop.drug_exposure (person_id integer, drug_concept_id integer, drug_exposure_start_date date)",
    "CREATE TABLE omop.procedure_occurrence (person_id integer, procedure_concept_id integer, procedure_date date)",
    "CREATE TABLE omop.observation (person_id integer, observation_concept_id integer, observation_date date)",
    "CREATE TABLE omop.measurement (person_id integer, measurement_concept_id integer, measurement_date date, value_as_number numeric)",
    """INSERT INTO omop.person VALUES
        (1, 8507, 8527, 38003564, 1950),
        (2, 8532, 8516, 38003564, 1960),
        (3, 8507, 8527, 38003563, 1970),
        (4, 8532, 8527, 38003564, 1980),
        (5, 8507, 8516, 38003564, 1990),
        (6, 8532, 99999999, 38003564, 2000)""",
    """INSERT INTO omop.concept VALUES
        (8507, 'Male', 'Gender', 'Gender'),
        (8532, 'Female', 'Gender', 'Gender'),
        (8527, 'White', 'Race', 'Race'),
        (8516, 'Black or African American', 'Race', 'Race'),
        (38003564, 'Not Hispanic or Latino', 'Ethnicity', 'Ethnicity'),
        (38003563, 'Hispanic or Latino', 'Ethnicity', 'Ethnicity'),
        (201826, 'Type 2 diabetes mellitus', 'Condition', 'SNOMED'),
        (320128, 'Essential hypertension', 'Condition', 'SNOMED'),
        (40000001, 'Metformin 500 MG Oral Tablet', 'Drug', 'RxNorm'),
        (40000002, 'Metformin 1000 MG Oral Tablet', 'Drug', 'RxNorm'),
        (40000003, 'Lisinopril 10 MG Oral Tablet', 'Drug', 'RxNorm'),
        (1503297, 'Metformin', 'Drug', 'RxNorm'),
        (4000001, 'Colonoscopy', 'Procedure', 'SNOMED'),
        (4000002, 'Appendectomy', 'Procedure', 'SNOMED'),
        (4100001, 'Current every day smoker', 'Observation', 'SNOMED'),
        (4100002, 'Never smoker', 'Observation', 'SNOMED'),
        (4200001, 'Hemoglobin A1c', 'Measurement', 'LOINC'),
        (4200002, 'Body mass index', 'Measurement', 'LOINC')""",
    """INSERT INTO omop.condition_occurrence VALUES
        (1, 201826, '2020-01-10'), (1, 201826, '2021-03-05'), (2, 201826, '2019-06-01'),
        (2, 320128, '2018-02-02'), (3, 320128, '2017-07-07'), (4, 201826, '2022-04-04')""",
    """INSERT INTO omop.drug_exposure VALUES
        (1, 40000001, '2020-02-01'), (2, 40000002, '2019-07-01'), (3, 40000001, '2018-03-03'),
        (4, 40000003, '2022-05-05')""",
    """INSERT INTO omop.procedure_occurrence VALUES
        (1, 4000001, '2020-05-05'), (2, 4000001, '2019-01-01'), (3, 4000002, '2018-08-08')""",
    """INSERT INTO omop.observation VALUES
        (1, 4100001, '2020-03-03'), (2, 4100002, '2019-09-09'), (4, 4100001, '2022-02-02')""",
    """INSERT INTO omop.measurement VALUES
        (1, 4200001, '2020-04-04', 6.1), (1, 4200001, '2021-04-04', 7.4),
        (3, 4200001, '2017-06-06', 5.2), (2, 4200002, '2019-02-02', 27.5),
        (4, 4200002, '2022-06-06', NULL)""",
]
