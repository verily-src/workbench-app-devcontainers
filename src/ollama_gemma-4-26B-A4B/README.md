# Ollama + Gemma 4 26B-A4B

Code-server IDE with an Ollama inference server running Gemma 4 26B MoE (4B active parameters). Opens a browser-based VS Code editor on port 8443 with Ollama serving an OpenAI-compatible API on port 11434 inside the container.

## Recommended VM Configuration

| Model | GPU | Machine type | CPUs | RAM | Notes |
|---|---|---|---|---|---|
| **Gemma 4 26B MoE** | **A100 (40 GB)** | **n1-standard-8** | **8** | **30 GB** | **Default config for this app** |
| Gemma 4 26B MoE | A100 (80 GB) | n1-standard-8 | 8 | 30 GB | More VRAM headroom for longer contexts |

## Changing the Model

Update the `ollama pull` command in `start-ollama.sh` and the `model=` parameter in your Python scripts. See available models at https://ollama.com/library.

## Usage

Once the app is ready, open the code-server IDE and run:

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:11434/v1", api_key="unused")

response = client.chat.completions.create(
    model="gemma4:26b",
    messages=[{"role": "user", "content": "Hello!"}],
    max_tokens=100,
)
print(response.choices[0].message.content)
```

### Using `uv`

1. Install uv

    ```sh
    pip install uv
    ```

2. Initialize the project

    ```sh
    uv init local-ollama-gemma4-26b
    ```

3. Add openai package

    ```sh
    cd local-ollama-gemma4-26b/
    uv add openai
    ```

4. Run the application

    ```sh
    uv run main.py
    ```

## Debugging

Check Ollama server logs:

```bash
tail -f ~/ollama-server.log
```

Verify the server is running:

```bash
curl http://localhost:11434/v1/models
```

List downloaded models:

```bash
ollama list
```
