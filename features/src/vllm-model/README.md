# vllm-model

Serves an open-weight model with [vLLM](https://docs.vllm.ai) on the app's GPU, through an
OpenAI-compatible API on port 8000. NVIDIA Nemotron Lightning 30B by default. Debian-based
images on x86_64; the VM needs NVIDIA driver 580 or newer.

```json
"features": {
  "./.devcontainer/features/vllm-model": {"username": "abc", "userHomeDir": "/config"}
}
```

The feature installs a pinned vLLM in `/opt/vllm` and its scripts in `/opt/vllm-model`. Run
`start-vllm.sh` from the app's start-up hook, as the user. It downloads the model if the store
lacks it, starts the server, and fails unless the server answers a chat request with the
configured model and context length. The log is `~/vllm-server.log`.

`models.json` pins the model's Hugging Face revision, minimum VRAM and extra `vllm serve`
arguments. Any other Hugging Face ID works in `VLLM_MODEL`, with the common arguments only.

## Settings

Environment variables, set in the app's compose file. Each must also be listed in the
`sudo --preserve-env` that runs `start-vllm.sh`, or it does not reach the server.

| Variable | Default | Meaning |
|---|---|---|
| `VLLM_MODEL` | none | Hugging Face ID of the model to serve |
| `VLLM_PORT`, `VLLM_BIND_ADDRESS` | `8000`, `0.0.0.0` | Where the server listens |
| `VLLM_CONTEXT_LENGTH` | `65536` | `--max-model-len` |
| `VLLM_GPU_MEMORY_UTILIZATION` | `0.90` | Fraction of VRAM vLLM reserves up front |
| `VLLM_MAX_NUM_SEQS` | `8` | Concurrent sequences |
| `VLLM_LOAD_TIMEOUT_MINUTES` | `25` | How long start-up waits for the server |
| `VLLM_EXTRA_ARGS` | empty | More `vllm serve` arguments |
| `VLLM_MODELS` | `~/.vllm/models` | The local model store |
| `VLLM_MODEL_STORE_SEARCH` | `~/workspace` | Where to look for a store on a bucket mount; `off` to skip |

## Model store on a bucket mount

Loading from the VM's local disk is slow (about ten minutes cold for Lightning). A store on a
Workbench bucket mount loads in two to four minutes and is shared between apps.

- At start-up, the workspace's bucket mounts are searched for a store that already holds the
  model. Otherwise the local store is used and the model is downloaded.
- To pin a store: `echo /config/workspace/<bucket>/vllm-store > /config/.vllm-model-store`,
  then restart the app.
- To populate one, copy from an app that has the model:
  `gcloud storage cp -r ~/.vllm/models/<org>--<model> gs://<bucket>/vllm-store/`

Tests: `python3 -m unittest discover -s tests/vllm-model`.
