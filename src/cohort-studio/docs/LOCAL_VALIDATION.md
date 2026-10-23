# Local container validation

Run from `src/cohort-studio`. Docker must be running; Docker Compose or the
standalone `docker-compose` command must be installed.

```sh
bash scripts/local-stack.sh up --build -d
```

Open `http://127.0.0.1:8080`. The stack seeds 100 synthetic OMOP persons,
100 linked samples, 20 synthetic variants and 2,000 genotypes. It preserves
the local database volume on restart. Ports bind to localhost. Override
`STUDIO_LOCAL_PORT` or `STUDIO_LOCAL_PG_PORT` if a port is already in use.

The local launcher registers one PostgreSQL resource using the normal Aurora
engine path. It does not use Workbench credentials or require a modified
`app/db.py`. Production continues to use Workbench Aurora resources.

## Browser outcome test

```sh
uv venv .venv
uv pip install --python .venv/bin/python -r app/requirements.txt pytest pytest-playwright
uv run --no-project --python .venv/bin/python -m playwright install chromium
STUDIO_LOCAL_URL=http://127.0.0.1:8080 uv run --no-project --python .venv/bin/python -m pytest app/tests/test_local_stack_e2e.py -q
```

The test uses the running API and database. It does not mock recommendation or
join responses. The ordinary frontend suite separately tests error and recovery
states with controlled API responses. Local PostgreSQL checks do not prove
Aurora networking, Workbench permissions or browser-sidecar isolation.

```sh
bash scripts/local-stack.sh logs --tail=100 app seed
bash scripts/local-stack.sh down
```

## Optional Jev classification

Set `TYPESAFE_API_KEY` and `STUDIO_JEV_MODEL` in the server environment before
starting the stack. Choose a model available to your TypeSafe account. The
adapter calls the [TypeSafe System One API](https://docs.typesafe.ai/api/system-one)
with schema metadata and non-null flags from a one-row probe. It does not send
row values. TypeSafe credentials are never sent to OpenRouter.

Without credentials, or when Jev fails, database metadata recommendations and
manual joins remain available. Model probability is not a measured match rate.
No live Jev inference has been verified in this environment.

`POST /api/joins/recommend` accepts `left` and `right` Aurora source references
and optional `refresh: true`. Metadata and results have a bounded in-process
cache, default 30 seconds (`STUDIO_JOIN_DISCOVERY_CACHE_TTL`, maximum 300).
