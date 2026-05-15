# vLLM

Code-server IDE with a vLLM inference server running Gemma 4 E4B. Opens a browser-based VS Code editor on port 8443 with vLLM serving an OpenAI-compatible API on port 8000 inside the container.

## Recommended VM Configuration

| Model | GPU | Machine type | CPUs | RAM | Notes |
|---|---|---|---|---|---|
| Gemma 4 E2B | T4 (16 GB) | n1-standard-2 | 2 | 7.5 GB | Smallest viable setup |
| **Gemma 4 E4B** | **T4 (16 GB)** | **n1-standard-4** | **4** | **15 GB** | **Default config, best value** |
| Gemma 4 E4B | L4 (24 GB) | n1-standard-4 | 4 | 15 GB | ~2x faster inference |
| Gemma 4 26B MoE | A100 (40 GB) | n1-standard-8 | 8 | 30 GB | Requires `--tensor-parallel-size` changes |

## Changing the Model

Update the `--model` flag in `start-vllm.sh` and the `model=` parameter in your Python scripts.

## Usage

Once the app is ready, open the code-server IDE and run:

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="unused")

response = client.chat.completions.create(
    model="google/gemma-4-E4B-it",
    messages=[{"role": "user", "content": "Hello!"}],
    max_tokens=100,
)
print(response.choices[0].message.content)
```

### Using `UV`


1. install uv

    ```sh 
    pip install uv
    ```

2. initialize the project

    ```sh 
    uv init local-vllm-gema4-test
    ```

3. Add open ai package to the registry

    ```sh 
    cd local-vllm-gema4-test/
    uv add opena
    ```

4. Run the application

    ```sh 
    uv run main.py
    ```

## Debugging

Check vLLM server logs:

```bash
tail -f ~/vllm-server.log
```

Verify the server is running:

```bash
curl http://localhost:8000/v1/models
```
