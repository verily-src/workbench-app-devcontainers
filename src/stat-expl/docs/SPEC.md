# Dataset Statistical Explorer (stat-expl) — Full Build Specification

---

## PHASE 0 — Schema discovery (run before writing any app code)

Your only job in Phase 0 is to inspect the BigQuery dataset schema and
produce docs/schema.json. Do not write any app code until Phase 0 is
complete and reviewed.

### GCP project structure
Data project:  wb-spotless-eggplant-4340   (where the data lives)
App project:   wb-rapid-apricot-2196        (where queries run from)

The data project contains multiple datasets: analysis, crf, sensordata,
and possibly others. Phase 0 discovers and inspects all of them.

### Rules
- Schema and metadata queries only. No SELECT on actual table data.
- Never run SELECT *, SELECT ... LIMIT N, or any row-level query.
- If a query fails, note the error and continue with the next one.
- Do not guess or infer values — use only what the queries return.
- Run all bq commands with --project_id=wb-rapid-apricot-2196

### Step 1 — discover all datasets in the data project
Saves to: docs/bq_datasets.json

```bash
bq ls --format=json --project_id=wb-spotless-eggplant-4340 > docs/bq_datasets.json
```

Parse the output to get the full list of dataset names before running Steps 2–5.

### Steps 2–5 — run once per dataset

For EACH dataset discovered in Step 1, run the following four queries.
Replace DATASET_NAME with the actual dataset name each time.
Save output as docs/bq_DATASETNAME_tables.json etc.

#### Tables with row counts and size
Saves to: docs/bq_DATASETNAME_tables.json

```bash
bq query --use_legacy_sql=false --format=json \
  --project_id=wb-rapid-apricot-2196 \
'SELECT
  table_id,
  ROUND(size_bytes / 1e6, 1)           AS size_mb,
  row_count,
  TIMESTAMP_MILLIS(creation_time)      AS created_at,
  TIMESTAMP_MILLIS(last_modified_time) AS last_modified
FROM `wb-spotless-eggplant-4340.DATASET_NAME.__TABLES__`
ORDER BY row_count DESC' \
> docs/bq_DATASETNAME_tables.json
```

#### All columns
Saves to: docs/bq_DATASETNAME_columns.json

```bash
bq query --use_legacy_sql=false --format=json \
  --project_id=wb-rapid-apricot-2196 \
'SELECT
  table_name,
  column_name,
  ordinal_position,
  data_type,
  is_nullable,
  is_partitioning_column
FROM `wb-spotless-eggplant-4340.DATASET_NAME.INFORMATION_SCHEMA.COLUMNS`
ORDER BY table_name, ordinal_position' \
> docs/bq_DATASETNAME_columns.json
```

#### Table and column descriptions
Saves to: docs/bq_DATASETNAME_descriptions.json

```bash
bq query --use_legacy_sql=false --format=json \
  --project_id=wb-rapid-apricot-2196 \
'SELECT
  c.table_name,
  c.column_name,
  c.description  AS column_description,
  t.option_value AS table_description
FROM `wb-spotless-eggplant-4340.DATASET_NAME.INFORMATION_SCHEMA.COLUMN_FIELD_PATHS` c
LEFT JOIN `wb-spotless-eggplant-4340.DATASET_NAME.INFORMATION_SCHEMA.TABLE_OPTIONS` t
  ON c.table_name = t.table_name AND t.option_name = "description"
ORDER BY c.table_name, c.column_name' \
> docs/bq_DATASETNAME_descriptions.json
```

#### Partition and clustering columns
Saves to: docs/bq_DATASETNAME_partitions.json

```bash
bq query --use_legacy_sql=false --format=json \
  --project_id=wb-rapid-apricot-2196 \
'SELECT
  table_name,
  column_name,
  data_type,
  is_partitioning_column,
  clustering_ordinal_position
FROM `wb-spotless-eggplant-4340.DATASET_NAME.INFORMATION_SCHEMA.COLUMNS`
WHERE is_partitioning_column = "YES"
   OR clustering_ordinal_position IS NOT NULL
ORDER BY table_name, clustering_ordinal_position' \
> docs/bq_DATASETNAME_partitions.json
```

### Consolidate into docs/schema.json

After running all queries across all datasets, consolidate into docs/schema.json:

```json
{
  "data_project": "wb-spotless-eggplant-4340",
  "app_project": "wb-rapid-apricot-2196",
  "extracted_at": "ISO timestamp",
  "datasets": [
    {
      "name": "analysis",
      "tables": [
        {
          "name": "table_name",
          "dataset": "analysis",
          "domain": "one of: ehr | labs | medications | diagnoses | sensor | pro | outcomes | admin | other",
          "row_count": 0,
          "size_mb": 0,
          "last_modified": "ISO date",
          "description": "from descriptions query or empty string",
          "partition_column": "column name or null",
          "columns": [
            {
              "name": "raw column name",
              "type": "BQ data type",
              "nullable": true,
              "ordinal_position": 1,
              "clinical_label": "plain English name a clinician recognises",
              "clinical_domain": "one of the domain values above",
              "description": "from descriptions query or empty string",
              "is_candidate_endpoint": false,
              "is_candidate_exposure": false,
              "is_candidate_confounder": false
            }
          ]
        }
      ]
    }
  ]
}
```

Guidance for clinical classification:
- clinical_label: map raw names to plain English
  (e.g. "egfr_mdrd" → "eGFR (MDRD)", "hrv_rmssd" → "HRV (RMSSD)", "bmi_value" → "BMI")
- domain: use dataset name as first hint (sensordata → sensor, crf → ehr/pro),
  then refine by table and column names
- is_candidate_endpoint: true if plausibly a study outcome
  (mortality, hospitalisation, lab value change, symptom score, sensor-derived metric)
- is_candidate_exposure: true if plausibly a treatment, medication, or risk factor
- is_candidate_confounder: true if a standard adjustment variable
  (age, sex, BMI, comorbidity score, prior treatment, site, enrollment year)

### Phase 0 end — print this summary and stop

After generating schema.json, print:
1. Datasets found inside wb-spotless-eggplant-4340
2. Tables per dataset — name, assigned clinical domain, row count, last modified
3. Total columns across all datasets
4. Columns with descriptions vs columns without
5. Partition columns found per dataset (reveal date range from metadata alone)
6. Any datasets or tables that failed to query — list with error
7. Any tables with 0 rows or suspicious metadata
8. Columns you could not classify — list by dataset.table.column

STOP HERE. Wait for review and confirmation before starting Phase 1.

---

## App architecture

```
src/stat-expl/
  src/
    context/
      CohortContext.tsx     — cohort filters, live N, flag list (global state)
    pages/
      Passport.tsx
      Population.tsx
      Variables.tsx
      Quality.tsx
      Hypotheses.tsx
    components/
      CohortBar.tsx         — persistent filter chip row, rendered on every page
      FlagTray.tsx          — persistent warning tray, rendered on every page
      ExportButton.tsx      — generates and downloads fitness report as .md
      Nav.tsx               — top navigation, 5 page items + export button
    lib/
      schema.ts             — loads and parses docs/schema.json
      flags.ts              — flag computation logic (never hardcode flags)
      power.ts              — naive power estimate calculations
      report.ts             — fitness report generator
    App.tsx                 — shell: Nav + CohortBar + FlagTray + <Routes>
  docs/
    SPEC.md                 — this file
    schema.json             — generated in Phase 0
  CLAUDE.md
```

---

## Persistent shell (rendered on every page)

### CohortBar
- Rendered in App.tsx above all page content
- State lives in CohortContext
- Shows: active filter chips (each removable), "+ add filter" button, live patient N
- Removing a chip re-computes N from remaining filters
- Adding a filter: simple modal, pick variable + operator + value
- Chip format: "Age 40–75 ×"  "Dx: Type 2 diabetes ×"  "Follow-up ≥ 6 mo ×"
- N shown as: "12,847 patients" — always formatted with locale separator, never float

### FlagTray
- Rendered in App.tsx below CohortBar
- Shows: most severe active flag as one line, "See all flags (N)" link
- Severity: red = stop | amber = caution | green = clear
- Flags computed in lib/flags.ts from schema.json + CohortContext state
- User can dismiss or annotate individual flags
- Hidden entirely when no active flags

---

## Page 1 — Passport

Decision: Is this dataset worth my time at all?
Target time: under 2 minutes.
Renders automatically — no user input required to see initial state.

### Display
- 4 stat cards: unique patients | date range | median follow-up with IQR | last data refresh
- Domain coverage grid: one card per domain, % patient coverage as a fill bar
  Colour thresholds: green ≥ 70% | amber 40–69% | red < 40%
- Enrollment density chart: Recharts BarChart, one bar per month, full timeline
  Highlight last 3 months in amber if enrollment drops > 50% vs prior 3-month average

### Controls
- Slider: minimum follow-up threshold (0–60 months) → updates patient count live
- Toggle: all patients vs patients with ≥ 1 record in every domain

### Auto-flags (written to CohortContext via lib/flags.ts)
- RED: median follow-up < 6 months
- RED: last data refresh > 180 days ago
- AMBER: any domain listed as available but < 20% patient coverage
- AMBER: enrollment drops > 50% in last 6 months

---

## Page 2 — Population

Decision: Is the population relevant to my scientific question?
Target time: under 5 minutes.

### Display
- Search input: clinical concept search across diagnoses, drug classes, lab names
  On match: show subgroup N, re-render all demographic cards for that subgroup
- 4 stat cards: median age | sex % | median Charlson index | site count
- Top-20 diagnoses: horizontal bar chart, ICD codes translated to clinical_label values
  from schema.json — never display raw ICD codes
- Top-20 medications: grouped by drug class, not individual drug names
- Comorbidity distribution: histogram of Charlson index scores
- Site distribution bar chart (only if > 1 site present in schema)

### Controls
- Clinical concept search — instant filter, subgroup N updates as you type
- Side-by-side comparison: select two subgroups, render demographics in two columns
- Stack inclusion/exclusion filters with N attrition shown per filter added

### Auto-flags
- AMBER: single site contributes > 70% of patients
- AMBER: age range spans < 15 years across the full registry

---

## Page 3 — Variables

Decision: Are the variables I need present AND usable?
Target time: under 10 minutes.

### Display
- Variable grid grouped by clinical_domain (not by source table name)
- Columns: Domain | Clinical label | Coverage bar + % | Median values/patient | Tag badge
- Coverage bar: green ≥ 70% | amber 40–69% | red < 40%
- Expandable row on click: full distribution description, temporal capture rate,
  unit/type info, outlier range if defined
- Sensor domain extra rows per variable:
  median wear-days | % patients ≥ 7 consecutive days | % patients ≥ 30 days

### Controls
- Slider: minimum patient coverage % (0–100) → filters grid live
- Slider: minimum values per patient (1–20) → filters grid live
- Search: clinical concept → matches clinical_label and description fields
- Tag controls per row: endpoint / exposure / confounder / none
  Tags persist in CohortContext and carry into Hypotheses page

### Auto-flags
- AMBER: any column tagged as endpoint has coverage < 60%
- AMBER: sensor domain median values/patient < 7
- RED: same clinical concept appears under 3+ differently named columns

---

## Page 4 — Quality

Decision: Is quality good enough for inference, or description only?
Target time: under 10 minutes.

### Display
- Missingness heatmap (main element):
  200 sampled patient rows × tagged columns
  Cell states: filled (present) | empty (missing) | hatched (out of range)
  Label: "Simulated pattern preview based on coverage statistics.
  Not derived from individual patient records."
- Missingness correlation panel: top 5 variable pairs where missingness
  on one correlates with value on another
- Outlier summary: per tagged variable, count > 3 SD and count outside
  physiological plausible range
- Temporal consistency: count of impossible event sequences by type
- 4 stat cards: impossible sequences | outlier flags | complete-case N | duplicate estimate

### Controls
- Sort heatmap by: follow-up duration | Charlson score | enrollment year | site
- Select 2 variables → scatter: is missingness on X associated with value of Y?
- Outlier threshold override: custom range per variable
- Complete-case calculator: select tagged variables → show N with all present

### Auto-flags
- RED: missingness on any tagged endpoint correlates with severity variable (r > 0.2)
- RED: impossible sequence count > 0.5% of patients
- AMBER: any tagged variable has > 5% values outside physiological range
- AMBER: duplicate patient estimate > 0.5%

---

## Page 5 — Hypotheses

Decision: What hypotheses is this dataset actually fit to answer?
Target time: under 15 minutes.

### Display
- Exposure selector: dropdown from columns tagged "exposure" in CohortContext
- Outcome selector: dropdown from columns tagged "endpoint" in CohortContext
- Hypothesis card (generated on selection, updates live):
  - Exposed N and unexposed N (or outcome event rate)
  - Confounder checklist: available (green ✓) | absent (red ✗) | partial (amber ~)
  - Naive power estimate — labelled "Exploratory estimate only — not a formal SAP calculation"
  - "What this hypothesis cannot answer" — ALWAYS populated, never empty
    Auto-generates from: absent confounders | RED flags from prior pages |
    insufficient follow-up | power < 80% at a clinically meaningful effect size |
    sensor coverage < 50% if sensor variable is involved
- Saved hypothesis cards list below the builder

### Controls
- Add/remove confounders → complete-case N updates live
- Effect size slider + event rate input → power estimate updates live
- Save card: name + status (Feasible | Needs investigation | Ruled out) + free text
- Compare saved cards side by side

### Auto-flags
- RED: exposure group imbalance > 80/20
- RED: key confounder (disease severity, prior treatment) absent from dataset
- AMBER: outcome event rate < 5% in current cohort
- AMBER: estimated power < 60% at any clinically meaningful effect size

---

## lib/power.ts

For binary outcomes: two-sample proportion test.
For continuous outcomes: two-sample t-test approximation.
Inputs: n_exposed, n_unexposed, event_rate or effect_size, alpha = 0.05 (fixed).
Output: power as integer percentage (0–100).
Label all estimates: "Exploratory estimate only — not a formal SAP calculation."

---

## Export (lib/report.ts + ExportButton.tsx)

Generates a Markdown file downloaded via browser.
Available at any point from the top-right button.
Filename: stat-expl-report-YYYY-MM-DD.md

Sections:
1. Dataset passport — key numbers from Page 1
2. Cohort definition — active filter list + final N
3. Quality flags — all active flags with severity and description
4. Hypothesis cards — each saved card with status, confounder list,
   power estimate, and "Cannot answer" content
5. Session notes — any free text annotations added during the session

---

## What NOT to build in v1
- No authentication or user accounts
- No backend, database, or API calls (schema.json is the only data source)
- No PDF export
- No mobile layout
- No statistical modelling beyond the naive power estimate in lib/power.ts
- No actual patient-level data — the missingness heatmap uses coverage
  statistics to simulate patterns, never real rows
- No real-time BigQuery connection in the running app

---

## Build sequence — one Claude Code session per phase

Start each phase with a fresh session.
Open with: "Read CLAUDE.md and the [PAGE NAME] section of docs/SPEC.md."

### Phase 1 — scaffold and data layer
Build: Vite + React + TypeScript scaffold, App shell, Nav,
CohortContext (filters + flag state), schema.ts loader.
Test: schema.json loads without errors, context accessible from any component.
Do not build any pages. Commit when tests pass.

### Phase 2 — Passport page
Build: Passport.tsx, CohortBar.tsx, lib/flags.ts (Passport flags only).
Test: page renders entirely from schema.json — no hardcoded numbers.
Commit when complete.

### Phase 3 — Population page
Build: Population.tsx.
Test: clinical concept search works against schema.json clinical_label fields.
Subgroup N is estimated from schema coverage statistics, not row queries.
Commit when complete.

### Phase 4 — Variables page
Build: Variables.tsx.
Test: sliders filter grid live, tags persist in CohortContext,
concept search returns correct variables.
Commit when complete.

### Phase 5 — Quality page
Build: Quality.tsx.
Missingness heatmap is a visual simulation from column coverage percentages.
Label it clearly in the UI: "Simulated pattern preview."
Test: sort controls update pattern note, complete-case calculator works.
Commit when complete.

### Phase 6 — Hypotheses page and Export
Build: Hypotheses.tsx, lib/power.ts, ExportButton.tsx, lib/report.ts.
Test: "Cannot answer" is never empty. Power updates live. Export downloads valid .md.
Commit when complete.
