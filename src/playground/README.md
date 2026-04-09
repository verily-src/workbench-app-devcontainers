# example

Web-based manager for creating and deploying custom devcontainer applications

## Access

Once deployed in Workbench, access the web interface at the app URL (port 8080).

For local testing:
1. Create Docker network: `docker network create app-network`
2. Run the app: `devcontainer up --workspace-folder .`
3. Access at: `http://localhost:8080`

## Customization

Edit the following files to customize your app:

- `.devcontainer.json` - Devcontainer configuration and features
- `docker-compose.yaml` - Docker Compose configuration (change the `command` to customize ttyd options)
- `devcontainer-template.json` - Template options and metadata

## Usage

1. Fork the repository
2. Modify the configuration files as needed
3. In Workbench UI, create a custom app pointing to your forked repository
4. Select this app template (example)
