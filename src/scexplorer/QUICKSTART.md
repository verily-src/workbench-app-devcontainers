# scExploreR Quick Start Guide

Get your scExploreR instance up and running in minutes!

## Step 1: Build the Container

Navigate to the scexplorer directory and build the container:

```bash
cd src/scexplorer
docker-compose up -d --build
```

**Note:** First build will take 10-15 minutes as it installs all R packages and dependencies.

## Step 2: Prepare Your Data

You have two options:

### Option A: Single Dataset (Recommended for First-Time Users)

1. Place your prepared Seurat object in the data directory:
   ```bash
   cp /path/to/your/seurat_object.rds data/object.rds
   ```

2. Access the app at `http://localhost:3838`

### Option B: Multi-Dataset Browser

1. Place all your data files in the `data/` directory:
   ```bash
   cp /path/to/dataset1.rds data/
   cp /path/to/dataset2.rds data/
   ```

2. Create a browser configuration:
   ```bash
   cp data/config_example.yaml data/config.yaml
   ```

3. Edit `data/config.yaml` to list your datasets

4. Restart the container:
   ```bash
   docker-compose restart
   ```

## Step 3: Access the Application

Open your web browser and navigate to:

```
http://localhost:3838
```

## Example Workflow

### Using a Public Dataset (PBMC 3k)

If you want to test with a public dataset:

```R
# In R or RStudio
library(Seurat)

# Download and process PBMC 3k dataset
pbmc.data <- Read10X(data.dir = "path/to/pbmc3k/")
pbmc <- CreateSeuratObject(counts = pbmc.data)

# Standard Seurat workflow
pbmc <- NormalizeData(pbmc)
pbmc <- FindVariableFeatures(pbmc)
pbmc <- ScaleData(pbmc)
pbmc <- RunPCA(pbmc)
pbmc <- FindNeighbors(pbmc, dims = 1:10)
pbmc <- FindClusters(pbmc, resolution = 0.5)
pbmc <- RunUMAP(pbmc, dims = 1:10)

# Save for scExploreR
saveRDS(pbmc, "data/object.rds")
```

Then restart the container and access the app!

## Configuration App (Optional but Recommended)

To customize your scExploreR experience, use the configuration app:

```R
# Install scExploreR in your local R environment
remotes::install_github('amc-heme/scExploreR@v1.0.0')

# Run the configuration app
library(scExploreR)
run_config(
  object_path = "./data/object.rds",
  config_path = "./data/object_config.yaml"
)
```

This will open an interactive app where you can:
- Select metadata fields to display
- Configure plot defaults
- Set up gene marker lists
- Define custom cell groupings

## Troubleshooting

### Container Won't Start
```bash
# Check logs
docker-compose logs -f

# Rebuild from scratch
docker-compose down
docker-compose up -d --build
```

### App Shows "Setup Required"
This means no data was found. Verify:
- Your data file is at `data/object.rds` OR
- Your browser config is at `data/config.yaml`

### Large Dataset Takes Too Long to Load
Edit `shiny-customized.conf` and increase timeouts:
```
app_init_timeout 120;  # Increase from 60
```

Then restart:
```bash
docker-compose restart
```

## Next Steps

1. **Explore the Documentation**: https://amc-heme.github.io/scExploreR/
2. **Customize Configuration**: Use the config app to optimize your experience
3. **Add More Datasets**: Set up multi-dataset browser for your team
4. **Deploy to Production**: Configure for remote access and authentication

## Common Use Cases

### For Individual Analysis
- Use single-dataset mode
- Configure cell type annotations
- Export high-quality plots

### For Lab/Team Sharing
- Use multi-dataset browser mode
- Set up different projects
- Allow team members to explore data independently

### For Publication
- Configure nice plot defaults
- Set up marker gene lists
- Generate consistent visualizations

## Getting Help

- **Documentation**: https://amc-heme.github.io/scExploreR/
- **Issues**: https://github.com/amc-heme/scExploreR/issues
- **Examples**: Check the scExploreR vignettes for detailed examples

## Data Privacy Note

All data remains on your local system or container. No data is sent externally unless you explicitly configure cloud storage integration.
