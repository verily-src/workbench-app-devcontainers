# VS Code with Docker (vscode-docker)

A VS Code (code-server) development environment with Docker daemon access and essential development tools pre-installed for Kubernetes and container-based development.

## Features

This development container includes:

- **VS Code (code-server 4.100.3)**: Browser-based VS Code IDE
- **Docker CLI**: Full Docker command-line interface with access to host Docker daemon
- **Kubernetes Tools**:
  - `kubectl`: Kubernetes command-line tool
  - `minikube`: Local Kubernetes cluster
  - `helm`: Kubernetes package manager
  - `skaffold`: Build and deployment automation
- **Development Tools**:
  - Go 1.23.5
  - Python 3 with `uv` package manager
  - Git with GitHub CLI (`gh`)
  - Build essentials (gcc, g++, make, etc.)
- **Utilities**: socat, curl, wget

## Docker Daemon Access

This container mounts the host's Docker daemon (`/var/run/docker.sock`), allowing you to:
- Build and run Docker containers from within VS Code
- Run Docker Compose
- Use minikube with the Docker driver
- Access the same Docker network as other containers

## Running minikube

To run minikube successfully in this environment:

```bash
# Start minikube with Docker driver and app network
minikube start --driver=docker --network=app-network --static-ip=172.18.0.10

# Enable gcp-auth addon for GCP authentication (use --force if in GCE)
minikube addons enable gcp-auth --force
```

## Pre-configured Environment

The container automatically configures:
- **Go environment**: `GOPATH=/config/go`, `GOPRIVATE=github.com/verily-src/*`
- **Git**: Configured to use SSH instead of HTTPS for GitHub repositories
- **Docker group**: User `abc` is added to the Docker group for daemon access

## Options

| Options Id | Description | Type | Default Value |
|-----|-----|-----|-----|
| cloud | VM cloud environment | string | gcp |
| login | Whether to log in to workbench CLI | string | false |

## Workspace

- **Default workspace**: `/config`
- **Mounted repository**: `/workspace`

## Example: Running modelhub tests

```bash
# Clone the repository
cd /config
git clone git@github.com:verily-src/verily1.git
cd verily1

# Set up Python environment
uv sync

# Set up GCP authentication
gcloud auth application-default login

# Install required tools (already pre-installed in this image)
# - Go, kubectl, minikube, skaffold, helm

# Create hermetic cortex stack
export PATH=/usr/local/go/bin:$PATH
export GOPRIVATE=github.com/verily-src/*
go run ./cortex/tools/cortex-cli stack create --zone operational

# Start minikube
minikube start --driver=docker --network=app-network --static-ip=172.18.0.10

# Enable gcp-auth addon
minikube addons enable gcp-auth --force

# Set up port forwarding (install socat if needed)
nohup socat TCP-LISTEN:32773,fork,reuseaddr TCP:172.18.0.10:22 > /tmp/socat-ssh.log 2>&1 &
# ... add other port forwards as needed

# Run skaffold
cd /config/verily1
skaffold run -p dev-hermetic -f mlplatform/modelhub/skaffold.yaml

# Set up service port forwarding
kubectl port-forward service/cortex-fhir-proxy-operational 8766:443 &
kubectl port-forward service/mlplatform-modelhub 8765:443 &

# Run BDD tests
source .venv/bin/activate
behave mlplatform/modelhub/behave
```

## Notes

- The Docker daemon is shared with the host, so be careful with destructive operations
- Minikube creates containers on the same Docker network, making them accessible
- Use `docker ps` to see all containers including minikube's control plane
- The gcp-auth addon automatically mounts GCP credentials into Kubernetes pods

---

_Note: This file was auto-generated from the [devcontainer-template.json](https://github.com/verily-src/workbench-app-devcontainers/blob/main/src/vscode-docker/devcontainer-template.json). Add additional notes to a `NOTES.md`._
