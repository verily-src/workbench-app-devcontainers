#!/usr/bin/env bash
#
# portforward.sh — Start all kubectl port-forwards for a given environment.
#
# Usage:
#   ./scripts/portforward.sh [dev-stable]
#   ./scripts/portforward.sh dev-stable --enrollment-only
#   ./scripts/portforward.sh dev-stable --local-mode-only
#
# This script:
#   1. Switches kubectl context to the target environment's GKE cluster.
#   2. Starts all needed port-forwards in the background.
#   3. Waits for Ctrl-C and cleans up all port-forwards on exit.
#
# Modes:
#   (default)           All port-forwards: enrollment-be, ciam-be, workflow-be, grpc-web-envoy
#   --enrollment-only   Only enrollment port-forwards: enrollment-be, ciam-be, workflow-be
#   --local-mode-only   Only the local mode port-forward: grpc-web-envoy
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STANDALONE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

TARGET_ENV="${1:-dev-stable}"
MODE="all"  # all | enrollment-only | local-mode-only

shift || true
for arg in "$@"; do
  case "$arg" in
    --enrollment-only)  MODE="enrollment-only" ;;
    --local-mode-only)  MODE="local-mode-only" ;;
    --help|-h)
      echo "Usage: $0 [dev-stable] [--enrollment-only|--local-mode-only]"
      exit 0
      ;;
    *)
      echo "Unknown flag: $arg" >&2
      exit 1
      ;;
  esac
done

# ─── Load environment config ─────────────────────────────────────────────────
ENV_FILE="${STANDALONE_DIR}/envs/${TARGET_ENV}.env"
if [[ -f "${ENV_FILE}" ]]; then
  set -a
  source "${ENV_FILE}"
  set +a
else
  echo "⚠️  No env file found at ${ENV_FILE}. Using defaults." >&2
fi

GCP_PROJECT="${GCP_PROJECT:-prj-d-1v-ucd}"
GKE_CLUSTER="${GKE_CLUSTER:-gke-cluster}"
GKE_REGION="${GKE_REGION:-us-west1}"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  Port-Forward Helper — ${TARGET_ENV}"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  GCP Project:  ${GCP_PROJECT}"
echo "║  GKE Cluster:  ${GKE_CLUSTER}"
echo "║  GKE Region:   ${GKE_REGION}"
echo "║  Mode:         ${MODE}"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ─── Ensure kubectl context ──────────────────────────────────────────────────
EXPECTED_CONTEXT="gke_${GCP_PROJECT}_${GKE_REGION}_${GKE_CLUSTER}"
CURRENT_CONTEXT="$(kubectl config current-context 2>/dev/null || true)"

if [[ "${CURRENT_CONTEXT}" != "${EXPECTED_CONTEXT}" ]]; then
  echo "ℹ  Switching kubectl context to ${EXPECTED_CONTEXT} ..."
  gcloud container clusters get-credentials "${GKE_CLUSTER}" \
    --region "${GKE_REGION}" --project "${GCP_PROJECT}" 2>&1
  echo "✔  kubectl context set to ${EXPECTED_CONTEXT}"
else
  echo "✔  kubectl context already set to ${EXPECTED_CONTEXT}"
fi
echo ""

# ─── Port-forward PIDs (for cleanup) ─────────────────────────────────────────
PF_PIDS=()

cleanup() {
  echo ""
  echo "Shutting down port-forwards..."
  for pid in "${PF_PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null
  echo "✔  All port-forwards stopped."
}
trap cleanup EXIT INT TERM

start_pf() {
  local label="$1"
  shift
  echo "  Starting: ${label}"
  echo "    → kubectl $*"
  kubectl "$@" &
  PF_PIDS+=($!)
  sleep 1  # give it a moment to bind
}

# ─── Enrollment port-forwards ────────────────────────────────────────────────
if [[ "${MODE}" == "all" || "${MODE}" == "enrollment-only" ]]; then
  echo "Starting enrollment port-forwards..."

  # enrollment-be (port 10293)
  ENROLLMENT_POD="$(kubectl get pod --namespace enrollment \
    --selector="service=enrollment-be" \
    --output jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
  if [[ -n "${ENROLLMENT_POD}" ]]; then
    start_pf "enrollment-be → :10293" port-forward --namespace enrollment "${ENROLLMENT_POD}" 10293:3000
  else
    echo "  ⚠️  No enrollment-be pod found. Skipping."
  fi

  # ciam-be (port 10294)
  CIAM_POD="$(kubectl get pod --namespace ciam \
    --selector="service=ciam-be" \
    --output jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
  if [[ -n "${CIAM_POD}" ]]; then
    start_pf "ciam-be → :10294" port-forward --namespace ciam "${CIAM_POD}" 10294:3000
  else
    echo "  ⚠️  No ciam-be pod found. Skipping."
  fi

  # workflow-be (port 10295)
  start_pf "workflow-be → :10295" port-forward --namespace workflow service/workflow-be 10295:443

  echo ""
fi

# ─── Local mode port-forward ─────────────────────────────────────────────────
if [[ "${MODE}" == "all" || "${MODE}" == "local-mode-only" ]]; then
  echo "Starting local mode port-forward..."
  start_pf "grpc-web-envoy → :16443" port-forward --namespace grpcweb-envoy svc/grpc-web-envoy 16443:6443
  echo ""
fi

# ─── Summary ─────────────────────────────────────────────────────────────────
echo "╔══════════════════════════════════════════════════════╗"
echo "║  All port-forwards running. Press Ctrl-C to stop.   ║"
echo "╠══════════════════════════════════════════════════════╣"
if [[ "${MODE}" == "all" || "${MODE}" == "enrollment-only" ]]; then
  echo "║  enrollment-be:    localhost:10293                  ║"
  echo "║  ciam-be:          localhost:10294                  ║"
  echo "║  workflow-be:      localhost:10295                  ║"
fi
if [[ "${MODE}" == "all" || "${MODE}" == "local-mode-only" ]]; then
  echo "║  grpc-web-envoy:   localhost:16443                  ║"
fi
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# Keep running until Ctrl-C
wait
