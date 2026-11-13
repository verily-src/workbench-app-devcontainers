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
    "CREATE TABLE omop.condition_occurrence (person_id integer, condition_concept_id integer)",
    "CREATE TABLE omop.drug_exposure (person_id integer, drug_concept_id integer)",
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
        (1503297, 'Metformin', 'Drug', 'RxNorm')""",
    """INSERT INTO omop.condition_occurrence VALUES
        (1, 201826), (1, 201826), (2, 201826), (2, 320128), (3, 320128), (4, 201826)""",
    """INSERT INTO omop.drug_exposure VALUES
        (1, 40000001), (2, 40000002), (3, 40000001), (4, 40000003)""",
]
