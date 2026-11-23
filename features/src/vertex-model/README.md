# vertex-model

A model on Vertex AI in place of vLLM, for an AI Research Assistant app without the GPUs for the
local model. A small OpenAI-compatible server (`proxy.py`) listens on vLLM's port and sends each
chat request to Vertex AI in the workspace's own Google Cloud project, as the VM's service account.
OpenCode in the sandbox keeps the address and API it uses with vLLM, and the credential stays
outside the sandbox. It answers from one of two places:

Both are for alpha users only, and neither inside a data perimeter (the ai-policy README).

- **A Nemotron endpoint in the workspace's project** (first choice): Super VL served
  by vLLM on a dedicated Vertex AI endpoint that a workspace owner deploys once with
  `deploy-endpoint.sh` (below). Every alpha user's app in the workspace without the GPUs uses it. The endpoint
  runs vLLM, so requests go on unchanged but for the model's name, and the cohort designer calls
  this server with its usual provider, as it calls vLLM.
- **Gemini** (when there is no endpoint): Vertex AI's OpenAI-compatible endpoint.
  The cohort designer does not use this server then: `start-services.sh` starts the designer on its
  own Gemini provider, which shapes the designer's tool schemas the way Gemini takes them.

| File | What it is |
|---|---|
| `proxy.py` | The server: `/health` and `/v1/models` answered locally, `/v1/chat/completions` sent to Vertex AI, streamed or not. `proxy.py find-endpoint` finds the workspace's endpoint |
| `start-server.sh` | Starts it as the app's user, waits for it, and sends the model one short request so a missing permission shows at start |
| `deploy-endpoint.sh` | For a workspace owner, outside the app: deploys Super VL to a dedicated endpoint, or `--delete`s it |
| `install.sh` | Copies `proxy.py` and `start-server.sh` into `/opt/vertex-model` |

## Settings

The app's compose file sets these. `start-services.sh` starts this server in place of vLLM when
the ai-policy feature's `access.py model` chooses the endpoint (the machine has no GPUs that fit
the local model, and `find-endpoint` found one) or Gemini (no endpoint, and the person has the
alpha `vertex_model` feature; the ai-policy README).

| Variable | Default | Meaning |
|---|---|---|
| `VERTEX_ENDPOINT` | `auto` (compose) | Which endpoint `find-endpoint` looks for: `auto`, the newest dedicated endpoint labelled `ara-model` with a model deployed; a label value (`super-vl`); or an endpoint ID. `off` or empty never looks |
| `VERTEX_ENDPOINT_LOCATION` | `us-central1` | Where it looks |
| `VERTEX_ENDPOINT_URL` | none | Set by `start-services.sh` from what `find-endpoint` found: the endpoint's OpenAI base URL (`https://<dns>/v1/projects/<number>/locations/<location>/endpoints/<id>/invoke/v1`). With it, the server sends requests there |
| `VERTEX_MODEL` | none | The model every request is answered by, whatever model the request names: the endpoint's served name (set by `start-services.sh`), or the Gemini model from compose, e.g. `gemini-3.5-flash` |
| `VERTEX_LOCATION` | `global` | The Vertex AI location; Gemini 3.x answers in `global` |
| `GOOGLE_CLOUD_PROJECT` | the VM's project | The project billed and called |
| `VLLM_PORT`, `VLLM_BIND_ADDRESS` | `8000`, `127.0.0.1` | Where it listens: vLLM's settings |
| `VLLM_CONTEXT_LENGTH` | `262144` | Reported in `/v1/models`; the agent and the designer size their budgets from it. With an endpoint, the endpoint's own `max_model_len` |

## A Nemotron endpoint

A workspace owner runs `deploy-endpoint.sh` once per workspace, from a Workbench JupyterLab app
or any machine with `gcloud`, `curl` and `jq` and owner access to the project:

```bash
features/src/vertex-model/deploy-endpoint.sh --project <workspace project> --yes   # 15-30 minutes
features/src/vertex-model/deploy-endpoint.sh --project <workspace project> --delete
```

Without `--yes` the script prints the project, region, machine type and hourly cost, creates
nothing, and exits 1. `--project` defaults to `GOOGLE_CLOUD_PROJECT`, else gcloud's configured
project: check the one it prints.

It makes, reusing whatever is already there:

- an Artifact Registry remote repository, `dockerhub`, that pulls vLLM's image (`vllm/vllm-openai`,
  0.34.0, the release the vllm-model feature installs) through from Docker Hub, since Vertex AI takes images only from Artifact Registry;
- a dedicated endpoint, `nemotron-super-vl`, labelled `ara-model=super-vl`, with a 30-minute reply
  limit. Dedicated endpoints stream replies as they come and take vLLM's OpenAI routes
  (`invokeRoutePrefix: "/*"`); shared ones answer only `:rawPredict`, within about a minute;
- the model, vLLM serving Super VL text-only with the vllm-model feature's settings (reasoning
  and tool parsers, the thinking-budget end string, strict tool arguments, 262,144 tokens), on one
  RTX PRO 6000 (`g4-standard-48`; `--machine`, `--accelerator` and `--count` for others), and
  its deployment on one replica.

`--delete` undeploys and deletes the endpoint and the models labelled `ara-model=super-vl`; it
leaves the `dockerhub` Artifact Registry repository, which a later deploy reuses and which holds
the cached vLLM image. An endpoint made with `--region` other than `us-central1` is found only by
an app whose `VERTEX_ENDPOINT_LOCATION` is set to that region.

Weights come from Hugging Face each time a replica starts, so this needs a workspace whose network
reaches the internet, not one under a policy that blocks external traffic.

A replica bills by the hour while deployed, called or not: about $6/h for one RTX PRO 6000 in
us-central1. One endpoint serves every alpha user's app in the workspace; delete it when the workspace no
longer needs it. Apps started while it is up use it; an app started before keeps the model it chose
until it restarts.

## Thought signatures

Gemini returns a thought signature with the first tool call of each step and refuses the next
request if that call comes back without it. Clients written for vLLM drop the field, so the
server keeps each signature by tool call id and puts it back. A call it never saw, such as one from
before a restart, gets Google's documented placeholder (`skip_thought_signature_validator`), which
Vertex accepts.

## Requirements

- The Vertex AI API enabled in the workspace's project, and `roles/aiplatform.user` for the VM's
  service account. `start-server.sh` says so if the test request is refused.
- For Gemini, the model in the chosen location. Model IDs change; check one with a request before
  setting it.
- For an endpoint, the VM must reach its DNS name (`*.prediction.vertexai.goog`, a public address),
  which a network policy that blocks external traffic may not allow.

## Known limitations

- Prompts, tool results and whatever data the agent reads into them go to Vertex AI in the
  workspace's project instead of staying on the VM: to Google's Gemini, or to the workspace's own
  endpoint.
- Vertex AI refuses requests over 1.5 MB. A conversation near the full 262,144-token context can
  exceed that through an endpoint; locally it would not.
- Like vLLM, the server has no authentication: any process that reaches the port can call Gemini as
  the VM's service account. It does not check the access tier or the data perimeter either: the
  app decides whether to start it, so anyone with a shell in the app container can start it by hand.
- Only chat completions are served: no `/v1/completions` or embeddings.
- Gemini ignores the vLLM-only fields a client sends (`chat_template_kwargs` and the like), but
  refuses a forced tool call (`tool_choice: required`) with large or recursive tool schemas, and a
  recursive schema whose loop runs only through required fields and non-empty lists.

## Logs and tests

`~/.vertex-model/server.log`. Tests: `python3 -m unittest discover -s tests/vertex-model`, against
stand-ins for Vertex AI and for vLLM on an endpoint.
