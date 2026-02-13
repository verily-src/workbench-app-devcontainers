# test-app

Integration test-only custom Workbench application based on docker/getting-started.


## Configuration

- **Image**: docker/getting-started
- **Port**: 8001
- **User**: root
- **Home Directory**: /root

## Access

Once deployed in Workbench, access your terminal at the app URL (port 80).

For local testing:
1. Create Docker network: `docker network create app-network`
2. Run the app: `devcontainer up --workspace-folder .`
3. Access at: `http://localhost:8001`

## Customization

Edit the following files to customize your app:

- `.devcontainer.json` - Devcontainer configuration and features
- `docker-compose.yaml` - Docker Compose configuration (change the `command` to customize ttyd options)
- `devcontainer-template.json` - Template options and metadata

## Testing

To test this app template:

```bash
cd test
./test.sh test-app
```

## Usage

1. Create app and select custom
2. Specify https://github.com/verily-src/workbench-app-devcontainers.git and branch `master` and src/test-app

