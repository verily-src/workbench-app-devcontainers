# scExploreR App Notes

## Important Implementation Details

### How It Works

This app integrates [scExploreR](https://github.com/amc-heme/scExploreR) with Workbench's GCS bucket mounting system.

**Key Features:**
- Users can store pre-processed single-cell data in their workspace GCS buckets
- Data files are accessed via gcsfuse-mounted paths at `/home/rstudio/workspace/`
- Multiple datasets can be configured in a single browser instance
- Users switch between datasets at runtime using the "Choose Dataset" menu

### Container Startup

The Docker image is built with scExploreR pre-installed. On container start:

1. **Dockerfile build time** (happens once when image is built):
   - Installs all system dependencies
   - Installs all R packages including scExploreR from GitHub
   - Copies entrypoint and launch scripts into the image

2. **Container startup** (happens each time container starts):
   - `entrypoint.sh` is executed as CMD
   - `launch-scexplorer.R` checks for `/workspace/config.yaml`
   - If not found, copies template from image
   - Launches scExploreR web app on port 3838

3. **Workbench integration** (via .devcontainer.json):
   - `postCreateCommand` runs `post-startup.sh` for CLI tools, gcsfuse, etc.
   - `postStartCommand` re-mounts GCS buckets on restart

### Configuration Workflow

#### Two-Level Configuration:

1. **Browser Config** (`/workspace/config.yaml`):
   - Lists all available datasets
   - Specifies paths to object files and their configs
   - Can be edited directly

2. **Dataset Configs** (one per dataset):
   - Created using `scExploreR::run_config_app()`
   - Defines dataset metadata, assays, visualizations
   - Stored alongside data in GCS buckets

### Memory Considerations

scExploreR loads datasets into memory. For large datasets:
- Use Seurat v5 with BPCells (on-disk arrays)
- Use SingleCellExperiment with HDF5Array (on-disk storage)
- Use Anndata .h5ad files (memory-efficient)

Ensure your Workbench VM has sufficient RAM for your datasets.

### GCS Bucket Access

Buckets are mounted by the `workbench-tools` feature via:
- `post-startup.sh` runs gcsfuse installation
- `wb resource mount` mounts buckets to `/home/rstudio/workspace/`
- Buckets appear as regular filesystem directories

### Python Support (for Anndata)

If using Anndata (.h5ad) files, ensure Python is available with:
- numpy
- pandas
- scipy
- anndata
- scanpy

These can be installed via conda/mamba in the base environment.

### Customization

To customize the app:
- Edit `startup.sh` to modify launch behavior
- Edit `config-template.yaml` to change default config structure
- Modify Dockerfile to add additional R packages or system dependencies

### Updating scExploreR

scExploreR is installed at Docker image build time. To update to a newer version:

1. Rebuild the Docker image (this will pull the latest version from GitHub)
2. Or, manually update inside a running container:
   ```r
   # In R console or terminal
   remotes::install_github("amc-heme/scExploreR", upgrade = "always", force = TRUE)
   ```
   Then restart the container.

Note: Manual updates will be lost when the container is recreated. For permanent updates, rebuild the image.

## Known Limitations

1. **Data must be pre-processed**: scExploreR expects normalized, clustered data with dimensionality reduction already computed
2. **Config files required**: Each dataset needs a config file created via the config app
3. **Memory constraints**: Large datasets may require significant RAM
4. **No live analysis**: scExploreR is for exploration/visualization, not for running analysis pipelines

## Tips

- **Start small**: Test with one small dataset first
- **Use example data**: scExploreR includes example datasets you can use for testing
- **Monitor memory**: Check VM memory usage if datasets fail to load
- **Save configs in GCS**: Store dataset config files alongside your data in GCS buckets

## Troubleshooting

### scExploreR fails to install

Check the container logs for R package installation errors. Common issues:
- Missing system dependencies (add to Dockerfile)
- GitHub rate limiting (wait and retry)
- Network connectivity issues

### Dataset won't load

- Verify the object path in config.yaml is correct
- Check that the object file is a valid Seurat/SCE/Anndata object
- Ensure sufficient memory is available
- Check container logs for detailed error messages

### Can't create config file

The config app may fail if:
- Object is corrupted or incomplete
- Missing required assays or metadata
- Memory issues loading large objects

### GCS bucket not mounted

- Check that `login: true` is set in app template options
- Verify bucket permissions in Workbench
- Check `/home/rstudio/workspace/` exists and is populated

## Support

For scExploreR-specific issues, see:
- [scExploreR GitHub Issues](https://github.com/amc-heme/scExploreR/issues)
- [scExploreR Documentation](https://amc-heme.github.io/scExploreR/)

For Workbench integration issues, contact your Workbench administrator.
