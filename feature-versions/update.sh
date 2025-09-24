#!/bin/bash

set -o errexit
set -o nounset
set -o pipefail


SCRIPT_DIR="$(dirname "$(realpath "$0")")"
SRC_DIR="$(realpath "$SCRIPT_DIR/../src")"
STATE_FILE="$SCRIPT_DIR/state.json"
readonly STATE_FILE
STATE="$(cat "$STATE_FILE")"
readonly STATE

for IMAGE in $(echo "$STATE" | jq -r 'keys | .[]'); do
    echo "Processing image: $IMAGE"
    TAG="$(jq -r --arg feat "$IMAGE" '.[$feat].tag' <<< "$STATE")"
    FILTER="$(jq -r --arg feat "$IMAGE" '.[$feat].filter' <<< "$STATE")"
    INSTALLED="$IMAGE@$(jq -r --arg feat "$IMAGE" '.[$feat].installed' <<< "$STATE")"
    LATEST="$IMAGE@$(docker buildx imagetools inspect "$IMAGE:$TAG" | grep "Digest:" | awk '{print $2}')"

    if [ "$INSTALLED" != "$LATEST" ]; then
        echo "Updating $IMAGE from $INSTALLED to $LATEST"

        pushd "$SRC_DIR"
        find . -regex "$FILTER" -print0 | xargs -0L1 sed -i "s|$INSTALLED|$LATEST|g"
        popd

        LATEST_TAG="$(echo "$LATEST" | cut -d'@' -f2)"
        NEW_STATE="$(jq --arg feat "$IMAGE" --arg latest "$LATEST_TAG" '.[$feat].installed = $latest' "$STATE_FILE")"
        cat <<< "$NEW_STATE" > "$STATE_FILE"
    else
        echo "$IMAGE is already up to date."
    fi

    echo ""
done
