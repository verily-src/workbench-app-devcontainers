# OpenCode + NVIDIA Nemotron + Workbench MCP

Code-server IDE with [OpenCode](https://opencode.ai), local
[NVIDIA Nemotron](https://developer.nvidia.com/topics/ai/nemotron) models served by
[Ollama](https://ollama.com), Workbench MCP tools, and generated workspace context.
The default is **Lightning 30B on A100/H100**, or **experimental Nano 4B on
T4/V100**. Explicit selections in `/config/.opencode-model` take precedence.

- Code-server UI on port 8443.
- Ollama API on `127.0.0.1:11434` and Workbench MCP on `127.0.0.1:9242` inside the container.
- `opencode` and `opencode-model` on the `PATH`.
- Local model inference; OpenCode session sharing is disabled. MCP tools use the
  authenticated user's Workbench/cloud APIs, and model downloads use Ollama's registry.

Use **`src/opencode-nemotron-mcp`** as the template path when creating this app.

## Models and GPU guidance

At startup the app detects the largest attached GPU's VRAM and filters the
catalog in `models.json`. Every compatible catalog model is downloaded so it is
usable from OpenCode's `/model` picker. Each model is loaded sequentially and
must pass a full-GPU, configured-context check before startup publishes the
configuration. Only one model is kept in VRAM at a time, with the default loaded last.

| Ollama tag | Weight download | Minimum VRAM | Available on |
|---|---|---|---|
| `nemotron-3-nano:4b` (experimental) | 2.8 GB | 15,000 MiB | T4/V100 16 GB and larger GPUs |
| `nemotron-3.5-lightning:30b` | 25 GB | 40,000 MiB | A100 40/80 GB and H100 80 GB variants |

On a T4/V100, `/model` offers Nano 4B only. On an A100/H100, it offers Nano 4B
and Lightning 30B. Capacity thresholds deliberately use MiB rather than GPU
names so provider-specific labels such as `MEGA` do not affect filtering.
Custom tags remain available through `opencode-model` for experimentation.
Nano 4B produced silent failures in 2 of 5 reported tests with the full Workbench
tool inventory. It remains available for experimentation, not as a reliability
claim. Lightning needs the same full-inventory evaluation on the target GPU.
Sizes and tool support come from the
[Nano tags](https://ollama.com/library/nemotron-3-nano/tags) and
[Lightning tag](https://ollama.com/library/nemotron-3.5-lightning:30b).
Example GCP configurations for the primary targets are N1 with one T4 and
`a2-highgpu-1g` with one A100 40 GB. See
[GCP GPU configurations](https://docs.cloud.google.com/compute/docs/gpus)
for memory capacities and machine availability.

**P4 8 GB is excluded from the catalog** at the configured 64K context. It leaves less
memory for context and runtime allocations. Ollama also requires
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

The initial startup downloads every model compatible with the attached GPU,
validates each model on the GPU, and leaves the default loaded. Subsequent restarts reuse cached weights in
`/config/.ollama/models`; they do not pull models again. To update an existing
tag deliberately, run `ollama pull <tag>`.

### Choose or change a model

Inside OpenCode, use `/model` to switch among the models that fit the attached
GPU. Ollama loads the selection and evicts the previous model when necessary;
switch latency depends on the model and storage, but the models do not need to fit in
VRAM concurrently.
Only the Ollama provider is enabled. No separate background `small_model` is
configured, so title generation can use the current Nemotron selection.

The companion command changes the persisted default or selects a custom tag:

```sh
opencode-model                         # numbered menu, including GPU guidance
opencode-model --list                  # inspect choices without downloading
opencode-model nemotron-3-nano:4b       # noninteractive selection
```

The command lists only catalog models compatible with the attached GPU. It
downloads all compatible choices, checks Ollama's advertised tool support and
GPU residency at the configured context, then updates both `/config/.opencode-model` and the
OpenCode config. Start a new OpenCode session after changing the persisted
default. A download or loading failure leaves the saved selection and OpenCode
config unchanged. Previously downloaded models stay cached; use
`ollama rm <tag>` to reclaim their disk space.

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
interactive `opencode` launch, a terminal menu asks for a default model, then
downloads and validates all compatible choices. Later launches use the saved choice. An existing
`/config/.opencode-model` takes precedence, so remove it to try the prompt on an
existing app. Cancelling the menu leaves the selection unset.

For automation, run `opencode-model <tag>` first. A model-dependent command
without a terminal fails with instructions rather than waiting for input.
Help, version, model listing, and MCP setup commands remain available.

The optional prompt implements initial selection at the first agent launch because devcontainer
`postCreateCommand`/`postStartCommand` run without an interactive terminal.
Blocking those hooks on `read` would prevent startup. Other options considered:

- **Workbench creation-form selection:** would require platform changes.
  Workbench substitutes a fixed set of template options on the VM, so adding
  a `model` template option here alone does not work.

## Workbench MCP and workspace context

This app reuses the `wb-mcp-server` and `llm-context` features from the Jupyter
LLM template. After Workbench authentication and mounts, `start-services.sh`:

1. Starts the feature's HTTP MCP daemon as `abc` for the other included clients.
2. Generates context as `abc` after the workspace becomes available.
3. Starts Ollama as `abc`, checks its pinned version, and validates all eligible models (or defers selection).
4. Writes the OpenCode configuration only after those checks succeed.

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
`OLLAMA_MODEL`, then `auto`. Auto chooses the highest-priority compatible catalog
model: Lightning on A100/H100, Nano 4B on T4/V100. Both the agent config and
Ollama startup use it. A saved choice from an earlier version is retained.

`available-models.sh` reads the largest attached GPU's memory with `nvidia-smi`
and filters `models.json` by `minimum_vram_mib`. `OPENCODE_GPU_MEMORY_MIB` can
override detection for testing or an operator-controlled deployment.

`configure-opencode.sh` owns `~/.config/opencode/opencode.json` and rewrites it
on startup and selection. It registers every compatible catalog model so
OpenCode's `/model` picker cannot accidentally select a catalog model that is
too large for the GPU. This is a usability guard, not a security boundary;
users can still supply a custom Ollama tag. The script also pins
`autoupdate: false`, disables sharing, enables only Ollama, and registers Workbench MCP/context.

OpenCode is pinned to 1.18.22. `ollama-release.json` pins Ollama 0.34.4 and the
SHA-256 of its Linux amd64 release archive. The build verifies that checksum;
startup rejects an already-running server with a different version. A100/H100
need a compatible NVIDIA host driver (550+ for this Ollama release). Model tags
remain mutable; the GPU acceptance report records the digests actually tested.

`OLLAMA_CONTEXT_LENGTH` defaults to 65536, following
[Ollama's OpenCode guidance](https://docs.ollama.com/integrations/opencode).
The same limit is advertised to OpenCode so its context management matches the
server. Larger contexts consume more VRAM. `OLLAMA_NUM_PARALLEL=1` and
`OLLAMA_MAX_LOADED_MODELS=1` limit concurrent model memory use; the five-minute
keep-alive keeps the active model warm while still allowing predictable swaps.
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
python3 -m unittest discover -s tests/opencode-nemotron-mcp -v
```

These cover GPU-aware configuration, `/model` registration, selection, cache
reuse, deferred startup, interactive input, and download/load failures with
mocked Ollama responses. The MCP test uses
the real server binary with a fake `wb` CLI for handshake, tool discovery, and
tool dispatch. It is skipped when `WB_MCP_TEST_BINARY` is unset.

CI also builds the complete devcontainer with its features and runs the installed
OpenCode as `abc`. It checks the model list, MCP connection, and a
Lightning → Nano → Lightning tool round trip in one session against a simulated
OpenAI-compatible server and fake `wb`. No weights or GPU are required for that
test. Workbench lifecycle hooks and CUDA inference still require a real VM.

### Real-GPU acceptance check

After startup, run this in the code-server terminal as `abc`:

```sh
opencode-gpu-check
```

The check alternates between every configured model, with five trials per model.
Each trial sends the entire discovered Workbench MCP tool inventory and configured
instructions through Ollama's `/v1/chat/completions` endpoint, requires a
`wb_wb_status` call with empty arguments, executes only that read-only tool, and
requires a nonempty completed summary. Requests for other tools are failures and
are never executed. It also verifies full GPU residency, configured context, and
one resident model after the requests. It restores the configured default and
exits nonzero if any trial or restoration fails.

Results go to `~/opencode-gpu-check-<timestamp>.json`, including model digests,
timings, context, VRAM, tool count, and individual pass/fail results. Prompts,
workspace results, and generated content are omitted. Use `--repeats 10` for more
trials or `--report /config/my-new-report.json` for a new report path. Run it with
other inference clients idle; concurrent work invalidates the residency check.

This command tests the backend and full MCP inventory, not the interactive TUI
or the exact OpenCode prompt with its additional built-in tools. Before recording,
use `/model` in OpenCode to switch both ways and repeat a read-only workspace
question. The report checks that a summary exists, not its semantic accuracy.
