#!/bin/bash

set -o errexit
set -o nounset
set -o pipefail


SCRIPT_DIR="$(dirname "$(realpath "$0")")"
ROOT_DIR="$(realpath "$SCRIPT_DIR/..")"
STATE_FILE="$SCRIPT_DIR/state.json"
readonly STATE_FILE
STATE="$(cat "$STATE_FILE")"
readonly STATE

for IMAGE in $(echo "$STATE" | jq -r 'keys | .[]'); do
    echo "Processing image: $IMAGE"
    TAG="$(jq -r --arg feat "$IMAGE" '.[$feat].tag' <<< "$STATE")"
    FILTER="$(jq -r --arg feat "$IMAGE" '.[$feat].filter' <<< "$STATE")"
    INSTALLED_DIGEST="$(jq -r --arg feat "$IMAGE" '.[$feat].installed' <<< "$STATE")"
    LATEST_DIGEST="$(docker buildx imagetools inspect "$IMAGE:$TAG" | grep "Digest:" | awk '{print $2}')"

    INSTALLED="$IMAGE@$INSTALLED_DIGEST"
    LATEST="$IMAGE@$LATEST_DIGEST"

    if [ "$INSTALLED" != "$LATEST" ]; then
        echo "Updating $IMAGE from $INSTALLED to $LATEST"

        pushd "$ROOT_DIR"
        find . -regextype posix-extended -regex "\.\/$FILTER" -print0 | xargs -0L1 sed -i "s|$INSTALLED|$LATEST|g"
        popd

        NEW_STATE="$(jq --arg feat "$IMAGE" --arg latest "$LATEST_DIGEST" '.[$feat].installed = $latest' "$STATE_FILE")"
        cat <<< "$NEW_STATE" > "$STATE_FILE"
    else
        echo "$IMAGE is already up to date."
    fi

    echo ""
done
