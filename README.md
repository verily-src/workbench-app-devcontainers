# workbench-app-devcontainer

Repo to store Verily Workbench-specific applications' devcontainer specifications. To develop your own custom app configuration, fork this repo.

## Repository Structure

- **`src/`**: Contains devcontainer app templates for various applications (Jupyter, R/RStudio, VSCode, etc.)
  - Each subdirectory represents a complete app template with `.devcontainer.json`, `docker-compose.yaml`, and startup scripts
  - Example: `src/example/` - A reference implementation showing the basic structure
- **`features/src/`**: Contains reusable devcontainer features that can be included in app templates
  - `workbench-tools/` - Bioinformatics tools (plink, plink2, regenie, bcftools, samtools, etc.)
  - `java/`, `jupyter/` - Language/framework-specific features
- **`startupscript/`**: VM provisioning scripts that run after container creation
- **`test/`**: Integration tests to verify app templates

## Workbench-specific application requirements

1. The custom app runs in a custom `app-network` bridge network and the app port is exposed on 0:0:0:0 (localhost)
2. The app's `container_name` must be `application-server`
3. In order to run `gcsfuse`, set `--cap-add SYS_ADMIN --device /dev/fuse --security-opt apparmor:unconfined` to the Docker container.

## What is a dev container?

https://containers.dev/

## Developing a New App

### Quick Start (Recommended)

The fastest way to create a custom app is using the `create-custom-app.sh` script:

```bash
./scripts/create-custom-app.sh <app-name> <docker-image> <port> [username] [home-dir]
```

**Example** (this created the current example app):
```bash
./scripts/create-custom-app.sh example quay.io/jupyter/base-notebook 8888 jovyan /home/jovyan
```

This script generates a complete app structure in `src/<app-name>/` with:
- `.devcontainer.json` - Devcontainer configuration
- `docker-compose.yaml` - Docker Compose setup with ttyd terminal
- `devcontainer-template.json` - Template metadata
- `README.md` - App-specific documentation

**Using a Dockerfile instead of a Docker image:**

If you don't have a pre-built Docker image and only have a Dockerfile:

1. Run the script with an empty image parameter:
   ```bash
   ./scripts/create-custom-app.sh my-app "" 8888 myuser /home/myuser
   ```

2. In the generated `src/my-app/docker-compose.yaml`, uncomment the `build` section:
   ```yaml
   build:
     context: .
   ```

3. Add your `Dockerfile` to `src/my-app/`

4. Remove the `image:` line from the `docker-compose.yaml`

**Arguments:**
- `app-name`: Name of your custom app (e.g., `my-jupyter-app`)
- `docker-image`: Docker image to use (e.g., `jupyter/base-notebook`, `rocker/rstudio`)
- `port`: Port your app exposes (e.g., `8888` for Jupyter, `8787` for RStudio)
- `username`: (Optional) User inside container (default: `root`)
- `home-dir`: (Optional) Home directory (default: `/root` or `/home/<username>`)

After running the script:
1. Review and customize the generated files in `src/<app-name>/`
2. Test your app: `cd test && ./test.sh <app-name>`
3. Commit and push to your forked repository
4. Create a custom app in Workbench UI using your repository

### Manual Setup (Advanced)

If you need more control, you can manually create a custom app:

1. **Fork this repository** to your own GitHub account or organization

2. **Create a new directory** under `src/` for your app (e.g., `src/my-custom-app/`)

3. **Add required files** to your app directory:
   - `.devcontainer.json` - The devcontainer specification that defines your app configuration
   - `docker-compose.yaml` - Docker Compose configuration (must follow Workbench requirements above)
   - `startup.sh` - App-specific startup script (if needed)

4. **Configure your `.devcontainer.json`**:

   At a bare minimum, you need to specify:

   - **Docker image**: The base container image your app runs on (e.g., `jupyter/base-notebook`, `rocker/rstudio`)
   - **Port**: The port your application exposes (e.g., `8888` for Jupyter, `8787` for RStudio). This port is exposed on the bridge network so Workbench can reach your app
   - **Default user**: The username that your application runs as inside the container (e.g., `jovyan` for Jupyter, `rstudio` for RStudio). If your app doesn't have a specific user, you can use `root`
   - **Home directory**: The default working directory for the user. In most cases, this is `/home/$(whoami)` (e.g., `/home/jovyan`, `/home/rstudio`). If the default user is `root`, the home directory is typically `/root`. Note: VSCode is a unique case where the home directory is `/config`

   **Important**: The home directory is where Workbench mounts cloud storage buckets and clones GitHub repositories. These will be located at:
   - Cloud storage buckets: `${homedir}/workspaces`
   - GitHub repositories: `${homedir}/repos`

   Additional configuration:
   - Set `postCreateCommand` to run `post-startup.sh` with parameters: `[username, home_dir, ${templateOption:cloud}]`
   - Include any needed features from `features/src/` (e.g., `workbench-tools`)
   - Use template option `${templateOption:cloud}` to specify the cloud provider (GCP or AWS)

5. **Test your app**:
   - Run the test script: `cd test && ./test.sh <your-app-name>`
   - Create a custom app in Workbench UI pointing to your forked repo and branch

6. **Reference the example app** at [src/example](https://github.com/verily-src/workbench-app-devcontainer/tree/main/src/example) to see a basic implementation

For detailed guidance, visit https://support.workbench.verily.com/docs/guides/cloud_apps/create_custom_apps/

## Running Linux Distros on Workbench

Linux distributions (Ubuntu, Debian, RHEL, etc.) typically don't have a web UI or exposed port by default. Since Workbench apps must be accessible via a browser, you need to add a web-based interface to your Linux distro container.

### Recommended Approaches

#### Option 1: JupyterLab (Recommended for Data Science & General Use)

JupyterLab provides a full-featured web interface with built-in terminal access, file browser, text editor, and notebook support.

**Examples**: See the NeMo and Parabricks apps (`src/nemo_jupyter/` and `src/workbench-jupyter-parabricks/`) which use JupyterLab to provide web access to specialized NVIDIA CUDA Linux environments.

To add JupyterLab to your Linux distro, use the `features/src/jupyter` feature with `installJupyterlab: true` and configure the container command:

```yaml
# docker-compose.yaml
services:
  app:
    container_name: "application-server"
    image: "ubuntu:22.04"
    command: ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--LabApp.token=''"]
    ports:
      - 8888:8888
    # ... rest of configuration
```

#### Option 2: ttyd (Lightweight Terminal-Only Access)

If you only need terminal access without the full JupyterLab interface, use [ttyd](https://github.com/tsl0922/ttyd) - a lightweight web-based terminal.

To add ttyd to your Linux distro, add the [ttyd feature](https://github.com/ar90n/devcontainer-features/tree/main/src/ttyd) to your `.devcontainer.json`:

```json
// .devcontainer.json
{
  "features": {
    "ghcr.io/ar90n/devcontainer-features/ttyd:1": {}
  }
}
```

Then configure the container command in your `docker-compose.yaml`:

```yaml
# docker-compose.yaml
services:
  app:
    container_name: "application-server"
    image: "mcr.microsoft.com/devcontainers/base:ubuntu"
    user: vscode
    command: ["ttyd", "-W", "-p", "7681", "bash"]
    ports:
      - 7681:7681
    cap_add:
      - SYS_ADMIN
    devices:
      - /dev/fuse
    security_opt:
      - apparmor:unconfined
    # ... rest of configuration
```

**Important**:
- The `-W` flag makes the terminal writable (interactive). Without it, the terminal will be read-only.

#### Option 3: VS Code Server (Full IDE Experience)

For a full IDE experience, use the [vscode-server feature](https://github.com/devcontainers-extra/features/tree/main/src/vscode-server) which provides VS Code in the browser with built-in terminal access.

## Debugging and Local Development

To run and debug your app locally:

1. **Install the devcontainer CLI**: Follow the installation instructions at https://code.visualstudio.com/docs/devcontainers/devcontainer-cli

2. **Create the Docker network**: Workbench apps require an external Docker network named `app-network`
   ```bash
   docker network create app-network
   ```

3. **Comment out Workbench-specific commands**: For local testing, you should comment out the `postCreateCommand` and `postStartCommand` in your `.devcontainer.json` since these scripts are designed to run in the Workbench environment and may fail locally:
   ```json
   {
     // "postCreateCommand": [
     //   "./startupscript/post-startup.sh",
     //   "username",
     //   "/home/username",
     //   "gcp"
     // ],
     // "postStartCommand": [
     //   "./startupscript/remount-on-restart.sh",
     //   "username",
     //   "/home/username",
     //   "gcp"
     // ]
   }
   ```

4. **Run your app**:
   ```bash
   cd src/<your-app-name>
   devcontainer up --workspace-folder .
   ```

5. **Access your app**: Once the container is running, you can access it at `localhost:<port>` where `<port>` is the port you specified in your configuration (e.g., `localhost:8888` for Jupyter, `localhost:7681` for ttyd)

## How to use

The `.devcontainer.json` file in the custom app folder (e.g. r-analysis/) contains the custom app configuration.
`post-startup.sh` contains workbench specific set up.

Please visit https://support.workbench.verily.com/docs/guides/cloud_apps/create_custom_apps/ for details about using a dev container specification to create a custom app in Workbench.
