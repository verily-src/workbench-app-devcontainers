#!/bin/bash
set -o errexit
set -o nounset
set -o pipefail

readonly VERSION="${1:?Usage: build-image.sh VERSION OUTPUT_DIR [SOURCE_COMMIT]}"
readonly OUTPUT_DIR="${2:?Usage: build-image.sh VERSION OUTPUT_DIR [SOURCE_COMMIT]}"
[[ "$VERSION" =~ ^[1-9][0-9]{0,17}$ ]] || { echo 'Invalid release version' >&2; exit 1; }
REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
SOURCE_COMMIT="${3:-$(git -C "$REPO_ROOT" rev-parse HEAD)}"
readonly REPO_ROOT SOURCE_COMMIT
[[ "$SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]] || { echo 'Use a full source commit' >&2; exit 1; }
SOURCE_EPOCH="$(git -C "$REPO_ROOT" show -s --format=%ct "$SOURCE_COMMIT")"
readonly SOURCE_EPOCH
[[ ! -e "$OUTPUT_DIR" ]] || { echo 'Output directory already exists' >&2; exit 1; }
mkdir -p "$OUTPUT_DIR"
OUTPUT_ABSOLUTE="$(cd "$OUTPUT_DIR" && pwd)"
TEMP_DIR="$(mktemp -d)"
readonly OUTPUT_ABSOLUTE TEMP_DIR
trap 'rm -rf "$TEMP_DIR"' EXIT
mkdir "$TEMP_DIR/source"
git -C "$REPO_ROOT" archive "$SOURCE_COMMIT" startupscript/butane startupscript/maintenance |
    tar -xf - -C "$TEMP_DIR/source"
# Git archives exclude untracked files and private configuration outside these public source paths.
docker build --platform linux/amd64 --iidfile "$TEMP_DIR/builder.id" \
    "$TEMP_DIR/source/startupscript/maintenance/build"
docker run --rm --platform linux/amd64 \
    --user "$(id -u):$(id -g)" \
    --mount "type=bind,source=$TEMP_DIR/source,target=/source,readonly" \
    --mount "type=bind,source=$OUTPUT_ABSOLUTE,target=/output" \
    "$(cat "$TEMP_DIR/builder.id")" "$VERSION" "$SOURCE_COMMIT" "$SOURCE_EPOCH"
