# verily-chat

Chat over BigQuery metadata: Q&A from profiling output + optional NL-to-SQL agent.

## Installation

```bash
# Metadata Q&A only
pip install -e .

# With BQ agent (LangGraph + tool calling)
pip install -e ".[agent]"
```

## Python API

```python
from verily_chat import chat, ChatContext
from verily_profiler import read_tech_profile, read_sem_profile

tech = read_tech_profile("my-bucket", "proj.ds.table", project_id="proj")
sem = read_sem_profile("my-bucket", "proj.ds.table", project_id="proj")

ctx = ChatContext(project_id="proj", billing_project="proj", tech_profiles={"proj.ds.table": tech}, sem_profiles={"proj.ds.table": sem})
reply = chat("What columns contain patient IDs?", ctx, model="gemini-2.5-flash", project_id="proj")
print(reply.content)
```

## CLI

```bash
verily-chat ask "What columns are in this table?" \
  --table my-project.dataset.table \
  --bucket metadata-json-my-project \
  --model gemini-2.5-flash

verily-chat session \
  --project my-project \
  --bucket metadata-json-my-project \
  --model gemini-2.5-flash
```
