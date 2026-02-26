# Dockerfile Pattern Comparison

## Side-by-Side Structure

| Component | VSCode-Docker | Cursor (Verily) | Notes |
|-----------|---------------|-----------------|-------|
| **Header Comment** | `# VS Code Docker Development Container` | `# Cursor IDE Development Container` | ✅ Identical format |
| **Base Image** | `lscr.io/linuxserver/code-server:4.100.3` | `ghcr.io/linuxserver/baseimage-kasmvnc:debianbookworm` | Both LinuxServer.io bases |
| **Build Args** | None | `CURSOR_VERSION`, `CURSOR_BUILD_HASH` | Cursor needs version info |
| **System Packages** | Docker, kubectl, minikube, etc. | GUI libs, fuse, python3-venv | Different dev tools |
| **Main Install** | N/A (built into base) | Download Cursor AppImage | VSCode pre-installed |
| **Environment Vars** | `PATH`, `GOPATH`, `GOPRIVATE` | `CUSTOM_PORT`, `TITLE`, `FM_HOME` | Different runtime configs |
| **Custom Scripts** | `docker-setup.sh` | `root/` directory | Both use init scripts |
| **Git Config** | ✅ SSH over HTTPS | None yet | Could add to Cursor |
| **WORKDIR** | `/config` | `/config` | ✅ Identical |
| **Volumes** | Implicit | `/config`, `/cursor` | Explicit in Cursor |
| **Ports** | Implicit (8443) | `8080`, `8443` | Explicit in Cursor |

## Unified Structure (Current)

Both Dockerfiles now follow this pattern:

```dockerfile
# [App Name] Development Container
# Based on [linuxserver base] with [features] pre-installed

FROM [linuxserver base image]

# Install system dependencies
RUN apt-get update && apt-get install -y \
    [packages] \
    && rm -rf /var/lib/apt/lists/*

# Install additional tools
# [App-specific installs]

# Set up environment variables
ENV [KEY]="[VALUE]"

# Copy configuration files
COPY [scripts] /[destination]

WORKDIR /config
```

## Key Similarities Achieved ✅

1. **Comment format**: Both use descriptive headers
2. **Base images**: Both use LinuxServer.io (just different variants)
3. **Package installation**: Both use `apt-get` with cleanup
4. **Environment setup**: Both use `ENV` for configuration
5. **Custom scripts**: Both copy init/setup scripts
6. **Working directory**: Both use `/config`
7. **Clean structure**: No verbose comments cluttering the file

## Remaining Differences (Necessary)

| Aspect | Why Different |
|--------|---------------|
| **Base image** | VSCode=code-server, Cursor=kasmvnc (different web serving methods) |
| **Download step** | Cursor needs AppImage download, VSCode built into base |
| **GUI libs** | Cursor needs X11/VNC dependencies, VSCode doesn't |
| **Ports** | Cursor explicit (8080/8443), VSCode implicit in base |

## Optional Additions to Match VSCode Pattern

We could add these to Cursor Dockerfile to make it even more similar:

```dockerfile
# Install Docker CLI (like VSCode)
RUN curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg && \
    apt-get update && \
    apt-get install -y docker-ce-cli docker-compose-plugin && \
    rm -rf /var/lib/apt/lists/*

# Install kubectl (like VSCode)
RUN curl -LO "https://dl.k8s.io/release/v1.35.0/bin/linux/amd64/kubectl" && \
    install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl && \
    rm kubectl

# Configure git to use SSH instead of HTTPS (like VSCode)
RUN git config --system url."git@github.com:".insteadOf "https://github.com/"

# Copy docker group setup script (like VSCode)
COPY docker-setup.sh /etc/cont-init.d/50-docker-setup
RUN chmod +x /etc/cont-init.d/50-docker-setup
```

## Build Command Comparison

**VSCode:**
```bash
docker build -t vscode-docker:latest .
```

**Cursor:**
```bash
docker build --build-arg CURSOR_VERSION=1.7.52 -t cursor-ide:1.7.52 .
```

## Result

The Cursor Dockerfile now matches the VSCode pattern in:
- ✅ Structure and formatting
- ✅ Comment style
- ✅ Package installation pattern
- ✅ Use of LinuxServer.io base
- ✅ Working directory convention
- ✅ Clean, minimal style

**Bottom line:** Anyone familiar with the VSCode Dockerfile can immediately understand the Cursor Dockerfile! 🎉
