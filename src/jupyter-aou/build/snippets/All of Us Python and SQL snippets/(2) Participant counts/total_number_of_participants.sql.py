
total_number_of_participants_df = pd.io.gbq.read_gbq(f'''

-- Compute the count of unique participants in our All of Us cohort.
SELECT
  COUNT(DISTINCT person_id) AS total_number_of_participants
FROM
  `{CDR}.person`
WHERE
  person_id IN ({COHORT_QUERY})

''',
  dialect='standard')

total_number_of_participants_df.head()