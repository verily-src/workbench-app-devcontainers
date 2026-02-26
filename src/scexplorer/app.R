# scExploreR Shiny Application Launcher
# This script launches the scExploreR application for single cell data visualization

library(scExploreR)

# Define paths for data objects and configuration
# Users can place their data objects in /srv/shiny-server/scexplorer/data/
# and configuration files in the same directory

# Check if a browser config file exists
browser_config_path <- "/srv/shiny-server/scexplorer/data/config.yaml"
default_object_path <- "/srv/shiny-server/scexplorer/data/object.rds"
default_config_path <- "/srv/shiny-server/scexplorer/data/object_config.yaml"

# Launch the application
if (file.exists(browser_config_path)) {
  # Multi-dataset mode using browser configuration
  message("Launching scExploreR with browser configuration: ", browser_config_path)
  scExploreR::run_scExploreR(
    browser_config = browser_config_path,
    host = "0.0.0.0",
    port = 3838,
    launch.browser = FALSE
  )
} else if (file.exists(default_object_path)) {
  # Single-dataset mode
  message("Launching scExploreR with single object: ", default_object_path)

  config_arg <- if (file.exists(default_config_path)) default_config_path else NULL

  scExploreR::run_scExploreR(
    object_path = default_object_path,
    config_path = config_arg,
    host = "0.0.0.0",
    port = 3838,
    launch.browser = FALSE
  )
} else {
  # No data found - show instructions
  message("No data objects found. Please configure your scExploreR instance.")
  message("Instructions:")
  message("1. Place your prepared single cell object at: ", default_object_path)
  message("2. Optionally, run the configuration app to generate config.yaml:")
  message("   scExploreR::run_config(object_path = '/path/to/object', config_path = '/path/to/config')")
  message("3. For multi-dataset mode, create a browser config at: ", browser_config_path)

  # Launch a placeholder app with instructions
  library(shiny)

  ui <- fluidPage(
    titlePanel("scExploreR - Setup Required"),

    mainPanel(
      h3("Welcome to scExploreR"),
      p("scExploreR is a Shiny app for single cell omics data visualization."),

      h4("Setup Instructions:"),
      tags$ol(
        tags$li("Prepare your single cell data object (Seurat, SingleCellExperiment, or Anndata format)"),
        tags$li("Place your object file at: ", tags$code("/srv/shiny-server/scexplorer/data/object.rds")),
        tags$li("Optionally, generate a configuration file using:",
                tags$pre("scExploreR::run_config(object_path = 'path_to_object', config_path = 'path_to_config')")),
        tags$li("For multi-dataset mode, create a browser config YAML file at:",
                tags$code("/srv/shiny-server/scexplorer/data/config.yaml"))
      ),

      h4("Documentation:"),
      p(tags$a("Visit the scExploreR documentation",
               href = "https://amc-heme.github.io/scExploreR/",
               target = "_blank")),

      h4("Current Status:"),
      p("No data objects detected. Please upload your data to get started.")
    )
  )

  server <- function(input, output, session) {
    # No server logic needed for this placeholder
  }

  shinyApp(ui = ui, server = server, options = list(host = "0.0.0.0", port = 3838))
}
