#!/usr/bin/env bats
# Test suite for create-custom-app.sh script

setup() {
    # Get the directory of this test file
    DIR="$( cd "$( dirname "$BATS_TEST_FILENAME" )" >/dev/null 2>&1 && pwd )"
    REPO_ROOT="$(cd "${DIR}/../.." && pwd)"
    SCRIPT="${REPO_ROOT}/scripts/create-custom-app.sh"

    export REPO_ROOT
    export SCRIPT

    # Work from repo root so script can create files correctly
    cd "${REPO_ROOT}"
}

teardown() {
    # Clean up any test apps created in src/
    if [ -d "${REPO_ROOT}/src/test-app" ]; then
        rm -rf "${REPO_ROOT}/src/test-app"
    fi
    if [ -d "${REPO_ROOT}/src/my-jupyter" ]; then
        rm -rf "${REPO_ROOT}/src/my-jupyter"
    fi
}

@test "create-custom-app.sh: shows usage when no arguments provided" {
    run bash "${SCRIPT}"
    [ "$status" -eq 1 ]
    [[ "$output" == *"Usage:"* ]]
    [[ "$output" == *"app-name"* ]]
    [[ "$output" == *"docker-image"* ]]
    [[ "$output" == *"port"* ]]
}

@test "create-custom-app.sh: shows usage when insufficient arguments provided" {
    run bash "${SCRIPT}" my-app
    [ "$status" -eq 1 ]
    [[ "$output" == *"Usage:"* ]]
}

@test "create-custom-app.sh: creates app with minimal arguments (defaults to root user)" {
    run bash "${SCRIPT}" test-app python:3.11 8080
    [ "$status" -eq 0 ]
    [ -d "src/test-app" ]
    [ -f "src/test-app/.devcontainer.json" ]
    [ -f "src/test-app/docker-compose.yaml" ]
    [ -f "src/test-app/devcontainer-template.json" ]
    [ -f "src/test-app/README.md" ]
}

@test "create-custom-app.sh: creates app with custom username and home directory" {
    run bash "${SCRIPT}" my-jupyter jupyter/base-notebook 8888 jovyan /home/jovyan
    [ "$status" -eq 0 ]
    [ -d "src/my-jupyter" ]
}

@test "create-custom-app.sh: .devcontainer.json contains correct template variables" {
    bash "${SCRIPT}" test-app python:3.11 8080 testuser /home/testuser

    # Check that .devcontainer.json has the correct structure
    [ -f "src/test-app/.devcontainer.json" ]

    # Verify it contains template options
    grep -q '${templateOption:username}' "src/test-app/.devcontainer.json"
    grep -q '${templateOption:homeDir}' "src/test-app/.devcontainer.json"
    grep -q '${templateOption:cloud}' "src/test-app/.devcontainer.json"

    # Verify postCreateCommand exists
    grep -q 'postCreateCommand' "src/test-app/.devcontainer.json"

    # Verify postStartCommand exists
    grep -q 'postStartCommand' "src/test-app/.devcontainer.json"
}

@test "create-custom-app.sh: docker-compose.yaml contains correct image and port template" {
    bash "${SCRIPT}" test-app python:3.11 8080

    [ -f "src/test-app/docker-compose.yaml" ]

    # Check for template variables
    grep -q '${templateOption:image}' "src/test-app/docker-compose.yaml"
    grep -q '${templateOption:port}' "src/test-app/docker-compose.yaml"
    grep -q '${templateOption:homeDir}' "src/test-app/docker-compose.yaml"

    # Check for required workbench settings
    grep -q 'container_name: "application-server"' "src/test-app/docker-compose.yaml"
    grep -q 'app-network' "src/test-app/docker-compose.yaml"
}

@test "create-custom-app.sh: devcontainer-template.json has correct default values" {
    bash "${SCRIPT}" my-jupyter jupyter/base-notebook 8888 jovyan /home/jovyan

    [ -f "src/my-jupyter/devcontainer-template.json" ]

    # Check for the app id
    grep -q '"id": "my-jupyter"' "src/my-jupyter/devcontainer-template.json"

    # Check for image option with default value
    grep -q '"default": "jupyter/base-notebook"' "src/my-jupyter/devcontainer-template.json"

    # Check for port option
    grep -q '"default": "8888"' "src/my-jupyter/devcontainer-template.json"

    # Check for username option
    grep -q '"default": "jovyan"' "src/my-jupyter/devcontainer-template.json"

    # Check for homeDir option
    grep -q '"default": "/home/jovyan"' "src/my-jupyter/devcontainer-template.json"

    # Check for cloud option
    grep -q '"cloud"' "src/my-jupyter/devcontainer-template.json"
}

@test "create-custom-app.sh: README.md is generated with correct content" {
    bash "${SCRIPT}" test-app python:3.11 8080 testuser /home/testuser

    [ -f "src/test-app/README.md" ]

    # Check for app name in README
    grep -q 'test-app' "src/test-app/README.md"

    # Check for image reference
    grep -q 'python:3.11' "src/test-app/README.md"

    # Check for port reference
    grep -q '8080' "src/test-app/README.md"

    # Check for username reference
    grep -q 'testuser' "src/test-app/README.md"

    # Check for home directory reference
    grep -q '/home/testuser' "src/test-app/README.md"
}

@test "create-custom-app.sh: uses /root as home dir when user is root" {
    bash "${SCRIPT}" test-app python:3.11 8080 root

    [ -f "src/test-app/devcontainer-template.json" ]

    # Check that default homeDir is /root for root user
    grep -q '"default": "/root"' "src/test-app/devcontainer-template.json"
}

@test "create-custom-app.sh: uses /home/username as home dir when user is not root" {
    bash "${SCRIPT}" test-app python:3.11 8080 myuser

    [ -f "src/test-app/devcontainer-template.json" ]

    # Check that default homeDir is /home/myuser
    grep -q '"default": "/home/myuser"' "src/test-app/devcontainer-template.json"
}

@test "create-custom-app.sh: all generated files are valid JSON" {
    bash "${SCRIPT}" test-app python:3.11 8080

    # Validate .devcontainer.json
    run python3 -m json.tool "src/test-app/.devcontainer.json"
    [ "$status" -eq 0 ]

    # Validate devcontainer-template.json
    run python3 -m json.tool "src/test-app/devcontainer-template.json"
    [ "$status" -eq 0 ]
}

@test "create-custom-app.sh: output message confirms creation" {
    run bash "${SCRIPT}" test-app python:3.11 8080
    [ "$status" -eq 0 ]
    [[ "$output" == *"Custom app created successfully"* ]]
    [[ "$output" == *"src/test-app"* ]]
}
