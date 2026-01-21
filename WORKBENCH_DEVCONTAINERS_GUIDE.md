# Workbench Devcontainers: Complete Guide with Examples

## What are Dev Containers?

**Dev Containers** (Development Containers) are a standardized way to define development environments using Docker containers. They allow you to:
- Package your entire development environment (tools, libraries, dependencies)
- Share consistent environments across teams
- Run applications in isolated, reproducible containers
- Use any Docker image or build custom environments

In **Verily Workbench**, devcontainers enable you to create **custom cloud apps** that run in isolated containers on GCP VMs.

---

## How Dev Containers Work in Workbench

### Architecture

```
┌─────────────────────────────────────┐
│  Workbench VM (GCE Instance)       │
│                                     │
│  ┌───────────────────────────────┐ │
│  │  Docker Container             │ │
│  │  (Your Custom App)            │ │
│  │                                │ │
│  │  - Application Server          │ │
│  │  - Port: 8888 (or custom)     │ │
│  │  - Network: app-network        │ │
│  └───────────────────────────────┘ │
│                                     │
│  ┌───────────────────────────────┐ │
│  │  app-network (bridge)         │ │
│  │  (External Docker network)     │ │
│  └───────────────────────────────┘ │
└─────────────────────────────────────┘
```

### Key Components

1. **`.devcontainer.json`** - Main configuration file
   - Defines Docker image, features, ports, commands
   - Specifies post-creation and startup scripts

2. **`docker-compose.yaml`** - Docker Compose configuration
   - Defines the container service
   - Sets up volumes, networks, ports
   - Configures security settings

3. **`devcontainer-template.json`** - Template metadata
   - Defines template options (cloud provider, login, etc.)
   - Used by Workbench UI to show template options

---

## Workbench-Specific Requirements

### 1. Container Name
**MUST** be `application-server`:
```yaml
container_name: "application-server"
```

### 2. Docker Network
**MUST** use external network `app-network`:
```yaml
networks:
  - app-network

networks:
  app-network:
    external: true
```

### 3. Port Exposure
Port must be exposed on `0.0.0.0` (localhost):
```yaml
ports:
  - "8888:8888"
```

### 4. File System Access (for GCS mounting)
If you need to mount workspace buckets, add:
```yaml
cap_add:
  - SYS_ADMIN
devices:
  - /dev/fuse
security_opt:
  - apparmor:unconfined
```

### 5. Startup Scripts
Include Workbench startup scripts:
```json
{
  "postCreateCommand": [
    "./startupscript/post-startup.sh",
    "username",
    "/home/username",
    "${templateOption:cloud}",
    "${templateOption:login}"
  ],
  "postStartCommand": [
    "./startupscript/remount-on-restart.sh",
    "username",
    "/home/username",
    "${templateOption:cloud}",
    "${templateOption:login}"
  ]
}
```

---

## Example Custom Apps

### Example 1: JupyterLab with Data Profiling (Your App!)

**Purpose**: Analyze data from GCS buckets and generate comprehensive profiling reports

**Location**: `src/lab-results-analyzer-dev/`

**Key Files**:
- **Image**: `jupyter/scipy-notebook`
- **Port**: `8888`
- **User**: `jovyan`
- **Features**: 
  - JupyterLab web interface
  - Python data science stack (pandas, numpy, matplotlib, seaborn)
  - Auto-installs `ydata-profiling` and `google-cloud-storage`

**docker-compose.yaml**:
```yaml
services:
  app:
    container_name: "application-server"
    image: "jupyter/scipy-notebook"
    user: "jovyan"
    restart: always
    volumes:
      - .:/workspace:cached
      - work:/home/jovyan/work
    ports:
      - 8888:8888
    networks:
      - app-network
    cap_add:
      - SYS_ADMIN
    devices:
      - /dev/fuse
    security_opt:
      - apparmor:unconfined
    command: "start-notebook.sh --ip=0.0.0.0 --port=8888 --no-browser --NotebookApp.token='' --NotebookApp.password='' --NotebookApp.allow_origin='*'"
```

**Use Case**: 
- Load CSV files from GCS data collections
- Generate automatic data profiling reports
- Analyze any dataset structure without hardcoding columns

---

### Example 2: R Analysis Environment (RStudio)

**Purpose**: Run R statistical analysis with RStudio interface

**Location**: `src/r-analysis/`

**Key Files**:
- **Image**: `ghcr.io/rocker-org/devcontainer/tidyverse:4.4`
- **Port**: `8787` (RStudio default)
- **User**: `rstudio`
- **Features**: 
  - RStudio Server web interface
  - Tidyverse packages pre-installed
  - Full R statistical computing environment

**docker-compose.yaml**:
```yaml
services:
  app:
    container_name: "application-server"
    image: "ghcr.io/rocker-org/devcontainer/tidyverse:4.4"
    restart: always
    volumes:
      - .:/workspace:cached
      - work:/home/rstudio:cached
    ports:
      - "8787:8787"
    environment:
      "DISABLE_AUTH": "true"
    networks:
      - app-network
    cap_add:
      - SYS_ADMIN
    devices:
      - /dev/fuse
    security_opt:
      - apparmor:unconfined
```

**Use Case**:
- Statistical analysis with R
- Data visualization with ggplot2
- R Shiny app development
- Bioinformatics analysis with R packages

---

### Example 3: VS Code Server

**Purpose**: Full IDE experience in the browser

**Location**: `src/vscode/`

**Key Files**:
- **Image**: Custom VS Code Server image
- **Port**: `8080`
- **User**: `vscode`
- **Features**:
  - Full VS Code interface in browser
  - Terminal access
  - Extension support
  - Git integration

**Use Case**:
- Code development and editing
- Full IDE features without local installation
- Multi-language support (Python, JavaScript, Go, etc.)

---

### Example 4: Ubuntu with Web Terminal (ttyd)

**Purpose**: Lightweight Linux environment with web-based terminal

**Location**: `src/ubuntu-example/`

**Key Files**:
- **Image**: `mcr.microsoft.com/devcontainers/base:ubuntu`
- **Port**: `7681`
- **User**: `vscode`
- **Features**:
  - ttyd web terminal
  - Full Ubuntu environment
  - Minimal overhead

**docker-compose.yaml**:
```yaml
services:
  app:
    container_name: "application-server"
    image: "mcr.microsoft.com/devcontainers/base:ubuntu"
    user: vscode
    restart: always
    volumes:
      - .:/workspace:cached
    ports:
      - "7681:7681"
    networks:
      - app-network
    cap_add:
      - SYS_ADMIN
    devices:
      - /dev/fuse
    security_opt:
      - apparmor:unconfined
    command: ["ttyd", "-W", "-p", "7681", "bash"]
```

**Use Case**:
- Command-line tools and scripts
- System administration tasks
- Lightweight development environment
- Custom tool installation

---

### Example 5: NVIDIA NeMo Jupyter (GPU-Enabled)

**Purpose**: Deep learning and AI model training with GPU support

**Location**: `src/nemo_jupyter/`

**Key Files**:
- **Image**: Custom Dockerfile with NVIDIA CUDA
- **Port**: `8888`
- **User**: `jupyter`
- **Features**:
  - NVIDIA GPU support
  - CUDA toolkit
  - PyTorch, TensorFlow
  - JupyterLab interface

**docker-compose.yaml**:
```yaml
services:
  app:
    container_name: "application-server"
    build:
      context: .
      target: nemo
    user: jupyter
    restart: always
    volumes:
      - .:/workspace:cached
    ports:
      - "8888:8888"
    networks:
      - app-network
    cap_add:
      - SYS_ADMIN
    devices:
      - /dev/fuse
    security_opt:
      - apparmor:unconfined
    command: jupyter lab --ip=0.0.0.0 --port=8888 --no-browser --LabApp.token=''
```

**Use Case**:
- Deep learning model training
- Large language model fine-tuning
- GPU-accelerated computations
- AI/ML research and development

---

### Example 6: Parabricks Jupyter (Bioinformatics)

**Purpose**: Genomics analysis with NVIDIA Parabricks tools

**Location**: `src/workbench-jupyter-parabricks/`

**Key Files**:
- **Image**: Custom Dockerfile with Parabricks
- **Port**: `8888`
- **Features**:
  - NVIDIA Parabricks genomics tools
  - GPU-accelerated DNA/RNA analysis
  - JupyterLab for analysis notebooks

**Use Case**:
- DNA sequencing analysis
- Variant calling
- Genomics pipeline execution
- Bioinformatics research

---

## Creating Your Own Custom App

### Quick Start Method

Use the provided script:

```bash
./scripts/create-custom-app.sh <app-name> <docker-image> <port> [username] [home-dir]
```

**Example**:
```bash
./scripts/create-custom-app.sh my-app jupyter/base-notebook 8888 jovyan /home/jovyan
```

This generates:
- `.devcontainer.json`
- `docker-compose.yaml`
- `devcontainer-template.json`
- `README.md`

### Manual Method

1. **Create directory**: `src/my-custom-app/`

2. **Create `.devcontainer.json`**:
```json
{
  "name": "my-custom-app",
  "dockerComposeFile": "docker-compose.yaml",
  "service": "app",
  "shutdownAction": "none",
  "workspaceFolder": "/workspace",
  "postCreateCommand": [
    "./startupscript/post-startup.sh",
    "jovyan",
    "/home/jovyan",
    "${templateOption:cloud}",
    "${templateOption:login}"
  ],
  "features": {
    "ghcr.io/devcontainers/features/java:1": {
      "version": "17"
    }
  },
  "remoteUser": "root"
}
```

3. **Create `docker-compose.yaml`**:
```yaml
services:
  app:
    container_name: "application-server"
    image: "your-docker-image:tag"
    user: "your-user"
    restart: always
    volumes:
      - .:/workspace:cached
      - work:/home/your-user/work
    ports:
      - "8888:8888"
    networks:
      - app-network
    cap_add:
      - SYS_ADMIN
    devices:
      - /dev/fuse
    security_opt:
      - apparmor:unconfined

volumes:
  work:

networks:
  app-network:
    external: true
```

4. **Create `devcontainer-template.json`**:
```json
{
  "id": "my-custom-app",
  "version": "1.0.0",
  "name": "my-custom-app",
  "description": "My custom application",
  "options": {
    "cloud": {
      "type": "string",
      "enum": ["gcp", "aws"],
      "default": "gcp"
    }
  }
}
```

---

## Dev Container Features

Dev Container Features are reusable components you can add to any container:

### Common Features

1. **Java**:
```json
"features": {
  "ghcr.io/devcontainers/features/java:1": {
    "version": "17"
  }
}
```

2. **Google Cloud CLI**:
```json
"features": {
  "ghcr.io/dhoeric/features/google-cloud-cli:1": {}
}
```

3. **AWS CLI**:
```json
"features": {
  "ghcr.io/devcontainers/features/aws-cli:1": {}
}
```

4. **ttyd (Web Terminal)**:
```json
"features": {
  "ghcr.io/ar90n/devcontainer-features/ttyd:1": {}
}
```

5. **Jupyter**:
```json
"features": {
  "ghcr.io/devcontainers/features/jupyter:1": {
    "installJupyterlab": true
  }
}
```

6. **R Packages**:
```json
"features": {
  "ghcr.io/rocker-org/devcontainer-features/r-packages:1": {
    "packages": "shiny,shinydashboard",
    "installSystemRequirements": true
  }
}
```

---

## Publishing Your Custom App

1. **Fork the repository**: `https://github.com/verily-src/workbench-app-devcontainers`

2. **Add your app** to `src/your-app-name/`

3. **Commit and push** to your fork

4. **In Workbench UI**:
   - Go to Apps → Create App → Custom
   - Enter your repository URL
   - Specify the template path: `src/your-app-name`
   - Configure options (cloud provider, etc.)
   - Deploy!

---

## Best Practices

1. **Use appropriate base images**: Choose images that match your use case
2. **Set correct user permissions**: Use non-root users when possible
3. **Include startup scripts**: Use Workbench's post-startup scripts
4. **Document your app**: Add clear README.md files
5. **Test locally**: Use `devcontainer up` to test before deploying
6. **Version your images**: Use specific tags, not `latest`
7. **Minimize image size**: Use multi-stage builds when possible
8. **Handle credentials securely**: Use Workbench's credential management

---

## Resources

- **Main Repository**: https://github.com/verily-src/workbench-app-devcontainers
- **Dev Container Spec**: https://containers.dev/
- **Workbench Docs**: https://support.workbench.verily.com/docs/guides/cloud_apps/create_custom_apps/
- **Dev Container Features**: https://containers.dev/features

---

## Summary

Workbench devcontainers provide a powerful way to:
- ✅ Create custom cloud applications
- ✅ Share consistent environments
- ✅ Use any Docker image or build custom ones
- ✅ Access GCS buckets and workspace resources
- ✅ Run web-based applications (Jupyter, RStudio, VS Code, etc.)
- ✅ Support GPU-enabled workloads
- ✅ Integrate with Workbench's infrastructure

The key is following Workbench's specific requirements (container name, network, ports) while leveraging the flexibility of Docker and devcontainer features!

