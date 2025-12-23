# ubuntu-example

Custom Workbench application based on mcr.microsoft.com/devcontainers/base:ubuntu.

## Configuration

- **Image**: mcr.microsoft.com/devcontainers/base:ubuntu
- **Port**: 7681
- **User**: vscode
- **Home Directory**: /home/vscode

## Access

This app uses [ttyd](https://github.com/tsl0922/ttyd) to provide web-based terminal access.

Once deployed in Workbench, access your terminal at the app URL (port 7681).

For local testing:
1. Create Docker network: `docker network create app-network`
2. Run the app: `devcontainer up --workspace-folder .`
3. Access at: `http://localhost:7681`

## Development

This app was created as a reference implementation for building custom distro image apps:

1. **Initial scaffold** - Created using the `scripts/create-custom-app.sh` script:
   ```bash
   ./scripts/create-custom-app.sh ubuntu-example mcr.microsoft.com/devcontainers/base:ubuntu 7681 vscode /home/vscode
   ```

2. **Added ttyd feature** - Modified `.devcontainer.json` to include the ttyd devcontainer feature:
   ```json
   "ghcr.io/ar90n/devcontainer-features/ttyd:1": {}
   ```

3. **Configured user** - Added `user: vscode` in `docker-compose.yaml` (line 13) because the default user is root, but we want to run as the vscode user for better permissions handling.

4. **Added ttyd command** - Added the ttyd startup command in `docker-compose.yaml` (line 14):
   ```yaml
   command: ["ttyd", "-W", "-p", "7681", "bash"]
   ```
   This starts ttyd with web terminal access on port 7681. Since we're already running as the vscode user (via `user: vscode` on line 13), we can start bash directly.

## Customization

Edit the following files to customize your app:

- `.devcontainer.json` - Devcontainer configuration and features
- `docker-compose.yaml` - Docker Compose configuration (change the `command` to customize ttyd options)
- `devcontainer-template.json` - Template options and metadata

## Testing

To test this app template:

```bash
cd test
./test.sh ubuntu-example
```

## Usage

1. Fork the repository
2. Modify the configuration files as needed
3. In Workbench UI, create a custom app pointing to your forked repository
4. Select this app template (ubuntu-example)
