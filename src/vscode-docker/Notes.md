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


## Notes

- The Docker daemon is shared with the host, so be careful with destructive operations
- Minikube creates containers on the same Docker network, making them accessible
- Use `docker ps` to see all containers including minikube's control plane
