#!/usr/bin/env Rscript

# launch-scexplorer.R
# Launches the scExploreR Shiny app

cat("=== Starting scExploreR ===\n")

# Check if config file exists, if not create from template
config_path <- Sys.getenv("SCEXPLORER_CONFIG", "/workspace/config.yaml")
template_path <- "/usr/local/share/scexplorer/config-template.yaml"

if (!file.exists(config_path)) {
    cat("Config file not found at:", config_path, "\n")

    if (file.exists(template_path)) {
        cat("Creating config.yaml from template...\n")
        file.copy(template_path, config_path)
        cat("\n")
        cat("============================================\n")
        cat("IMPORTANT: Edit /workspace/config.yaml\n")
        cat("to add paths to your single-cell datasets!\n")
        cat("============================================\n")
        cat("\n")
        cat("Your workspace GCS buckets are mounted at:\n")
        cat("  /home/rstudio/workspace/<bucket-name>/\n")
        cat("\n")
        cat("To create dataset configs, use:\n")
        cat("  scExploreR::run_config_app(object_path = '/path/to/object.rds')\n")
        cat("\n")
    } else {
        cat("ERROR: Neither config file nor template found!\n")
        quit(status = 1)
    }
}

cat("Using config file:", config_path, "\n")
cat("Loading scExploreR...\n")

# Load scExploreR
library(scExploreR)

cat("Launching scExploreR on port 3838...\n")

# Launch the app
scExploreR::run_scExploreR(
    browser_config = config_path,
    host = "0.0.0.0",
    port = 3838,
    launch_browser = FALSE
)
