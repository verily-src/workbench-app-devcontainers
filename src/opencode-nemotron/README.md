# OpenCode + NVIDIA Nemotron

Code-server IDE with the [opencode](https://opencode.ai) coding agent wired to a
local [NVIDIA Nemotron](https://developer.nvidia.com/topics/ai/nemotron) model.
[Ollama](https://ollama.com) serves the model inside the container. No prompt,
code, or data leaves the VM.

- Code-server UI on port 8443.
- Ollama OpenAI-compatible API on port 11434 (container-local only).
- `opencode` on the `PATH`, preconfigured to use the local model.

## Recommended VM Configuration

| Model | Weights | GPU | Machine type |
|---|---|---|---|
| **`nemotron-3.5-lightning:30b`** | **25 GB** | **A100 40 GB** | **`a2-highgpu-1g`** |
| `nemotron-3-nano:30b` | 24 GB | A100 40 GB | `a2-highgpu-1g` |
| `nemotron-3-nano:4b` | 2.8 GB | L4 24 GB | `g2-standard-8` |

`nemotron-3.5-lightning:30b` is the default. It is a 30B mixture-of-experts model
with 3B active parameters and tool-calling support, which suits an agent loop.

## Usage

1. Open the code-server IDE.
2. Open a terminal.
3. Start the agent in a project directory:

    ```sh
    cd ~/repos/<your-repo>
    opencode
    ```

The first run takes a few minutes. The app pulls the model on create and on every
container restart. A pulled model persists in the `/config` volume.

You can also call the model directly:

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:11434/v1", api_key="unused")

response = client.chat.completions.create(
    model="nemotron-3.5-lightning:30b",
    messages=[{"role": "user", "content": "Hello!"}],
    max_tokens=100,
)
print(response.choices[0].message.content)
```

## Changing the Model

Set the `model` template option when you create the app. Use any tag from
https://ollama.com/library. The value must be a tag that Ollama can pull, and the
model must support tools for `opencode` to work.

To change the model on a running app, edit `~/.config/opencode/opencode.json` and
run `ollama pull <tag>`. The app rewrites that file on each restart.

## Configuration

`configure-opencode.sh` writes `~/.config/opencode/opencode.json` on create and
on restart. It sets:

- `provider.ollama` — an OpenAI-compatible provider at `http://localhost:11434/v1`.
- `autoupdate: false` — keeps the version that the Dockerfile pins.
- `share: "disabled"` — blocks the hosted session-sharing service.

`OLLAMA_CONTEXT_LENGTH` is set to 32768 in `docker-compose.yaml`. Smaller contexts
make tool calls unreliable.

## Debugging

Check the Ollama server log:

```sh
tail -f ~/ollama-server.log
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
