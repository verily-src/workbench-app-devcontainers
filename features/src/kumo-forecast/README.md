# kumo-forecast

NVIDIA Kumo Relational, served as an MCP server for the sandboxed agent. It forecasts an outcome
for the members of a cohort the [cohort designer](../cohort-designer/README.md) has locked, over
the tables of the cohort's own BigQuery dataset, compares the forecast with classical baselines,
and writes the highest-risk members to a controlled bucket of the workspace. It works on any
dataset with a key column shared by several tables, at least one of them dated; no table, code or
outcome is named in the code.

## How it fits

```
sandbox: OpenCode ──MCP──▶ host.openshell.internal:9243/mcp   cohort designer (locks the cohort)
                  ──MCP──▶ host.openshell.internal:9244/mcp   kumo-forecast (serve.py, as the user)
                                                                ├─ reads the designer's sessions/ (the lock)
                                                                ├─ BigQuery: the user's credentials
                                                                ├─ model: Kumo Relational on the freest GPU, capped
                                                                ├─ writes: one CSV, only to a controlled bucket (gcloud, wb)
                                                                └─ state: ~/.kumo-forecast/{runs,cache,server.log}
```

**The cohort** is one the designer locked. Its lock's key column says what the members are (the
`person_key`, or a `key` with the data column it is read from, such as `person_id`): that is the
*entity key*. The dataset is the one the lock reads. A lock with no key is refused.

**The outcome** is described in the call, not locked: rows of one table of the cohort's dataset
that has the entity key, and conditions on its columns that must all hold, such as
`{"table": "condition_occurrence", "where": [{"column": "condition_concept_id", "op": "in", "value": [443597]}]}`.
An entity has the outcome from the date of its first such row, by the table's time column (below)
or `time_column`. The operators are `in`, `=`, `!=`, `<`, `<=`, `>`, `>=` and `between`; text
columns take only `in`, `=` and `!=`. With no conditions, any row is the outcome (a `death` table).
The table and columns must be in the schema, and each value is sent as a BigQuery query
parameter typed by its column (`kumo_forecast/outcome.py`), so nothing the agent writes is run as
SQL. The forecast scores the cohort's members; Kumo learns from the labeled histories of everyone
in the dataset.

**The tables** are the ones the agent passes as `tables` (each must be in the dataset and have
the entity key column), else every base table of the dataset that has the key column (views are
not read). `get_cohort_info` lists the candidates with their rows, time columns and first 20 column names. A table's time column is its only `DATE`, `DATETIME` or `TIMESTAMP` column; with
several, the one whose name contains `start`, else the first in schema order; `time_columns`
(`{table: column}`) overrides it. A table with no such column is static. Columns are typed by
`sdm.infer_stypes` (text and unsupported types dropped). The entity key is an `id`. A table's own
primary key is `<table>_id` when that column is unique in the first 10,000 rows; otherwise a
row-number column is added. The static table with one row per entity is the entity table, which
every other table links to on the key; if none is unique on the key, the entity table is built
from the distinct keys (the answer's `tables_read` says which). Before reading, the tables' row
counts are summed; above `KUMO_FORECAST_MAX_ROWS` (50,000,000) the forecast is refused, with the
total and the largest tables. The tables are cached owner-only as Parquet until BigQuery says one
changed.

**Long tables are split by code.** In a dated table with a numeric value column (a name containing
`value`) and a code column (integer or string, named `..._concept_id`, `..._code` or `...code`, with
at most 5,000 distinct values; of several, the one with the most), the codes with at least 0.5% of
the rows, at most 20, get tables of their own, `<table>__<code>`, named from a `concept`-shaped
table (`concept_id`, `concept_name`) when the dataset has one. In OMOP this splits `measurement`
and `observation` by concept.

**At risk** at a cutoff: a dated row on or before it, and no outcome by it. If the dataset has an
`observation_period` table with start and end dates, in observation at the cutoff instead.
`data_end` is the latest date across the dated tables, capped at today. `as_of` defaults to
`data_end` less the horizon, so the outcome can be checked; the answer says the date used.

| File | What it is |
|---|---|
| `serve.py` | The MCP server: eight tools, HTTP on port 9244 |
| `kumo_forecast/cohort.py` | Reads the designer's locks (standard library only) |
| `kumo_forecast/outcome.py` | Checks the outcome against the schema and builds its parameterised query (standard library only) |
| `kumo_forecast/schema.py` | The time column, code column, entity table, size guard and split naming, over schema dicts (standard library only) |
| `kumo_forecast/tables.py` | Reads the schemas and tables from BigQuery, cached owner-only per dataset |
| `kumo_forecast/dataset.py` | The graph in pandas: entity table, splits, who is at risk when |
| `kumo_forecast/model.py` | Kumo Relational over the graph, with the leakage rules below |
| `kumo_forecast/baselines.py` | Logistic regression and gradient-boosted trees on features built by rule |
| `kumo_forecast/profile.py` | What the top 10% have in common, by rule |
| `kumo_forecast/views.py` | The ready answers of show_cohort_records, show_genomes and forecast_with_genotypes: timelines from the graph, manifest counts and a sarek samplesheet, a VCF's summary, the two-forecast comparison |
| `kumo_forecast/destination.py` | The controlled-bucket check for the selection (standard library only) |
| `kumo_forecast/privacy.py` | Small-cell masking (counts and part-of-whole counts under 20, group rates) |
| `sandbox/forecast.yaml` | The catalog the sandbox policy is rendered from |

## Options

| Option | Default | Does |
|---|---|---|
| `port` | `9244` | The port of the forecast MCP server |
| `bindAddress` | `127.0.0.1` | The address the server listens on: `127.0.0.1` keeps it to this container; `0.0.0.0` lets the container publish the port to sandboxed agents on the same VM. `KUMO_FORECAST_BIND` overrides it at start |
| `role` | `app` | `app`: the model and its server. `broker`: only the catalog the sandbox-broker renders the policy from |

## Tools

| Tool | Does |
|---|---|
| `get_cohort_info` | A locked cohort: its request, size, dataset, entity key, `data_end` and the tables a forecast would read with their time columns |
| `forecast_risk` | Kumo's forecast for the cohort's members at risk on `as_of`, that the `outcome` starts within `horizon_days` (30 to 1,825), over `tables` (optional) and `extra_tables` (optional: `project.dataset.table` names of other datasets' tables with the entity key, such as a genotype table per person). `population_table` (optional, `project.dataset.table`) scores everyone in that table instead of the cohort's members, for example everyone with a genome. Risk quartiles, what the top 10% have in common against the rest, and where already observed, observed rates and AUROC. Returns a `run_id` |
| `show_cohort_records` | A ready table for visitors: what Kumo learns from (every table and row of the dataset, for all its people) and whom it forecasts for (the cohort), the largest tables by what they hold (lab results, visits, prescriptions, ...) with their rows for everyone and for the cohort, then up to 5 members picked at random (2 by default), labelled Patient 1, 2, ...: the year they joined the cohort, first diagnoses and prescriptions by year, and three lab values first to last. Off unless `KUMO_FORECAST_SAMPLE_RECORDS=1` (synthetic data only) |
| `show_genomes` | A ready table for visitors. From a manifest table (one row per genome, the entity key, `*_uri` columns): genomes in all and in the cohort, coverage, one genome's aligned-reads size and the total estimated for all; from a VCF (`gs://`): variants per named region, and three variants of the first region as gene, position, change and copies |
| `forecast_with_genotypes` | Two forecasts for everyone in a genotype table, on the same people: from the health records alone, then with the genotype table read too. Answered with a ready table of both side by side (AUROC, the cases the highest-risk tenth holds, its rate against the rest, each genotype's share in that tenth against the rest) and the same numbers |
| `compare_to_baselines` | Kumo against logistic regression and gradient-boosted trees on the same rows; the agent calls it only when asked to compare |
| `select_highest_risk` | The `top_n` highest-risk members, written as `<key>,risk` to a `gs://` file in a controlled bucket resource of the workspace |
| `wait_for_result` | The answer of a `get_cohort_info`, `forecast_risk` or `compare_to_baselines` call that outlasted 50 seconds and returned a `job_id` |

What goes back to the agent is counts, rates and medians, never an id. A count of 1 to 19 is
masked (`KUMO_FORECAST_SMALL_CELL`, 0 turns it off; a median over fewer is left out), including
the number of people without the outcome: a count beside its total is shown as `<20`, or as
`>total - 20` when fewer than 20 of the total are left out. A rate is a bound when its events or
its non-events are under 20, and is not shown for a group of fewer than 40 members. When exactly one risk quartile's rate is masked, the quartile with the
next smallest count of the same kind is shown as a bound too, so the masked one cannot be worked
out from the overall count. A table's row count is masked in the same way, and so are the counts
in error messages. `select_highest_risk` reports `top_n` as the caller gave it, and a smaller number
selected as a masked count. Participant-level scores stay in `~/.kumo-forecast/runs`, mode 600.
`select_highest_risk` checks the destination against `wb resource list`: a bucket that is not a
controlled resource of the workspace is refused, and the answer names the controlled ones. It
copies with `gcloud storage cp` from a mode-600 temporary file, as the server's user.

## The forecast

- **No training, no features.** Kumo Relational (`structured-data-models` 0.2.1, weights
  `nvidia/Kumo-Relational`) reads the tables as they are, linked by the entity key, and learns in
  context from labeled histories.
- **No leakage by date.** Labeled rows are the dataset's entities at yearly cutoffs up to five years
  before `as_of` whose outcome window ends on or before `as_of`, which is why `horizon_days` is at
  most 1,825; the sampler shows each row only records dated on or before its cutoff
  (`time_columns`). A forecast needs at least 10 labeled cases.
- **One table per frequent code.** With one table of many codes the sampler's 16 rows per table per
  entity mostly miss the code that predicts the outcome, so each frequent code gets a table of its
  own.
- **Baselines.** Per cutoff: rows in the year before for each dated table; the last value and
  its change over two years for each split table; each static table's numeric columns as they
  are and a one-hot of each categorical column's four most common values; the cutoff's year.
  They are trained on all labeled history.
- **Defaults** (`start-server.sh` settings): 3,000 labeled rows in context, an ensemble of 2
  (on the EHR-and-genomes synthetic data, 2 matched 4's AUROC in half the time),
  16 sampled rows per table, a 5 GB GPU memory cap on the GPU with the most free memory.
- **The high-risk profile** leaves out race and ethnicity columns (a column whose name, or a part of it
  after `_`, starts with `race` or `ethnic`): the top 10% are described by their clinical record.

## Warm start

The server keeps the two most recently used dataset graphs (`KUMO_FORECAST_GRAPHS`), each with its
model, so a forecast with an extra table does not push out the cohort's own. At start it builds
the newest locked cohort's graph and model, and one more for each table in
`KUMO_FORECAST_WARM_TABLES` (comma-separated; `dataset.table` is in the workspace's project, where BigQuery jobs run),
so the first calls do not wait on reading the data. With nothing locked yet, the first call does it.

## GPU

The model shares the app's GPUs with vLLM, so its memory is capped. Memory grows with the context
size and the number of tables: choose `tables` with the cap in mind, since each table, and each
frequent code of a long table, is a table of the graph. `KUMO_FORECAST_GPU_GB` caps the process;
a run past it fails with an out-of-memory error rather than taking vLLM's memory.

## Installing

`install.sh` installs into `/opt/kumo-forecast`: a Python 3.12 venv (torch 2.13, CUDA 13 build;
`pyg-lib` 0.8.0's CPU build from PyG's index for the sampler), the weights pre-fetched to
`/opt/kumo-forecast/hf` so the server runs offline, the code, and `start-server.sh` and
`stop-server.sh`. Not under `/config`: a large tree in the code-server workspace sets the editor
searching it and the bucket mounts, which overloads the app.
With `role: broker` it installs only the catalog.

## Known limitations

- The cohort breakdown (the two excluded counts, `members_at_risk` and `cohort_members`)
  always adds up, so when exactly one of them is under 20 it can be worked out from the others.
- Dates must be calendar dates (`DATE`, `DATETIME`, `TIMESTAMP`). A table whose times are a count
  of days from another date (a study day, as in many CRF datasets) is read as static, and a
  forecast over tables with no calendar date is refused.
- A table with no calendar date column is read as static, so it is visible in full at every
  cutoff: facts recorded after the cutoff in such a table (including study-day tables) reach the
  model, the baselines and the reported AUROC.
- The forecast model shares the app's two GPUs with vLLM, which is why its memory is capped
  (see GPU above).
- Tables are read whole, up to the size guard (`KUMO_FORECAST_MAX_ROWS`). A larger dataset
  needs its population sampled first, which this server does not do.
- Without an `observation_period` table, "at risk" is "has a record by the cutoff".
- The time-column choice is a heuristic; `time_columns` overrides it. A column holding a later
  date than its row's time column (an end date) is read as it is.
- The code column of a long table is chosen by name and cardinality; a table whose codes are in
  a column that does not match the naming rule is not split.
- An outcome is one table's rows: an outcome that is any of several tables (a diagnosis or a
  prescription) needs one forecast for each.
- `index_dates` in `get_cohort_info` gives the earliest and latest member's exact index date, each
  the date of a single person.
