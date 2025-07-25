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

for FEATURE in $(echo "$STATE" | jq -r 'keys | .[]'); do
    echo "Processing feature: $FEATURE"
    INSTALLED="$FEATURE$(jq -r --arg feat "$FEATURE" '.[$feat].installed' <<< "$STATE")"
    LATEST="$(devcontainer features info manifest "$FEATURE" --output-format=json | jq -r '.canonicalId')"

    if [ "$INSTALLED" != "$LATEST" ]; then
        echo "Updating $FEATURE from $INSTALLED to $LATEST"

        pushd "$SRC_DIR"
        find . -name ".devcontainer.json" -print0 | xargs -0L1 sed -i "s|\"$INSTALLED\"|\"$LATEST\"|g"
        popd

        LATEST_TAG="@$(echo "$LATEST" | cut -d'@' -f2)"
        NEW_STATE="$(jq --arg feat "$FEATURE" --arg latest "$LATEST_TAG" '.[$feat].installed = $latest' "$STATE_FILE")"
        cat <<< "$NEW_STATE" > "$STATE_FILE"
    else
        echo "$FEATURE is already up to date."
    fi

    echo ""
done
