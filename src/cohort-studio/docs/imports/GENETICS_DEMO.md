# Synthetic genetics join demo

Status 2026-10-22: COMPLETE. SSM `efb3c4c4-1e05-4bcf-97e1-94c2274c35d9` succeeded. Aurora committed 5,000 samples, 200 annotated synthetic variants and 1,000,000 genotypes. Live normal table listing/open passed; Dashboard API join to OMOP returned 5,000 rows using Aurora. Planted pattern verified: 500 people, 10,000 genotype rows. Real database tests: 3 passed. Do not rerun the loader.

This importer adds a reproducible, fabricated genotype dataset to a new
`genetics_demo` schema in the selected Aurora database. It links to the
existing `cms_synpuf_100k.person` IDs. It does not change OMOP tables.

The default load creates 5,000 samples, 200 fabricated variant records, and
1,000,000 genotype rows. IDs use `SYN_` labels; these are not rsIDs. All
genotypes, variant positions, depth and quality values are simulated. They
must not be used for clinical or scientific conclusions. The first 20
variants carry `demo_group = planted_demo_pattern`; every tenth sample carries
`demo_group = planted_demo_group` and has dosage 2 at those variants. Other
samples have dosage 0. Gene names such as `SYN_GENE_001` and the
`missense`/`synonymous`/`splice` consequence labels are fabricated fields, not
genome annotations. This known pattern
exists only to make the join and variant filtering easy to inspect. The seed,
source schema, counts, and notice are stored in `genetics_demo.import_metadata`.

Run from the Studio app directory after code is available in the container:

```sh
python genetics_demo.py
```

To export the rows loaded in Aurora, pass a new output directory:

```sh
python genetics_demo.py --export-only \
  --export-csv /tmp/genetics-demo-csv
```

The command writes `samples.csv`, `variants.csv`, `genotypes.csv`, and a
`manifest.json` with the seed, source, counts and synthetic notice. It refuses
to use an output directory that already exists. Export does not regenerate
data; it reads the committed Aurora tables.

The importer refuses to replace an existing target schema. Its schema create,
data inserts, indexes, summary view and metadata commit in one transaction. If
the transaction fails, PostgreSQL rolls it back. The target is fixed to the
existing `cohort-dash-db-20261005` resource unless maintainers change the
allowlist in the script.

## Explore in Cohort Studio

1. Select the Aurora resource that contains `cms_synpuf_100k`.
2. In the schema browser, open `genetics_demo.samples`, then add
   `genetics_demo.genotypes` with `sample_id` as the join key. Add
   `genetics_demo.variants` with `variant_id` as the next join key.
3. Add `cms_synpuf_100k.person` and join `samples.person_id` to
   `person.person_id`. Keep the person count separate from genotype row count.
4. Filter `samples.demo_group` to `planted_demo_group` and
   `variants.demo_group` to `planted_demo_pattern`. The result should show 500
   people and 10,000 genotype rows with the default size.
5. For a compact variant summary, open `genetics_demo.demo_pattern_summary`
and filter `dosage = 2`. It reports 500 samples for each of the 20 planted
   variants.

The equivalent join check is:

```sql
SELECT count(DISTINCT s.person_id) AS people,
       count(*) AS genotype_rows,
       count(DISTINCT v.variant_id) AS variants
FROM genetics_demo.genotypes g
JOIN genetics_demo.samples s USING (sample_id)
JOIN genetics_demo.variants v USING (variant_id)
JOIN cms_synpuf_100k.person p USING (person_id)
WHERE v.demo_group = 'planted_demo_pattern'
  AND s.demo_group = 'planted_demo_group'
  AND g.dosage = 2;
```

Expected defaults: 500 people, 10,000 genotype rows, 20 variants. The view and
tables appear through the normal Aurora schema browser; no genetics-specific
UI or scientific association analysis is provided.

CSV files and manifest are in workspace resource `nextflow_outputs`, prefix
`_studio_imports/genetics_demo/20261022/csv/`. They contain the committed table
rows, not a separate regenerated sample.
