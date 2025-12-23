# ttyd Feature Tests

This directory contains tests for the `ttyd` devcontainer feature.

## Test Structure

Following the [devcontainer feature testing guidelines](https://github.com/devcontainers/cli/blob/main/docs/features/test.md), this directory contains:

- **`scenarios.json`**: Defines test scenarios with different feature configurations
- **`test.sh`**: Test script that validates ttyd installation and functionality

## Test Scenarios

### ttyd-default
Tests ttyd installation with default options (latest version, default port 7681)

### ttyd-specific-version
Tests ttyd installation with a specific version (1.7.7)

### ttyd-custom-port
Tests ttyd installation with a custom port (8080)

## Running Tests Locally

### Prerequisites

Install the devcontainer CLI:
```bash
npm install -g @devcontainers/cli
```

### Run All Tests

From the `features` directory:
```bash
cd features
devcontainer features test --features ttyd --base-image mcr.microsoft.com/devcontainers/base:ubuntu .
```

### Run Specific Scenario

```bash
cd features
devcontainer features test \
  --features ttyd \
  --base-image mcr.microsoft.com/devcontainers/base:ubuntu \
  --filter ttyd-default \
  .
```

**Note**: Running tests locally on macOS with Colima may encounter Docker mount issues. The tests will run properly in Linux environments and in CI.

## What the Tests Verify

The test script (`test.sh`) verifies:

1. ✅ ttyd is installed and in PATH
2. ✅ ttyd version command works
3. ✅ ttyd version output matches expected format
4. ✅ ttyd help command works

## CI/CD Integration

These tests run automatically in GitHub Actions when:
- A pull request modifies `features/**`
- Changes are pushed to the master branch

See `.github/workflows/test-scripts.yaml` for the CI configuration.
