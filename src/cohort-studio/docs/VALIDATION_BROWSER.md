# Browser isolation validation

## Local evidence

On 2026-10-25, the Chromium browser test
`test_local_omop_summary_charts_follow_cohort_filters` passed against the local
Compose application at `127.0.0.1:8081` and the seeded PostgreSQL 16 database at
`127.0.0.1:55433` (1 passed in 4.79 s). It searched OMOP concepts, filtered and
counted a cohort, opened the matching people, and checked the summary against
SQL on the same database. This tested the local app and database through a
host browser; it did not test the streamed browser sidecar.

The in-process local OMOP browser flow also passed (1 passed in 2.04 s) using a
temporary Uvicorn app, the local PostgreSQL fixture, and Chromium. It selected
concepts, counted a cohort, and opened cohort people and clinical records. This
confirms the app/API/browser path with real PostgreSQL, but not the S3 join,
saved-view reload, workflow, or sidecar path.

## Routing review

The Cohort Studio virtual-browser template uses the same two-container route
as `virtual-browser-jupyter` on `master`: Workbench proxy traffic targets the
`browser` service on port 3000; Chromium opens `http://application-server:8080`;
the app is on `backend-network` only and has no published port. The shared
managed Chromium policy allows only that app origin and blocks all other URLs.
The Cohort Studio frontend sends API requests to relative `/api/...` paths, so
these requests use the allowed app origin. This is a source/configuration
review, not a runtime enforcement test.

The local Compose inventory contained `application-server` and PostgreSQL, but
no `browser` container. The active app inventory reported by the deployment
check also contained no `browser` container. Therefore the Workbench proxy,
Selkies WebSocket stream, Chromium URL policy, upload path, and pixel-stream
interaction remain unverified. Do not use the local direct app port as evidence
that those controls work.

## Workflow boundary

The workflow launch browser test stubs browser API responses. The workflow API
tests replace S3 and Workbench submission helpers. Together they validate UI
payloads and server request construction without creating cloud objects or
submitting a run. They do not validate one browser flow from a real OMOP cohort
through an S3-backed join and saved-view reload into a submitted workflow.

Disk-backed chat API tests use a real DuckDB file with 1,000 synthetic rows and
a fake provider. They confirm full-source counts and aggregates run through
DuckDB, current UI filters stay in scope, the in-memory preview remains 60 rows,
and provider row previews remain capped at five. `/ask` profile bounds and
categories also come from DuckDB. These tests validate app API/tool behavior,
not provider connectivity or the streamed browser.
