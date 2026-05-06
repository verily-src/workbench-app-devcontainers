# fast-omop

Custom Workbench application based on FastOMOP framework. Within a workspace containing OMOP data, the application can correctly answer questions about that data without requiring the user to supply additional context or prompt engineering.


## Configuration

- **Image**: 
- **Port**: 3000
- **User**: root
- **Home Directory**: /root

## Access

Once deployed in Workbench, access your terminal at the app URL (port 3000).

For local testing:
1. Create Docker network: `docker network create app-network`
2. Run the app: `devcontainer up --workspace-folder .`
3. Access at: `http://localhost:5000`

## Customization

Edit the following files to customize your app:

- `.devcontainer.json` - Devcontainer configuration and features
- `docker-compose.yaml` - Docker Compose configuration (change the `command` to customize ttyd options)
- `devcontainer-template.json` - Template options and metadata

## Testing

To test this app template:

```bash
cd test
./test.sh fast-omop
```

## Usage

1. Fork the repository
2. Modify the configuration files as needed
3. In Workbench UI, create a custom app pointing to your forked repository
4. Select this app template (fast-omop)
