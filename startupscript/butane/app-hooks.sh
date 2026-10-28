#!/bin/bash

# app-hooks.sh declares optional app lifecycle hooks with no-op defaults.
# Files in overrides.d redefine them for apps that opt in through
# customizations.workbench in devcontainer.json. Callers export
# WB_APP_CUSTOMIZATIONS (that JSON object) before calling hooks that run
# without a container; hooks that inspect a running container gate themselves.

# Runs before devcontainer build/up: <config_path> <config_json> <primary_container_id>
app_prepare() { :; }

# Whether the app starts from a local image, so build and feature prefetch can be skipped.
app_build_cached() { return 1; }

# Runs after a successful devcontainer up.
app_post_up() { :; }

# Asserts the app completed setup: [container]. A failure makes the calling service retry.
app_validate_setup() { :; }

for _hook_override in "$(dirname "${BASH_SOURCE[0]}")"/overrides.d/*.sh; do
    if [[ -e "${_hook_override}" ]]; then
        # shellcheck source=/dev/null
        source "${_hook_override}"
    fi
done
unset _hook_override
