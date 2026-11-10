#!/usr/bin/env bash
# Loads the generated synthetic tables (data/synthetic/tables/) into a BigQuery dataset.
#
#   data/synthetic/load_bq.sh [project:dataset] [vat_table]
#
# Defaults to aou-via-dev:foxtrot_synthetic, with the VAT going to table v3. Each table is
# replaced outright (--replace), using the schemas in data/synthetic/schemas/. Generate the tables
# first (see data/README.md); run from the repo root, with gcloud credentials that can write to
# the dataset.
set -euo pipefail

DATASET="${1:-aou-via-dev:foxtrot_synthetic}"
VAT_TABLE="${2:-v3}"
DIR="data/synthetic"

load() {
  local table="$1" ndjson="$2" schema="$3"
  echo "Loading ${DIR}/tables/${ndjson} -> ${DATASET}.${table}"
  bq load --replace --source_format=NEWLINE_DELIMITED_JSON \
    "${DATASET}.${table}" "${DIR}/tables/${ndjson}" "${DIR}/schemas/${schema}"
}

for f in synthetic_foxtrot_vat synthetic_cb_criteria synthetic_concept_ancestor synthetic_condition_occurrence; do
  [[ -f "${DIR}/tables/${f}.ndjson" ]] || { echo "Missing ${DIR}/tables/${f}.ndjson -- run the generators first." >&2; exit 1; }
done

load "${VAT_TABLE}" synthetic_foxtrot_vat.ndjson foxtrot_v4_2025_07_29_vat_v9_r2_p2_schema.json
load cb_criteria synthetic_cb_criteria.ndjson cb_criteria_schema.json
load concept_ancestor synthetic_concept_ancestor.ndjson concept_ancestor_schema.json
load condition_occurrence synthetic_condition_occurrence.ndjson condition_occurrence_schema.json

echo "Done. To use the new VAT, set VAT_TABLE_ID=${VAT_TABLE} (or change the default in api/src/main/resources/application.properties)."
