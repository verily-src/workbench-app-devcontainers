#!/bin/bash
# Runs the UI on a machine with no GPU and no sandbox (README.md, "Working on the UI"): the
# stand-in cohort designer, OpenCode at the version the sandbox pins on a Vertex AI model, and
# the UI's server. Ctrl-C stops all three.
#
# usage: dev/run-dev.sh            then open http://127.0.0.1:9002/
# Needs: uv, npx, and Google credentials that can call Vertex AI in GOOGLE_CLOUD_PROJECT.
set -o errexit -o nounset -o pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ui="$(dirname "${here}")"
repo="$(cd "${ui}/../../.." && pwd)"
state="${ASSISTANT_UI_STATE:-${TMPDIR:-/tmp}/assistant-ui-dev}"
version="$(sed -n 's/^ARG OPENCODE_VERSION=//p' "${repo}/features/src/opencode-harness/sandbox/Dockerfile")"
export GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
export VERTEX_LOCATION="${VERTEX_LOCATION:-global}"
export GOOGLE_CLOUD_LOCATION="${VERTEX_LOCATION}"

mkdir -p "${state}/work"
[[ -d "${state}/venv" ]] || uv venv -q --python 3.12 "${state}/venv"
uv pip install -q --python "${state}/venv/bin/python" -r "${ui}/requirements.txt" fastmcp==4.1.8

# The agent's instructions for the designer, as the app gives them.
"${state}/venv/bin/python" - "${repo}/features/src/cohort-designer/sandbox/cohort.yaml" > "${here}/instructions.dev.md" <<'PY'
import sys, yaml
print(yaml.safe_load(open(sys.argv[1]))["instructions"])
PY

trap 'kill 0' EXIT
"${state}/venv/bin/python" "${here}/stub_cohort_mcp.py" --port 9243 &
(cd "${state}/work" && ASSISTANT_UI_DEV="${here}" OPENCODE_CONFIG="${here}/opencode.dev.json" \
  OPENCODE_DISABLE_AUTOUPDATE=true npx --yes "opencode-ai@${version}" serve --port 4096) &
ASSISTANT_ACCESS=open OPENCODE_URL="http://127.0.0.1:4096" PORT=9002 "${state}/venv/bin/python" "${ui}/server.py"
