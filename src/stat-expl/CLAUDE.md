# Dataset Statistical Explorer (stat-expl)

## What this app is
A 5-page scientific workspace for senior biostatisticians to assess whether
an EHR/registry dataset is fit for a given research purpose.
The output of a session is a structured fitness report, not a dashboard.

Pages (in order): Passport · Population · Variables · Quality · Hypotheses
Persistent across all pages: cohort filter bar, flag tray, export button.

## Stack
React + TypeScript + Vite. Tailwind CSS for layout only — no component libraries.
Recharts for all charts. No backend. All data loaded from docs/schema.json,
which is generated in Phase 0 before any app code is written.

## GCP architecture
Data project:  wb-spotless-eggplant-4340   (BigQuery data lives here)
App project:   wb-rapid-apricot-2196        (queries run from here)

Known datasets inside wb-spotless-eggplant-4340:
  analysis | crf | sensordata | (others discovered in Phase 0)

All BigQuery queries run from wb-rapid-apricot-2196 and reference
wb-spotless-eggplant-4340.DATASET_NAME.TABLE_NAME

NEVER query row data. Schema and metadata only. See docs/schema.json.

## Non-negotiables
- Every number rendered on screen must be rounded (no float artifacts)
- Cohort filters persist across all page navigation via React context
- Flags are computed automatically from schema.json — never hardcoded
- The "Cannot answer" section on the Hypotheses page is always populated
- Mobile layout not required for v1

## Where to find the full spec
docs/SPEC.md — read this before building any page.
docs/schema.json — generated in Phase 0, required before Phase 1.
