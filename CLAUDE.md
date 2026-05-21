# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## IMPORTANT: This is a PUBLIC repository

**Never write individual names, customer/partner identities, or company names (other than Verily) into any file in this repo.** This includes code comments, commit messages, documentation, plan files, and READMEs. Use generic references like "the partner," "the workflow team," or "the customer" instead. Violations expose sensitive business relationships in a public GitHub repo.

## Project Overview

This repository contains Verily Workbench-specific application devcontainer specifications for creating custom apps. Each application runs in a custom `app-network` bridge network with the container name `application-server` and port exposed on localhost.

## Architecture

### Directory Structure
- `src/` - Application configurations (21 apps including jupyter variants, r-analysis, vscode, nemo, parabricks, etc.)
- `features/src/` - Custom devcontainer features (gemini-cli, java, jupyter, postgres-client, workbench-tools)
- `startupscript/` - Platform-specific startup scripts for AWS/GCP/dataproc/vertex-ai/butane
- `scripts/` - Utility scripts including `create-custom-app.sh`
- `test/` - Testing infrastructure and utilities
- `feature-versions/` - Feature version management and update automation

### Application Configuration Pattern
Each app in `src/` follows this structure:
- `.devcontainer.json` - Development devcontainer configuration
- `devcontainer-template.json` - Production template with `${templateOption:...}` placeholders
- `docker-compose.yaml` - Container orchestration (must use `container_name: application-server`)
- Optional: `post-startup.sh` for custom initialization

### Critical Requirements for Custom Apps
1. **Container name**: Must use `container_name: application-server`
2. **Network**: Must use external `app-network` bridge network
3. **Port binding**: Expose on `0.0.0.0` (localhost)
4. **gcsfuse support**: Requires `--cap-add SYS_ADMIN --device /dev/fuse --security-opt apparmor:unconfined`
5. **Service name**: Must be `app` in docker-compose.yaml
6. **Shutdown**: Use `shutdownAction: none` in .devcontainer.json
7. **Workspace**: Use `workspaceFolder: /workspace`

### Template Options System
Templates use `${templateOption:name}` placeholders that are replaced during deployment:
- `${templateOption:cloud}` - Platform (gcp/aws)
- `${templateOption:login}` - Authentication flag (true/false)

Options are defined in `devcontainer-template.json` with default values used during testing.

### Startup Script Architecture
Two lifecycle hooks in `.devcontainer.json`:
- `postCreateCommand`: Runs `./startupscript/post-startup.sh <user> <home> <cloud> <login>` on initial creation
- `postStartCommand`: Runs `./startupscript/remount-on-restart.sh <user> <home> <cloud> <login>` on container restart

Where:
- `<user>`: Application user (jovyan, jupyter, rstudio, abc, vscode, etc.)
- `<home>`: User home directory path
- `<cloud>`: Platform (gcp/aws)
- `<login>`: Authentication flag (true/false)

The startup scripts are cloud-specific and source scripts from `startupscript/${CLOUD}/` subdirectories.

## Common Development Commands

### Creating a New Custom App

```bash
# Use the create-custom-app.sh script
./scripts/create-custom-app.sh <app-name> <docker-image> <port> [username] [home-dir]

# Example:
./scripts/create-custom-app.sh my-jupyter jupyter/base-notebook 8888 jovyan /home/jovyan
```

### Testing Applications

```bash
# Run smoke tests for a specific app
./test/test.sh <app-name>

# Run tests via GitHub Actions smoke test workflow
./.github/actions/smoke-test/test.sh <app-name>

# The smoke test workflow:
# 1. Copies startup scripts into src/ directories
# 2. Replaces template options with defaults from devcontainer-template.json
# 3. Copies features/ into .devcontainer/features/
# 4. Creates app-network bridge network
# 5. Builds container with devcontainer CLI
# 6. Runs test/test.sh inside container
```

### Building and Testing Locally

```bash
# Create the required network first
docker network create -d bridge app-network

# Build using devcontainer CLI
devcontainer up --workspace-folder ./src/<app-name>

# Execute commands in container
devcontainer exec --workspace-folder ./src/<app-name> <command>
```

### Linting

```bash
# Shell scripts are linted with shellcheck
# Disable checks SC1090 and SC1091 for dynamic sourcing
shellcheck -e SC1090 -e SC1091 startupscript/**/*.sh
```

Configure `~/.shellcheckrc`:
```
disable=SC1090,SC1091
```

### Feature Version Updates

```bash
# Update devcontainer feature versions (automated weekly)
# Run manually via workflow_dispatch or automatic Monday 7AM UTC
./feature-versions/update.sh

# Updates are tracked in feature-versions/state.json
# PR is auto-created with updated feature references in src/ configs
```

## Key Configuration Patterns

### Devcontainer Structure
All apps follow this pattern in `.devcontainer.json`:
```json
{
  "dockerComposeFile": "docker-compose.yaml",
  "service": "app",
  "shutdownAction": "none",
  "workspaceFolder": "/workspace",
  "postCreateCommand": ["./startupscript/post-startup.sh", "<user>", "<home>", "${templateOption:cloud}", "${templateOption:login}"],
  "postStartCommand": ["./startupscript/remount-on-restart.sh", "<user>", "<home>", "${templateOption:cloud}", "${templateOption:login}"],
  "features": { /* ... */ },
  "remoteUser": "root"
}
```

### Docker Compose Structure
All apps follow this pattern in `docker-compose.yaml`:
```yaml
services:
  app:
    container_name: "application-server"
    image: "<base-image>"
    restart: always
    volumes:
      - .:/workspace:cached
    ports:
      - "<port>:<port>"
    networks:
      - app-network
    cap_add:
      - SYS_ADMIN
    devices:
      - /dev/fuse
    security_opt:
      - apparmor:unconfined
networks:
  app-network:
    external: true
```

### Features Integration
Common features across apps:
- Java (version 17) - Uses SHA-pinned feature reference
- AWS CLI - Uses SHA-pinned feature reference
- Google Cloud CLI - Uses SHA-pinned feature reference
- Custom workbench-tools feature (for bioinformatics apps)
- Custom postgres-client feature (PostgreSQL client tools: psql, pg_dump, pg_restore)
- Custom gemini-cli feature (Google Gemini CLI)

Features use SHA256 pinning for reproducibility. Update via `feature-versions/update.sh`.

### Workbench-Tools Feature
Apps with bioinformatics tools (`custom-workbench-jupyter-template`, `jupyter-aou`, `r-analysis`, `vscode`, `nemo_jupyter`, etc.):
- Installs plink, plink2, regenie, bedtools, bcftools, bgenix, samtools, vcftools, VEP
- Workflow tools: cromwell, nextflow, dsub
- Python packages: google-cloud-storage, ipykernel, ipywidgets, matplotlib, numpy, pandas, scikit-learn, scipy, seaborn, plotly, tqdm, openai
- Only supports Debian-based systems on x86_64

### Postgres-Client Feature
Apps needing database connectivity (`r-analysis`, `vscode`, `jupyter-aou`, etc.):
- Installs psql, pg_dump, pg_restore from official PostgreSQL repository
- Configurable version (default: 16)

## Testing Infrastructure

### Test Validation
`test/test.sh` validates (receives template_id, test_user, has_workbench_tools, has_postgres_client as args):
- gcsfuse availability
- wb CLI tool installation
- fuse.conf user_allow_other configuration

### Additional Validation for Workbench-Tools Apps
When `HAS_WORKBENCH_TOOLS=true`:
- python3, pip3, python venv
- cromwell (except nemo variants), nextflow, dsub
- bcftools, bedtools, bgenix, plink, plink2, samtools, bgzip, tabix, vcftools (including fill-an-ac, fill-fs)
- regenie, vep (including filter_vep, variant_recoder, haplo)
- Python packages: google-cloud-storage, ipykernel, ipywidgets, jupyter, openai, matplotlib, numpy, plotly, pandas, seaborn, scikit-learn, scipy, tqdm

### Additional Validation for Postgres-Client Apps
When `HAS_POSTGRES_CLIENT=true`:
- psql, pg_dump, pg_restore

### Test Utilities
`test/test-utils/test-utils.sh` provides:
- `check_user "<user>" "<label>" <command>` - Run test as specified user and track results
- `reportResults` - Print summary and exit with status
- `echoStderr` - Echo to stderr

## Application-Specific Notes

### User Accounts by App (from test-pr.yaml)
- example, jupyter-template: `jovyan`/`jupyter`
- custom-workbench-jupyter-template, jupyter-aou, nemo_jupyter, nemo_jupyter_aou, workbench-jupyter-parabricks, workbench-jupyter-parabricks-aou: `jupyter`
- r-analysis, r-analysis-aou: `rstudio`
- vscode, vscode-docker: `abc`
- ubuntu-example: `vscode`

### Startup Script Debugging
Check `/home/<user>/.workbench/post-startup-output.txt` for startup script execution logs and errors.

### Butane Startup Scripts
The `startupscript/butane/` directory contains numbered scripts for Fedora CoreOS/Butane deployments:
- `010-install-node.sh` - Node.js installation
- `020-create-docker-network.sh` - Docker network setup
- `030-configure-wb.sh` - Workbench CLI configuration
- `035-register-key.sh` - App key registration
- `040-git-clone-devcontainer.sh` - Clone devcontainer repo
- `050-parse-devcontainer.sh` - Parse devcontainer configuration
- `060-start-proxy-agent.sh` - Start proxy agent

## Shell Script Best Practices

Variables and functions should be marked `readonly`:
```bash
# Simple assignment
readonly FOO="foo"

# Command output (split to avoid masking errors per SC2155)
FOO="$(command)"
readonly FOO

# Functions
function my_function {
    # ...
}
readonly -f my_function
```

## CI/CD Workflows

### PR Testing (test-pr.yaml)
- Lints all shell scripts with shellcheck
- Detects changed apps using path filters (including workbench-tools and postgres-client feature changes)
- Runs smoke tests only for changed apps
- Maximizes disk space for large builds (jupyter-aou, nemo_jupyter, parabricks variants)
- Uses `continue-on-error: true` for test jobs

### Release (release.yaml)
- Manual workflow_dispatch on master branch
- Publishes templates using devcontainers/action
- Generates documentation
- Creates PR for documentation updates

### Feature Updates (update-features.yaml)
- Automated weekly Monday 7AM UTC
- Updates devcontainer feature SHA references
- Creates PR with updated versions

### Script Testing (test-scripts.yaml)
- Validates utility scripts in `scripts/` directory
