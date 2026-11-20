# cohort-designer

The cohort designer, served as an MCP server for the sandboxed agent to drive. The designer is
itself an agent: it reads a research question, explores the workspace's BigQuery data with
read-only tools, writes a cohort definition, compiles it to SQL and counts it. Authored by
[Michail Ouroutzoglou](https://github.com/michail-v).

## How it fits

```
sandbox: OpenCode ──MCP, 8 tools, by name──▶ host.openshell.internal:9243/mcp
                                               │
application-server:  cohort designer (cohort-designer serve, as the user)
                       ├─ model: vLLM on 127.0.0.1:8000, the same Nemotron OpenCode runs on,
                       │         or Gemini on Vertex AI (COHORT_DESIGNER_PROVIDER=gemini)
                       ├─ BigQuery: the user's credentials, only the workspace's datasets
                       └─ state: ~/.cohort-designer/{sessions,logs,config.yaml,server.log}
```

The designer runs in the app, outside the sandbox, the way the Workbench MCP server does. The
sandboxed agent never sees its credentials or its SQL; it sends messages and reads replies.
The model never writes SQL: the designer's code compiles the definition. Sampled rows and
column profiles do come back in the designer's replies, so they reach the agent's transcript.

| File | What it is |
|---|---|
| `install.sh` | Fetches the designer's binary and writes `start-server.sh` and `stop-server.sh` in `/opt/cohort-designer` |
| `fetch-designer.sh` | Downloads the binary from its release and installs it only if its sha256 matches |
| `sandbox/cohort.yaml` | The catalog the sandbox policy is rendered from: the tools, which ones ask the person, the agent's instructions |

## The binary

The designer's source is not in this repository: it is kept under its own license and
released on its own schedule, as one Linux x86_64 binary (PyInstaller, Python 3.12, glibc 2.39
or newer). The feature's `release` and `sha256` options pin the release; moving to a new one
changes only those two.

- `cohort-designer serve --config … --state-dir … --bind … --port … --allowed-host …`: the
  designer's MCP server with a bind address and a state folder, plus `wait_for_reply` and
  `new_cohort` and without `reset_session` (below).
- `cohort-designer make-config <out> --model … --base-url … [--context] [--datasets]
  [--provider gemini --region …]`: writes the designer's config from `wb resource list`.

`release` is `gs://bucket/object` or an `https://` URL. A `gs://` release is read as the VM's
service account, so the person's Workbench access to the bucket decides whether the app gets
it. The build fetches it; a build that cannot read it leaves it to the first
`start-server.sh`, which fetches it into `~/.cohort-designer/bin`. A binary whose sha256 does
not match is never installed. A download that connects slowly or runs past 15 minutes is
abandoned, so a stalled transfer does not hold the app's start.

Other options of the feature:

| Option | Default | Does |
|---|---|---|
| `port` | `9243` | The port of the designer's MCP server |
| `bindAddress` | `127.0.0.1` | The address the server listens on: `127.0.0.1` keeps it to this container; `0.0.0.0` lets the container publish the port to sandboxed agents on the same VM. `COHORT_DESIGNER_BIND` overrides it at start |
| `role` | `app` | `app`: the designer and its server. `broker`: only the catalog the sandbox-broker renders the policy from |

## A locked cohort in other steps

A locked cohort's SQL is what other steps use. `get_results` with `which: "export"` returns it;
the agent runs it from its own Python, as `/sandbox/data-access.md` describes, and builds what
the next step needs from the rows (a workflow's samplesheet, for example). Only a locked
cohort's SQL is final; a draft changes as the conversation goes.

## Approvals

The designer stops for a person's approval before it locks a cohort and before an edit that
removes or narrows something. Over MCP the driver answers with `respond_approval`. The catalog
marks that tool `ask`, so OpenCode shows its permission prompt and the person answers there;
the agent's instructions tell it to show the request first. `answer_choices` asks the same
way, so the person sees the picks before they are sent.

The lock goes through only once the person allows the prompt. A model can answer a choice
without showing it, which is why `answer_choices` asks too.

## What the driver is given

A driving model tends to poll the status many times in a few seconds and to reset the session
while the designer is working. So the server the sandbox sees differs from the designer's own
in its tools:

- `wait_for_reply` is added. It holds the call for up to 50 seconds and returns the status
  with the reply, the choices or the approval request, so the driver loops on one tool.
- `reset_session` is withheld. A new conversation is a restart of the server
  (`stop-server.sh`, then `start-server.sh`).
- `read_events` and `get_choices` are withheld: `wait_for_reply` returns what the driver
  needs of both.

## What the designer is given

`cohort-designer make-config` writes the designer's config at every start:

- The reply and thinking budgets its author runs Nemotron with (32,768 and 16,384 tokens)
  where the context holds them, and smaller ones on a 65,536-token server.
- At most 6 commands per edit call, the cap every model ran under in the author's comparison.
- With `COHORT_DESIGNER_PROVIDER=gemini` (the AI Research Assistant sets it when it serves Gemini),
  the designer's own Gemini provider on Vertex AI in the workspace's project, in place of the local
  server, in `COHORT_DESIGNER_REGION` (default `global`). That provider shapes the tool schemas
  and the tool choice the way Gemini takes them; a request in vLLM's form is refused by Gemini,
  which takes neither the recursive definition schema with its required lists nor a forced tool
  call with it.
- The dataset card (measured column profiles, reused across sessions) in
  `~/.cohort-designer/cards`. Its default is beside the code, which the user cannot write.
- `COHORT_DESIGNER_DATASETS` (`project.dataset`, comma-separated) narrows what it reads to
  some of the workspace's datasets, so it does not explore the rest. The AI Research
  Assistant's compose file leaves it empty, so the designer reads every dataset the workspace
  lists and settles with the person which one a cohort is drawn from; a dataset it names that
  the workspace does not hold stops the designer from starting, rather than widening what it
  reads.

## Control

```sh
/opt/cohort-designer/start-server.sh     # also re-reads the workspace's datasets
/opt/cohort-designer/stop-server.sh
tail -f ~/.cohort-designer/server.log
agent-sandbox policy explain             # shows the designer's tools once the policy is rendered
```

After a dataset is added to the workspace, stop and start the server; the stop returns once
the designer has exited, so the two can be run together. A workspace with no
BigQuery dataset gets no designer: it refuses to start with nothing to read.

## Known limitations

- Each request the designer sends carries its system prompt and 32 tool schemas, about 60,000
  tokens before any conversation, so it needs a model server with at least 131,072 tokens of
  context. The app's local model serves 262,144.
- An approval given through MCP is recorded as the driver's, not a person's.
- Sampled rows and column profiles come back in the designer's replies, so they reach the
  agent's transcript.
- The designer's replies carry exact counts, including 1 to 19; only the agent's instructions
  keep them out of its answers.
- A column named in capitals is handled for a person's sex at a lock; other places that write a
  column name into a formula may not handle one.
- The designer's guide says the dataset card is off by default; the code turns it on.
- The binary unpacks itself at every start, which takes about 10 seconds before the server
  answers.

Tests: `python3 -m unittest discover -s tests/cohort-designer`. With `COHORT_DESIGNER_BIN` set to
a binary, the tests of the config it writes run too.
