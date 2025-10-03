
-- Compute summary information for our measurements of interest for our cohort.
--
-- PARAMETERS:
--   MEASUREMENT_OF_INTEREST: a case-insensitive string, such as "hemoglobin", to be compared
--                            to all measurement concept names to identify those of interest

WITH
  --
  -- Use a case insensitive string to search the measurement concept names of those
  -- measurements we do have in the measurements table.
  --
  labs_of_interest AS (
  SELECT
    measurement_concept_id,
    measurement_concept.concept_name AS measurement_name,
    unit_concept_id,
    unit_concept.concept_name AS unit_name
  FROM
    `{CDR}.measurement`
  LEFT JOIN `{CDR}.concept` AS measurement_concept
  ON measurement_concept.concept_id = measurement_concept_id
  LEFT JOIN `{CDR}.concept` AS unit_concept
  ON unit_concept.concept_id = unit_concept_id
  WHERE
    REGEXP_CONTAINS(measurement_concept.concept_name, r"(?i){MEASUREMENT_OF_INTEREST}")
  GROUP BY
    measurement_concept_id,
    unit_concept_id,
    measurement_concept.concept_name,
    unit_concept.concept_name
)
  --
  -- Summarize the information about each measurement concept of interest that our
  -- prior query identified.
  --
SELECT
  measurement_name AS measurement,
  IFNULL(unit_name, "NA") AS unit,
  COUNT(1) AS N,
  COUNTIF(value_as_number IS NULL
    AND (value_as_concept_id IS NULL
      OR value_as_concept_id = 0)) AS missing,
  MIN(value_as_number) AS min,
  MAX(value_as_number) AS max,
  AVG(value_as_number) AS avg,
  STDDEV(value_as_number) AS stddev,
  APPROX_QUANTILES(value_as_number, 4) AS quantiles,
  COUNTIF(value_as_number IS NOT NULL) AS num_numeric_values,
  COUNTIF(value_as_concept_id IS NOT NULL
      AND value_as_concept_id != 0) AS num_concept_values,
  COUNTIF(operator_concept_id IS NOT NULL) AS num_operators,
  IF(src_id = "PPI/PM", "PPI", "EHR") AS measurement_source,
  measurement_concept_id,
  unit_concept_id
FROM
  `{CDR}.measurement`
INNER JOIN
 labs_of_interest USING(measurement_concept_id, unit_concept_id)
LEFT JOIN
  `{CDR}.measurement_ext` USING(measurement_id)
WHERE
  person_id IN ({COHORT_QUERY})
GROUP BY
  measurement_concept_id,
  measurement_name,
  measurement_source,
  unit_concept_id,
  unit_name
ORDER BY
  N DESC

