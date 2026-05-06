# Cirrocumulus

Custom Workbench application for visualizing single-cell data using Cirrocumulus - an interactive visualization tool for exploring single-cell data.

## Configuration

- **Base Image**: mcr.microsoft.com/vscode/devcontainers/python:3.12-bookworm
- **Port**: 3000
- **User**: root
- **Home Directory**: /root
- **Database**: MongoDB (mongo:latest)

## Access

Once deployed in Workbench, access the Cirrocumulus UI at the app URL (port 3000).

## Automatic Dataset Discovery

The app automatically discovers all single-cell datasets in your Workbench workspace and creates pre-configured datasets in Cirrocumulus.

### How It Works

1. **Auto-Discovery**: Every 5 seconds, the app scans `/root/workspace` for single-cell data files:
   - `.zarr` folders (Zarr format datasets)
   - `.h5ad` files (AnnData/h5ad format datasets)
2. **Dataset Creation**: For each discovered file, the app automatically creates a dataset in Cirrocumulus if it doesn't already exist
3. **Always Fresh**: New datasets appear automatically as they're added to your workspace

### Supported Data Formats

- **Zarr** (`.zarr` directories) - Multi-dimensional array storage format
- **AnnData** (`.h5ad` files) - Annotated data matrices for single-cell data

### Using Datasets

When you open Cirrocumulus, you'll see all discovered datasets available for visualization. Simply click on a dataset to begin exploring your single-cell data.

## Resource Mounting

The app uses the Workbench CLI (`wb resource mount`) to mount workspace resources, making your data accessible to Cirrocumulus.

## Local Testing

For local testing:

1. Create Docker network: `docker network create app-network`
2. Run the app: `devcontainer up --workspace-folder .`
3. Access at: `http://localhost:3000`

## Customization

Edit the following files to customize your app:

- `.devcontainer.json` - Devcontainer configuration and features
- `docker-compose.yaml` - Docker Compose configuration
- `Dockerfile` - Container image configuration
- `cirro-scanner.sh` - Dataset discovery script
- `devcontainer-template.json` - Template options and metadata

## About Cirrocumulus

Cirrocumulus is an interactive visualization tool for large-scale single-cell data built by the Broad Institute. For more information, visit the [Cirrocumulus GitHub repository](https://github.com/lilab-bcb/cirrocumulus).

## Testing

To test this app template:

```bash
cd test
./test.sh cirrocumulus
```

## Usage

1. Fork the repository
2. Modify the configuration files as needed
3. In Workbench UI, create a custom app pointing to your forked repository
4. Select this app template (cirrocumulus)
