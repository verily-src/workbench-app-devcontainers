
number_of_participants_with_measurements_df <- bq_table_download(bq_project_query(
    BILLING_PROJECT_ID, page_size = 25000,
    query = str_glue('
-- Compute the count of unique participants in our All of Us cohort
-- that have at least one measurement.
SELECT
  COUNT(DISTINCT person_id) AS number_of_participants_with_measurements
FROM
  `{CDR}.measurement`
WHERE
  person_id IN ({COHORT_QUERY})
')))

print(skim(number_of_participants_with_measurements_df))

head(number_of_participants_with_measurements_df)