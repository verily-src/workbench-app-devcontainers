# OMOP CDM Join Patterns and Table Relationships

This document provides practical guidance on how to join OMOP CDM tables correctly. Master these patterns and your queries will be correct and efficient.

## Core Join Pattern: The Person Hub

**Principle:** Person table is the central hub for all patient-level analysis.

```
           ┌─────────────┐
           │   person    │ ← Central hub
           └──────┬──────┘
                  │
        ┌─────────┼─────────┐
        │         │         │
        ▼         ▼         ▼
 ┌──────────┐ ┌────────┐ ┌──────────┐
 │condition │ │  drug  │ │procedure │
 │occurrence│ │exposure│ │occurrence│
 └──────────┘ └────────┘ └──────────┘
```

**All clinical event tables join to person via `person_id`**

---

## Pattern 1: Person → Clinical Event

### Template
```sql
SELECT p.person_id, [person columns], [event columns]
FROM person p
[LEFT/INNER] JOIN [clinical_table] ct ON p.person_id = ct.person_id
WHERE [conditions]
LIMIT 1000;
```

### Example: Person → Conditions
```sql
SELECT p.person_id,
       g.concept_name AS gender,
       p.year_of_birth,
       c.concept_name AS condition,
       co.condition_start_date
FROM person p
INNER JOIN condition_occurrence co ON p.person_id = co.person_id
INNER JOIN concept c ON co.condition_concept_id = c.concept_id
LEFT JOIN concept g ON p.gender_concept_id = g.concept_id
WHERE c.concept_name LIKE '%diabetes%'
LIMIT 1000;
```

### LEFT vs INNER JOIN Decision

**Use INNER JOIN when:**
- You want only patients WITH the event
- Example: "Find patients who have diabetes"

**Use LEFT JOIN when:**
- You want all patients, regardless of whether they have the event
- Example: "Show all patients and their conditions (if any)"
- Useful for checking completeness

---

## Pattern 2: Clinical Event → Concept (Mandatory)

### Template
```sql
SELECT [event columns], c.concept_name AS [readable_name]
FROM [clinical_table] ct
INNER JOIN concept c ON ct.[concept_id_column] = c.concept_id
WHERE [conditions]
LIMIT 1000;
```

### Rule: ALWAYS Join with Concept Table

**Why:** Concept IDs are just numbers. Users need readable names.

```sql
-- ❌ WRONG - returns numbers
SELECT condition_concept_id FROM condition_occurrence LIMIT 1000;
-- Returns: 201826, 320128, ...

-- ✅ CORRECT - returns readable names
SELECT c.concept_name
FROM condition_occurrence co
JOIN concept c ON co.condition_concept_id = c.concept_id
LIMIT 1000;
-- Returns: "Type 2 diabetes mellitus", "Hypertension", ...
```

### Multiple Concept Joins in One Table

Many clinical tables have multiple `_concept_id` columns. Join each one you need:

```sql
SELECT co.person_id,
       cc.concept_name AS condition,
       tc.concept_name AS type_of_record,
       sc.concept_name AS status
FROM condition_occurrence co
INNER JOIN concept cc ON co.condition_concept_id = cc.concept_id
LEFT JOIN concept tc ON co.condition_type_concept_id = tc.concept_id
LEFT JOIN concept sc ON co.condition_status_concept_id = sc.concept_id
LIMIT 1000;
```

**Tip:** Use table aliases that indicate which concept:
- `cc` = condition concept
- `tc` = type concept
- `sc` = status concept

---

## Pattern 3: Person → Multiple Clinical Events

### Template
```sql
SELECT p.person_id,
       [person demographics],
       [aggregations from clinical tables]
FROM person p
LEFT JOIN [clinical_table_1] ct1 ON p.person_id = ct1.person_id
LEFT JOIN [clinical_table_2] ct2 ON p.person_id = ct2.person_id
WHERE [conditions]
GROUP BY p.person_id, [person columns]
LIMIT 1000;
```

### Example: Patient Summary Across All Clinical Domains
```sql
SELECT p.person_id,
       g.concept_name AS gender,
       p.year_of_birth,
       COUNT(DISTINCT co.condition_occurrence_id) AS num_conditions,
       COUNT(DISTINCT de.drug_exposure_id) AS num_drugs,
       COUNT(DISTINCT po.procedure_occurrence_id) AS num_procedures,
       COUNT(DISTINCT m.measurement_id) AS num_measurements,
       COUNT(DISTINCT vo.visit_occurrence_id) AS num_visits
FROM person p
LEFT JOIN concept g ON p.gender_concept_id = g.concept_id
LEFT JOIN condition_occurrence co ON p.person_id = co.person_id
LEFT JOIN drug_exposure de ON p.person_id = de.person_id
LEFT JOIN procedure_occurrence po ON p.person_id = po.person_id
LEFT JOIN measurement m ON p.person_id = m.person_id
LEFT JOIN visit_occurrence vo ON p.person_id = vo.person_id
GROUP BY p.person_id, g.concept_name, p.year_of_birth
HAVING COUNT(DISTINCT co.condition_occurrence_id) > 0
LIMIT 1000;
```

**Key:** Use LEFT JOIN to avoid filtering out patients without events, then filter in HAVING if needed.

---

## Pattern 4: Event → Visit Context

### Template
```sql
SELECT [event columns],
       vc.concept_name AS visit_type,
       vo.visit_start_date
FROM [clinical_table] ct
LEFT JOIN visit_occurrence vo ON ct.visit_occurrence_id = vo.visit_occurrence_id
LEFT JOIN concept vc ON vo.visit_concept_id = vc.concept_id
WHERE [conditions]
LIMIT 1000;
```

### Example: Conditions with Visit Context
```sql
SELECT co.person_id,
       cc.concept_name AS condition,
       co.condition_start_date,
       vc.concept_name AS visit_type,
       vo.visit_start_date,
       vo.visit_end_date
FROM condition_occurrence co
INNER JOIN concept cc ON co.condition_concept_id = cc.concept_id
LEFT JOIN visit_occurrence vo ON co.visit_occurrence_id = vo.visit_occurrence_id
LEFT JOIN concept vc ON vo.visit_concept_id = vc.concept_id
WHERE cc.concept_name LIKE '%diabetes%'
LIMIT 1000;
```

**When to use:** Understanding clinical context (inpatient vs outpatient, ER vs clinic)

---

## Pattern 5: Condition → Treatment (Condition + Drug)

### Template
```sql
SELECT DISTINCT p.person_id,
       cc.concept_name AS condition,
       dc.concept_name AS drug
FROM person p
INNER JOIN condition_occurrence co ON p.person_id = co.person_id
INNER JOIN concept cc ON co.condition_concept_id = cc.concept_id
INNER JOIN drug_exposure de ON p.person_id = de.person_id
INNER JOIN concept dc ON de.drug_concept_id = dc.concept_id
WHERE cc.concept_name LIKE '%[condition]%'
  AND dc.concept_name LIKE '%[drug]%'
LIMIT 1000;
```

### Example: Diabetes Patients on Metformin
```sql
SELECT DISTINCT p.person_id,
       cc.concept_name AS diabetes_type,
       dc.concept_name AS medication,
       de.drug_exposure_start_date
FROM person p
INNER JOIN condition_occurrence co ON p.person_id = co.person_id
INNER JOIN concept cc ON co.condition_concept_id = cc.concept_id
INNER JOIN drug_exposure de ON p.person_id = de.person_id
INNER JOIN concept dc ON de.drug_concept_id = dc.concept_id
WHERE cc.concept_name LIKE '%diabetes%'
  AND dc.concept_name LIKE '%metformin%'
LIMIT 1000;
```

### Temporal Refinement: Treatment AFTER Diagnosis
```sql
SELECT DISTINCT p.person_id,
       cc.concept_name AS condition,
       co.condition_start_date AS diagnosis_date,
       dc.concept_name AS drug,
       de.drug_exposure_start_date AS treatment_start_date,
       DATEDIFF(day, co.condition_start_date, de.drug_exposure_start_date) AS days_to_treatment
FROM person p
INNER JOIN condition_occurrence co ON p.person_id = co.person_id
INNER JOIN concept cc ON co.condition_concept_id = cc.concept_id
INNER JOIN drug_exposure de ON p.person_id = de.person_id
              AND de.drug_exposure_start_date >= co.condition_start_date
INNER JOIN concept dc ON de.drug_concept_id = dc.concept_id
WHERE cc.concept_name LIKE '%diabetes%'
  AND dc.concept_name LIKE '%metformin%'
LIMIT 1000;
```

**Key:** Add temporal logic in JOIN condition, not just WHERE

---

## Pattern 6: Measurement Values for Condition Cohort

### Template
```sql
SELECT p.person_id,
       cc.concept_name AS condition,
       mc.concept_name AS measurement,
       m.value_as_number,
       uc.concept_name AS unit,
       m.measurement_date
FROM person p
INNER JOIN condition_occurrence co ON p.person_id = co.person_id
INNER JOIN concept cc ON co.condition_concept_id = cc.concept_id
INNER JOIN measurement m ON p.person_id = m.person_id
INNER JOIN concept mc ON m.measurement_concept_id = mc.concept_id
LEFT JOIN concept uc ON m.unit_concept_id = uc.concept_id
WHERE cc.concept_name LIKE '%[condition]%'
  AND mc.concept_name LIKE '%[measurement]%'
ORDER BY p.person_id, m.measurement_date
LIMIT 1000;
```

### Example: HbA1c Levels in Diabetic Patients
```sql
SELECT p.person_id,
       cc.concept_name AS diabetes_type,
       mc.concept_name AS test,
       m.value_as_number AS hba1c_value,
       uc.concept_name AS unit,
       m.measurement_date,
       CASE
           WHEN m.value_as_number < 5.7 THEN 'Normal'
           WHEN m.value_as_number BETWEEN 5.7 AND 6.4 THEN 'Prediabetes'
           WHEN m.value_as_number >= 6.5 THEN 'Diabetes'
       END AS diabetes_category
FROM person p
INNER JOIN condition_occurrence co ON p.person_id = co.person_id
INNER JOIN concept cc ON co.condition_concept_id = cc.concept_id
INNER JOIN measurement m ON p.person_id = m.person_id
INNER JOIN concept mc ON m.measurement_concept_id = mc.concept_id
LEFT JOIN concept uc ON m.unit_concept_id = uc.concept_id
WHERE cc.concept_name LIKE '%diabetes%'
  AND mc.concept_name LIKE '%hemoglobin A1c%'
  AND m.value_as_number IS NOT NULL
ORDER BY p.person_id, m.measurement_date
LIMIT 1000;
```

---

## Pattern 7: Hierarchical Concept Queries (Using concept_ancestor)

### Template
```sql
-- Step 1: Find all descendant concepts
WITH descendant_concepts AS (
    SELECT ca.descendant_concept_id
    FROM concept_ancestor ca
    WHERE ca.ancestor_concept_id = (
        SELECT concept_id
        FROM concept
        WHERE concept_name = '[parent concept name]'
          AND domain_id = '[domain]'
          AND standard_concept = 'S'
        LIMIT 1
    )
)
-- Step 2: Query clinical table with descendants
SELECT p.person_id,
       c.concept_name AS specific_concept,
       ct.event_date
FROM person p
INNER JOIN [clinical_table] ct ON p.person_id = ct.person_id
INNER JOIN concept c ON ct.[concept_id_column] = c.concept_id
WHERE ct.[concept_id_column] IN (SELECT descendant_concept_id FROM descendant_concepts)
LIMIT 1000;
```

### Example: All Types of Diabetes
```sql
-- Find patients with ANY type of diabetes (Type 1, Type 2, gestational, etc.)
WITH diabetes_concepts AS (
    SELECT ca.descendant_concept_id
    FROM concept_ancestor ca
    WHERE ca.ancestor_concept_id = (
        SELECT concept_id
        FROM concept
        WHERE concept_name = 'Diabetes mellitus'
          AND domain_id = 'Condition'
          AND standard_concept = 'S'
        LIMIT 1
    )
)
SELECT DISTINCT p.person_id,
       c.concept_name AS specific_diabetes_type,
       co.condition_start_date
FROM person p
INNER JOIN condition_occurrence co ON p.person_id = co.person_id
INNER JOIN concept c ON co.condition_concept_id = c.concept_id
WHERE co.condition_concept_id IN (SELECT descendant_concept_id FROM diabetes_concepts)
LIMIT 1000;
```

**Power:** Catches all subtypes without enumerating them manually

---

## Pattern 8: Concept Mapping (Source → Standard)

### Template
```sql
-- Map source codes (ICD10, NDC, etc.) to standard concepts
SELECT sc.concept_code AS source_code,
       sc.concept_name AS source_name,
       sc.vocabulary_id AS source_vocabulary,
       cr.relationship_id,
       c.concept_id AS standard_concept_id,
       c.concept_name AS standard_concept_name,
       c.vocabulary_id AS standard_vocabulary
FROM concept sc
INNER JOIN concept_relationship cr ON sc.concept_id = cr.concept_id_1
                                    AND cr.relationship_id = 'Maps to'
INNER JOIN concept c ON cr.concept_id_2 = c.concept_id
                     AND c.standard_concept = 'S'
WHERE sc.concept_code IN ('[code1]', '[code2]', ...)
  AND sc.vocabulary_id = '[source_vocabulary]'
LIMIT 1000;
```

### Example: ICD10CM → SNOMED Mapping
```sql
SELECT icd.concept_code AS icd10_code,
       icd.concept_name AS icd10_name,
       cr.relationship_id,
       snomed.concept_id AS snomed_concept_id,
       snomed.concept_name AS snomed_name
FROM concept icd
INNER JOIN concept_relationship cr ON icd.concept_id = cr.concept_id_1
                                    AND cr.relationship_id = 'Maps to'
INNER JOIN concept snomed ON cr.concept_id_2 = snomed.concept_id
                          AND snomed.standard_concept = 'S'
WHERE icd.concept_code IN ('E11.9', 'I10', 'E78.5')
  AND icd.vocabulary_id = 'ICD10CM'
LIMIT 1000;
```

---

## Common Join Antipatterns to AVOID

### Antipattern 1: Cartesian Product (Missing Join Condition)
```sql
--  WRONG - creates cartesian product (every person × every condition)
SELECT p.person_id, c.concept_name
FROM person p, condition_occurrence co, concept c
LIMIT 1000;

--  CORRECT - explicit join conditions
SELECT p.person_id, c.concept_name
FROM person p
JOIN condition_occurrence co ON p.person_id = co.person_id
JOIN concept c ON co.condition_concept_id = c.concept_id
LIMIT 1000;
```

### Antipattern 2: Forgetting Concept Join
```sql
--  WRONG - returns concept IDs (meaningless numbers)
SELECT person_id, condition_concept_id FROM condition_occurrence LIMIT 1000;

--  CORRECT - joins with concept for readable names
SELECT co.person_id, c.concept_name
FROM condition_occurrence co
JOIN concept c ON co.condition_concept_id = c.concept_id
LIMIT 1000;
```

### Antipattern 3: INNER JOIN Causing Accidental Filtering
```sql
--  WRONG - excludes patients without measurements
SELECT p.person_id, COUNT(*) AS measurement_count
FROM person p
INNER JOIN measurement m ON p.person_id = m.person_id
GROUP BY p.person_id
LIMIT 1000;

--  CORRECT - includes all patients, even those without measurements
SELECT p.person_id, COUNT(m.measurement_id) AS measurement_count
FROM person p
LEFT JOIN measurement m ON p.person_id = m.person_id
GROUP BY p.person_id
LIMIT 1000;
```

### Antipattern 4: Ambiguous Column References
```sql
--  WRONG - which concept_id?
SELECT concept_id, concept_name
FROM condition_occurrence co
JOIN concept c ON co.condition_concept_id = c.concept_id
LIMIT 1000;

--  CORRECT - always use table aliases
SELECT c.concept_id, c.concept_name
FROM condition_occurrence co
JOIN concept c ON co.condition_concept_id = c.concept_id
LIMIT 1000;
```

---

## Performance Tips for Large Databases

### 1. Filter Early
```sql
--  GOOD - filter before joining
SELECT p.person_id, c.concept_name
FROM person p
JOIN condition_occurrence co ON p.person_id = co.person_id
                              AND co.condition_start_date >= '2020-01-01'
JOIN concept c ON co.condition_concept_id = c.concept_id
LIMIT 1000;
```

### 2. Use DISTINCT Wisely
```sql
-- Only use DISTINCT when needed (causes sort)
SELECT DISTINCT person_id FROM condition_occurrence LIMIT 1000;

-- Better: Use GROUP BY if aggregating anyway
SELECT person_id, COUNT(*) FROM condition_occurrence GROUP BY person_id LIMIT 1000;
```

### 3. Limit Joins to Needed Columns
```sql
--  SLOW - selects all columns
SELECT * FROM person p
JOIN condition_occurrence co ON p.person_id = co.person_id
LIMIT 1000;

--  FAST - selects only needed columns
SELECT p.person_id, p.year_of_birth, co.condition_start_date
FROM person p
JOIN condition_occurrence co ON p.person_id = co.person_id
LIMIT 1000;
```

---

## Quick Reference: Common Join Combinations

| Query Goal | Tables to Join | Join Pattern |
|------------|----------------|--------------|
| Patient demographics | person, concept | person → concept (gender, race, ethnicity) |
| Patients with condition | person, condition_occurrence, concept | person → condition_occurrence → concept |
| Patients on medication | person, drug_exposure, concept | person → drug_exposure → concept |
| Condition + Treatment | person, condition_occurrence, drug_exposure, concept × 2 | person → both clinical tables → concepts |
| Lab results for condition | person, condition_occurrence, measurement, concept × 2 | person → both clinical tables → concepts |
| Visit context | [clinical_table], visit_occurrence, concept | clinical_table → visit_occurrence → concept |
| Hierarchical concepts | concept_ancestor, condition_occurrence, concept | concept_ancestor (CTE) → clinical_table → concept |
| Map source codes | concept × 2, concept_relationship | concept (source) → concept_relationship → concept (standard) |

---

## Summary: Golden Rules for OMOP Joins

1. **Always join clinical tables to person via `person_id`**
2. **Always join `_concept_id` columns to `concept.concept_id` for readable names**
3. **Use LEFT JOIN for optional relationships, INNER JOIN for required**
4. **Use table aliases consistently** (p, co, de, c, etc.)
5. **Filter by `domain_id` on concept table**
6. **Use `concept_ancestor` for hierarchical queries**
7. **Add temporal logic in JOIN conditions for time-based analysis**
8. **Always include LIMIT to prevent massive result sets**

Master these patterns and your OMOP queries will be correct, efficient, and maintainable.

# OMOP Query Validation Errors and Fixes

This document provides a comprehensive guide to understanding and fixing SQL validation errors from the OMCP MCP server. Use this as a troubleshooting reference when queries fail.

## Understanding OMCP Validation

The OMCP MCP server validates ALL SQL queries before execution for:
1. **Security** - Prevent SQL injection, unauthorized access
2. **Privacy** - Block PHI/PII exposure
3. **Safety** - Prevent resource exhaustion
4. **Data Quality** - Ensure OMOP-compliant queries

**Key Principle:** Validation errors are HELPFUL. They guide you toward secure, correct queries.

---

##Error handling


## Error Type 1: Source Value Column Access

### Error Message
```
UnauthorizedColumnError: Column '[column_name]_source_value' is not allowed.
This is a security measure to prevent access to potentially sensitive source data.
Use the standardized concept_id column with a join to the concept table instead.
```

### Why This Happens
- `_source_value` columns contain original source system codes (ICD10, NDC, etc.)
- May contain free-text, PHI, or non-standardized data
- OMCP blocks these by default for security

### The Fix: Use Concept IDs Instead

** WRONG - Attempts to access source_value:**
```sql
SELECT condition_source_value
FROM condition_occurrence
WHERE condition_source_value LIKE '%E11%'
LIMIT 1000;
```

** CORRECT - Uses standardized concept_id:**
```sql
SELECT c.concept_name, c.concept_code, c.vocabulary_id
FROM condition_occurrence co
JOIN concept c ON co.condition_concept_id = c.concept_id
WHERE c.concept_name LIKE '%diabetes%'
  AND c.domain_id = 'Condition'
LIMIT 1000;
```

### Blocked Columns (Common)
- `condition_source_value`, `condition_source_concept_id`
- `drug_source_value`, `drug_source_concept_id`
- `procedure_source_value`, `procedure_source_concept_id`
- `measurement_source_value`, `measurement_source_concept_id`
- `observation_source_value`, `observation_source_concept_id`
- `value_source_value` (in measurement table)
- `unit_source_value`, `unit_source_concept_id`

### Decision Tree
```
Need source code information?
  ├─ NO → Use concept_name from concept table ✓
  └─ YES → Can you use concept_code instead?
      ├─ YES → Join with concept table, use concept_code ✓
      └─ NO → This data is intentionally blocked for security
```

---

## Error Type 2: Table Not Found in OMOP CDM

### Error Message
```
TableNotFoundError: Table '[table_name]' is not a valid OMOP CDM table.
```

### Why This Happens
- Table name typo
- Table is not part of OMOP CDM standard
- Using a CTE name that looks like a table reference

### The Fix: Verify Table Names

** WRONG - Typo or non-OMOP table:**
```sql
SELECT * FROM conditions LIMIT 1000;  -- Should be condition_occurrence
SELECT * FROM patients LIMIT 1000;    -- Should be person
```

** CORRECT - Standard OMOP table names:**
```sql
SELECT * FROM condition_occurrence LIMIT 1000;
SELECT * FROM person LIMIT 1000;
```

### Valid OMOP CDM Table Names

**Clinical Tables:**
- `person`
- `condition_occurrence`
- `drug_exposure`
- `procedure_occurrence`
- `measurement`
- `observation`
- `device_exposure`
- `visit_occurrence`
- `visit_detail`

**Vocabulary Tables:**
- `concept`
- `concept_relationship`
- `concept_ancestor`
- `concept_synonym`
- `vocabulary`
- `domain`
- `concept_class`
- `relationship`

**Health System Tables:**
- `care_site`
- `provider`
- `location`

**Metadata:**
- `cdm_source`
- `metadata`

### Special Case: CTEs Are Allowed
```sql
-- ✓ This is fine - CTE names don't trigger table validation
WITH diabetes_patients AS (
    SELECT person_id FROM condition_occurrence
    WHERE condition_concept_id = 201826
)
SELECT * FROM diabetes_patients LIMIT 1000;
```

---

## Error Type 3: Column Not Found

### Error Message
```
ColumnNotFoundError: No valid columns found in the query.
```

### Why This Happens
- Column name typo
- Column doesn't exist in that table
- All columns in SELECT are blocked (e.g., all source_value columns)

### The Fix: Verify Column Names with Schema

**Step 1: Call Get_Information_Schema() to see available columns**

**Step 2: Fix column names**

** WRONG - Column doesn't exist:**
```sql
SELECT patient_id FROM person LIMIT 1000;  -- Should be person_id
SELECT diagnosis FROM condition_occurrence LIMIT 1000;  -- Should be condition_concept_id
```

** CORRECT - Standard OMOP column names:**
```sql
SELECT person_id FROM person LIMIT 1000;
SELECT condition_concept_id FROM condition_occurrence LIMIT 1000;
```

### Common Column Name Mistakes

| Wrong | Correct |
|-------|---------|
| patient_id | person_id |
| diagnosis | condition_concept_id |
| medication | drug_concept_id |
| test_result | value_as_number (measurement) |
| visit_date | visit_start_date |
| birth_date | year_of_birth |

---

## Error Type 4: Unauthorized Table Access

### Error Message
```
UnauthorizedTableError: Access to table '[table_name]' is not authorized.
This table has been excluded from access by the administrator.
```

### Why This Happens
- Administrator has excluded certain tables for privacy/security
- Common exclusions: tables with detailed location data, provider details

### The Fix: Use Allowed Tables

**Check which tables are available:**
1. Call `Get_Information_Schema()` to see allowed tables
2. Adjust query to use only available tables

**If table is blocked, consider:**
- Can you answer the question without this table?
- Is there an alternative table with similar information?
- Can you aggregate/anonymize the data differently?

**Example: Location is blocked**
```sql
--  WRONG - location table blocked
SELECT l.city, COUNT(DISTINCT p.person_id)
FROM person p
JOIN location l ON p.location_id = l.location_id
GROUP BY l.city
LIMIT 1000;

--  CORRECT - use person table only (no detailed location)
SELECT COUNT(DISTINCT person_id) AS patient_count
FROM person
LIMIT 1000;
```

---

## Error Type 5: Not a SELECT Query

### Error Message
```
NotSelectQueryError: Only SELECT queries are allowed.
Query type detected: [INSERT/UPDATE/DELETE/CREATE/etc.]
```

### Why This Happens
- Security: OMCP is read-only for safety
- Only SELECT statements are allowed

### The Fix: Convert to SELECT

** WRONG - Modifying data:**
```sql
INSERT INTO person (...) VALUES (...);
UPDATE person SET year_of_birth = 1980 WHERE person_id = 123;
DELETE FROM condition_occurrence WHERE person_id = 123;
CREATE TABLE my_table (...);
```

** CORRECT - Read-only queries:**
```sql
SELECT * FROM person WHERE person_id = 123 LIMIT 1000;
SELECT * FROM condition_occurrence WHERE person_id = 123 LIMIT 1000;
```

### CTEs and Subqueries Are Allowed
```sql
-- ✓ This is fine - still just SELECT
WITH cohort AS (
    SELECT person_id FROM condition_occurrence
    WHERE condition_concept_id = 201826
)
SELECT * FROM cohort LIMIT 1000;
```

---

## Error Type 6: SQL Syntax Error

### Error Message
```
SqlSyntaxError: Failed to parse SQL query.
[Specific syntax error details]
```

### Why This Happens
- SQL syntax mistake (missing comma, unclosed quote, etc.)
- Invalid SQL for the database engine (DuckDB/Postgres)

### The Fix: Correct SQL Syntax

**Common syntax errors:**

**Missing comma:**
```sql
--  WRONG
SELECT person_id
       gender_concept_id
FROM person LIMIT 1000;

--  CORRECT
SELECT person_id,
       gender_concept_id
FROM person LIMIT 1000;
```

**Unclosed quote:**
```sql
--  WRONG
SELECT * FROM concept WHERE concept_name LIKE '%diabetes LIMIT 1000;

--  CORRECT
SELECT * FROM concept WHERE concept_name LIKE '%diabetes%' LIMIT 1000;
```

**Missing FROM:**
```sql
--  WRONG
SELECT person_id WHERE person_id = 123 LIMIT 1000;

--  CORRECT
SELECT person_id FROM person WHERE person_id = 123 LIMIT 1000;
```

**Wrong JOIN syntax:**
```sql
--  WRONG
SELECT * FROM person p, condition_occurrence co
WHERE p.person_id = co.person_id LIMIT 1000;

--  CORRECT (explicit JOIN)
SELECT * FROM person p
JOIN condition_occurrence co ON p.person_id = co.person_id
LIMIT 1000;
```

---

## Error Type 7: Query Execution Failure

### Error Message
```
Failed to execute query: [Database error message]
```

### Why This Happens
- Query is syntactically valid but fails at runtime
- Common causes: division by zero, type mismatch, missing data

### The Fix: Handle Edge Cases

**Division by zero:**
```sql
--  MAY FAIL
SELECT value_as_number / range_low FROM measurement LIMIT 1000;

--  SAFE - handle NULL and zero
SELECT CASE
    WHEN range_low IS NULL OR range_low = 0 THEN NULL
    ELSE value_as_number / range_low
END AS ratio
FROM measurement LIMIT 1000;
```

**Type mismatch:**
```sql
--  MAY FAIL - comparing string to number
SELECT * FROM measurement
WHERE value_as_number = 'high'
LIMIT 1000;

--  CORRECT - use value_as_concept_id for categorical
SELECT * FROM measurement m
JOIN concept c ON m.value_as_concept_id = c.concept_id
WHERE c.concept_name = 'High'
LIMIT 1000;
```

---

## Validation Error Troubleshooting Workflow

```
Query fails with error
  │
  ├─ Source value error?
  │   └─ Replace with concept_id + concept join
  │
  ├─ Table not found?
  │   └─ Check spelling, call Get_Information_Schema()
  │
  ├─ Column not found?
  │   └─ Check spelling, call Get_Information_Schema()
  │
  ├─ Unauthorized table?
  │   └─ Use alternative tables, check Get_Information_Schema()
  │
  ├─ Not SELECT query?
  │   └─ Convert to SELECT (read-only)
  │
  ├─ Syntax error?
  │   └─ Fix SQL syntax (commas, quotes, JOINs)
  │
  └─ Execution error?
      └─ Handle edge cases (NULL, division by zero, types)
```

---

## Retry Strategy After Errors

### Step 1: Parse Error Message
- Read error carefully
- Identify error type
- Note specific column/table/syntax issue

### Step 2: Make ONE Fix
- Don't change multiple things at once
- Fix the specific issue mentioned in error
- Keep rest of query the same

### Step 3: Validate Fix Logic
- Does the fix maintain query intent?
- Does the fix follow OMOP best practices?
- Is the fix more secure/compliant?

### Step 4: Retry Query
- Execute modified query
- If still fails, repeat steps 1-3
- Max 3 retry attempts (avoid infinite loops)

### Step 5: Escalate if Stuck
- After 3 failed attempts, explain issue to user
- Ask for clarification or alternative approach

---

## Example Error → Fix Sequences

### Example 1: Source Value Error
```
Attempt 1:
❌ SELECT condition_source_value FROM condition_occurrence LIMIT 1000;
→ Error: UnauthorizedColumnError: condition_source_value not allowed

Fix Applied: Replace with concept join
Attempt 2:
✅ SELECT c.concept_name FROM condition_occurrence co
   JOIN concept c ON co.condition_concept_id = c.concept_id LIMIT 1000;
→ Success!
```

### Example 2: Multiple Errors
```
Attempt 1:
❌ SELECT patient_id, diagnosis_source_value
   FROM conditions WHERE patient_id = 123 LIMIT 1000;
→ Error: TableNotFoundError: 'conditions' not valid

Fix Applied: Correct table name
Attempt 2:
❌ SELECT patient_id, diagnosis_source_value
   FROM condition_occurrence WHERE patient_id = 123 LIMIT 1000;
→ Error: ColumnNotFoundError: 'patient_id' doesn't exist

Fix Applied: Correct column name
Attempt 3:
❌ SELECT person_id, diagnosis_source_value
   FROM condition_occurrence WHERE person_id = 123 LIMIT 1000;
→ Error: UnauthorizedColumnError: 'diagnosis_source_value' not allowed

Fix Applied: Remove source_value, add concept join
Attempt 4:
✅ SELECT co.person_id, c.concept_name
   FROM condition_occurrence co
   JOIN concept c ON co.condition_concept_id = c.concept_id
   WHERE co.person_id = 123 LIMIT 1000;
→ Success!
```

---

## Prevention: Write Valid Queries from the Start

### Checklist Before Executing Query

1.  Did I call `Get_Information_Schema()` first?
2.  Are all table names valid OMOP tables?
3.  Are all column names verified against schema?
4.  Am I avoiding all `_source_value` columns?
5.  Am I joining `_concept_id` columns with `concept` table?
6.  Is my SQL syntax correct?
7.  Did I include `LIMIT 1000`?
8.  Am I only using SELECT (no INSERT/UPDATE/DELETE)?

---

## Quick Reference: Error → Solution

| Error Type | Quick Fix |
|------------|-----------|
| UnauthorizedColumnError | Replace `_source_value` with concept join |
| TableNotFoundError | Fix spelling, check Get_Information_Schema() |
| ColumnNotFoundError | Fix spelling, check Get_Information_Schema() |
| UnauthorizedTableError | Use alternative tables from schema |
| NotSelectQueryError | Convert to SELECT-only query |
| SqlSyntaxError | Fix commas, quotes, JOIN syntax |
| Execution error | Handle NULLs, zeros, type mismatches |

---

## Summary: Validation Error Philosophy

**Errors are not failures - they are guidance toward correct queries.**

- Read errors carefully
- Make targeted fixes
- Learn patterns to avoid future errors
- Build incrementally (start simple, add complexity)
- Always call `Get_Information_Schema()` first

With experience, you'll write valid queries on the first try. Until then, use errors as teaching moments.




##Query examples

# OMOP CDM Production Query Patterns

**IMPORTANT:** This document supersedes concept_name LIKE patterns in other documents. Always use concept_code-based lookups for production queries.

## Critical Architectural Decisions

### 1. Use concept_code, NOT concept_name LIKE if a concept_code is provided
**Why:** concept_name matching is unreliable (synonyms, variations, case sensitivity)

**If concept code is available DONT DO THIS:**
```sql
WHERE c.concept_name LIKE '%diabetes%'
```

**ALWAYS DO THIS:**
```sql
WHERE c.vocabulary_id = 'SNOMED'
  AND c.concept_code = '73211009'  -- Type 2 diabetes SNOMED code
```

**When no concept code is available:**
 ```sql
  -- Example: Find patients with diabetes (no concept code available)
  WITH seed_concepts AS (
      SELECT c.concept_id
      FROM base.concept c
      WHERE c.vocabulary_id = 'SNOMED'
        AND c.domain_id = 'Condition'
        AND LOWER(c.concept_name) LIKE '%diabetes%'
        AND c.standard_concept = 'S'
        AND c.invalid_reason IS NULL
  ),
  -- Then continue with standard→descendant pattern

  Warning: This is less precise. Prefer concept_code when available.

### 2. Include the concept code from context

### 3. Postgres-Specific Temporal Logic
**Date arithmetic:**
```sql
-- Days between dates
WHERE ABS(date1 - date2) <= 90

-- NOT DATEDIFF (SQL Server)
-- NOT EXTRACT(epoch...) unless necessary
```

### 4. Schema Prefix
Always use the schema prefix you retrieve from Get_information_Schema() from the MCP server:
```sql
FROM base.drug_exposure
FROM base.condition_occurrence
FROM base.concept
```

---

## Production Pattern 1: Drug Concept Lookup with Hierarchy

**Use case:** Find patients taking a specific drug (includes generics, brands, formulations)

```sql
-- Example: Find patients on metformin (any formulation)
-- concept_code '6809' = Metformin (RxNorm ingredient)

SELECT COUNT(DISTINCT pe.person_id)
FROM base.person AS pe
JOIN base.drug_exposure AS de ON pe.person_id = de.person_id
JOIN (
    -- Map concept_code to standard concept, then get all descendants
    SELECT ca.descendant_concept_id AS concept_id
    FROM (
        -- Get source concept by code
        SELECT c.concept_id
        FROM base.concept c
        WHERE c.vocabulary_id = 'RxNorm'
          AND c.concept_code = '6809'  -- From Milvus
          AND c.invalid_reason IS NULL
    ) AS seed
    -- Map to standard if needed
    JOIN base.concept_relationship cr
      ON seed.concept_id = cr.concept_id_1
     AND cr.relationship_id = 'Maps to'
     AND cr.invalid_reason IS NULL
    JOIN base.concept std
      ON cr.concept_id_2 = std.concept_id
    -- Get all drug formulations via hierarchy
    JOIN base.concept_ancestor ca
      ON std.concept_id = ca.ancestor_concept_id
) AS drug_concepts
  ON de.drug_concept_id = drug_concepts.concept_id
LIMIT 1000;
```

**Generalized template:**
```sql
SELECT COUNT(DISTINCT pe.person_id)
FROM base.person AS pe
JOIN base.drug_exposure AS de ON pe.person_id = de.person_id
JOIN (
    SELECT ca.descendant_concept_id AS concept_id
    FROM (
        SELECT c.concept_id
        FROM base.concept c
        WHERE c.vocabulary_id = '[VOCABULARY]'  -- e.g., 'RxNorm'
          AND c.concept_code = '[CODE]'  -- From Milvus
          AND c.invalid_reason IS NULL
    ) AS seed
    JOIN base.concept_relationship cr
      ON seed.concept_id = cr.concept_id_1
     AND cr.relationship_id = 'Maps to'
    JOIN base.concept std
      ON cr.concept_id_2 = std.concept_id
    JOIN base.concept_ancestor ca
      ON std.concept_id = ca.ancestor_concept_id
) AS drug_concepts
  ON de.drug_concept_id = drug_concepts.concept_id
LIMIT 1000;
```

### How to Adapt Pattern 1 (Drug Lookup):

  **Step 1:** Identify seed concept
  - Use `concept_code` from SemanticContext
  - Use `vocabulary_id` from SemanticContext (usually 'RxNorm' for drugs)

  **Step 2:** Map to standard concept
  - Join `concept_relationship` with relationship_id = 'Maps to'
  - Handle case where seed is already standard (seed_id = standard_id)

  **Step 3:** Expand hierarchy
  - Join `concept_ancestor` to get all descendants
  - This captures all formulations/brands/generics

  **Step 4:** Join to clinical table
  - Use `drug_exposure.drug_concept_id`
  - Always include `person` join for demographics

---

## Production Pattern 2: Condition Concept Lookup with Hierarchy

**Use case:** Find patients with a specific condition (includes subtypes)

```sql
-- Example: Find patients with diabetes (any type)
-- concept_code '73211009' = Type 2 diabetes (SNOMED)

WITH seed_concepts AS (
    SELECT c.concept_id AS src_id
    FROM base.concept c
    WHERE c.vocabulary_id = 'SNOMED'
      AND c.concept_code = '73211009'  -- From Milvus
      AND c.invalid_reason IS NULL
),
standard_concepts AS (
    SELECT COALESCE(cr.concept_id_2, s.src_id) AS standard_id
    FROM seed_concepts s
    LEFT JOIN base.concept_relationship cr
      ON s.src_id = cr.concept_id_1
     AND cr.relationship_id = 'Maps to'
     AND cr.invalid_reason IS NULL
),
descendant_concepts AS (
    SELECT ca.descendant_concept_id AS concept_id
    FROM standard_concepts sc
    JOIN base.concept_ancestor ca
      ON sc.standard_id = ca.ancestor_concept_id
)
SELECT COUNT(DISTINCT co.person_id)
FROM base.condition_occurrence co
JOIN descendant_concepts dc
  ON co.condition_concept_id = dc.concept_id
LIMIT 1000;
```

**Generalized template:**
```sql
WITH seed_concepts AS (
    SELECT c.concept_id AS src_id
    FROM base.concept c
    WHERE c.vocabulary_id = '[VOCABULARY]'  -- e.g., 'SNOMED'
      AND c.concept_code = '[CODE]'  -- From Milvus
      AND c.invalid_reason IS NULL
),
standard_concepts AS (
    SELECT COALESCE(cr.concept_id_2, s.src_id) AS standard_id
    FROM seed_concepts s
    LEFT JOIN base.concept_relationship cr
      ON s.src_id = cr.concept_id_1
     AND cr.relationship_id = 'Maps to'
     AND cr.invalid_reason IS NULL
),
descendant_concepts AS (
    SELECT ca.descendant_concept_id AS concept_id
    FROM standard_concepts sc
    JOIN base.concept_ancestor ca
      ON sc.standard_id = ca.ancestor_concept_id
)
SELECT COUNT(DISTINCT co.person_id)
FROM base.condition_occurrence co
JOIN descendant_concepts dc
  ON co.condition_concept_id = dc.concept_id
LIMIT 1000;
```

---

## Production Pattern 3: Temporal Co-occurrence (Drugs)

**Use case:** Patients taking two drugs within N days

```sql
-- Example: Patients on metformin AND insulin within 90 days
-- Drug A code: '6809' (Metformin)
-- Drug B code: '5856' (Insulin)

WITH drug_a_concepts AS (
    SELECT ca.descendant_concept_id AS concept_id
    FROM (
        SELECT c.concept_id
        FROM base.concept c
        WHERE c.vocabulary_id = 'RxNorm'
          AND c.concept_code = '6809'
    ) seed
    JOIN base.concept_relationship cr ON seed.concept_id = cr.concept_id_1
     AND cr.relationship_id = 'Maps to'
    JOIN base.concept std ON cr.concept_id_2 = std.concept_id
    JOIN base.concept_ancestor ca ON std.concept_id = ca.ancestor_concept_id
),
drug_a AS (
    SELECT de.person_id, de.drug_exposure_start_date AS start_date
    FROM base.drug_exposure de
    JOIN drug_a_concepts dc ON de.drug_concept_id = dc.concept_id
),
drug_b_concepts AS (
    SELECT ca.descendant_concept_id AS concept_id
    FROM (
        SELECT c.concept_id
        FROM base.concept c
        WHERE c.vocabulary_id = 'RxNorm'
          AND c.concept_code = '5856'
    ) seed
    JOIN base.concept_relationship cr ON seed.concept_id = cr.concept_id_1
     AND cr.relationship_id = 'Maps to'
    JOIN base.concept std ON cr.concept_id_2 = std.concept_id
    JOIN base.concept_ancestor ca ON std.concept_id = ca.ancestor_concept_id
),
drug_b AS (
    SELECT de.person_id, de.drug_exposure_start_date AS start_date
    FROM base.drug_exposure de
    JOIN drug_b_concepts dc ON de.drug_concept_id = dc.concept_id
)
SELECT COUNT(DISTINCT a.person_id)
FROM drug_a a
JOIN drug_b b ON a.person_id = b.person_id
WHERE ABS(a.start_date - b.start_date) <= 90  -- Postgres date arithmetic
LIMIT 1000;
```

---

## Production Pattern 4: Temporal Co-occurrence (Conditions)

**Use case:** Patients with two conditions within N days

```sql
-- Example: Patients with diabetes AND hypertension within 180 days
-- Condition A: '73211009' (Type 2 diabetes)
-- Condition B: '38341003' (Hypertension)

WITH condition_a_concepts AS (
    SELECT ca.descendant_concept_id AS concept_id
    FROM (
        SELECT COALESCE(cr.concept_id_2, c.concept_id) AS standard_id
        FROM base.concept c
        LEFT JOIN base.concept_relationship cr
          ON c.concept_id = cr.concept_id_1
         AND cr.relationship_id = 'Maps to'
        WHERE c.vocabulary_id = 'SNOMED'
          AND c.concept_code = '73211009'
    ) std
    JOIN base.concept_ancestor ca ON std.standard_id = ca.ancestor_concept_id
),
condition_a AS (
    SELECT co.person_id, co.condition_start_date AS start_date
    FROM base.condition_occurrence co
    JOIN condition_a_concepts cac ON co.condition_concept_id = cac.concept_id
),
condition_b_concepts AS (
    SELECT ca.descendant_concept_id AS concept_id
    FROM (
        SELECT COALESCE(cr.concept_id_2, c.concept_id) AS standard_id
        FROM base.concept c
        LEFT JOIN base.concept_relationship cr
          ON c.concept_id = cr.concept_id_1
         AND cr.relationship_id = 'Maps to'
        WHERE c.vocabulary_id = 'SNOMED'
          AND c.concept_code = '38341003'
    ) std
    JOIN base.concept_ancestor ca ON std.standard_id = ca.ancestor_concept_id
),
condition_b AS (
    SELECT co.person_id, co.condition_start_date AS start_date
    FROM base.condition_occurrence co
    JOIN condition_b_concepts cbc ON co.condition_concept_id = cbc.concept_id
)
SELECT COUNT(DISTINCT a.person_id)
FROM condition_a a
JOIN condition_b b ON a.person_id = b.person_id
WHERE ABS(a.start_date - b.start_date) <= 180
LIMIT 1000;
```

---

## Production Pattern 5: Demographics

**Use case:** Patient demographics with concept joins

```sql
-- Distribution by gender
SELECT g.concept_name AS gender,
       COUNT(DISTINCT p.person_id) AS patient_count
FROM base.person p
JOIN base.concept g
  ON p.gender_concept_id = g.concept_id
 AND g.domain_id = 'Gender'
 AND g.standard_concept = 'S'
GROUP BY g.concept_name
LIMIT 1000;

-- Distribution by race
SELECT r.concept_name AS race,
       COUNT(DISTINCT p.person_id) AS patient_count
FROM base.person p
LEFT JOIN base.concept r
  ON p.race_concept_id = r.concept_id
 AND r.domain_id = 'Race'
 AND r.standard_concept = 'S'
GROUP BY r.concept_name
LIMIT 1000;

-- Age distribution by birth year
SELECT year_of_birth,
       COUNT(DISTINCT person_id) AS patient_count
FROM base.person
GROUP BY year_of_birth
ORDER BY year_of_birth
LIMIT 1000;
```

---

## Key Differences from Generic Examples

### Temporal Logic
 **Don't use SQL Server syntax:**
```sql
DATEDIFF(day, date1, date2) <= 90
```

 **Use Postgres syntax:**
```sql
ABS(date1 - date2) <= 90
```

### Concept Lookup
 **Don't use string matching:**
```sql
WHERE concept_name LIKE '%diabetes%'
```

 **Use concept_code from Milvus:**
```sql
WHERE vocabulary_id = 'SNOMED' AND concept_code = '73211009'
```

### Schema Prefix
 **Don't omit schema:**
```sql
FROM condition_occurrence
```

 **Always include base prefix:**
```sql
FROM base.condition_occurrence
```

---

## Integration with Milvus Concept Search

### Workflow: Natural Language → Concept Code → SQL

1. **User query:** "Find patients with type 2 diabetes"

2. **Semantic Agent:** Query Milvus vector DB
   - Input: "type 2 diabetes"
   - Output:
     ```json
     {
       "concept_id": 201826,
       "concept_code": "73211009",
       "concept_name": "Type 2 diabetes mellitus",
       "vocabulary_id": "SNOMED",
       "domain_id": "Condition"
     }
     ```

3. **Database Agent:** Use concept_code in SQL
   ```sql
   WHERE c.vocabulary_id = 'SNOMED'
     AND c.concept_code = '73211009'
   ```

### Why This Approach?
- **Precise:** No ambiguity from string matching
- **Fast:** Direct concept_id lookup, no LIKE scans
- **Correct:** Semantic search handles synonyms, typos
- **Hierarchical:** concept_ancestor captures all subtypes

---

## Common Concept Codes for Examples

### Drugs (RxNorm)
- **Metformin:** '6809'
- **Insulin:** '5856'
- **Lisinopril:** '29046'
- **Amlodipine:** '17767'
- **Simvastatin:** '36567'

### Conditions (SNOMED)
- **Type 2 diabetes:** '73211009'
- **Hypertension:** '38341003'
- **Anemia:** '271737000'
- **Chronic sinusitis:** '40055000'
- **Impaired glucose tolerance:** '9414007'

### Note
Always query Milvus for actual concept_codes. These are examples only.

---

## Summary: Production Query Checklist

Before generating SQL:

1. Include concept codes from semantic context concept_code (don't use concept_name LIKE)
2. Use concept_relationship + concept_ancestor for hierarchies
3. Use date arithmetic (`ABS(date1 - date2)`)
4. Include `base.` schema prefix
5. Always use CTEs for readability
6. Always include `LIMIT 1000`
7. Check `invalid_reason IS NULL` on seed concepts

**Golden Rule:** If you're writing `LIKE '%text%'` on concept_name, you're doing it wrong. Use the concept_code.
