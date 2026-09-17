# verily-profiler

BigQuery table profiling: technical stats + LLM-driven semantic metadata.

## Installation

```bash
pip install -e .
```

## Python API

```python
from verily_profiler import (
    discover_datasets, discover_tables,
    profile_technical, profile_semantic,
    write_tech_profile, write_sem_profile,
)

tables = discover_tables("my-project", "my-dataset", billing_project="my-billing")
for table in tables:
    tech = profile_technical(table, billing_project="my-billing")
    write_tech_profile("my-bucket", table.fq_name, tech, project_id="my-billing")

    sem = profile_semantic(tech, model="gemini-2.5-flash", project_id="my-billing")
    write_sem_profile("my-bucket", table.fq_name, sem, project_id="my-billing")
```

## CLI

```bash
verily-profiler discover my-gcp-project
verily-profiler tech my-project.dataset.table --billing-project my-project --bucket my-bucket
verily-profiler semantic my-project.dataset.table --model gemini-2.5-flash --billing-project my-project --bucket my-bucket
verily-profiler profile my-project.dataset.table --model gemini-2.5-flash --billing-project my-project --bucket my-bucket
verily-profiler profile-dataset my-project.dataset --model gemini-2.5-flash --billing-project my-project --bucket my-bucket
```
