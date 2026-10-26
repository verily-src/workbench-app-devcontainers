# Repeatable Studio evaluations

Run from `src/cohort-studio` with the app test dependencies installed:

```sh
uv run --no-project --python .venv/bin/python scripts/evaluate_studio.py \
  --suite all --repeat 2 --nextflow /path/to/nextflow
```

Use an installed Nextflow runtime and Java 17 or later. Set `JAVA_HOME` if Java
is not on PATH. The runner does not install tools or download models. Nextflow
runs with its local profile and offline mode; no HealthOmics run is submitted.
The default database is the local development PostgreSQL server on port 55433.
Set `STUDIO_EVAL_DB_DSN` to use another **loopback** server with permission to
create databases. Each repetition creates three uniquely named test databases
and removes them in `finally`. Never point this runner at a shared application DB.

Choose `--suite agent`, `--suite jev`, or `--suite demo` to run one group.
`--repeat` accepts 1–10; the default is two independent runs. `--output PATH`
selects the report folder. The default `.eval-results/` is Git-ignored.

Each run writes a log and JUnit XML. `report.json` records every case and its
status, plus demo counts and integrity evidence. Failures, skips and missing
cases cause a nonzero exit. A passing report is deterministic contract evidence,
not a live-model accuracy score.

## What the checks prove

| Group | Boundary and expected behavior |
| --- | --- |
| Agent | Typed tools, unsupported tool rejection, reference-data isolation, external-search scope, citations, owner-scoped history, approval, duplicate submission and result verification |
| Jev | Real PostgreSQL metadata and join execution; fixture TypeSafe responses; saved/environment tokens; metadata-only payloads; person/sample/variant classifications; abstention on role/type mismatch, low confidence or malformed responses |
| Demo | HTTP OMOP cohort selection → PostgreSQL genetics join → file-backed S3 dictionary join in DuckDB → frozen approval/export → real local Nextflow → manifest/checksum verification → results dashboard → assistant aggregate tool |

The demo derives expected cohort membership from the independent OMOP CSV
fixture. It compares exact exported person IDs, required columns and carrier
counts. It checks that preparing a plan does not submit, repeating approval
submits once, and summary counts sum `people` rather than count strata.

The staging regression covers an empty preview, a first batch of nulls, dates,
time zones, IDs above 2^53 and decimal precision. PostgreSQL result metadata
controls DuckDB storage types; display/filter classifications do not.

## What these checks do not prove

- Live Jev or general model accuracy, probabilistic stability or injection immunity.
- AWS IAM, real S3 transfer, HealthOmics provisioning or container execution.
- Browser interactions or the quality of generated prose.

Keep live provider evaluations separate, use public synthetic metadata, and
record the provider/model version. Run the live demo with explicit workflow
approval and verify its exact run ID and output checksums before interpreting
results. Existing live-demo evidence is in `DEMO_OMOP_GENETICS.md`.
