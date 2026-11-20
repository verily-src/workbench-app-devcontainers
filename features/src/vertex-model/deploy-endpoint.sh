#!/bin/bash

# deploy-endpoint.sh puts Nemotron 3.5 Super VL on a dedicated Vertex AI endpoint in a workspace's
# project, for every AI Research Assistant app there that has no GPU for it (README.md, "A Nemotron
# endpoint"). A workspace owner runs it once, from any machine with gcloud and jq, such as a
# Workbench JupyterLab app. It is not part of the app.
#
#   deploy-endpoint.sh --yes [--project P] [--region R] [--machine M --accelerator A --count N]
#   deploy-endpoint.sh --delete    # undeploy and delete the endpoint and its models
#
# Without --yes the script prints the project, region, machine and hourly cost it would deploy
# with, creates nothing and exits 1.
#
# What it makes, each reused when it is already there:
#   - an Artifact Registry remote repository "dockerhub" that pulls vLLM's image through from
#     Docker Hub (Vertex AI takes images only from Artifact Registry);
#   - a dedicated endpoint labelled ara-model=super-vl, which the app finds (VERTEX_ENDPOINT=auto),
#     with a 30-minute reply limit;
#   - the model, vLLM serving Super VL with the vllm-model feature's settings on one GPU, and its
#     deployment on one replica. Weights come from Hugging Face when the server starts, so the
#     project needs internet access (no strict network policy).
#
# A replica bills by the hour while deployed, called or not (about $6/h for one RTX PRO 6000 in
# us-central1). --delete leaves the Artifact Registry repository. A deploy takes 15-30 minutes; "Machine type temporarily unavailable" means no host
# was free, and the script tries again.

set -o errexit
set -o nounset
set -o pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2> /dev/null)}"
REGION="us-central1"
MACHINE="g4-standard-48"
ACCELERATOR="NVIDIA_RTX_PRO_6000"
COUNT=1
DELETE=false
YES=false
while (( $# )); do
  case "$1" in
    --project) PROJECT="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    --machine) MACHINE="$2"; shift 2 ;;
    --accelerator) ACCELERATOR="$2"; shift 2 ;;
    --count) COUNT="$2"; shift 2 ;;
    --delete) DELETE=true; shift ;;
    --yes) YES=true; shift ;;
    *) echo "unknown argument: $1 (see the top of $0)" >&2; exit 2 ;;
  esac
done
[[ -n "${PROJECT}" ]] || { echo "No project: pass --project or set GOOGLE_CLOUD_PROJECT." >&2; exit 2; }

readonly LABEL="super-vl"
readonly NAME="nemotron-super-vl"
readonly MODEL="nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4"
# The weights' revision, vLLM release and settings the vllm-model feature runs (its start-vllm.sh
# and vllm-release.json); keep them in step.
readonly REVISION="3acb09951cff50cda7be0200ebbad2c15a3e63ba"
readonly VLLM_TAG="v0.34.0"
readonly CONTEXT=262144
# A long-running operation is polled once a minute for up to an hour.
readonly POLL_SECONDS="${DEPLOY_POLL_SECONDS:-60}"
readonly MAX_ROUNDS=60
readonly API="https://${REGION}-aiplatform.googleapis.com/v1beta1/projects/${PROJECT}/locations/${REGION}"

call() {
  local method="$1" path="$2" body="${3:-}"
  curl -sS -X "${method}" -H "Authorization: Bearer $(gcloud auth print-access-token)" \
    -H "x-goog-user-project: ${PROJECT}" -H "Content-Type: application/json" \
    "${API}${path}" ${body:+-d "${body}"}
}

# Waits for a long-running operation and prints its final state. Fails with the API's message
# when the reply is an error, and after MAX_ROUNDS polls; a failed request is tried again.
wait_for() {
  local op="$1" reply rounds=0 failures=0
  if [[ -z "${op}" || "${op}" == null ]]; then
    echo "No operation to wait for: the request before it was refused (its reply is above)." >&2
    return 1
  fi
  while :; do
    if ! reply="$(curl -sS -H "Authorization: Bearer $(gcloud auth print-access-token)" \
      -H "x-goog-user-project: ${PROJECT}" "https://${REGION}-aiplatform.googleapis.com/v1beta1/${op}")"; then
      failures=$(( failures + 1 ))
      if (( failures > 3 )); then
        echo "Could not reach the Vertex AI API to check ${op}." >&2
        return 1
      fi
      sleep $(( POLL_SECONDS < 10 ? POLL_SECONDS : 10 ))
      continue
    fi
    failures=0
    if [[ "$(jq -r '.done // false' <<< "${reply}" 2> /dev/null)" == true ]]; then
      printf '%s\n' "${reply}"
      return
    fi
    if jq -e '.error' <<< "${reply}" > /dev/null 2>&1; then
      echo "The Vertex AI API refused the request for ${op}: $(jq -r '.error.message // .error' <<< "${reply}")" >&2
      return 1
    fi
    rounds=$(( rounds + 1 ))
    if (( rounds >= MAX_ROUNDS )); then
      echo "Timed out after ${MAX_ROUNDS} polls waiting for ${op}; check it in the Vertex AI console." >&2
      return 1
    fi
    sleep "${POLL_SECONDS}"
    (( rounds % 5 == 0 )) && echo "  ... ${rounds} min" >&2
  done
}

endpoints() {
  call GET "/endpoints?filter=labels.ara-model%3D${LABEL}" | jq -c '.endpoints // []'
}

if [[ "${DELETE}" == true ]]; then
  for endpoint in $(endpoints | jq -r '.[].name'); do
    id="${endpoint##*/}"
    for deployed in $(call GET "/endpoints/${id}" | jq -r '.deployedModels[]?.id'); do
      echo "Undeploying ${deployed} from ${id}..."
      wait_for "$(call POST "/endpoints/${id}:undeployModel" "{\"deployedModelId\": \"${deployed}\"}" | jq -r '.name // error(tostring)')" > /dev/null
    done
    echo "Deleting endpoint ${id}..."
    call DELETE "/endpoints/${id}" > /dev/null
  done
  for model in $(call GET "/models?filter=labels.ara-model%3D${LABEL}" | jq -r '.models[]?.name'); do
    echo "Deleting model ${model##*/}..."
    call DELETE "/models/${model##*/}" > /dev/null
  done
  exit 0
fi

echo "Project ${PROJECT}, region ${REGION}: ${COUNT} x ${ACCELERATOR} on ${MACHINE}."
echo "A replica bills by the hour while deployed, called or not: about \$6/h for one RTX PRO 6000 in us-central1 (other machines and regions differ)."
if [[ "${YES}" != true ]]; then
  echo "Nothing was created. To deploy this, run again with --yes." >&2
  exit 1
fi

# The image, through a pull-through repository in the project.
if ! gcloud artifacts repositories describe dockerhub --project "${PROJECT}" --location "${REGION}" > /dev/null 2>&1; then
  echo "Creating the Artifact Registry remote repository dockerhub (Docker Hub)..."
  gcloud artifacts repositories create dockerhub --project "${PROJECT}" --location "${REGION}" \
    --repository-format docker --mode remote-repository --remote-docker-repo DOCKER-HUB \
    --description "Pull-through cache of Docker Hub, for vLLM's image on Vertex AI"
fi
readonly IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/dockerhub/vllm/vllm-openai:${VLLM_TAG}"

# The endpoint: dedicated, so replies stream and take the OpenAI routes.
endpoint="$(endpoints | jq -r 'sort_by(.createTime) | last | .name // empty')"
if [[ -z "${endpoint}" ]]; then
  echo "Creating the dedicated endpoint ${NAME}..."
  op="$(call POST "/endpoints" "$(jq -nc --arg name "${NAME}" --arg label "${LABEL}" '{displayName: $name,
    dedicatedEndpointEnabled: true, labels: {app: "ai-research-assistant", "ara-model": $label},
    clientConnectionConfig: {inferenceTimeout: "1800s"}}')")"
  endpoint="$(wait_for "$(jq -r '.name // error(tostring)' <<< "${op}")" | jq -r '.response.name // error(tostring)')"
fi
readonly ENDPOINT_ID="${endpoint##*/}"
if [[ -n "$(call GET "/endpoints/${ENDPOINT_ID}" | jq -r '.deployedModels[0].id // empty')" ]]; then
  echo "Endpoint ${ENDPOINT_ID} already serves a model; run with --delete first to replace it."
  exit 0
fi

# The model: vLLM as the vllm-model feature runs it, on one GPU (--count for more).
echo "Uploading the model (vLLM ${VLLM_TAG}, ${MODEL})..."
upload="$(jq -nc --arg model "${MODEL}" --arg rev "${REVISION}" --arg image "${IMAGE}" --arg label "${LABEL}" \
  --arg name "${NAME}-${VLLM_TAG}" --arg tp "${COUNT}" --arg context "${CONTEXT}" '{model: {
  displayName: $name, labels: {app: "ai-research-assistant", "ara-model": $label},
  containerSpec: {imageUri: $image, command: ["vllm", "serve"],
    args: [$model, "--revision", $rev, "--served-model-name", $model, "--trust-remote-code",
      "--host", "0.0.0.0", "--port", "8080", "--tensor-parallel-size", $tp, "--language-model-only",
      "--max-model-len", $context, "--gpu-memory-utilization", "0.92", "--max-num-seqs", "8",
      "--max-num-batched-tokens", "16384", "--block-size", "64", "--enable-prefix-caching",
      "--prefix-match-unit", "64", "--mamba-backend", "flashinfer", "--mamba-cache-mode", "align",
      "--mamba-ssm-cache-dtype", "float16", "--enable-mamba-cache-stochastic-rounding",
      "--mamba-cache-philox-rounds", "5", "--enable-mamba-shared-prefix-checkpoint", "--async-scheduling",
      "--reasoning-parser", "nemotron_v3",
      "--reasoning-config", "{\"reasoning_end_str\": \"\\n\\nEnough thinking, time to act.\\n\\n</think>\"}",
      "--enable-auto-tool-choice", "--tool-call-parser", "qwen3_coder", "--tool-strict-level", "parameter",
      "--enable-prompt-tokens-details",
      "--structured-outputs-config", "{\"backend\": \"xgrammar\", \"disable_any_whitespace\": true}"],
    env: [{name: "HF_HOME", value: "/dev/shm/hf"}, {name: "HF_XET_HIGH_PERFORMANCE", value: "1"},
      {name: "HF_XET_CHUNK_CACHE_SIZE_BYTES", value: "0"}, {name: "VLLM_WORKER_MULTIPROC_METHOD", value: "spawn"},
      {name: "VLLM_USE_V2_MODEL_RUNNER", value: "1"}, {name: "VLLM_HTTP_TIMEOUT_KEEP_ALIVE", value: "3600"},
      {name: "VLLM_NO_USAGE_STATS", value: "1"}, {name: "DO_NOT_TRACK", value: "1"}],
    ports: [{containerPort: 8080}], healthRoute: "/health", invokeRoutePrefix: "/*",
    sharedMemorySizeMb: "81920", deploymentTimeout: "7200s"}}}')"
model="$(wait_for "$(call POST "/models:upload" "${upload}" | jq -r '.name // error(tostring)')" |
  jq -r '.response.model // error(tostring)')"

# The deployment, retried while no host is free.
deploy="$(jq -nc --arg model "${model}" --arg machine "${MACHINE}" --arg accelerator "${ACCELERATOR}" \
  --argjson count "${COUNT}" '{deployedModel: {model: $model, displayName: "nemotron-super-vl",
  dedicatedResources: {machineSpec: {machineType: $machine, acceleratorType: $accelerator, acceleratorCount: $count},
    minReplicaCount: 1, maxReplicaCount: 1}, enableContainerLogging: true}, trafficSplit: {"0": 100}}')"
for attempt in 1 2 3 4 5 6; do
  echo "Deploying to endpoint ${ENDPOINT_ID} on ${MACHINE} (attempt ${attempt}; 15-30 minutes)..."
  result="$(wait_for "$(call POST "/endpoints/${ENDPOINT_ID}:deployModel" "${deploy}" | jq -r '.name // error(tostring)')")"
  if ! jq -e '.error' <<< "${result}" > /dev/null; then
    dns="$(call GET "/endpoints/${ENDPOINT_ID}" | jq -r '.dedicatedEndpointDns')"
    echo "Serving. The app's OpenAI base URL: https://${dns}/v1/${endpoint}/invoke/v1"
    exit 0
  fi
  echo "The deploy failed: $(jq -r '.error.message' <<< "${result}")" >&2
  jq -e '.error.message | test("temporarily unavailable"; "i")' <<< "${result}" > /dev/null || exit 1
  sleep 120
done
exit 1
