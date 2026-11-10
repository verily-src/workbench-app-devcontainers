# data

Synthetic data for prototyping against the All of Us tables VIA queries, so local
development and testing don't need access to a real CDR.

## Layout

```
data/synthetic/
  generators/   the scripts that produce the tables below
  schemas/      BigQuery table schemas (field name, type, mode)
  tables/       generated NDJSON, one JSON object per line, ready for `bq load`
```

There are currently two synthetic datasets, with generators for each:

## Variant Annotation Table (VAT)

| | |
|---|---|
| Schema | `schemas/foxtrot_v4_2025_07_29_vat_v9_r2_p2_schema.json` |
| Table | `tables/synthetic_foxtrot_vat.ndjson` (1,060 rows: 1,000 random plus 60 from the use cases) |
| Generator | `generators/generate_vat_synthetic.py` |

114 fields covering variant identity, GVS allele counts and frequencies (overall and
per-subpopulation), gnomAD frequencies, transcript/consequence annotations, ClinVar, OMIM,
and in-silico predictors (REVEL, SpliceAI, GERP, LoF).

```
python3 data/synthetic/generators/generate_vat_synthetic.py
```

Deterministic given `--seed` (default 42). `--rows` changes the row count, and `--schema ""`
skips field validation.

## Condition lookup

Three tables backing free-text → condition `concept_id` → `person_id`.

| Schema | Table | Rows |
|---|---|---|
| `schemas/cb_criteria_schema.json` | `tables/synthetic_cb_criteria.ndjson` | 16 |
| `schemas/concept_ancestor_schema.json` | `tables/synthetic_concept_ancestor.ndjson` | 21 |
| `schemas/condition_occurrence_schema.json` | `tables/synthetic_condition_occurrence.ndjson` | 6,544 |

The counts include the three conditions the demo use cases add (below). They come after the
fixture's own rows in every table, so the fixture described here is unchanged by them.

A search can filter by several conditions at once, matching participants recorded with any of
them, and shows each condition's own count beside the union. So that the union isn't always the
sum, 13 of long QT syndrome's 131 participants are also hypertrophic cardiomyopathy participants
(`SHARED_PARTICIPANTS` in the generator): searching on both matches 214 + 131 − 13 = 332. Each
condition's own count is unchanged, so the use case fixtures still apply.

`cb_criteria` is the All of Us cohort-builder table the text search runs against;
`concept_ancestor` expands a concept to its descendants; `condition_occurrence` is standard
OMOP and is where the participants come from.

```
python3 data/synthetic/generators/generate_condition_lookup_tables_synthetic.py
```

Deterministic given `--seed` (default 42).

### What the fixture is built around

`cb_criteria` shape:

- **9000010 appears twice** at different `path` values, identical in every other column a
  search projects. Dedup works only because `id` and `path` are excluded from the `SELECT`;
  adding either back reintroduces the duplicate.
- **One group row with `concept_id = NULL`**, whose `full_text` deliberately matches the
  fallot searches. The `concept_id IS NOT NULL` filter is the only thing keeping it out.
- **`est_count` of `-1` (9000015) and `NULL` (9000016)** sit on their own concepts rather
  than on concepts that already have a normal row — otherwise `SELECT DISTINCT` wouldn't
  collapse them and they'd break the appears-once case above.
- **9000018 "Fallot tetralogy, repaired"** contains no `of` in any form. Requiring the
  literal token `of` drops it, which is the inverted-word-order case that dropping
  connectives before matching exists to catch.

Cohort counts, exact by construction and verified against BigQuery:

| Seed | Participants | Why |
|---|---|---|
| `[9000010]` | 214 | 180 + 26 + 8 via descendant expansion; seed-only matching gives 180 |
| `[9000001]` | 225 | also pulls in Pentalogy — the "don't seed on a parent" failure, made visible |
| `[9000030]` | 1,200 | high-prevalence anchor |
| `[9000031]` | 180 | subset of the above |

9000010's `est_count` is **205** against a true cohort of **214**. That mismatch is
intentional: `est_count` is an estimate in the real table, so a sanity check should tolerate
small divergence while still catching gross error.

9000014, 9000015, 9000016 and 9000018 have self-rows in `concept_ancestor` and no
participants. They exist to exercise search ranking and filtering, and staying out of the
hierarchy keeps the cohort counts above exact.

## Demo use cases

Four curated searches, each a condition plus 15 or 16 hand-picked variants, written so every
panel of the results page looks right for them. They're what the entry page's **Try an
example** menu fills in.

| Use case | Condition (concept, participants) | Variants |
|---|---|---|
| Tetralogy of Fallot | 9000010, 214 (the fixture above) | NKX2-5, GATA4, GATA6, TBX5, TBX1, JAG1, FLT4, GDF1, ZFPM2 |
| Hypertrophic cardiomyopathy | 9000040, 214 | MYH7, MYBPC3, TNNT2, TNNI3, TPM1, ACTC1 |
| Familial hypercholesterolemia | 9000050, 391 | LDLR, APOB, PCSK9 |
| Long QT syndrome | 9000060, 131 | KCNQ1, KCNH2, SCN5A, KCNE1 |

Each lives in its own file under `generators/use_cases/`, as plain Python data in the types
from `use_cases/common.py`.

**The variants are real, and so is most of what's said about them.** Their GRCh38 positions,
alleles, MANE Select transcripts, HGVS and ClinVar records (classification, review status, RCVs,
conditions) were checked against ClinVar and Ensembl VEP; their SpliceAI, REVEL and LOFTEE
(pLOF) calls are VEP's own, from its plugins; and their gnomAD counts are gnomAD v4
genomes', per population, from its API -- so the gnomAD and ClinVar links open pages that agree with the app.
Per-RCV review status isn't recorded; each RCV gets the variant's overall stars.

Each use case mixes classes -- missense, nonsense, frameshift, splice donor/acceptor, synonymous
-- and frequencies, from ultra-rare pathogenic variants to common benign ones.

**Everything about the All of Us cohort is synthetic**: its allele counts, who among the matched
participants carries what, and their ancestry and age. A common variant's All of Us frequencies
are drawn from its gnomAD ones; a rare variant's counts are set by hand. Those are chosen per use
case to show off the app: strongly enriched rare pathogenic variants, common variants at
background, depleted protective variants, a VUS or two, and one variant missing from All of Us.

The use cases feed all three generators:

- `generate_vat_synthetic.py` appends each variant's VAT row: a random row with every column
  the app shows overwritten from its spec. A variant with no All of Us data gets no row.
- `generate_condition_lookup_tables_synthetic.py` adds the new conditions, each with its own
  block of participants so the counts above are exact.
- `generate_use_case_fixtures.py` writes the two fixtures the app reads outside BigQuery:
  - `api/src/main/resources/fixtures/phenotype_use_cases.json`: each use case's
    phenotype-matched counts and ancestry and age breakdowns. The backend has no genotype data,
    so it serves these for a use case's condition and makes the numbers up
    (`MockPhenotypeData`) for anything else. It ignores a use case whose participant count
    doesn't match what the loaded condition tables return.
  - `ui/src/data/useCases.json`: the **Try an example** menu.

  Unlike the NDJSON tables, **commit these two**: the API and UI builds read them.

`use_cases/__init__.py` validates every use case on import (breakdowns sum to the participant
count, matched counts fit the cohort, and so on), so a generator run fails on a use case that
would render as contradictory numbers.

### Adding a use case

`generators/curate_use_case_variant.py` does the lookups. Give it variants, as GRCh38
`chr-pos-ref-alt` IDs or `GENE:CHANGE` (ClinVar's one-letter protein change), and it prints a
`Variant(...)` spec for each with its ClinVar record, VEP annotation (MANE Select consequence,
HGVS, SpliceAI, REVEL, LOFTEE) and gnomAD v4 genome counts filled in. For a common variant it also
drafts the All of Us frequencies from gnomAD's, and with `--participants N` the matched carriers;
for a rare one those are left as `TODO`s to set by hand.

```
python3 data/synthetic/generators/curate_use_case_variant.py MYH7:R403Q 19-11105540-TC-T
python3 data/synthetic/generators/curate_use_case_variant.py 19-11120205-T-C --participants 391
```

1. Run it on the variants you want, and review what it prints.
2. Write `use_cases/<name>.py` with a `CASE`, following an existing one, pasting the specs in and
   settling the `TODO`s; add it to `USE_CASES` in `use_cases/__init__.py`. Give a new condition
   an unused concept ID (9000070 and up).
3. Rerun all three generators, reload the tables (below), and commit the two fixtures.

`--verify` re-checks every variant already in the use cases against the live sources and lists
anything that has drifted since -- a reclassified ClinVar record, new gnomAD counts. It needs
network access, and takes a few minutes: ClinVar allows 3 requests a second (10 with
`NCBI_API_KEY` set) and gnomAD about one.

## Regenerating and loading

From the repo root:

```
python3 data/synthetic/generators/generate_vat_synthetic.py
python3 data/synthetic/generators/generate_condition_lookup_tables_synthetic.py
python3 data/synthetic/generators/generate_use_case_fixtures.py
data/synthetic/load_bq.sh                       # aou-via-dev:foxtrot_synthetic, VAT into v3
```

`load_bq.sh [project:dataset] [vat_table]` replaces each table with `bq load --replace`, using
the schemas here. It needs gcloud credentials that can write to the dataset. The API reads the
VAT table named by `VAT_TABLE_ID` (default `v3`), so set it to the table you loaded.

