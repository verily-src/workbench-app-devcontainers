# OpenCode + NVIDIA Nemotron

Code-server IDE with the [opencode](https://opencode.ai) coding agent wired to
three local [NVIDIA Nemotron](https://developer.nvidia.com/topics/ai/nemotron)
models. [Ollama](https://ollama.com) serves one model at a time inside the
container. No prompt, code, or data leaves the VM.

- Code-server UI on port 8443.
- Ollama OpenAI-compatible API on port 11434 (container-local only).
- `opencode` on the `PATH`, preconfigured to choose among the three local models.

## Recommended VM Configuration

| OpenCode model | Weights | Recommended GPU | Notes |
|---|---|---|---|
| **`nemotron-nano-9b:v2`** | **6.53 GB** | **T4 16 GB or larger** | Bartowski Q4_K_M GGUF; default |
| `nemotron-3-nano:4b` | 2.8 GB | T4 16 GB or larger | Configured as chat only |
| `nemotron-3.5-lightning:30b` | 25 GB | A100 40 GB | Agent with tool calls |

The 9B model is [Bartowski's NVIDIA Nemotron Nano 9B v2 Q4_K_M GGUF](https://huggingface.co/bartowski/nvidia_NVIDIA-Nemotron-Nano-9B-v2-GGUF/blob/main/nvidia_NVIDIA-Nemotron-Nano-9B-v2-Q4_K_M.gguf).
It is pulled from Hugging Face through Ollama and stored under the short local
name `nemotron-nano-9b:v2`. The 4B and Lightning models come from Ollama's
library. All three pulls need about 35 GB of persistent model storage. The 30B
model does not fit fully in a T4's 16 GB of VRAM and will be much slower there.

The 9B GGUF uses NVIDIA's `<SPECIAL_10>` / `<SPECIAL_11>` chat format. Startup
creates its Ollama model from the local GGUF blob with the model-specific
`Modelfile-nano-9b-v2`; an existing 9B alias is rebuilt without a second
download. This avoids Ollama's automatic `nemotron-3-nano` ChatML renderer,
which can make the model emit fake conversation turns under agent prompts.
After startup, `ollama show --modelfile nemotron-nano-9b:v2` should show the
`<SPECIAL_10>` template and no `RENDERER nemotron-3-nano` line. Test an actual
OpenCode tool call before relying on the 9B model for agent tasks.

## Usage

1. Open the code-server IDE.
2. Open a terminal.
3. Start the agent in a project directory:

    ```sh
    cd ~/repos/<your-repo>
    opencode
    ```

The first run pulls all three models and can take a while. They persist in the
`/config` volume, so later restarts skip models already present. In OpenCode,
use `/models` to switch between the three. The 4B model is for chat and small
tasks; select 9B or Lightning when you need the agent to call tools.

You can also call the model directly:

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:11434/v1", api_key="unused")

response = client.chat.completions.create(
    model="nemotron-nano-9b:v2",
    messages=[{"role": "user", "content": "Hello!"}],
)

# Nemotron reasons before it answers. Ollama returns the thinking tokens in a
# non-standard `reasoning` field, so a small max_tokens truncates the reply
# before `content` holds anything.
message = response.choices[0].message
print(getattr(message, "reasoning", ""))
print(message.content)
```

## Changing the Default Model

Write the tag to `/config/.opencode-model`, then restart the app:

```sh
echo nemotron-3.5-lightning:30b > /config/.opencode-model
```

`/config` is a volume, so the override survives a restart and a machine-type
change. On restart the app rewrites `~/.config/opencode/opencode.json` with the
new default. Delete the file to return to the 9B default. The override accepts
only the three models listed above. The `/models` menu changes the active model
within OpenCode without changing the default.

Pick a model that fits the GPU. A model larger than VRAM runs partly on the CPU
and is slow. Only one model remains loaded at a time, so switching models does
not require the combined weight size in VRAM.

To change the default for new apps, edit `OLLAMA_MODEL` in `docker-compose.yaml`
in your fork and point the app config at that branch. Workbench substitutes only
a fixed set of template options on the VM, so a custom `model` template option
would not work.

## Configuration

`configure-opencode.sh` writes `~/.config/opencode/opencode.json` on create and
on restart. It sets:

- `enabled_providers: ["ollama"]` — only this provider appears in OpenCode.
- `provider.ollama` — an OpenAI-compatible provider with exactly three models.
- `tool_call: false` on 4B — marks it as chat only in OpenCode. Some OpenCode
  versions still send tool definitions despite this setting, so verify the
  behavior before relying on 4B for a tool-free session.
- `autoupdate: false` — keeps the version that the Dockerfile pins.
- `share: "disabled"` — blocks the hosted session-sharing service.

`resolve-model.sh` picks the default model tag. `/config/.opencode-model` wins,
then `OLLAMA_MODEL` from `docker-compose.yaml`.

`OLLAMA_CONTEXT_LENGTH` is set to 32768 in `docker-compose.yaml`. Smaller contexts
make tool calls unreliable.

## Debugging

Check the Ollama server log:

```sh
tail -f /config/ollama-server.log
```

Verify that the server answers and the model is present:

```sh
curl http://localhost:11434/v1/models
ollama list
```

Confirm that the GPU is in use. `ollama ps` reports `100% GPU` when the model fits
in VRAM:

```sh
nvidia-smi
ollama ps
```

Print the resolved opencode config:

```sh
opencode models
```
