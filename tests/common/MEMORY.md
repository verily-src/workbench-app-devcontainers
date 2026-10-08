# App memory checks

1. `memory-collect.sh start CONTEXT_JSON OUTPUT_DIR` starts before app bootstrap; `workload.sh APP PROFILE OUTPUT_DIR` runs after startup COMPLETE; `memory-collect.sh finish OUTPUT_DIR OUTPUT_DIR/workload.json` captures final counters before any container is stopped or deleted.
2. Context fields are `schema_version:1`, `run_id`, `app`, `cloud`, `profile`, `sample`, `inputs_hash`, immutable `source_sha`, and `machine:{type,ram_bytes,gpu_type,gpu_count}`; the collector records observed RAM and the cold boot ID from the guest.
3. The host requires Bash, jq, GNU coreutils, Docker, readable cgroup v2 counters, and `nvidia-smi` for GPU profiles; Python/R run inside the existing application image.
4. `python3 tests/common/memory-compare.py --candidate sample1.json sample2.json sample3.json --baseline prior1.json prior2.json prior3.json --output decision.json` compares the same cloud, machine, GPU, workload and collector; use `--unchanged` only for one smoke with a complete matching promoted baseline.
5. Smoke is cold sample 1; only changed inputs require two more cold samples, and baseline reruns happen only to confirm a suspected regression within the runner's shared budget.
6. The gate rejects missing counters, missing sidecars, lost cgroups, OOM, swap, inadequate 25% headroom and growth above `max(10% baseline median,256 MiB,3 baseline MAD)`; summed cgroup peaks are conservative bounds, while host peaks are sampled every 100 ms.
7. `profiles.json` defines all 24 app directory keys and required Compose services; fixtures use seed 189771, 60 seconds idle before and after work, and bounded execution times.
8. NeMo GPU uses one A100-80GB, Parabricks uses T4, and the shared Jupyter GPU check uses `custom-workbench-jupyter-template` on T4; CPU startup has separate evidence and never substitutes for GPU work.
9. SAS requires existing registry/license access, test secrets require synthetic delivery, and access-logging requires `DC_ACCESS_ENV=test` before startup; absent access yields a blocked workload, while fixture query execution replaces BigQuery with a local stub.
10. LLM profiles exercise installed clients and context generation; four generated templates get separate Compose render checks, and external inference is not claimed.
11. Workload-created child containers remain alive for final collection and are deleted with the owned VM; the runner owns lifecycle checks, fresh workspaces, the 07:00 UTC boundary, resource budgets and cleanup.
12. Local Bats and Python fixtures validate failure handling; `scripts/test/integration/memory.bats` runs real Docker/cgroup spike, surviving-parent child OOM and sidecar checks in the existing Linux CI suite.
13. Host/digest source pins are candidates; only the weekly lock reaches prod, and floating in-container installs remain risks without replay or package storage.
