# =============================================================================
# RShiny Dashboard Template for Verily Workbench
# =============================================================================

library(shiny)
library(shinydashboard)
library(DT)
library(plotly)
library(ggplot2)
library(dplyr)

# =============================================================================
# WORKSPACE HELPERS
# =============================================================================

get_workspace_resources <- function() {
  env_vars <- Sys.getenv()
  workbench_vars <- env_vars[grepl("^WORKBENCH_", names(env_vars))]
  names(workbench_vars) <- gsub("^WORKBENCH_", "", names(workbench_vars))
  as.list(workbench_vars)
}

# Get workspace resources
resources <- get_workspace_resources()

# =============================================================================
# UI
# =============================================================================

ui <- dashboardPage(
  dashboardHeader(title = "Workbench Dashboard"),
  
  dashboardSidebar(
    sidebarMenu(
      menuItem("Overview", tabName = "overview", icon = icon("dashboard")),
      menuItem("Data Explorer", tabName = "data", icon = icon("table")),
      menuItem("Visualization", tabName = "viz", icon = icon("chart-line")),
      menuItem("Resources", tabName = "resources", icon = icon("cloud"))
    )
  ),
  
  dashboardBody(
    tabItems(
      # Overview Tab
      tabItem(
        tabName = "overview",
        fluidRow(
          box(
            title = "Welcome to Your Workbench Dashboard",
            status = "primary",
            solidHeader = TRUE,
            width = 12,
            p("This RShiny template integrates with your Workbench workspace resources."),
            p("Use the sidebar to navigate between data exploration and visualization.")
          )
        ),
        fluidRow(
          valueBoxOutput("resource_count"),
          valueBoxOutput("bucket_count"),
          valueBoxOutput("dataset_count")
        )
      ),
      
      # Data Explorer Tab
      tabItem(
        tabName = "data",
        fluidRow(
          box(
            title = "Upload Data",
            status = "info",
            solidHeader = TRUE,
            width = 4,
            fileInput("file_upload", "Choose CSV File", accept = ".csv"),
            actionButton("load_data", "Load Data", class = "btn-primary")
          ),
          box(
            title = "Data Preview",
            status = "success",
            solidHeader = TRUE,
            width = 8,
            DTOutput("data_table")
          )
        )
      ),
      
      # Visualization Tab
      tabItem(
        tabName = "viz",
        fluidRow(
          box(
            title = "Chart Settings",
            status = "warning",
            solidHeader = TRUE,
            width = 3,
            selectInput("x_var", "X Variable", choices = NULL),
            selectInput("y_var", "Y Variable", choices = NULL),
            selectInput("chart_type", "Chart Type", 
                       choices = c("Scatter", "Line", "Bar", "Histogram")),
            actionButton("create_chart", "Create Chart", class = "btn-success")
          ),
          box(
            title = "Chart",
            status = "primary",
            solidHeader = TRUE,
            width = 9,
            plotlyOutput("main_chart", height = "500px")
          )
        )
      ),
      
      # Resources Tab
      tabItem(
        tabName = "resources",
        fluidRow(
          box(
            title = "Workspace Resources",
            status = "info",
            solidHeader = TRUE,
            width = 12,
            DTOutput("resources_table")
          )
        )
      )
    )
  )
)

# =============================================================================
# SERVER
# =============================================================================

server <- function(input, output, session) {
  
  # Reactive values
  data <- reactiveVal(NULL)
  
  # Load data from file upload
  observeEvent(input$load_data, {
    req(input$file_upload)
    df <- read.csv(input$file_upload$datapath)
    data(df)
    
    # Update variable selectors
    updateSelectInput(session, "x_var", choices = names(df))
    updateSelectInput(session, "y_var", choices = names(df))
  })
  
  # Data table output
  output$data_table <- renderDT({
    req(data())
    datatable(data(), options = list(pageLength = 10, scrollX = TRUE))
  })
  
  # Value boxes
  output$resource_count <- renderValueBox({
    valueBox(
      length(resources),
      "Workspace Resources",
      icon = icon("folder"),
      color = "blue"
    )
  })
  
  output$bucket_count <- renderValueBox({
    bucket_count <- sum(grepl("^gs://", unlist(resources)))
    valueBox(
      bucket_count,
      "GCS Buckets",
      icon = icon("cloud"),
      color = "green"
    )
  })
  
  output$dataset_count <- renderValueBox({
    dataset_count <- sum(grepl("bigquery://", unlist(resources)))
    valueBox(
      dataset_count,
      "BigQuery Datasets",
      icon = icon("database"),
      color = "purple"
    )
  })
  
  # Resources table
  output$resources_table <- renderDT({
    df <- data.frame(
      Name = names(resources),
      Path = unlist(resources),
      stringsAsFactors = FALSE
    )
    datatable(df, options = list(pageLength = 20))
  })
  
  # Create chart
  observeEvent(input$create_chart, {
    req(data(), input$x_var, input$y_var)
    
    df <- data()
    
    output$main_chart <- renderPlotly({
      p <- switch(
        input$chart_type,
        "Scatter" = ggplot(df, aes_string(x = input$x_var, y = input$y_var)) + 
                    geom_point(alpha = 0.6),
        "Line" = ggplot(df, aes_string(x = input$x_var, y = input$y_var)) + 
                 geom_line(),
        "Bar" = ggplot(df, aes_string(x = input$x_var, y = input$y_var)) + 
                geom_bar(stat = "identity"),
        "Histogram" = ggplot(df, aes_string(x = input$x_var)) + 
                      geom_histogram(bins = 30)
      )
      
      ggplotly(p + theme_minimal())
    })
  })
}

# =============================================================================
# RUN APP
# =============================================================================

shinyApp(ui = ui, server = server)
