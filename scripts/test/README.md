# Script Tests

This directory contains tests for scripts in the `scripts/` directory.

## Prerequisites

Install [bats-core](https://github.com/bats-core/bats-core) to run the tests:

```bash
# On macOS with Homebrew
brew install bats-core

# On Ubuntu/Debian
sudo apt-get install bats

# Or install from source
git clone https://github.com/bats-core/bats-core.git
cd bats-core
sudo ./install.sh /usr/local
```

## Running Tests

### Run all tests

```bash
cd scripts/test
bats .
```

### Run a specific test file

```bash
bats scripts/test/create-custom-app.bats
```

### Run a specific test case

```bash
bats scripts/test/create-custom-app.bats --filter "shows usage"
```

## Test Coverage

### create-custom-app.bats

Tests for the `create-custom-app.sh` script:

- ✅ Usage/help message validation
- ✅ Minimal arguments (defaults to root user)
- ✅ Custom username and home directory
- ✅ Generated `.devcontainer.json` structure
- ✅ Generated `docker-compose.yaml` structure
- ✅ Generated `devcontainer-template.json` with correct defaults
- ✅ Generated README.md content
- ✅ Home directory defaults (/root for root, /home/username otherwise)
- ✅ Valid JSON output
- ✅ Success message output

## Writing New Tests

Follow the bats format:

```bash
@test "description of test" {
    run ./your-script.sh args
    [ "$status" -eq 0 ]
    [[ "$output" == *"expected string"* ]]
}
```

Use the `setup()` and `teardown()` functions to manage test state:

```bash
setup() {
    # Runs before each test
    TEST_TEMP_DIR="$(mktemp -d)"
}

teardown() {
    # Runs after each test
    rm -rf "${TEST_TEMP_DIR}"
}
```
