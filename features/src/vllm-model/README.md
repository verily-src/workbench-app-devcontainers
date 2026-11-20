# vllm-model

Serves `nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4`, text only, with
[vLLM](https://docs.vllm.ai) across two H100 80 GB GPUs, through an OpenAI-compatible API on
port 8000. It is the app's local model. Debian-based images on x86_64; the VM needs NVIDIA driver
580 or newer, two GPUs of 79,000 MiB or more (`a3-highgpu-2g`), and room for the weights.

```json
"features": {
  "./.devcontainer/features/vllm-model": {"username": "abc", "userHomeDir": "/config"}
}
```

| File | What it is |
|---|---|
| `vllm-release.json` | The vLLM release (0.34.0, the first with vllm#58231, the thinking-budget fix with `top_p` below 1) and the FlashInfer version it pins (0.7.3) |
| `install.sh` | Installs vLLM into `/opt/vllm` with FlashInfer's prebuilt kernels (the cubin wheel, the `flashinfer-jit-cache` shim and its H100 `sm90a` set), the CUDA 13.0 toolkit, and the start script into `/opt/vllm-model` |
| `start-vllm.sh` | Downloads the weights (75 GB) at a pinned revision unless the store holds a finished download of it (the marker `.download-complete` in the model's directory, written after `hf download` succeeds), starts the server with the recipe's flags, and fails unless it answers a chat request with the configured model and context length |

The app's start-up hook runs `start-vllm.sh` as the app's user. The log is `~/vllm-server.log`.

The CUDA 13.0 toolkit is there for one kernel: no FlashInfer wheel carries the Mamba state update
for the recipe's float16 state, so FlashInfer compiles it on first start, and the compiler pip
brings does not match the CUDA 13.0 headers FlashInfer bundles. The compile caches persist under
`~/.cache`.

## Settings

Environment variables, set in the app's compose file. Each must also be listed in the
`sudo --preserve-env` that runs `start-vllm.sh`, or it does not reach the server.

| Variable | Default | Meaning |
|---|---|---|
| `VLLM_MODEL` | Super VL | Hugging Face ID of the model, and the name it is served under |
| `VLLM_PORT`, `VLLM_BIND_ADDRESS` | `8000`, `0.0.0.0` | Where the server listens |
| `VLLM_CONTEXT_LENGTH` | `262144` | `--max-model-len` |
| `VLLM_GPU_MEMORY_UTILIZATION` | `0.89` | Fraction of VRAM vLLM reserves up front |
| `VLLM_MAX_NUM_SEQS` | `8` | Concurrent sequences |
| `VLLM_LOAD_TIMEOUT_MINUTES` | `25` | How long start-up waits for the server |
| `VLLM_EXTRA_ARGS` | empty | More `vllm serve` arguments |
| `VLLM_MODELS` | `~/.vllm/models` | The model store |
| `VLLM_HTTP_TIMEOUT_KEEP_ALIVE` | `3600` | Seconds an idle connection stays open |

The compose file also sets `shm_size: 32g`: tensor parallelism passes messages through
`/dev/shm`, and Docker's 64 MiB default fails at start.

## The recipe

The serve flags follow one tested recipe for Super VL; the vertex-model feature's
`deploy-endpoint.sh` runs the same flags, release and weights on one GPU. Where this differs:

- The model is served under its Hugging Face ID alone, the name the rest of the app uses.
- 262,144 tokens of context, not the model's 1,048,576.
- Weights are downloaded at a pinned revision into the model store and served from there, with
  Hugging Face off at run time.
- `VLLM_FLASHINFER_ALLREDUCE_BACKEND=trtllm`: the default picks a multi-node kernel with no
  prebuilt binary for H100.

Speculative decoding stays off, as in the recipe: it degraded grammar-constrained tool calls.

## Running it

```sh
tail -f ~/vllm-server.log
/opt/vllm-model/start-vllm.sh             # as the app's user, with the compose file's VLLM_* settings
pkill -f '[v]llm serve'                    # stop it
```

## Known limitations

- Only two H100 80 GB (or larger) GPUs run it. On a VM without them, the app uses the
  vertex-model feature instead, for alpha users only.
- A new app downloads the 75 GB of weights from Hugging Face on first start; there is no shared
  model store.
- The first start compiles one FlashInfer kernel and vLLM's CUDA graphs, which adds minutes.
- vLLM warns about the app's own `VLLM_*` settings, which it does not know, at start.

Tests: `python3 -m unittest discover -s tests/vllm-model`.
