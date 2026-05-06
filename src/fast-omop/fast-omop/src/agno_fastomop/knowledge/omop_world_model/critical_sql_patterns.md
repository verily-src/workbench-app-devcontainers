# Critical SQL Patterns for Common Query Types

This document contains PROVEN SQL patterns for query types that frequently fail. Use these templates exactly as written.

---

## Pattern: Age-Constrained Queries

**Use case:** Find patients with a condition/procedure/drug at a specific age

**Critical requirement:** Age must be calculated as age AT THE TIME OF THE EVENT, not current age

### Template (Condition at Age)
```sql
WITH seed_concepts AS (
    SELECT c.concept_id
    FROM base.concept c
    WHERE c.vocabulary_id = '[VOCABULARY]'
      AND c.concept_code = '[CODE]'
      AND c.invalid_reason IS NULL
),
standard_concepts AS (
    SELECT COALESCE(cr.concept_id_2, s.concept_id) AS standard_id
    FROM seed_concepts s
    LEFT JOIN base.concept_relationship cr
      ON s.concept_id = cr.concept_id_1
     AND cr.relationship_id = 'Maps to'
),
descendant_concepts AS (
    SELECT ca.descendant_concept_id AS concept_id
    FROM standard_concepts sc
    JOIN base.concept_ancestor ca
      ON sc.standard_id = ca.ancestor_concept_id
)
SELECT COUNT(DISTINCT p.person_id)
FROM base.person p
JOIN base.condition_occurrence co ON p.person_id = co.person_id
JOIN descendant_concepts dc ON co.condition_concept_id = dc.concept_id
WHERE EXTRACT(YEAR FROM co.condition_start_date) - p.year_of_birth = [AGE]
LIMIT 1000;
```

### Template (Drug at Age)
```sql
WITH drug_concepts AS (
    SELECT COALESCE(std.concept_id, seed.concept_id) AS concept_id
    FROM (
        SELECT c.concept_id
        FROM base.concept c
        WHERE c.vocabulary_id = '[VOCABULARY]'
          AND c.concept_code = '[CODE]'
          AND c.invalid_reason IS NULL
    ) seed
    LEFT JOIN base.concept_relationship cr ON seed.concept_id = cr.concept_id_1
     AND cr.relationship_id = 'Maps to'
    LEFT JOIN base.concept std ON cr.concept_id_2 = std.concept_id
)
SELECT COUNT(DISTINCT p.person_id)
FROM base.person p
JOIN base.drug_exposure de ON p.person_id = de.person_id
JOIN drug_concepts dc ON de.drug_concept_id = dc.concept_id
WHERE EXTRACT(YEAR FROM de.drug_exposure_start_date) - p.year_of_birth = [AGE]
LIMIT 1000;
```

### Key Points
- Age formula: `EXTRACT(YEAR FROM event_date) - person.year_of_birth`
- Use event date (condition_start_date, drug_exposure_start_date, etc.)
- NOT current date - age must be at time of event
- Works with year_of_birth (no need for birth_datetime)

### Example
```sql
-- Patients with diabetes diagnosed at age 18
WHERE EXTRACT(YEAR FROM co.condition_start_date) - p.year_of_birth = 18
```

---

## Pattern: OR Queries (UNION)

**Use case:** Find patients with Drug A OR Drug B (union, not intersection)

**Critical requirement:** Use UNION to combine patient sets, count DISTINCT

### Template (Two Drugs - INGREDIENT LEVEL with Hierarchy Expansion)

**When to use:** Entity concept_names are ingredient-level only (e.g., "Hydrochlorothiazide", "Terfenadine")
- No "MG", "ML", "ACTUAT" in concept_name
- No "Oral Tablet", "Inhaler", "Injector" in concept_name
- Query intent is broad (any formulation)

**CRITICAL:** Use this template EXACTLY as written. Do NOT rename CTEs. The _hierarchy CTEs MUST use ca.descendant_concept_id to expand ingredient to all formulations.

```sql
WITH drug_a_seed AS (
    SELECT c.concept_id
    FROM base.concept c
    WHERE c.vocabulary_id = '[VOCAB_A]'
      AND c.concept_code = '[CODE_A]'
      AND c.invalid_reason IS NULL
),
drug_a_standard AS (
    SELECT COALESCE(cr.concept_id_2, s.concept_id) AS standard_id
    FROM drug_a_seed s
    LEFT JOIN base.concept_relationship cr
      ON s.concept_id = cr.concept_id_1
     AND cr.relationship_id = 'Maps to'
),
drug_a_hierarchy AS (
    -- ⭐ HIERARCHY EXPANSION via concept_ancestor
    SELECT DISTINCT ca.descendant_concept_id AS concept_id
    FROM drug_a_standard std
    JOIN base.concept c ON std.standard_id = c.concept_id
    JOIN base.concept_ancestor ca
      ON c.concept_id = ca.ancestor_concept_id
    UNION
    -- Include the ingredient concept itself
    SELECT std.standard_id AS concept_id
    FROM drug_a_standard std
),
drug_b_seed AS (
    SELECT c.concept_id
    FROM base.concept c
    WHERE c.vocabulary_id = '[VOCAB_B]'
      AND c.concept_code = '[CODE_B]'
      AND c.invalid_reason IS NULL
),
drug_b_standard AS (
    SELECT COALESCE(cr.concept_id_2, s.concept_id) AS standard_id
    FROM drug_b_seed s
    LEFT JOIN base.concept_relationship cr
      ON s.concept_id = cr.concept_id_1
     AND cr.relationship_id = 'Maps to'
),
drug_b_hierarchy AS (
    -- ⭐ HIERARCHY EXPANSION via concept_ancestor
    SELECT DISTINCT ca.descendant_concept_id AS concept_id
    FROM drug_b_standard std
    JOIN base.concept c ON std.standard_id = c.concept_id
    JOIN base.concept_ancestor ca
      ON c.concept_id = ca.ancestor_concept_id
    UNION
    -- Include the ingredient concept itself
    SELECT std.standard_id AS concept_id
    FROM drug_b_standard std
)
SELECT COUNT(DISTINCT person_id) FROM (
    SELECT DISTINCT person_id
    FROM base.drug_exposure
    WHERE drug_concept_id IN (SELECT concept_id FROM drug_a_hierarchy)
    UNION
    SELECT DISTINCT person_id
    FROM base.drug_exposure
    WHERE drug_concept_id IN (SELECT concept_id FROM drug_b_hierarchy)
) AS combined
LIMIT 1000;
```

### Template (Two Drugs - FORMULATION SPECIFIC without Hierarchy)

**When to use:** Entity concept_names contain specific formulation details
- Contains "MG", "ML", "ACTUAT" (specific strength)
- Contains "Oral Tablet", "Inhaler", "Injector" (specific form)
- Contains "NDA" codes (specific product)
- Query explicitly specifies exact formulation

```sql
WITH drug_a_seed AS (
    SELECT c.concept_id
    FROM base.concept c
    WHERE c.vocabulary_id = '[VOCAB_A]'
      AND c.concept_code = '[CODE_A]'
      AND c.invalid_reason IS NULL
),
drug_a_standard AS (
    SELECT COALESCE(cr.concept_id_2, s.concept_id) AS standard_id
    FROM drug_a_seed s
    LEFT JOIN base.concept_relationship cr
      ON s.concept_id = cr.concept_id_1
     AND cr.relationship_id = 'Maps to'
),
drug_a_concepts AS (
    SELECT std.standard_id AS concept_id
    FROM drug_a_standard std
),
drug_b_seed AS (
    SELECT c.concept_id
    FROM base.concept c
    WHERE c.vocabulary_id = '[VOCAB_B]'
      AND c.concept_code = '[CODE_B]'
      AND c.invalid_reason IS NULL
),
drug_b_standard AS (
    SELECT COALESCE(cr.concept_id_2, s.concept_id) AS standard_id
    FROM drug_b_seed s
    LEFT JOIN base.concept_relationship cr
      ON s.concept_id = cr.concept_id_1
     AND cr.relationship_id = 'Maps to'
),
drug_b_concepts AS (
    SELECT std.standard_id AS concept_id
    FROM drug_b_standard std
)
SELECT COUNT(DISTINCT person_id) FROM (
    SELECT DISTINCT person_id
    FROM base.drug_exposure
    WHERE drug_concept_id IN (SELECT concept_id FROM drug_a_concepts)
    UNION
    SELECT DISTINCT person_id
    FROM base.drug_exposure
    WHERE drug_concept_id IN (SELECT concept_id FROM drug_b_concepts)
) AS combined
LIMIT 1000;
```

### Template (Two Conditions)
```sql
WITH condition_a_concepts AS (
    SELECT ca.descendant_concept_id AS concept_id
    FROM (
        SELECT COALESCE(cr.concept_id_2, c.concept_id) AS standard_id
        FROM base.concept c
        LEFT JOIN base.concept_relationship cr
          ON c.concept_id = cr.concept_id_1
         AND cr.relationship_id = 'Maps to'
        WHERE c.vocabulary_id = '[VOCAB_A]'
          AND c.concept_code = '[CODE_A]'
          AND c.invalid_reason IS NULL
    ) std
    JOIN base.concept_ancestor ca ON std.standard_id = ca.ancestor_concept_id
),
condition_b_concepts AS (
    SELECT ca.descendant_concept_id AS concept_id
    FROM (
        SELECT COALESCE(cr.concept_id_2, c.concept_id) AS standard_id
        FROM base.concept c
        LEFT JOIN base.concept_relationship cr
          ON c.concept_id = cr.concept_id_1
         AND cr.relationship_id = 'Maps to'
        WHERE c.vocabulary_id = '[VOCAB_B]'
          AND c.concept_code = '[CODE_B]'
          AND c.invalid_reason IS NULL
    ) std
    JOIN base.concept_ancestor ca ON std.standard_id = ca.ancestor_concept_id
)
SELECT COUNT(DISTINCT person_id) FROM (
    SELECT DISTINCT person_id
    FROM base.condition_occurrence
    WHERE condition_concept_id IN (SELECT concept_id FROM condition_a_concepts)
    UNION
    SELECT DISTINCT person_id
    FROM base.condition_occurrence
    WHERE condition_concept_id IN (SELECT concept_id FROM condition_b_concepts)
) AS combined
LIMIT 1000;
```

### Key Points
- UNION combines patient sets (not INTERSECT)
- COUNT(DISTINCT person_id) ensures no duplicates
- Each entity gets its own CTE for concept expansion
- Final query wraps UNIONed results

---

## Pattern: AND Queries (Intersection - 2 Entities)

**Use case:** Find patients with Drug A AND Drug B (both required)

**Critical requirement:** Use EXISTS clauses to find patients having BOTH

**IMPORTANT:** For ingredient-level drugs, use hierarchy expansion (same logic as UNION queries above)

### Template (Two Drugs - with Hierarchy if Ingredient Level)

**If entities are ingredient-level (no MG/ML/Tablet), use hierarchy expansion:**

```sql
WITH drug_a_seed AS (
    SELECT c.concept_id
    FROM base.concept c
    WHERE c.vocabulary_id = '[VOCAB_A]'
      AND c.concept_code = '[CODE_A]'
      AND c.invalid_reason IS NULL
),
drug_a_standard AS (
    SELECT COALESCE(cr.concept_id_2, s.concept_id) AS standard_id
    FROM drug_a_seed s
    LEFT JOIN base.concept_relationship cr
      ON s.concept_id = cr.concept_id_1
     AND cr.relationship_id = 'Maps to'
),
drug_a_hierarchy AS (
    -- Use this CTE for ingredient-level concepts
    SELECT DISTINCT ca.descendant_concept_id AS concept_id
    FROM drug_a_standard std
    JOIN base.concept c ON std.standard_id = c.concept_id
    JOIN base.concept_ancestor ca
      ON c.concept_id = ca.ancestor_concept_id
    UNION
    SELECT std.standard_id AS concept_id
    FROM drug_a_standard std
),
drug_b_seed AS (
    SELECT c.concept_id
    FROM base.concept c
    WHERE c.vocabulary_id = '[VOCAB_B]'
      AND c.concept_code = '[CODE_B]'
      AND c.invalid_reason IS NULL
),
drug_b_standard AS (
    SELECT COALESCE(cr.concept_id_2, s.concept_id) AS standard_id
    FROM drug_b_seed s
    LEFT JOIN base.concept_relationship cr
      ON s.concept_id = cr.concept_id_1
     AND cr.relationship_id = 'Maps to'
),
drug_b_hierarchy AS (
    -- Use this CTE for ingredient-level concepts
    SELECT DISTINCT ca.descendant_concept_id AS concept_id
    FROM drug_b_standard std
    JOIN base.concept c ON std.standard_id = c.concept_id
    JOIN base.concept_ancestor ca
      ON c.concept_id = ca.ancestor_concept_id
    UNION
    SELECT std.standard_id AS concept_id
    FROM drug_b_standard std
)
SELECT COUNT(DISTINCT p.person_id)
FROM base.person p
WHERE EXISTS (
    SELECT 1 FROM base.drug_exposure de1
    WHERE de1.person_id = p.person_id
      AND de1.drug_concept_id IN (SELECT concept_id FROM drug_a_hierarchy)
)
AND EXISTS (
    SELECT 1 FROM base.drug_exposure de2
    WHERE de2.person_id = p.person_id
      AND de2.drug_concept_id IN (SELECT concept_id FROM drug_b_hierarchy)
)
LIMIT 1000;
```

**If entities are formulation-specific (have MG/ML/Tablet), use direct matching:**

```sql
WITH drug_a_seed AS (
    SELECT c.concept_id
    FROM base.concept c
    WHERE c.vocabulary_id = '[VOCAB_A]'
      AND c.concept_code = '[CODE_A]'
      AND c.invalid_reason IS NULL
),
drug_a_standard AS (
    SELECT COALESCE(cr.concept_id_2, s.concept_id) AS standard_id
    FROM drug_a_seed s
    LEFT JOIN base.concept_relationship cr
      ON s.concept_id = cr.concept_id_1
     AND cr.relationship_id = 'Maps to'
),
drug_a_concepts AS (
    SELECT std.standard_id AS concept_id
    FROM drug_a_standard std
),
drug_b_seed AS (
    SELECT c.concept_id
    FROM base.concept c
    WHERE c.vocabulary_id = '[VOCAB_B]'
      AND c.concept_code = '[CODE_B]'
      AND c.invalid_reason IS NULL
),
drug_b_standard AS (
    SELECT COALESCE(cr.concept_id_2, s.concept_id) AS standard_id
    FROM drug_b_seed s
    LEFT JOIN base.concept_relationship cr
      ON s.concept_id = cr.concept_id_1
     AND cr.relationship_id = 'Maps to'
),
drug_b_concepts AS (
    SELECT std.standard_id AS concept_id
    FROM drug_b_standard std
)
SELECT COUNT(DISTINCT p.person_id)
FROM base.person p
WHERE EXISTS (
    SELECT 1 FROM base.drug_exposure de1
    WHERE de1.person_id = p.person_id
      AND de1.drug_concept_id IN (SELECT concept_id FROM drug_a_concepts)
)
AND EXISTS (
    SELECT 1 FROM base.drug_exposure de2
    WHERE de2.person_id = p.person_id
      AND de2.drug_concept_id IN (SELECT concept_id FROM drug_b_concepts)
)
LIMIT 1000;
```

### Key Points
- EXISTS clauses check for presence of each drug
- Anchor on person table
- Each EXISTS is independent (different table aliases)
- Returns count of patients having BOTH

---

## Pattern: Multi-Entity Intersection (3+ Entities)

**Use case:** Find patients with Drug A AND Drug B AND Drug C AND Drug D (all required)

**Critical requirement:** One EXISTS clause per entity

### Template (4 Drugs)
```sql
WITH drug1_seed AS (
    SELECT c.concept_id
    FROM base.concept c
    WHERE c.vocabulary_id = '[VOCAB_1]'
      AND c.concept_code = '[CODE_1]'
      AND c.invalid_reason IS NULL
),
drug1_standard AS (
    SELECT COALESCE(cr.concept_id_2, s.concept_id) AS standard_id
    FROM drug1_seed s
    LEFT JOIN base.concept_relationship cr
      ON s.concept_id = cr.concept_id_1
     AND cr.relationship_id = 'Maps to'
),
drug1_concepts AS (
    SELECT std.standard_id AS concept_id
    FROM drug1_standard std
),
drug2_seed AS (
    SELECT c.concept_id
    FROM base.concept c
    WHERE c.vocabulary_id = '[VOCAB_2]'
      AND c.concept_code = '[CODE_2]'
      AND c.invalid_reason IS NULL
),
drug2_standard AS (
    SELECT COALESCE(cr.concept_id_2, s.concept_id) AS standard_id
    FROM drug2_seed s
    LEFT JOIN base.concept_relationship cr
      ON s.concept_id = cr.concept_id_1
     AND cr.relationship_id = 'Maps to'
),
drug2_concepts AS (
    SELECT std.standard_id AS concept_id
    FROM drug2_standard std
),
drug3_seed AS (
    SELECT c.concept_id
    FROM base.concept c
    WHERE c.vocabulary_id = '[VOCAB_3]'
      AND c.concept_code = '[CODE_3]'
      AND c.invalid_reason IS NULL
),
drug3_standard AS (
    SELECT COALESCE(cr.concept_id_2, s.concept_id) AS standard_id
    FROM drug3_seed s
    LEFT JOIN base.concept_relationship cr
      ON s.concept_id = cr.concept_id_1
     AND cr.relationship_id = 'Maps to'
),
drug3_concepts AS (
    SELECT std.standard_id AS concept_id
    FROM drug3_standard std
),
drug4_seed AS (
    SELECT c.concept_id
    FROM base.concept c
    WHERE c.vocabulary_id = '[VOCAB_4]'
      AND c.concept_code = '[CODE_4]'
      AND c.invalid_reason IS NULL
),
drug4_standard AS (
    SELECT COALESCE(cr.concept_id_2, s.concept_id) AS standard_id
    FROM drug4_seed s
    LEFT JOIN base.concept_relationship cr
      ON s.concept_id = cr.concept_id_1
     AND cr.relationship_id = 'Maps to'
),
drug4_concepts AS (
    SELECT std.standard_id AS concept_id
    FROM drug4_standard std
)
SELECT COUNT(DISTINCT p.person_id)
FROM base.person p
WHERE EXISTS (
    SELECT 1 FROM base.drug_exposure
    WHERE person_id = p.person_id
      AND drug_concept_id IN (SELECT concept_id FROM drug1_concepts)
)
AND EXISTS (
    SELECT 1 FROM base.drug_exposure
    WHERE person_id = p.person_id
      AND drug_concept_id IN (SELECT concept_id FROM drug2_concepts)
)
AND EXISTS (
    SELECT 1 FROM base.drug_exposure
    WHERE person_id = p.person_id
      AND drug_concept_id IN (SELECT concept_id FROM drug3_concepts)
)
AND EXISTS (
    SELECT 1 FROM base.drug_exposure
    WHERE person_id = p.person_id
      AND drug_concept_id IN (SELECT concept_id FROM drug4_concepts)
)
LIMIT 1000;
```

### Key Points
- One CTE per drug for concept expansion
- One EXISTS clause per drug in final query
- Anchor on person table
- Add as many EXISTS as needed (no limit)
- Each EXISTS uses same table but different CTE

### Scaling
For N drugs, create N CTEs and N EXISTS clauses. Pattern is fully extensible.

---

## Pattern: Demographics Only (No Medical Concepts)

**Use case:** Count patients by gender, race, age range

### Template (Gender)
```sql
SELECT COUNT(DISTINCT person_id)
FROM base.person
WHERE gender_concept_id = [CONCEPT_ID]
LIMIT 1000;
```

**Gender concept IDs:**
- Female: 8532
- Male: 8507

### Template (Race)
```sql
SELECT COUNT(DISTINCT p.person_id)
FROM base.person p
JOIN base.concept c
  ON p.race_concept_id = c.concept_id
WHERE c.concept_name = '[RACE_NAME]'
  AND c.domain_id = 'Race'
LIMIT 1000;
```

### Template (Age Range by Birth Year)
```sql
SELECT COUNT(DISTINCT person_id)
FROM base.person
WHERE year_of_birth BETWEEN [START_YEAR] AND [END_YEAR]
LIMIT 1000;
```

---

## Pattern: Temporal Constraints (Drug AND Drug within N days)

**Use case:** Find patients with TWO drug exposures within a specified time window

**CRITICAL REQUIREMENT:** Use the EXACT date arithmetic formula below. DO NOT use DATEDIFF, DATE_DIFF, julianday, or simple subtraction.

**Why this formula:** Battle-tested on 680+ queries, works across SQL engines (DuckDB, PostgreSQL), handles edge cases correctly.

### ⚠️ DATE ARITHMETIC - CRITICAL FORMULA

**NEVER use these (they will fail):**
- ❌ `DATEDIFF(date1, date2)`
- ❌ `DATE_DIFF('day', date1, date2)`
- ❌ `julianday(date1) - julianday(date2)`
- ❌ `ABS(date1 - date2)`

**ALWAYS use this formula:**
```sql
WHERE CAST(
    EXTRACT(epoch FROM
        CAST(GREATEST(date1, date2) AS TIMESTAMP) -
        CAST(LEAST(date1, date2) AS TIMESTAMP)
    ) / 86400 AS BIGINT
) <= [N_DAYS]
```

**What this does:**
- `GREATEST/LEAST`: Ensures later_date - earlier_date (always positive)
- `EXTRACT(epoch FROM ...)`: Converts to seconds since epoch
- `/ 86400`: Converts seconds to days (86400 seconds/day)
- `CAST(... AS BIGINT)`: Integer days for comparison
- Works in DuckDB, PostgreSQL, and most SQL engines

---

### Template (Drug AND Drug Temporal - INGREDIENT LEVEL with Hierarchy)

**When to use:**
- Both drugs are ingredient-level (e.g., "metformin", "lisinopril")
- No "MG", "ML", "ACTUAT", "Tablet" in concept names
- Query: "Drug A and Drug B within N days"

**Critical:** Uses concept_ancestor to expand ingredient → all formulations

```sql
WITH drug_a_seed AS (
    SELECT c.concept_id
    FROM base.concept c
    WHERE c.vocabulary_id = '[VOCAB_A]'
      AND c.concept_code = '[CODE_A]'
      AND c.invalid_reason IS NULL
),
drug_a_standard AS (
    SELECT COALESCE(cr.concept_id_2, s.concept_id) AS standard_id
    FROM drug_a_seed s
    LEFT JOIN base.concept_relationship cr
      ON s.concept_id = cr.concept_id_1
     AND cr.relationship_id = 'Maps to'
),
drug_a_hierarchy AS (
    SELECT DISTINCT ca.descendant_concept_id AS concept_id
    FROM drug_a_standard std
    JOIN base.concept c ON std.standard_id = c.concept_id
    JOIN base.concept_ancestor ca ON c.concept_id = ca.ancestor_concept_id
),
drug_a_exposures AS (
    SELECT de.person_id,
           de.drug_exposure_start_date AS start_date
    FROM base.drug_exposure de
    JOIN drug_a_hierarchy h ON de.drug_concept_id = h.concept_id
),
drug_b_seed AS (
    SELECT c.concept_id
    FROM base.concept c
    WHERE c.vocabulary_id = '[VOCAB_B]'
      AND c.concept_code = '[CODE_B]'
      AND c.invalid_reason IS NULL
),
drug_b_standard AS (
    SELECT COALESCE(cr.concept_id_2, s.concept_id) AS standard_id
    FROM drug_b_seed s
    LEFT JOIN base.concept_relationship cr
      ON s.concept_id = cr.concept_id_1
     AND cr.relationship_id = 'Maps to'
),
drug_b_hierarchy AS (
    SELECT DISTINCT ca.descendant_concept_id AS concept_id
    FROM drug_b_standard std
    JOIN base.concept c ON std.standard_id = c.concept_id
    JOIN base.concept_ancestor ca ON c.concept_id = ca.ancestor_concept_id
),
drug_b_exposures AS (
    SELECT de.person_id,
           de.drug_exposure_start_date AS start_date
    FROM base.drug_exposure de
    JOIN drug_b_hierarchy h ON de.drug_concept_id = h.concept_id
)
SELECT COUNT(DISTINCT a.person_id)
FROM drug_a_exposures a
JOIN drug_b_exposures b ON a.person_id = b.person_id
WHERE CAST(
    EXTRACT(epoch FROM
        CAST(GREATEST(a.start_date, b.start_date) AS TIMESTAMP) -
        CAST(LEAST(a.start_date, b.start_date) AS TIMESTAMP)
    ) / 86400 AS BIGINT
) <= [N_DAYS]
LIMIT 1000;
```

**Placeholders:**
- `[VOCAB_A]` = First drug vocabulary (usually 'RxNorm')
- `[CODE_A]` = First drug concept_code
- `[VOCAB_B]` = Second drug vocabulary
- `[CODE_B]` = Second drug concept_code
- `[N_DAYS]` = Number of days (e.g., 30, 60, 90)

---

### Template (Drug AND Drug Temporal - FORMULATION SPECIFIC, Direct Match)

**When to use:**
- Drugs are formulation-specific (e.g., "amlodipine 5 MG Oral Tablet")
- Contains "MG", "ML", "ACTUAT", "Tablet", "Inhaler" in concept names
- Query specifies exact formulation

**Critical:** NO hierarchy expansion, direct concept_id matching only

```sql
WITH drug_a_seed AS (
    SELECT c.concept_id
    FROM base.concept c
    WHERE c.vocabulary_id = '[VOCAB_A]'
      AND c.concept_code = '[CODE_A]'
      AND c.invalid_reason IS NULL
),
drug_a_standard AS (
    SELECT COALESCE(cr.concept_id_2, s.concept_id) AS standard_id
    FROM drug_a_seed s
    LEFT JOIN base.concept_relationship cr
      ON s.concept_id = cr.concept_id_1
     AND cr.relationship_id = 'Maps to'
),
drug_a_exposures AS (
    SELECT de.person_id,
           de.drug_exposure_start_date AS start_date
    FROM base.drug_exposure de
    JOIN drug_a_standard std ON de.drug_concept_id = std.standard_id
),
drug_b_seed AS (
    SELECT c.concept_id
    FROM base.concept c
    WHERE c.vocabulary_id = '[VOCAB_B]'
      AND c.concept_code = '[CODE_B]'
      AND c.invalid_reason IS NULL
),
drug_b_standard AS (
    SELECT COALESCE(cr.concept_id_2, s.concept_id) AS standard_id
    FROM drug_b_seed s
    LEFT JOIN base.concept_relationship cr
      ON s.concept_id = cr.concept_id_1
     AND cr.relationship_id = 'Maps to'
),
drug_b_exposures AS (
    SELECT de.person_id,
           de.drug_exposure_start_date AS start_date
    FROM base.drug_exposure de
    JOIN drug_b_standard std ON de.drug_concept_id = std.standard_id
)
SELECT COUNT(DISTINCT a.person_id)
FROM drug_a_exposures a
JOIN drug_b_exposures b ON a.person_id = b.person_id
WHERE CAST(
    EXTRACT(epoch FROM
        CAST(GREATEST(a.start_date, b.start_date) AS TIMESTAMP) -
        CAST(LEAST(a.start_date, b.start_date) AS TIMESTAMP)
    ) / 86400 AS BIGINT
) <= [N_DAYS]
LIMIT 1000;
```

---

### Template (Condition AND Condition Temporal - with Hierarchy)

**Use case:** Find patients with two conditions diagnosed within N days

**Example:** "Patients with diabetes and hypertension within 90 days"

```sql
WITH condition_a_seed AS (
    SELECT c.concept_id
    FROM base.concept c
    WHERE c.vocabulary_id = '[VOCAB_A]'
      AND c.concept_code = '[CODE_A]'
      AND c.invalid_reason IS NULL
),
condition_a_standard AS (
    SELECT COALESCE(cr.concept_id_2, s.concept_id) AS standard_id
    FROM condition_a_seed s
    LEFT JOIN base.concept_relationship cr
      ON s.concept_id = cr.concept_id_1
     AND cr.relationship_id = 'Maps to'
),
condition_a_hierarchy AS (
    SELECT ca.descendant_concept_id AS concept_id
    FROM condition_a_standard std
    JOIN base.concept_ancestor ca ON std.standard_id = ca.ancestor_concept_id
),
condition_a_occurrences AS (
    SELECT co.person_id,
           co.condition_start_date::date AS start_date
    FROM base.condition_occurrence co
    JOIN condition_a_hierarchy h ON co.condition_concept_id = h.concept_id
),
condition_b_seed AS (
    SELECT c.concept_id
    FROM base.concept c
    WHERE c.vocabulary_id = '[VOCAB_B]'
      AND c.concept_code = '[CODE_B]'
      AND c.invalid_reason IS NULL
),
condition_b_standard AS (
    SELECT COALESCE(cr.concept_id_2, s.concept_id) AS standard_id
    FROM condition_b_seed s
    LEFT JOIN base.concept_relationship cr
      ON s.concept_id = cr.concept_id_1
     AND cr.relationship_id = 'Maps to'
),
condition_b_hierarchy AS (
    SELECT ca.descendant_concept_id AS concept_id
    FROM condition_b_standard std
    JOIN base.concept_ancestor ca ON std.standard_id = ca.ancestor_concept_id
),
condition_b_occurrences AS (
    SELECT co.person_id,
           co.condition_start_date::date AS start_date
    FROM base.condition_occurrence co
    JOIN condition_b_hierarchy h ON co.condition_concept_id = h.concept_id
)
SELECT COUNT(DISTINCT a.person_id)
FROM condition_a_occurrences a
JOIN condition_b_occurrences b ON a.person_id = b.person_id
WHERE CAST(
    EXTRACT(epoch FROM
        CAST(GREATEST(a.start_date, b.start_date) AS TIMESTAMP) -
        CAST(LEAST(a.start_date, b.start_date) AS TIMESTAMP)
    ) / 86400 AS BIGINT
) <= [N_DAYS]
LIMIT 1000;
```

---

### Key Points for Temporal Constraints

1. **Date Formula is NON-NEGOTIABLE**: Use the exact EXTRACT(epoch) formula
2. **Hierarchy Expansion**: Use for ingredient-level drugs and broad conditions
3. **Direct Match**: Use for formulation-specific drugs
4. **Table Aliases**: `a` for first entity, `b` for second entity
5. **CTEs**: Separate CTEs for seed → standard → hierarchy → exposures/occurrences
6. **GREATEST/LEAST**: Handles any date order (earlier or later doesn't matter)

---

### Search Keywords for KB Retrieval

**Database agent should search for:**
- "Drug AND temporal ingredient hierarchy" → Use ingredient-level template
- "Drug AND temporal formulation direct" → Use formulation-specific template
- "Condition AND temporal hierarchy" → Use condition temporal template
- "within N days date arithmetic" → Get the correct EXTRACT formula

---

## Quick Reference: Query Type → Pattern

| User Query | Query Type | Pattern to Use |
|------------|------------|----------------|
| "Drug A or Drug B" | union | OR Queries (UNION) |
| "Drug A and Drug B" | intersection | AND Queries (Intersection) |
| "Drug A, Drug B, Drug C, Drug D" | multi_intersection | Multi-Entity Intersection |
| "Condition X at age Y" | age_constrained | Age-Constrained Queries (Condition) |
| "Drug X at age Y" | age_constrained | Age-Constrained Queries (Drug) |
| "How many patients are female?" | demographics | Demographics Only (Gender) |

---

## Common Mistakes to Avoid

### ❌ WRONG: Date arithmetic with DATEDIFF (WILL FAIL)
```sql
-- These functions DO NOT EXIST in this database:
WHERE DATEDIFF(date1, date2) <= 30  -- FAILS
WHERE DATE_DIFF('day', date1, date2) <= 30  -- FAILS
WHERE julianday(date1) - julianday(date2) <= 30  -- FAILS
WHERE ABS(date1 - date2) <= 30  -- UNRELIABLE
```

### ✓ CORRECT: Use EXTRACT(epoch) formula
```sql
WHERE CAST(
    EXTRACT(epoch FROM
        CAST(GREATEST(date1, date2) AS TIMESTAMP) -
        CAST(LEAST(date1, date2) AS TIMESTAMP)
    ) / 86400 AS BIGINT
) <= 30
```

### ❌ WRONG: Age = current age
```sql
WHERE (EXTRACT(YEAR FROM CURRENT_DATE) - year_of_birth) = 18
```

### ✓ CORRECT: Age at event
```sql
WHERE (EXTRACT(YEAR FROM co.condition_start_date) - p.year_of_birth) = 18
```

### ❌ WRONG: OR query using INTERSECT
```sql
SELECT person_id FROM drug_a
INTERSECT
SELECT person_id FROM drug_b
```

### ✓ CORRECT: OR query using UNION
```sql
SELECT person_id FROM drug_a
UNION
SELECT person_id FROM drug_b
```

### ❌ WRONG: Multi-entity with JOINs
```sql
FROM drug_exposure de1
JOIN drug_exposure de2 ON de1.person_id = de2.person_id
JOIN drug_exposure de3 ON de1.person_id = de3.person_id
```

### ✓ CORRECT: Multi-entity with EXISTS
```sql
WHERE EXISTS (drug1)
  AND EXISTS (drug2)
  AND EXISTS (drug3)
```

---

## Summary

Use these patterns EXACTLY as written. They are battle-tested and correct:

1. **Age constraints**: `EXTRACT(YEAR FROM event_date) - year_of_birth`
2. **OR queries**: UNION with COUNT(DISTINCT person_id)
3. **AND queries**: Multiple EXISTS clauses
4. **Multi-entity**: One EXISTS per entity
5. **Demographics**: Direct person table query

Do NOT deviate from these patterns unless you have a specific reason documented in code.
