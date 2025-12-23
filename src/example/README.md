# example

Custom Workbench application based on quay.io/jupyter/base-notebook.

## Configuration

- **Image**: quay.io/jupyter/base-notebook
- **Port**: 8888
- **User**: jovyan
- **Home Directory**: /home/jovyan

## Access

This app uses [ttyd](https://github.com/tsl0922/ttyd) to provide web-based terminal access.

Once deployed in Workbench, access your terminal at the app URL (port 8888).

For local testing:
1. Create Docker network: `docker network create app-network`
2. Run the app: `devcontainer up --workspace-folder .`
3. Access at: `http://localhost:8888`

## Customization

Edit the following files to customize your app:

- `.devcontainer.json` - Devcontainer configuration and features
- `docker-compose.yaml` - Docker Compose configuration (change the `command` to customize ttyd options)
- `devcontainer-template.json` - Template options and metadata

## Testing

To test this app template:

```bash
cd test
./test.sh example
```

## Usage

1. Fork the repository
2. Modify the configuration files as needed
3. In Workbench UI, create a custom app pointing to your forked repository
4. Select this app template (example)
