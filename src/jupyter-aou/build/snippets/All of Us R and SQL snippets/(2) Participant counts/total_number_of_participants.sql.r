
total_number_of_participants_df <- bq_table_download(bq_project_query(
    BILLING_PROJECT_ID, page_size = 25000,
    query = str_glue('
-- Compute the count of unique participants in our All of Us cohort.
SELECT
  COUNT(DISTINCT person_id) AS total_number_of_participants
FROM
  `{CDR}.person`
WHERE
  person_id IN ({COHORT_QUERY})
')))

print(skim(total_number_of_participants_df))

head(total_number_of_participants_df)