# OpenCode + NVIDIA Nemotron

Code-server IDE with [OpenCode](https://opencode.ai), local
[NVIDIA Nemotron](https://developer.nvidia.com/topics/ai/nemotron) models served by
[Ollama](https://ollama.com), Workbench MCP tools, and generated workspace context.
**Nemotron 3 Nano 4B is the default**, so an A100 is no longer needed to get started.

- Code-server UI on port 8443.
- Ollama API on `127.0.0.1:11434` and Workbench MCP on `127.0.0.1:9242` inside the container.
- `opencode` and `opencode-model` on the `PATH`.
- Local model inference; OpenCode session sharing is disabled. MCP tools use the
  authenticated user's Workbench/cloud APIs, and model downloads use Ollama's registry.

## Models and GPU guidance

`opencode-model --list` shows the catalog in `models.json`. Only the selected
model is downloaded, rather than every model in the catalog.

| Ollama tag | Weight download | Primary GPU target | Other Workbench GPU options |
|---|---|---|---|
| **`nemotron-3-nano:4b`** (default) | **2.8 GB** | **T4 16 GB** | V100 16 GB |
| `nemotron-3.5-lightning:30b` | 25 GB | A100 40 GB | A100 80 GB, H100 80 GB, H100 80 GB MEGA |

The menu offers two choices: **Nano 4B for smaller GPUs** and **Lightning 30B for
A100/H100 GPUs**. Precision variants and a second 30B model would overlap these
hardware targets. Custom tags remain available for experimentation.
Sizes and tool support come from the
[Nano tags](https://ollama.com/library/nemotron-3-nano/tags) and
[Lightning tag](https://ollama.com/library/nemotron-3.5-lightning:30b).
Example GCP configurations for the primary targets are N1 with one T4 and
`a2-highgpu-1g` with one A100 40 GB. See
[GCP GPU configurations](https://docs.cloud.google.com/compute/docs/gpus)
for memory capacities and machine availability.

**P4 8 GB is an experimental Nano 4B target**, excluded from the recommended
menu guidance until tested with the configured 64K context. It leaves less
memory for context and runtime allocations. Current Ollama also requires
driver 570 or newer for P4; see
[Ollama hardware requirements](https://docs.ollama.com/gpu).

GPU suggestions are memory-budget estimates, not benchmark results. Weights are
only part of VRAM use: context, KV cache, and runtime allocations also need room.
Check `ollama ps` for `100% GPU` at the configured context length, and compare
task quality and latency on your target VM. Smaller models can be less reliable
on complex coding and MCP tasks. A T4 offers a smaller hardware configuration
than an A100; actual cost depends on region, machine size, and provisioning.

The older `nemotron-mini:4b` is deliberately excluded: its
[4K context window](https://ollama.com/library/nemotron-mini/tags) is too short
for OpenCode plus Workbench context and MCP tools.

## Usage

1. Open the code-server IDE and a terminal.
2. Start the agent in a project directory:

   ```sh
   cd ~/repos/<your-repo>
   opencode
   ```

The initial startup downloads the selected model and loads it. Subsequent
restarts reuse cached weights in `/config/.ollama/models`; they do not pull
the model again. To update an existing tag deliberately, run `ollama pull <tag>`.

### Choose or change a model

```sh
opencode-model                         # numbered menu, including GPU guidance
opencode-model --list                  # inspect choices without downloading
opencode-model nemotron-3-nano:4b       # noninteractive selection
```

The picker downloads the selection, checks Ollama's advertised tool support,
loads it, then updates both `/config/.opencode-model` and the OpenCode config.
Start a new OpenCode session after switching. A download or loading failure
leaves the saved selection and OpenCode config unchanged. Previously downloaded
models stay cached; use `ollama rm <tag>` to reclaim their disk space.

The existing override workflow also works:

```sh
echo nemotron-3-nano:4b > /config/.opencode-model
# Restart the app to apply this manually written override.
```

The saved tag survives restarts and machine-type changes. Select a smaller model
before moving from an A100 to a T4/V100. Delete `/config/.opencode-model` and restart
to return to the compose default. Custom Ollama tags can be passed to the picker;
they must support tools, sufficient context, and your GPU. The catalog uses local
model tags, not Ollama cloud models.

### Optional first-launch prompt

Set this in your fork's `docker-compose.yaml` before creating/rebuilding the app:

```yaml
OLLAMA_MODEL: "prompt"
```

Startup launches the services without downloading a model. On the first
interactive `opencode` launch, a terminal menu asks for a model and downloads
only that selection. Later launches use the saved choice. An existing
`/config/.opencode-model` takes precedence, so remove it to try the prompt on an
existing app. Cancelling the menu leaves the selection unset.

For automation, run `opencode-model <tag>` first. A model-dependent command
without a terminal fails with instructions rather than waiting for input.
Help, version, model listing, and MCP setup commands remain available.

This implements selection at the first agent launch because devcontainer
`postCreateCommand`/`postStartCommand` run without an interactive terminal.
Blocking those hooks on `read` would prevent startup. Other options considered:

- **Automatic GPU selection:** possible using `nvidia-smi`, but total VRAM alone
  does not account for other workloads or the user's quality/latency preference.
- **Workbench creation-form selection:** would require platform changes.
  Workbench substitutes a fixed set of template options on the VM, so adding
  a `model` template option here alone does not work.

## Workbench MCP and workspace context

This app reuses the `wb-mcp-server` and `llm-context` features from the Jupyter
LLM template. After Workbench authentication and mounts, `start-services.sh`:

1. Writes the OpenCode configuration.
2. Starts the feature's HTTP MCP daemon as `abc` for the other included clients.
3. Generates context as `abc` after the workspace becomes available.
4. Starts Ollama as `abc` and prepares the selected model (or defers selection).

OpenCode's `mcp.wb` launches `/opt/wb-mcp-server/wb-mcp-server` using the server's
native stdio transport. OpenCode manages that process as the agent user. This
uses the same binary as the feature's HTTP daemon, without relying on its HTTP
transport compatibility or readiness. It uses the user's existing `wb`
authentication; no hosted LLM API key or separate MCP OAuth login is needed.
OpenCode's `instructions` setting loads
`/config/.claude/CLAUDE.md` explicitly, including when working in a nested repo.
The context generator also installs its Workbench guides in `~/.claude/skills/`.
A short OpenCode instruction file maps the guides' Claude-style tool names to
the `wb_` tool names exposed in OpenCode.

Try asking: "List the resources in my Workbench workspace."

```sh
opencode mcp list
wb workspace describe
generate-llm-context   # refresh after authentication or workspace changes
```

If context is not ready during startup, the generator retries and logs how to
refresh it later; local coding remains available. Context and MCP outputs are
sent to the selected local model, while executing tools can call Workbench and
cloud services according to the user's existing permissions.

## Configuration

`resolve-model.sh` applies this precedence: `/config/.opencode-model`, then
`OLLAMA_MODEL`, then `nemotron-3-nano:4b`. Both the agent config and Ollama startup
use it. A saved choice from an earlier version is retained.

`configure-opencode.sh` owns `~/.config/opencode/opencode.json` and rewrites it
on startup and selection. It configures the selected model only, so OpenCode's
model menu does not offer catalog entries that have not been downloaded. It also
pins `autoupdate: false`, disables sharing, and registers Workbench MCP/context.

`OLLAMA_CONTEXT_LENGTH` defaults to 65536, following
[Ollama's OpenCode guidance](https://docs.ollama.com/integrations/opencode).
The same limit is advertised to OpenCode so its context management matches the
server. Larger contexts consume more VRAM. `OLLAMA_NUM_PARALLEL=1` and
`OLLAMA_MAX_LOADED_MODELS=1` limit concurrent model memory use on smaller GPUs.
`OPENCODE_HOME` defaults to `/config` and can redirect state for script testing.

You can also call the local API directly:

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:11434/v1", api_key="unused")
response = client.chat.completions.create(
    model="nemotron-3-nano:4b",  # use the tag you selected
    messages=[{"role": "user", "content": "Hello!"}],
)
message = response.choices[0].message
# Reasoning tokens may precede content; leave room for them in the output budget.
print(getattr(message, "reasoning", ""))
print(message.content)
```

## Debugging and validation

```sh
tail -f ~/ollama-server.log
tail -f /tmp/wb-mcp-server.log
curl http://localhost:11434/v1/models
ollama list
nvidia-smi
ollama ps
opencode models
opencode mcp list
```

Run the GPU-independent regression tests from the repository root:

```sh
go build -o /tmp/wb-mcp-server-test features/src/wb-mcp-server/main.go
export WB_MCP_TEST_BINARY=/tmp/wb-mcp-server-test
python3 -m unittest discover -s tests/opencode-nemotron -v
```

These cover configuration, selection, cache reuse, deferred startup, interactive
input, and download/load failures with mocked Ollama responses. The MCP test uses
the real server binary with a fake `wb` CLI for handshake, tool discovery, and
tool dispatch. It is skipped when `WB_MCP_TEST_BINARY` is unset. Before release,
build the devcontainer on a Workbench GPU VM, confirm MCP connectivity and a
read-only tool call, and check `100% GPU` during an OpenCode task at 64K context.
