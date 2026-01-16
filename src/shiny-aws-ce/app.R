# AWS Cost Analysis Dashboard
# R Shiny Application

# Load required libraries
library(shiny)
library(shinydashboard)
library(DT)
library(plotly)
library(dplyr)
library(ggplot2)
library(lubridate)
library(scales)
library(readr)
library(shinycssloaders)
library(tidyr)
library(stringr)

# Suppress dplyr summarise warnings
options(dplyr.summarise.inform = FALSE)

# Data loading function
load_aws_data <- function() {
  tryCatch({
    # Define data directory
    data_dir <- "verily_cost"

    # Core cost data
    cost_by_category <- read_csv(file.path(data_dir, "cost_by_category.csv"), show_col_types = FALSE)
    #daily_cost_trends <- read_csv(file.path(data_dir, "daily_cost_trends.csv"), show_col_types = FALSE)
    #cost_by_region <- read_csv(file.path(data_dir, "cost_by_region.csv"), show_col_types = FALSE)
    top_services <- read_csv(file.path(data_dir, "top_services.csv"), show_col_types = FALSE)
    service_usage_lines <- read_csv(file.path(data_dir, "service_usage_lines.csv"), show_col_types = FALSE)

    # Compute data
    ec2_instance_types <- read_csv(file.path(data_dir, "ec2_instance_types.csv"), show_col_types = FALSE)
    ec2_families <- read_csv(file.path(data_dir, "ec2_families.csv"), show_col_types = FALSE)
    #ec2_cost_by_region <- read_csv(file.path(data_dir, "ec2_cost_by_region.csv"), show_col_types = FALSE)

    # Daily granular EC2 instance data (with dates for trending, now includes service info)
    ec2_instance_daily_file <- file.path(data_dir, "ec2_instance_daily.csv")
    if (file.exists(ec2_instance_daily_file)) {
      ec2_instance_daily <- read_csv(ec2_instance_daily_file, show_col_types = FALSE)
      ec2_instance_daily$date <- as.Date(ec2_instance_daily$date)
    } else {
      ec2_instance_daily <- data.frame(date = as.Date(character()), instance_type = character(),
                                     service = character(), hours = numeric(), hours_unit = character(), cost_usd = numeric())
    }

    # Storage data
    s3_buckets <- read_csv(file.path(data_dir, "s3_buckets.csv"), show_col_types = FALSE)
    ebs_by_region <- read_csv(file.path(data_dir, "ebs_by_region.csv"), show_col_types = FALSE)

    # EC2 Other data
    #ec2_other_categories <- read_csv(file.path(data_dir, "ec2_other_categories.csv"), show_col_types = FALSE)
    #ec2_other_usage_lines <- read_csv(file.path(data_dir, "ec2_other_usage_lines.csv"), show_col_types = FALSE)
    #ec2_other_usage_summary <- read_csv(file.path(data_dir, "ec2_other_usage_summary.csv"), show_col_types = FALSE)

    # Workspace data
    workspaces_ec2 <- read_csv(file.path(data_dir, "workspaces_ec2.csv"), show_col_types = FALSE)

    # Check if workspaces_omics exists
    omics_file <- file.path(data_dir, "workspaces_omics.csv")
    if (file.exists(omics_file)) {
      workspaces_omics <- read_csv(omics_file, show_col_types = FALSE)
    } else {
      workspaces_omics <- data.frame(WorkspaceId = character(), hours = numeric(),
                                   hours_unit = character(), cost_usd = numeric())
    }

    # Daily granular storage and workspace data (if available)
    s3_daily_costs_file <- file.path(data_dir, "s3_daily_costs.csv")
    s3_daily_costs <- if (file.exists(s3_daily_costs_file)) {
      read_csv(s3_daily_costs_file, show_col_types = FALSE) %>%
        dplyr::mutate(date = as.Date(date))
    } else {
      data.frame(date = as.Date(character()), usage_type = character(),
                linked_account = character(), cost_usd = numeric(),
                usage_quantity = numeric(), usage_unit = character())
    }

    ebs_daily_costs_file <- file.path(data_dir, "ebs_daily_costs.csv")
    ebs_daily_costs <- if (file.exists(ebs_daily_costs_file)) {
      read_csv(ebs_daily_costs_file, show_col_types = FALSE) %>%
        dplyr::mutate(date = as.Date(date))
    } else {
      data.frame(date = as.Date(character()), usage_type = character(),
                region = character(), cost_usd = numeric(),
                usage_quantity = numeric(), usage_unit = character())
    }

    workspaces_ec2_daily_file <- file.path(data_dir, "workspaces_ec2_daily.csv")
    workspaces_ec2_daily <- if (file.exists(workspaces_ec2_daily_file)) {
      read_csv(workspaces_ec2_daily_file, show_col_types = FALSE) %>%
        dplyr::mutate(date = as.Date(date))
    } else {
      data.frame(date = as.Date(character()), workspace_id = character(),
                cost_usd = numeric(), usage_quantity = numeric(), usage_unit = character())
    }

    workspaces_omics_daily_file <- file.path(data_dir, "workspaces_omics_daily.csv")
    workspaces_omics_daily <- if (file.exists(workspaces_omics_daily_file)) {
      read_csv(workspaces_omics_daily_file, show_col_types = FALSE) %>%
        dplyr::mutate(date = as.Date(date))
    } else {
      data.frame(date = as.Date(character()), workspace_id = character(),
                cost_usd = numeric(), usage_quantity = numeric(), usage_unit = character())
    }

    # Process dates
    #daily_cost_trends$date <- as.Date(daily_cost_trends$date)
    #daily_cost_trends <- daily_cost_trends %>% dplyr::arrange(date, category)

    # Clean and filter data
    ec2_instance_types <- ec2_instance_types %>%
      dplyr::filter(!is.na(instance_type), instance_type != "", !is.na(cost_usd), !is.na(hours))

    # Keep all EC2 families including NoInstanceType (handle empty family names)
    ec2_families <- ec2_families %>%
      dplyr::filter(!is.na(cost_usd), !is.na(hours)) %>%
      dplyr::mutate(family = ifelse(is.na(family) | family == "", "NoInstanceType", family))

    workspaces_ec2 <- workspaces_ec2 %>%
      dplyr::filter(cost_usd > 0, !is.na(WorkspaceId), WorkspaceId != "")

    list(
      cost_by_category = cost_by_category,
      #daily_cost_trends = daily_cost_trends,
      #cost_by_region = cost_by_region,
      top_services = top_services,
      service_usage_lines = service_usage_lines,
      ec2_instance_types = ec2_instance_types,
      ec2_instance_daily = ec2_instance_daily,
      ec2_families = ec2_families,
      #ec2_cost_by_region = ec2_cost_by_region,
      s3_buckets = s3_buckets,
      ebs_by_region = ebs_by_region,
      #ec2_other_categories = ec2_other_categories,
      #ec2_other_usage_lines = ec2_other_usage_lines,
      #ec2_other_usage_summary = ec2_other_usage_summary,
      workspaces_ec2 = workspaces_ec2,
      workspaces_omics = workspaces_omics,
      s3_daily_costs = s3_daily_costs,
      ebs_daily_costs = ebs_daily_costs,
      workspaces_ec2_daily = workspaces_ec2_daily,
      workspaces_omics_daily = workspaces_omics_daily
    )
  }, error = function(e) {
    stop("Error loading data: ", e$message,
         "\nPlease ensure the 'verily_cost' directory exists with the required CSV files.")
  })
}

# Load data
aws_data <- load_aws_data()

# Define UI
ui <- dashboardPage(
  dashboardHeader(title = "AWS Cost Analysis Dashboard"),

  dashboardSidebar(
    sidebarMenu(
      menuItem("Overview", tabName = "overview", icon = icon("dashboard")),
      menuItem("Compute Analysis", tabName = "compute", icon = icon("server")),
      menuItem("Storage Analysis", tabName = "storage", icon = icon("database")),
      menuItem("EC2-Other Usage", tabName = "ec2_other", icon = icon("cogs")),
      menuItem("Workspaces", tabName = "workspaces", icon = icon("desktop")),
      menuItem("Omics Workspaces", tabName = "omics", icon = icon("dna"))
    )
  ),

  dashboardBody(
    # Custom CSS
    tags$head(
      tags$style(HTML("
        .content-wrapper, .right-side {
          background-color: #f4f4f4;
        }
        .global-filters {
          background: white;
          padding: 15px;
          margin-bottom: 20px;
          border-radius: 5px;
          box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .filter-row {
          display: flex;
          align-items: center;
          gap: 20px;
          flex-wrap: wrap;
        }
        .time-buttons {
          display: flex;
          gap: 10px;
        }
        .value-box-icon {
          font-size: 24px !important;
        }
      "))
    ),

    # Global date range filter
    div(class = "global-filters",
      div(class = "filter-row",
        div(
          h4("Time Range Selection", style = "margin: 0; margin-right: 20px;"),
          div(class = "time-buttons",
            actionButton("global_last_30_days", "Last 30 Days", class = "btn-primary btn-sm"),
            actionButton("global_last_60_days", "Last 60 Days", class = "btn-primary btn-sm"),
            actionButton("global_last_90_days", "Last 90 Days", class = "btn-primary btn-sm")
          )
        ),
        div(
          dateRangeInput("global_date_range", "Custom Range:",
                        start = Sys.Date() - 90, end = Sys.Date(),
                        max = Sys.Date())
        )
      )
    ),

    tabItems(
      # Overview Tab
      tabItem(tabName = "overview",
        fluidRow(
          valueBoxOutput("total_cost_box"),
          valueBoxOutput("compute_cost_box"),
          valueBoxOutput("storage_cost_box")
        ),

        fluidRow(
          box(
            title = "Cost Trends Over Time", status = "primary", solidHeader = TRUE,
            width = 12, height = "500px",
            div(
              selectInput("time_granularity", "Time Granularity:",
                         choices = c("Daily" = "daily", "Monthly" = "monthly"),
                         selected = "monthly", width = "200px"),
              withSpinner(plotlyOutput("cost_trends_plot", height = "400px"))
            )
          )
        ),

        fluidRow(
          box(
            title = "Cost Breakdown by Category", status = "info", solidHeader = TRUE,
            width = 6, height = "400px",
            withSpinner(plotlyOutput("category_pie_chart", height = "350px"))
          ),
          box(
            title = "Top Services", status = "info", solidHeader = TRUE,
            width = 6, height = "400px",
            withSpinner(plotlyOutput("top_services_plot", height = "350px"))
          )
        )
      ),

      # Compute Analysis Tab
      tabItem(tabName = "compute",
        fluidRow(
          valueBoxOutput("ec2_total_cost", width = 12)
        ),

        fluidRow(
          box(
            title = "EC2 Cost by Family", status = "primary", solidHeader = TRUE,
            width = 12, height = "500px",
            withSpinner(plotlyOutput("ec2_families_plot", height = "450px"))
          )
        ),
        fluidRow(
          box(
            title = "Top EC2 Instance Types", status = "primary", solidHeader = TRUE,
            width = 12, height = "500px",
            withSpinner(plotlyOutput("top_instances_plot", height = "450px"))
          )
        ),

        fluidRow(
          box(
            title = "EC2 Cost by Region (All Regions)", status = "info", solidHeader = TRUE,
            width = 6, height = "400px",
            withSpinner(plotlyOutput("ec2_region_plot", height = "350px"))
          ),
          box(
            title = "NoInstanceType Cost Breakdown by Service", status = "warning", solidHeader = TRUE,
            width = 6, height = "400px",
            withSpinner(plotlyOutput("noinstance_service_breakdown_plot", height = "350px"))
          )
        ),

        fluidRow(
          box(
            title = "EC2 Instance Trends Over Time", status = "info", solidHeader = TRUE,
            width = 12, height = "400px",
            withSpinner(plotlyOutput("ec2_instance_trends_plot", height = "350px"))
          )
        ),

        fluidRow(
          box(
            title = "Instance Types Daily Details", status = "info", solidHeader = TRUE,
            width = 8, height = "500px",
            withSpinner(DT::dataTableOutput("ec2_instances_table")),
            footer = "Shows daily breakdown of EC2 instance costs and hours for selected date range. Use CSV download button above table to export data."
          ),
          box(
            title = "NoInstanceType Daily Trends by Service", status = "warning", solidHeader = TRUE,
            width = 4, height = "500px",
            withSpinner(plotlyOutput("noinstance_daily_trends_plot", height = "450px"))
          )
        )
      ),

      # Storage Analysis Tab
      tabItem(tabName = "storage",
        fluidRow(
          valueBoxOutput("s3_total_cost"),
          valueBoxOutput("ebs_total_cost"),
          valueBoxOutput("storage_total_cost")
        ),

        fluidRow(
          box(
            title = "S3 Buckets Cost Distribution", status = "primary", solidHeader = TRUE,
            width = 6, height = "400px",
            withSpinner(plotlyOutput("s3_cost_plot", height = "350px"))
          ),
          box(
            title = "EBS Cost by Region", status = "primary", solidHeader = TRUE,
            width = 6, height = "400px",
            withSpinner(plotlyOutput("ebs_region_plot", height = "350px"))
          )
        ),

        fluidRow(
          box(
            title = "S3 Daily Cost Breakdown", status = "info", solidHeader = TRUE,
            width = 6, height = "400px",
            withSpinner(plotlyOutput("s3_daily_breakdown_plot", height = "350px")),
            footer = "Shows daily S3 costs by usage type (if s3_daily_costs.csv available). Filtered by selected date range."
          ),
          box(
            title = "Storage Cost Over Time", status = "info", solidHeader = TRUE,
            width = 6, height = "400px",
            withSpinner(plotlyOutput("storage_trends_plot", height = "350px")),
            footer = "Shows daily S3/EBS costs (if daily cost files available) or falls back to aggregated storage data. Filtered by selected date range."
          )
        )
      ),

      # EC2-Other Usage Tab
      #tabItem(tabName = "ec2_other",
      #  fluidRow(
      #    valueBoxOutput("ec2_other_total_cost"),
      #    valueBoxOutput("ec2_other_categories_count"),
      #    valueBoxOutput("ec2_other_usage_types_count")
      #  ),

      #  fluidRow(
      #    box(
      #      title = "EC2-Other Cost by Category", status = "primary", solidHeader = TRUE,
      #      width = 6, height = "400px",
      #      withSpinner(plotlyOutput("ec2_other_categories_plot", height = "350px"))
      #    ),
      #    box(
      #      title = "Top EC2-Other Usage Types", status = "primary", solidHeader = TRUE,
      #      width = 6, height = "400px",
      #      withSpinner(plotlyOutput("ec2_other_usage_plot", height = "350px"))
      #    )
      #  ),

      #  fluidRow(
      #    box(
      #      title = "EC2-Other Usage Details", status = "info", solidHeader = TRUE,
      #      width = 12, height = "400px",
      #      withSpinner(DT::dataTableOutput("ec2_other_table"))
      #    )
      #  )
      #),

      # Workspaces Tab
      tabItem(tabName = "workspaces",
        fluidRow(
          valueBoxOutput("workspace_total_cost"),
          valueBoxOutput("workspace_count"),
          valueBoxOutput("workspace_avg_cost")
        ),

        fluidRow(
          box(
            title = "Workspace Cost Distribution", status = "primary", solidHeader = TRUE,
            width = 6, height = "400px",
            withSpinner(plotlyOutput("workspace_cost_plot", height = "350px"))
          ),
          box(
            title = "Workspace Hours vs Cost", status = "primary", solidHeader = TRUE,
            width = 6, height = "400px",
            withSpinner(plotlyOutput("workspace_scatter_plot", height = "350px"))
          )
        ),

        fluidRow(
          box(
            title = "Workspace Details", status = "info", solidHeader = TRUE,
            width = 12, height = "400px",
            withSpinner(DT::dataTableOutput("workspace_table"))
          )
        )
      ),

      # Omics Workspaces Tab
      tabItem(tabName = "omics",
        fluidRow(
          valueBoxOutput("omics_total_cost"),
          valueBoxOutput("omics_count"),
          valueBoxOutput("omics_avg_cost")
        ),

        conditionalPanel(
          condition = "output.has_omics_data",
          fluidRow(
            box(
              title = "Omics Workspace Cost Distribution", status = "primary", solidHeader = TRUE,
              width = 6, height = "400px",
              withSpinner(plotlyOutput("omics_cost_plot", height = "350px"))
            ),
            box(
              title = "Omics Hours vs Cost", status = "primary", solidHeader = TRUE,
              width = 6, height = "400px",
              withSpinner(plotlyOutput("omics_scatter_plot", height = "350px"))
            )
          ),

          fluidRow(
            box(
              title = "Omics Workspace Details", status = "info", solidHeader = TRUE,
              width = 12, height = "400px",
              withSpinner(DT::dataTableOutput("omics_table"))
            )
          )
        ),

        conditionalPanel(
          condition = "!output.has_omics_data",
          fluidRow(
            box(
              title = "No Omics Data Available", status = "warning", solidHeader = TRUE,
              width = 12,
              h4("No Omics workspace data found."),
              p("This could mean:"),
              tags$ul(
                tags$li("No Omics workspaces are currently running"),
                tags$li("The workspaces_omics.csv file was not generated"),
                tags$li("There were no Omics costs in the selected time period")
              )
            )
          )
        )
      )
    )
  )
)

# Define Server
server <- function(input, output, session) {

  # Global date filtering
  #global_filtered_daily_data <- reactive({
  #  aws_data$daily_cost_trends %>%
  #    dplyr::filter(date >= input$global_date_range[1], date <= input$global_date_range[2])
  #})

  global_filtered_cost_data <- reactive({
    # Filter cost data based on date if date column exists
    if ("date" %in% names(aws_data$cost_by_category)) {
      aws_data$cost_by_category %>%
        dplyr::filter(date >= input$global_date_range[1], date <= input$global_date_range[2])
    } else {
      aws_data$cost_by_category
    }
  })

  # Date range buttons
  observeEvent(input$global_last_30_days, {
    updateDateRangeInput(session, "global_date_range",
                        start = Sys.Date() - 30, end = Sys.Date())
  })

  observeEvent(input$global_last_60_days, {
    updateDateRangeInput(session, "global_date_range",
                        start = Sys.Date() - 60, end = Sys.Date())
  })

  observeEvent(input$global_last_90_days, {
    updateDateRangeInput(session, "global_date_range",
                        start = Sys.Date() - 90, end = Sys.Date())
  })

  # Overview Tab Outputs
  output$total_cost_box <- renderValueBox({
    total_cost <- sum(global_filtered_cost_data()$amount_usd, na.rm = TRUE)
    valueBox(
      value = paste0("$", format(round(total_cost, 0), big.mark = ",")),
      subtitle = "Total Cost",
      icon = icon("dollar-sign"),
      color = "blue"
    )
  })

  output$compute_cost_box <- renderValueBox({
    compute_cost <- global_filtered_cost_data() %>%
      dplyr::filter(category %in% c("Compute", "EC2-Instance", "EC2-Other")) %>%
      dplyr::summarise(total = sum(amount_usd, na.rm = TRUE)) %>%
      dplyr::pull(total)

    valueBox(
      value = paste0("$", format(round(compute_cost, 0), big.mark = ",")),
      subtitle = "Compute Cost",
      icon = icon("server"),
      color = "green"
    )
  })

  output$storage_cost_box <- renderValueBox({
    storage_cost <- global_filtered_cost_data() %>%
      dplyr::filter(category %in% c("Storage", "S3", "EBS")) %>%
      dplyr::summarise(total = sum(amount_usd, na.rm = TRUE)) %>%
      dplyr::pull(total)

    valueBox(
      value = paste0("$", format(round(storage_cost, 0), big.mark = ",")),
      subtitle = "Storage Cost",
      icon = icon("database"),
      color = "yellow"
    )
  })

  output$cost_trends_plot <- renderPlotly({
    trends_data <- global_filtered_daily_data()

    if (nrow(trends_data) == 0) {
      p <- plot_ly() %>%
        add_text(x = 0.5, y = 0.5, text = "No data available for selected time range") %>%
        layout(xaxis = list(visible = FALSE), yaxis = list(visible = FALSE))
      return(p)
    }

    if (input$time_granularity == "monthly") {
      trends_data <- trends_data %>%
        dplyr::mutate(period = lubridate::floor_date(date, "month")) %>%
        dplyr::group_by(period, category) %>%
        dplyr::summarise(cost = sum(amount_usd, na.rm = TRUE), .groups = "drop")
    } else {
      trends_data <- trends_data %>%
        dplyr::mutate(period = date) %>%
        dplyr::rename(cost = amount_usd)
    }

    p <- plot_ly(trends_data, x = ~period, y = ~cost, color = ~category, type = 'scatter', mode = 'lines+markers') %>%
      layout(
        title = paste("Cost Trends -", str_to_title(input$time_granularity)),
        xaxis = list(title = "Time Period"),
        yaxis = list(title = "Cost (USD)"),
        hovermode = 'x unified'
      )

    p
  })

  output$category_pie_chart <- renderPlotly({
    category_data <- global_filtered_cost_data() %>%
      dplyr::group_by(category) %>%
      dplyr::summarise(total_cost = sum(amount_usd, na.rm = TRUE), .groups = "drop") %>%
      dplyr::arrange(desc(total_cost))

    plot_ly(category_data, labels = ~category, values = ~total_cost, type = 'pie') %>%
      layout(title = "Cost Distribution by Category")
  })

  output$top_services_plot <- renderPlotly({
    if (nrow(aws_data$top_services) > 0) {
      top_services <- aws_data$top_services %>%
        dplyr::slice_head(n = 10) %>%
        dplyr::arrange(amount_usd)

      plot_ly(top_services, x = ~amount_usd, y = ~reorder(service, amount_usd), type = 'bar', orientation = 'h') %>%
        layout(
          title = "Top 10 Services by Cost",
          xaxis = list(title = "Cost (USD)"),
          yaxis = list(title = "Service")
        )
    } else {
      plot_ly() %>%
        add_text(x = 0.5, y = 0.5, text = "No services data available") %>%
        layout(xaxis = list(visible = FALSE), yaxis = list(visible = FALSE))
    }
  })

  # Compute Tab Outputs
  output$ec2_total_cost <- renderValueBox({
    if (nrow(aws_data$ec2_instance_daily) > 0) {
      # Use filtered daily data
      total_cost <- aws_data$ec2_instance_daily %>%
        dplyr::filter(date >= input$global_date_range[1], date <= input$global_date_range[2]) %>%
        dplyr::summarise(total = sum(cost_usd, na.rm = TRUE)) %>%
        dplyr::pull(total)
    } else {
      # Fallback to aggregated data
      total_cost <- sum(aws_data$ec2_instance_types$cost_usd, na.rm = TRUE)
    }

    valueBox(
      value = paste0("$", format(round(total_cost, 0), big.mark = ",")),
      subtitle = "EC2 Total Cost (Date Filtered)",
      icon = icon("server"),
      color = "blue"
    )
  })


  output$ec2_families_plot <- renderPlotly({
    # Use daily data and aggregate by family for selected date range
    if (nrow(aws_data$ec2_instance_daily) > 0) {
      families_data <- aws_data$ec2_instance_daily %>%
        dplyr::filter(date >= input$global_date_range[1], date <= input$global_date_range[2]) %>%
        dplyr::mutate(family = ifelse(stringr::str_detect(instance_type, "\\."),
                                     stringr::str_extract(instance_type, "^[^.]+"),
                                     instance_type)) %>%
        dplyr::group_by(family) %>%
        dplyr::summarise(
          cost_usd = sum(cost_usd, na.rm = TRUE),
          hours = sum(hours, na.rm = TRUE),
          .groups = "drop"
        ) %>%
        dplyr::filter(!is.na(cost_usd), !is.na(hours)) %>%
        dplyr::arrange(desc(cost_usd), desc(hours)) %>%
        dplyr::slice_head(n = 15)
    } else {
      # Fallback to aggregated data
      families_data <- aws_data$ec2_families %>%
        dplyr::filter(!is.na(cost_usd), !is.na(hours)) %>%
        dplyr::arrange(desc(cost_usd), desc(hours)) %>%
        dplyr::slice_head(n = 15)
    }

    if (nrow(families_data) > 0) {
      # Color coding: zero cost = orange, regular cost = green, NoInstanceType = blue
      families_data <- families_data %>%
        dplyr::mutate(
          bar_color = dplyr::case_when(
            family == "NoInstanceType" ~ 'lightblue',
            cost_usd == 0 ~ 'orange',
            TRUE ~ 'lightgreen'
          )
        )

      # Ensure we show all families including zero-cost ones
      max_cost <- max(families_data$cost_usd)
      has_zero_cost <- any(families_data$cost_usd <= 0.001)

      # For display purposes, show hours for zero-cost families
      families_data <- families_data %>%
        dplyr::mutate(
          display_value = ifelse(cost_usd <= 0.001, hours / 1000, cost_usd),  # Scale hours down
          family_short = stringr::str_trunc(family, 25)  # Truncate long family names
        )

      max_display <- max(families_data$display_value)
      if (max_display == 0) {
        x_range <- c(-0.1, 5)
      } else if (has_zero_cost) {
        x_range <- c(-max_display * 0.05, max_display * 1.1)
      } else {
        x_range <- c(0, max_display * 1.1)
      }

      plot_ly(families_data, x = ~display_value, y = ~reorder(family_short, cost_usd + hours/10000),
              type = 'bar', orientation = 'h', marker = list(color = ~bar_color),
              text = ~paste("Family:", family, "<br>Cost: $", round(cost_usd, 6), "<br>Hours:", round(hours, 1)),
              hovertemplate = "%{text}<extra></extra>") %>%
          layout(
            title = "EC2 Cost by Instance Family (Blue=NoInstanceType shows Hours/1000, Others show Cost) - Filtered by Date Range",
            xaxis = list(title = "Cost (USD) / Hours (scaled)", range = x_range),
            yaxis = list(title = "Instance Family", tickfont = list(size = 10)),
            margin = list(l = 200, r = 50, t = 80, b = 50)
          )
    } else {
      plot_ly() %>%
        layout(xaxis = list(visible = FALSE), yaxis = list(visible = FALSE))
    }
  })

  output$top_instances_plot <- renderPlotly({
    # Use daily data and aggregate by instance type for selected date range
    if (nrow(aws_data$ec2_instance_daily) > 0) {
      instance_summary <- aws_data$ec2_instance_daily %>%
        dplyr::filter(date >= input$global_date_range[1], date <= input$global_date_range[2]) %>%
        dplyr::group_by(instance_type) %>%
        dplyr::summarise(
          cost_usd = sum(cost_usd, na.rm = TRUE),
          hours = sum(hours, na.rm = TRUE),
          .groups = "drop"
        )

      # Get top instances by cost (non-NoInstanceType)
      top_cost_instances <- instance_summary %>%
        dplyr::filter(instance_type != "NoInstanceType") %>%
        dplyr::arrange(desc(cost_usd)) %>%
        dplyr::slice_head(n = 10)

      # Always include ALL NoInstanceType entries
      all_noinstancetype <- instance_summary %>%
        dplyr::filter(instance_type == "NoInstanceType") %>%
        dplyr::arrange(desc(hours))
    } else {
      # Fallback to aggregated data
      top_cost_instances <- aws_data$ec2_instance_types %>%
        dplyr::filter(instance_type != "NoInstanceType") %>%
        dplyr::arrange(desc(cost_usd)) %>%
        dplyr::slice_head(n = 10)

      all_noinstancetype <- aws_data$ec2_instance_types %>%
        dplyr::filter(instance_type == "NoInstanceType") %>%
        dplyr::arrange(desc(hours))
    }

      # Combine and prepare for plotting
      combined_instances <- dplyr::bind_rows(top_cost_instances, all_noinstancetype) %>%
        dplyr::mutate(
          total_cost = cost_usd,
          display_name = paste0(instance_type, " (", format(round(hours, 1), big.mark = ","), "h)"),
          display_name_short = stringr::str_trunc(paste0(instance_type, " (", format(round(hours, 1), big.mark = ","), "h)"), 35)
        ) %>%
        # Sort by cost first, then by hours for zero-cost items
        dplyr::arrange(desc(total_cost), desc(hours))

    if (nrow(combined_instances) > 0) {
      # Enhanced color coding
      combined_instances <- combined_instances %>%
        dplyr::mutate(
          bar_color = dplyr::case_when(
            instance_type == "NoInstanceType" ~ 'lightblue',
            total_cost == 0 ~ 'orange',
            TRUE ~ 'lightcoral'
          )
        )

      # Ensure proper x-axis range to show zero-cost items
      max_cost <- max(combined_instances$total_cost)
      # If we have NoInstanceType with zero cost, make sure it's visible
      has_zero_cost <- any(combined_instances$total_cost <= 0.001)
      if (max_cost == 0) {
        x_range <- c(-0.1, 5)  # Show negative range to make zero visible
      } else if (has_zero_cost) {
        x_range <- c(-max_cost * 0.05, max_cost * 1.1)  # Small negative range for zero-cost visibility
      } else {
        x_range <- c(0, max_cost * 1.1)
      }

      # For zero-cost items, use hours for bar length to make them visible
      combined_instances <- combined_instances %>%
        dplyr::mutate(
          display_value = ifelse(total_cost <= 0.001, hours / 1000, total_cost),  # Scale hours down for display
          display_type = ifelse(total_cost <= 0.001, "Hours (scaled)", "Cost")
        )

      plot_ly(combined_instances, x = ~display_value, y = ~reorder(display_name_short, total_cost + hours/100000),
              type = 'bar', orientation = 'h', marker = list(color = ~bar_color),
              text = ~paste("Instance:", instance_type, "<br>Cost: $", round(total_cost, 6), "<br>Hours:", round(hours, 3)),
              hovertemplate = "%{text}<extra></extra>") %>%
        layout(
          title = "Top EC2 Instance Types (Blue=NoInstanceType shows Hours/1000, Others show Cost) - Filtered by Date Range",
          xaxis = list(title = "Cost (USD) / Hours (scaled)", range = x_range),
          yaxis = list(title = "Instance Type", tickfont = list(size = 10)),
          margin = list(l = 250, r = 50, t = 80, b = 50)
        )
    } else {
      plot_ly() %>%
        layout(xaxis = list(visible = FALSE), yaxis = list(visible = FALSE))
    }
  })

  output$noinstance_service_breakdown_plot <- renderPlotly({
    if (nrow(aws_data$ec2_instance_daily) > 0) {
      # Filter to NoInstanceType only and aggregate by service (top 10)
      noinstance_data <- aws_data$ec2_instance_daily %>%
        dplyr::filter(instance_type == "NoInstanceType") %>%
        dplyr::filter(date >= input$global_date_range[1], date <= input$global_date_range[2]) %>%
        dplyr::group_by(service) %>%
        dplyr::summarise(
          total_cost = sum(cost_usd, na.rm = TRUE),
          total_hours = sum(hours, na.rm = TRUE),
          .groups = "drop"
        ) %>%
        dplyr::arrange(desc(total_cost)) %>%
        dplyr::slice_head(n = 10)  # Show only top 10 services by cost

      if (nrow(noinstance_data) > 0 && sum(noinstance_data$total_cost) > 0) {
        # Color services differently
        noinstance_data <- noinstance_data %>%
          dplyr::mutate(
            service_short = stringr::str_trunc(service, 25),  # Truncate long service names
            bar_color = dplyr::case_when(
              stringr::str_detect(service, "Omics") ~ '#FF6B6B',      # Red for Omics
              stringr::str_detect(service, "EC2") ~ '#4ECDC4',        # Teal for EC2
              stringr::str_detect(service, "Elastic Block") ~ '#45B7D1',  # Blue for EBS
              stringr::str_detect(service, "Lambda") ~ '#96CEB4',     # Green for Lambda
              TRUE ~ '#FFEAA7'  # Yellow for others
            )
          )

        plot_ly(noinstance_data,
                x = ~total_cost,
                y = ~reorder(service_short, total_cost),
                type = 'bar',
                orientation = 'h',
                marker = list(color = ~bar_color),
                text = ~paste("Service:", service, "<br>Cost: $", round(total_cost, 2), "<br>Hours:", round(total_hours, 1)),
                hovertemplate = "%{text}<extra></extra>") %>%
          layout(
            title = "NoInstanceType Costs by Service (Top 10)",
            xaxis = list(title = "Cost (USD)"),
            yaxis = list(title = "Service"),
            margin = list(l = 280, r = 50, t = 80, b = 50)
          )
      } else {
        plot_ly() %>%
          layout(xaxis = list(visible = FALSE), yaxis = list(visible = FALSE))
      }
    } else {
      plot_ly() %>%
        layout(xaxis = list(visible = FALSE), yaxis = list(visible = FALSE))
    }
  })

  #output$ec2_region_plot <- renderPlotly({
  #  if (nrow(aws_data$ec2_cost_by_region) > 0) {
  #    # Aggregate EC2 cost by region (sum across dates) for selected date range
  #    region_data <- aws_data$ec2_cost_by_region %>%
  #      dplyr::mutate(date = as.Date(period_start)) %>%
  #      dplyr::filter(date >= input$global_date_range[1], date <= input$global_date_range[2]) %>%
  #      dplyr::group_by(region) %>%
  #      dplyr::summarise(total_cost = sum(amount_usd, na.rm = TRUE), .groups = "drop") %>%
  #      dplyr::filter(total_cost > 0) %>%  # Remove zero-cost regions
  #      dplyr::arrange(desc(total_cost))

      # Show all regions with costs, but if too many, show top 20
  #    if (nrow(region_data) > 20) {
  #      region_data <- region_data %>% dplyr::slice_head(n = 20)
  #      title_suffix <- " (Top 20)"
  #    } else {
  #      title_suffix <- " (All Regions)"
  #    }

  #    if (nrow(region_data) > 0) {
  #      plot_ly(region_data, x = ~total_cost, y = ~reorder(region, total_cost),
  #              type = 'bar', orientation = 'h',
  #              hovertemplate = paste0(
  #                "Region: %{y}<br>",
  #                "Total Cost: $%{x:,.2f}<br>",
  #                "<extra></extra>"
  #              )) %>%
  #      layout(
  #        title = paste0("EC2 Cost by Region", title_suffix, " - Filtered by Date Range"),
  #        xaxis = list(title = "Total Cost (USD)"),
  #        yaxis = list(title = "Region"),
  #        margin = list(l = 200, r = 50, t = 80, b = 50)
  #      )
  #    } else {
  #      plot_ly() %>%
  #        layout(xaxis = list(visible = FALSE), yaxis = list(visible = FALSE))
  #    }
  #  } else {
  #    plot_ly() %>%
  #      layout(xaxis = list(visible = FALSE), yaxis = list(visible = FALSE))
  #  }
  #})

  output$ec2_instance_trends_plot <- renderPlotly({
    if (nrow(aws_data$ec2_instance_daily) > 0) {
      # Filter to date range
      filtered_daily <- aws_data$ec2_instance_daily %>%
        dplyr::filter(date >= input$global_date_range[1], date <= input$global_date_range[2])

      # Get top instance types by total cost OR hours (to include NoInstanceType)
      instance_summary <- filtered_daily %>%
        dplyr::group_by(instance_type) %>%
        dplyr::summarise(
          total_cost = sum(cost_usd, na.rm = TRUE),
          total_hours = sum(hours, na.rm = TRUE),
          .groups = "drop"
        )

      # Get top 6 by cost (excluding NoInstanceType)
      top_by_cost <- instance_summary %>%
        dplyr::filter(instance_type != "NoInstanceType") %>%
        dplyr::arrange(desc(total_cost)) %>%
        dplyr::slice_head(n = 6) %>%
        dplyr::pull(instance_type)

      # Always include ALL NoInstanceType instances (they have zero cost but significant hours)
      noinstance_types <- instance_summary %>%
        dplyr::filter(instance_type == "NoInstanceType") %>%
        dplyr::pull(instance_type)

      # Combine selected instances
      selected_instances <- unique(c(top_by_cost, noinstance_types))

      # Filter daily data to selected instances
      plot_data <- filtered_daily %>%
        dplyr::filter(instance_type %in% selected_instances) %>%
        dplyr::group_by(date, instance_type) %>%
        dplyr::summarise(daily_cost = sum(cost_usd, na.rm = TRUE),
                        daily_hours = sum(hours, na.rm = TRUE), .groups = "drop")

      if (nrow(plot_data) > 0) {
        # Create separate plots for cost and hours to handle NoInstanceType visibility
        # For NoInstanceType, we'll show hours/100 to make it visible alongside costs
        plot_data <- plot_data %>%
          dplyr::mutate(
            display_value = ifelse(instance_type == "NoInstanceType", daily_hours / 100, daily_cost),
            value_type = ifelse(instance_type == "NoInstanceType", "Hours/100", "Cost USD")
          )

        plot_ly(plot_data, x = ~date, y = ~display_value, color = ~instance_type,
                type = 'scatter', mode = 'lines+markers',
                text = ~paste("Date:", date, "<br>Instance:", instance_type, "<br>Cost: $", round(daily_cost, 6), "<br>Hours:", round(daily_hours, 1)),
                hovertemplate = "%{text}<extra></extra>") %>%
            layout(
              title = "EC2 Instance Trends (Top 6 Cost + NoInstanceType Hours/100)",
              xaxis = list(title = "Date"),
              yaxis = list(title = "Daily Cost (USD) / Hours (scaled)"),
              hovermode = 'x unified',
              margin = list(l = 100, r = 50, t = 80, b = 100)
            )
      } else {
        plot_ly() %>%
          layout(xaxis = list(visible = FALSE), yaxis = list(visible = FALSE))
      }
    } else {
      plot_ly() %>%
        layout(xaxis = list(visible = FALSE), yaxis = list(visible = FALSE))
    }
  })

  output$ec2_instances_table <- DT::renderDataTable({
    if (nrow(aws_data$ec2_instance_daily) > 0) {
      # Show daily breakdown filtered by date range (now includes service info)
      table_data <- aws_data$ec2_instance_daily %>%
        dplyr::filter(date >= input$global_date_range[1], date <= input$global_date_range[2]) %>%
        dplyr::select(date, instance_type, service, hours, cost_usd) %>%
        dplyr::arrange(desc(date), desc(cost_usd)) %>%
        dplyr::mutate(
          cost_usd = round(cost_usd, 6),  # More precision for small costs
          hours = round(hours, 3)
        )

      # Create formatted column names
      colnames(table_data) <- c("Date", "Instance Type", "Service", "Hours", "Cost (USD)")

      DT::datatable(
        table_data,
        extensions = c('Buttons', 'Scroller'),
        options = list(
          pageLength = 15,
          scrollY = "300px",
          scrollX = TRUE,
          dom = 'Bfrtip',
          buttons = list(
            list(extend = 'csv', text = 'Download CSV', filename = paste0('ec2_instance_daily_details_', Sys.Date()))
          ),
          columnDefs = list(
            list(className = 'dt-center', targets = c(0, 3, 4)),  # Center align date, hours, cost columns
            list(width = '100px', targets = 0),  # Date column
            list(width = '150px', targets = 1),  # Instance type column
            list(width = '200px', targets = 2),  # Service column
            list(width = '80px', targets = 3),   # Hours column
            list(width = '100px', targets = 4)   # Cost column
          )
        ),
        rownames = FALSE,
        class = 'cell-border stripe hover'
      )
    } else {
      DT::datatable(
        data.frame(Message = "No data available for selected date range"),
        options = list(dom = 't'),
        rownames = FALSE
      )
    }
  })

  output$noinstance_daily_trends_plot <- renderPlotly({
    if (nrow(aws_data$ec2_instance_daily) > 0) {
      # NoInstanceType daily trends by service (top 5 services by cost)
      noinstance_daily <- aws_data$ec2_instance_daily %>%
        dplyr::filter(instance_type == "NoInstanceType") %>%
        dplyr::filter(date >= input$global_date_range[1], date <= input$global_date_range[2])

      if (nrow(noinstance_daily) > 0) {
        # Get top 5 services by total cost
        top_services <- noinstance_daily %>%
          dplyr::group_by(service) %>%
          dplyr::summarise(total_cost = sum(cost_usd, na.rm = TRUE), .groups = "drop") %>%
          dplyr::arrange(desc(total_cost)) %>%
          dplyr::slice_head(n = 5) %>%
          dplyr::pull(service)

        # Filter to top services and aggregate by date and service
        plot_data <- noinstance_daily %>%
          dplyr::filter(service %in% top_services) %>%
          dplyr::group_by(date, service) %>%
          dplyr::summarise(
            daily_cost = sum(cost_usd, na.rm = TRUE),
            daily_hours = sum(hours, na.rm = TRUE),
            .groups = "drop"
          ) %>%
          dplyr::mutate(service_short = stringr::str_trunc(service, 20))

        if (nrow(plot_data) > 0) {
          plot_ly(plot_data, x = ~date, y = ~daily_cost, color = ~service_short,
                  type = 'scatter', mode = 'lines+markers',
                  text = ~paste("Date:", date, "<br>Service:", service, "<br>Cost: $", round(daily_cost, 4), "<br>Hours:", round(daily_hours, 1)),
                  hovertemplate = "%{text}<extra></extra>") %>%
            layout(
              title = "NoInstanceType Daily Costs (Top 5 Services)",
              xaxis = list(title = "Date"),
              yaxis = list(title = "Daily Cost (USD)"),
              legend = list(orientation = "h", x = 0, y = -0.2),
              margin = list(l = 100, r = 50, t = 80, b = 140)
            )
        } else {
          plot_ly() %>%
            layout(xaxis = list(visible = FALSE), yaxis = list(visible = FALSE))
        }
      } else {
        plot_ly() %>%
          layout(xaxis = list(visible = FALSE), yaxis = list(visible = FALSE))
      }
    } else {
      plot_ly() %>%
        layout(xaxis = list(visible = FALSE), yaxis = list(visible = FALSE))
    }
  })

  # Storage Tab Outputs
  output$s3_total_cost <- renderValueBox({
    if (nrow(aws_data$s3_buckets) > 0 && "cost_usd" %in% colnames(aws_data$s3_buckets)) {
      total_cost <- sum(aws_data$s3_buckets$cost_usd, na.rm = TRUE)
      value_text <- paste0("$", format(round(total_cost, 0), big.mark = ","))
      subtitle_text <- "S3 Total Cost"
    } else if (nrow(aws_data$s3_buckets) > 0 && "standard_gib" %in% colnames(aws_data$s3_buckets)) {
      total_gib <- sum(aws_data$s3_buckets$standard_gib + ifelse(is.na(aws_data$s3_buckets$standard_ia_gib), 0, aws_data$s3_buckets$standard_ia_gib), na.rm = TRUE)
      value_text <- paste0(format(round(total_gib, 1), big.mark = ","), " GB")
      subtitle_text <- "S3 Total Storage (Cost N/A)"
    } else {
      value_text <- "No Data"
      subtitle_text <- "S3 Storage"
    }

    valueBox(
      value = value_text,
      subtitle = subtitle_text,
      icon = icon("cloud"),
      color = "blue"
    )
  })

  output$ebs_total_cost <- renderValueBox({
    if (nrow(aws_data$ebs_by_region) > 0 && "amount_usd" %in% colnames(aws_data$ebs_by_region)) {
      total_cost <- sum(aws_data$ebs_by_region$amount_usd, na.rm = TRUE)
      value_text <- paste0("$", format(round(total_cost, 0), big.mark = ","))
      subtitle_text <- "EBS Total Cost"
    } else if (nrow(aws_data$ebs_by_region) > 0 && "ebs_allocated_gib" %in% colnames(aws_data$ebs_by_region)) {
      total_gib <- sum(aws_data$ebs_by_region$ebs_allocated_gib, na.rm = TRUE)
      value_text <- paste0(format(round(total_gib, 1), big.mark = ","), " GB")
      subtitle_text <- "EBS Allocated Storage (Cost N/A)"
    } else {
      value_text <- "No Data"
      subtitle_text <- "EBS Storage"
    }

    valueBox(
      value = value_text,
      subtitle = subtitle_text,
      icon = icon("hdd"),
      color = "red"
    )
  })

  output$storage_total_cost <- renderValueBox({
    # Try to get cost data first, then fall back to storage size
    s3_has_cost <- nrow(aws_data$s3_buckets) > 0 && "cost_usd" %in% colnames(aws_data$s3_buckets)
    ebs_has_cost <- nrow(aws_data$ebs_by_region) > 0 && "amount_usd" %in% colnames(aws_data$ebs_by_region)

    if (s3_has_cost || ebs_has_cost) {
      s3_cost <- if (s3_has_cost) sum(aws_data$s3_buckets$cost_usd, na.rm = TRUE) else 0
      ebs_cost <- if (ebs_has_cost) sum(aws_data$ebs_by_region$amount_usd, na.rm = TRUE) else 0
      total_cost <- s3_cost + ebs_cost

      valueBox(
        value = paste0("$", format(round(total_cost, 0), big.mark = ",")),
        subtitle = "Total Storage Cost",
        icon = icon("database"),
        color = "yellow"
      )
    } else {
      # Fall back to storage size if available
      s3_gib <- if (nrow(aws_data$s3_buckets) > 0 && "standard_gib" %in% colnames(aws_data$s3_buckets)) {
        sum(aws_data$s3_buckets$standard_gib + ifelse(is.na(aws_data$s3_buckets$standard_ia_gib), 0, aws_data$s3_buckets$standard_ia_gib), na.rm = TRUE)
      } else { 0 }

      ebs_gib <- if (nrow(aws_data$ebs_by_region) > 0 && "ebs_allocated_gib" %in% colnames(aws_data$ebs_by_region)) {
        sum(aws_data$ebs_by_region$ebs_allocated_gib, na.rm = TRUE)
      } else { 0 }

      total_gib <- s3_gib + ebs_gib

      valueBox(
        value = paste0(format(round(total_gib, 1), big.mark = ","), " GB"),
        subtitle = "Total Storage Size (Cost N/A)",
        icon = icon("database"),
        color = "yellow"
      )
    }
  })

  output$s3_cost_plot <- renderPlotly({
    if (nrow(aws_data$s3_buckets) > 0) {
      # Check if we have cost_usd column, otherwise use storage size
      if ("cost_usd" %in% colnames(aws_data$s3_buckets) && any(aws_data$s3_buckets$cost_usd > 0, na.rm = TRUE)) {
        # Use cost data
        s3_data <- aws_data$s3_buckets %>%
          dplyr::filter(!is.na(cost_usd), cost_usd > 0) %>%
          dplyr::arrange(desc(cost_usd)) %>%
          dplyr::slice_head(n = 15)

        plot_ly(s3_data, x = ~cost_usd, y = ~reorder(bucket, cost_usd),
                type = 'bar', orientation = 'h',
                marker = list(color = 'lightblue')) %>%
          layout(
            title = "Top S3 Buckets by Cost",
            xaxis = list(title = "Cost (USD)"),
            yaxis = list(title = "Bucket Name"),
            margin = list(l = 200, r = 50, t = 60, b = 50)
          )
      } else if ("standard_gib" %in% colnames(aws_data$s3_buckets)) {
        # Use storage size as fallback
        s3_data <- aws_data$s3_buckets %>%
          dplyr::mutate(total_gib = standard_gib + ifelse(is.na(standard_ia_gib), 0, standard_ia_gib)) %>%
          dplyr::filter(!is.na(total_gib), total_gib > 0) %>%
          dplyr::arrange(desc(total_gib)) %>%
          dplyr::slice_head(n = 15)

        if (nrow(s3_data) > 0) {
          plot_ly(s3_data, x = ~total_gib, y = ~reorder(bucket, total_gib),
                  type = 'bar', orientation = 'h',
                  marker = list(color = 'lightblue')) %>%
            layout(
              title = "Top S3 Buckets by Storage Size (Cost data not available)",
              xaxis = list(title = "Storage (GB)"),
              yaxis = list(title = "Bucket Name"),
              margin = list(l = 200, r = 50, t = 60, b = 50)
            )
        } else {
          plot_ly() %>%
            layout(xaxis = list(visible = FALSE), yaxis = list(visible = FALSE))
        }
      } else {
        plot_ly() %>%
          layout(xaxis = list(visible = FALSE), yaxis = list(visible = FALSE))
      }
    } else {
      plot_ly() %>%
        layout(xaxis = list(visible = FALSE), yaxis = list(visible = FALSE))
    }
  })

  output$ebs_region_plot <- renderPlotly({
    if (nrow(aws_data$ebs_by_region) > 0) {
      # Check if we have amount_usd column, otherwise use allocated storage
      if ("amount_usd" %in% colnames(aws_data$ebs_by_region) && any(aws_data$ebs_by_region$amount_usd > 0, na.rm = TRUE)) {
        # Use cost data
        ebs_data <- aws_data$ebs_by_region %>%
          dplyr::filter(!is.na(amount_usd), amount_usd > 0) %>%
          dplyr::arrange(desc(amount_usd))

        plot_ly(ebs_data, x = ~amount_usd, y = ~reorder(region, amount_usd),
                type = 'bar', orientation = 'h',
                marker = list(color = 'lightcoral')) %>%
          layout(
            title = "EBS Cost by Region",
            xaxis = list(title = "Cost (USD)"),
            yaxis = list(title = "Region"),
            margin = list(l = 150, r = 50, t = 60, b = 50)
          )
      } else if ("ebs_allocated_gib" %in% colnames(aws_data$ebs_by_region)) {
        # Use allocated storage as fallback
        ebs_data <- aws_data$ebs_by_region %>%
          dplyr::filter(!is.na(ebs_allocated_gib), ebs_allocated_gib > 0) %>%
          dplyr::arrange(desc(ebs_allocated_gib))

        if (nrow(ebs_data) > 0) {
          plot_ly(ebs_data, x = ~ebs_allocated_gib, y = ~reorder(region, ebs_allocated_gib),
                  type = 'bar', orientation = 'h',
                  marker = list(color = 'lightcoral')) %>%
            layout(
              title = "EBS Allocated Storage by Region (Cost data not available)",
              xaxis = list(title = "Allocated Storage (GB)"),
              yaxis = list(title = "Region"),
              margin = list(l = 150, r = 50, t = 60, b = 50)
            )
        } else {
          plot_ly() %>%
            layout(xaxis = list(visible = FALSE), yaxis = list(visible = FALSE))
        }
      } else {
        plot_ly() %>%
          layout(xaxis = list(visible = FALSE), yaxis = list(visible = FALSE))
      }
    } else {
      plot_ly() %>%
        layout(xaxis = list(visible = FALSE), yaxis = list(visible = FALSE))
    }
  })

  output$s3_daily_breakdown_plot <- renderPlotly({
    # Check if s3_daily_costs.csv file exists
    s3_file_exists <- file.exists(file.path("verily_cost", "s3_daily_costs.csv"))

    if (!s3_file_exists) {
      # Show message when file doesn't exist due to permissions
      plot_ly() %>%
        add_annotations(
          text = "S3 daily cost data not available<br>Requires additional AWS permissions:<br>- S3 service access in Cost Explorer API",
          x = 0.5, y = 0.5, xref = "paper", yref = "paper",
          showarrow = FALSE, font = list(size = 14, color = "gray")
        ) %>%
        layout(
          xaxis = list(visible = FALSE),
          yaxis = list(visible = FALSE),
          plot_bgcolor = 'rgba(0,0,0,0)',
          paper_bgcolor = 'rgba(0,0,0,0)'
        )
    } else if (nrow(aws_data$s3_daily_costs) > 0) {
      # Filter S3 daily costs by date range and show top usage types
      s3_breakdown <- aws_data$s3_daily_costs %>%
        dplyr::filter(date >= input$global_date_range[1], date <= input$global_date_range[2]) %>%
        dplyr::group_by(usage_type) %>%
        dplyr::summarise(total_cost = sum(cost_usd, na.rm = TRUE), .groups = "drop") %>%
        dplyr::filter(total_cost > 0) %>%
        dplyr::arrange(desc(total_cost)) %>%
        dplyr::slice_head(n = 10) %>%
        dplyr::mutate(usage_type_short = stringr::str_trunc(usage_type, 25))

      if (nrow(s3_breakdown) > 0) {
        plot_ly(s3_breakdown, x = ~total_cost, y = ~reorder(usage_type_short, total_cost),
                type = 'bar', orientation = 'h',
                marker = list(color = 'lightblue'),
                text = ~paste("Usage Type:", usage_type, "<br>Total Cost: $", round(total_cost, 2)),
                hovertemplate = "%{text}<extra></extra>") %>%
          layout(
            title = "S3 Costs by Usage Type (Top 10)",
            xaxis = list(title = "Total Cost (USD)"),
            yaxis = list(title = "Usage Type"),
            margin = list(l = 200, r = 50, t = 60, b = 50)
          )
      } else {
        plot_ly() %>%
          add_annotations(
            text = "No S3 cost data available for selected date range",
            x = 0.5, y = 0.5, xref = "paper", yref = "paper",
            showarrow = FALSE, font = list(size = 14, color = "gray")
          ) %>%
          layout(xaxis = list(visible = FALSE), yaxis = list(visible = FALSE))
      }
    } else {
      plot_ly() %>%
        add_annotations(
          text = "S3 daily cost data file is empty",
          x = 0.5, y = 0.5, xref = "paper", yref = "paper",
          showarrow = FALSE, font = list(size = 14, color = "gray")
        ) %>%
        layout(xaxis = list(visible = FALSE), yaxis = list(visible = FALSE))
    }
  })

  output$storage_trends_plot <- renderPlotly({
    # Check for daily cost files existence
    s3_file_exists <- file.exists(file.path("verily_cost", "s3_daily_costs.csv"))
    ebs_file_exists <- file.exists(file.path("verily_cost", "ebs_daily_costs.csv"))

    date_range <- input$global_date_range
    storage_daily_data <- data.frame()

    # Add S3 daily costs if file exists and data is available
    if (s3_file_exists && nrow(aws_data$s3_daily_costs) > 0) {
      s3_filtered <- aws_data$s3_daily_costs %>%
        dplyr::filter(date >= date_range[1], date <= date_range[2]) %>%
        dplyr::group_by(date) %>%
        dplyr::summarise(daily_cost = sum(cost_usd, na.rm = TRUE), .groups = "drop") %>%
        dplyr::mutate(service = "S3")
      storage_daily_data <- dplyr::bind_rows(storage_daily_data, s3_filtered)
    }

    # Add EBS daily costs if file exists and data is available
    if (ebs_file_exists && nrow(aws_data$ebs_daily_costs) > 0) {
      ebs_filtered <- aws_data$ebs_daily_costs %>%
        dplyr::filter(date >= date_range[1], date <= date_range[2]) %>%
        dplyr::group_by(date) %>%
        dplyr::summarise(daily_cost = sum(cost_usd, na.rm = TRUE), .groups = "drop") %>%
        dplyr::mutate(service = "EBS")
      storage_daily_data <- dplyr::bind_rows(storage_daily_data, ebs_filtered)
    }

    # If no daily storage data available, fall back to aggregated Storage category
    if (nrow(storage_daily_data) == 0) {
      storage_daily_data <- global_filtered_daily_data() %>%
        dplyr::filter(category == "Storage") %>%
        dplyr::select(date, daily_cost = amount_usd) %>%
        dplyr::mutate(service = "Storage (Aggregated)")
    }

    if (nrow(storage_daily_data) > 0) {
      # Show daily data without monthly aggregation
      plot_ly(storage_daily_data, x = ~date, y = ~daily_cost, color = ~service,
              type = 'scatter', mode = 'lines+markers') %>%
        layout(
          title = "Daily Storage Costs Over Time",
          xaxis = list(title = "Date"),
          yaxis = list(title = "Daily Cost (USD)"),
          hovermode = 'x unified',
          margin = list(l = 80, r = 50, t = 60, b = 80)
        )
    } else {
      plot_ly() %>%
        add_annotations(
          text = "No storage cost data available<br>Missing daily S3/EBS cost files due to AWS permissions",
          x = 0.5, y = 0.5, xref = "paper", yref = "paper",
          showarrow = FALSE, font = list(size = 14, color = "gray")
        ) %>%
        layout(
          xaxis = list(visible = FALSE),
          yaxis = list(visible = FALSE),
          plot_bgcolor = 'rgba(0,0,0,0)',
          paper_bgcolor = 'rgba(0,0,0,0)'
        )
    }
  })

  # EC2-Other Tab Outputs
  #output$ec2_other_total_cost <- renderValueBox({
  #  if (nrow(aws_data$ec2_other_usage_lines) > 0) {
  #    date_range <- input$global_date_range
  #    total_cost <- aws_data$ec2_other_usage_lines %>%
  #      dplyr::mutate(period_start = as.Date(period_start)) %>%
  #      dplyr::filter(period_start >= date_range[1], period_start <= date_range[2]) %>%
  #      dplyr::summarise(total_cost = sum(amount_usd, na.rm = TRUE)) %>%
  #      dplyr::pull(total_cost)
  #  } else {
  #    total_cost <- 0
  #  }
  #  valueBox(
  #    value = paste0("$", format(round(total_cost, 0), big.mark = ",")),
  #    subtitle = "EC2-Other Total Cost (Filtered)",
  #    icon = icon("cogs"),
  #    color = "blue"
  #  )
  #})

  #output$ec2_other_categories_count <- renderValueBox({
  #  if (nrow(aws_data$ec2_other_usage_lines) > 0) {
  #    date_range <- input$global_date_range
  #    count <- aws_data$ec2_other_usage_lines %>%
  #      dplyr::mutate(period_start = as.Date(period_start)) %>%
  #      dplyr::filter(period_start >= date_range[1], period_start <= date_range[2]) %>%
  #      dplyr::distinct(category) %>%
  #      nrow()
  #  } else {
  #    count <- 0
  #  }
  #  valueBox(
  #    value = count,
  #    subtitle = "Categories (Filtered)",
  #    icon = icon("list"),
  #    color = "green"
  #  )
  #})

  #output$ec2_other_usage_types_count <- renderValueBox({
  #  if (nrow(aws_data$ec2_other_usage_lines) > 0) {
  #    date_range <- input$global_date_range
  #    count <- aws_data$ec2_other_usage_lines %>%
  #      dplyr::mutate(period_start = as.Date(period_start)) %>%
  #      dplyr::filter(period_start >= date_range[1], period_start <= date_range[2]) %>%
  #      dplyr::distinct(usage_type) %>%
  #      nrow()
  #  } else {
  #    count <- 0
  #  }
  #  valueBox(
  #    value = count,
  #    subtitle = "Usage Types (Filtered)",
  #    icon = icon("tags"),
  #    color = "yellow"
  #  )
  #})

  #output$ec2_other_categories_plot <- renderPlotly({
  #  if (nrow(aws_data$ec2_other_usage_lines) > 0) {
  #    # Filter by date range and aggregate by category
  #    date_range <- input$global_date_range

  #    filtered_data <- aws_data$ec2_other_usage_lines %>%
  #      dplyr::mutate(period_start = as.Date(period_start)) %>%
  #      dplyr::filter(period_start >= date_range[1], period_start <= date_range[2]) %>%
  #      dplyr::group_by(category) %>%
  #      dplyr::summarise(amount_usd = sum(amount_usd, na.rm = TRUE), .groups = "drop") %>%
  #      dplyr::filter(amount_usd > 0)

  #    if (nrow(filtered_data) > 0) {
  #      plot_ly(filtered_data, labels = ~category, values = ~amount_usd, type = 'pie') %>%
  #        layout(title = "EC2-Other Cost by Category (Filtered by Date Range)")
  #    } else {
  #      plot_ly() %>%
  #        add_text(x = 0.5, y = 0.5, text = "No EC2-Other data for selected date range") %>%
  #        layout(xaxis = list(visible = FALSE), yaxis = list(visible = FALSE))
  #    }
  #  } else {
  #    plot_ly() %>%
  #      add_text(x = 0.5, y = 0.5, text = "No EC2-Other categories data available") %>%
  #      layout(xaxis = list(visible = FALSE), yaxis = list(visible = FALSE))
  #  }
  #})

  #output$ec2_other_usage_plot <- renderPlotly({
  #  if (nrow(aws_data$ec2_other_usage_lines) > 0) {
  #    # Filter by date range and aggregate by usage_type
  #    date_range <- input$global_date_range

  #    filtered_data <- aws_data$ec2_other_usage_lines %>%
  #      dplyr::mutate(period_start = as.Date(period_start)) %>%
  #      dplyr::filter(period_start >= date_range[1], period_start <= date_range[2]) %>%
  #      dplyr::group_by(usage_type) %>%
  #      dplyr::summarise(amount_usd = sum(amount_usd, na.rm = TRUE), .groups = "drop") %>%
  #      dplyr::filter(amount_usd > 0) %>%
  #      dplyr::arrange(desc(amount_usd)) %>%
  #      dplyr::slice_head(n = 15)

  #    if (nrow(filtered_data) > 0) {
  #      plot_ly(filtered_data, x = ~amount_usd, y = ~reorder(usage_type, amount_usd),
  #              type = 'bar', orientation = 'h') %>%
  #        layout(
  #          title = "Top EC2-Other Usage Types (Filtered by Date Range)",
  #          xaxis = list(title = "Cost (USD)"),
  #          yaxis = list(title = "Usage Type"),
  #          margin = list(l = 150)
  #        )
  #    } else {
  #      plot_ly() %>%
  #        add_text(x = 0.5, y = 0.5, text = "No EC2-Other data for selected date range") %>%
  #        layout(xaxis = list(visible = FALSE), yaxis = list(visible = FALSE))
  #    }
  #  } else {
  #    plot_ly() %>%
  #      add_text(x = 0.5, y = 0.5, text = "No EC2-Other usage data available") %>%
  #      layout(xaxis = list(visible = FALSE), yaxis = list(visible = FALSE))
  #  }
  #})

  #output$ec2_other_table <- DT::renderDataTable({
  #  if (nrow(aws_data$ec2_other_usage_lines) > 0) {
  #    date_range <- input$global_date_range
  #    filtered_data <- aws_data$ec2_other_usage_lines %>%
  #      dplyr::mutate(period_start = as.Date(period_start)) %>%
  #      dplyr::filter(period_start >= date_range[1], period_start <= date_range[2]) %>%
  #      dplyr::arrange(desc(amount_usd))

  #    if (nrow(filtered_data) > 0) {
  #      filtered_data
  #    } else {
  #      data.frame(Message = "No EC2-Other data for selected date range")
  #    }
  #  } else {
  #    data.frame(Message = "No EC2-Other usage details available")
  #  }
  #}, extensions = 'Buttons',
  #options = list(
  #  pageLength = 15,
  #  scrollX = TRUE,
  #  dom = 'Bfrtip',
  #  buttons = list(
  #    list(extend = 'csv', filename = 'ec2_other_usage_details', text = 'Download CSV')
  #  )
  #))

  # Workspaces Tab Outputs
  output$workspace_total_cost <- renderValueBox({
    # Check if daily workspace data exists
    workspace_daily_exists <- file.exists(file.path("verily_cost", "workspaces_ec2_daily.csv"))

    if (workspace_daily_exists && nrow(aws_data$workspaces_ec2_daily) > 0) {
      date_range <- input$global_date_range
      total_cost <- aws_data$workspaces_ec2_daily %>%
        dplyr::mutate(date = as.Date(date)) %>%
        dplyr::filter(date >= date_range[1], date <= date_range[2]) %>%
        dplyr::summarise(total_cost = sum(cost_usd, na.rm = TRUE)) %>%
        dplyr::pull(total_cost)
      subtitle_text <- "Workspace Total Cost (Filtered)"
    } else {
      total_cost <- sum(aws_data$workspaces_ec2$cost_usd, na.rm = TRUE)
      subtitle_text <- "Workspace Total Cost (Aggregated)"
    }

    valueBox(
      value = paste0("$", format(round(total_cost, 0), big.mark = ",")),
      subtitle = subtitle_text,
      icon = icon("desktop"),
      color = "blue"
    )
  })

  output$workspace_count <- renderValueBox({
    count <- nrow(aws_data$workspaces_ec2)
    valueBox(
      value = count,
      subtitle = "Active Workspaces",
      icon = icon("users"),
      color = "green"
    )
  })

  output$workspace_avg_cost <- renderValueBox({
    avg_cost <- mean(aws_data$workspaces_ec2$cost_usd, na.rm = TRUE)
    valueBox(
      value = paste0("$", format(round(avg_cost, 2), nsmall = 2)),
      subtitle = "Avg Cost per Workspace",
      icon = icon("calculator"),
      color = "yellow"
    )
  })

  output$workspace_cost_plot <- renderPlotly({
    workspace_daily_exists <- file.exists(file.path("verily_cost", "workspaces_ec2_daily.csv"))

    if (workspace_daily_exists && nrow(aws_data$workspaces_ec2_daily) > 0) {
      # Use daily data with date filtering
      date_range <- input$global_date_range
      workspace_data <- aws_data$workspaces_ec2_daily %>%
        dplyr::mutate(date = as.Date(date)) %>%
        dplyr::filter(date >= date_range[1], date <= date_range[2]) %>%
        dplyr::group_by(workspace_id) %>%
        dplyr::summarise(total_cost = sum(cost_usd, na.rm = TRUE), .groups = "drop") %>%
        dplyr::filter(total_cost > 0) %>%
        dplyr::arrange(desc(total_cost)) %>%
        dplyr::slice_head(n = 15)

      if (nrow(workspace_data) > 0) {
        plot_ly(workspace_data, x = ~total_cost, y = ~reorder(workspace_id, total_cost),
                type = 'bar', orientation = 'h') %>%
          layout(
            title = "Top Workspaces by Cost (Daily Filtered)",
            xaxis = list(title = "Cost (USD)"),
            yaxis = list(title = "Workspace ID"),
            margin = list(l = 200)
          )
      } else {
        plot_ly() %>%
          add_text(x = 0.5, y = 0.5, text = "No workspace data for selected date range") %>%
          layout(xaxis = list(visible = FALSE), yaxis = list(visible = FALSE))
      }
    } else if (nrow(aws_data$workspaces_ec2) > 0) {
      # Fall back to aggregated data
      top_workspaces <- aws_data$workspaces_ec2 %>%
        dplyr::group_by(WorkspaceId) %>%
        dplyr::summarise(total_cost = sum(cost_usd, na.rm = TRUE), .groups = "drop") %>%
        dplyr::arrange(desc(total_cost)) %>%
        dplyr::slice_head(n = 15)

      plot_ly(top_workspaces, x = ~total_cost, y = ~reorder(WorkspaceId, total_cost),
              type = 'bar', orientation = 'h') %>%
        layout(
          title = "Top Workspaces by Cost (Aggregated - No Daily Data)",
          xaxis = list(title = "Cost (USD)"),
          yaxis = list(title = "Workspace ID"),
          margin = list(l = 200)
        )
    } else {
      plot_ly() %>%
        add_text(x = 0.5, y = 0.5, text = "No workspace data available") %>%
        layout(xaxis = list(visible = FALSE), yaxis = list(visible = FALSE))
    }
  })

  output$workspace_scatter_plot <- renderPlotly({
    if (nrow(aws_data$workspaces_ec2) > 0) {
      plot_ly(aws_data$workspaces_ec2, x = ~hours, y = ~cost_usd, type = 'scatter', mode = 'markers',
              text = ~WorkspaceId, hovertemplate = "Workspace: %{text}<br>Hours: %{x}<br>Cost: $%{y:.2f}<extra></extra>") %>%
        layout(
          title = "Workspace Hours vs Cost",
          xaxis = list(title = "Hours"),
          yaxis = list(title = "Cost (USD)")
        )
    } else {
      plot_ly() %>%
        add_text(x = 0.5, y = 0.5, text = "No workspace data available") %>%
        layout(xaxis = list(visible = FALSE), yaxis = list(visible = FALSE))
    }
  })

  output$workspace_table <- DT::renderDataTable({
    workspace_daily_exists <- file.exists(file.path("verily_cost", "workspaces_ec2_daily.csv"))

    if (workspace_daily_exists && nrow(aws_data$workspaces_ec2_daily) > 0) {
      date_range <- input$global_date_range
      filtered_data <- aws_data$workspaces_ec2_daily %>%
        dplyr::mutate(date = as.Date(date)) %>%
        dplyr::filter(date >= date_range[1], date <= date_range[2]) %>%
        dplyr::arrange(desc(cost_usd))

      if (nrow(filtered_data) > 0) {
        filtered_data
      } else {
        data.frame(Message = "No workspace data for selected date range")
      }
    } else {
      aws_data$workspaces_ec2 %>%
        dplyr::arrange(desc(cost_usd))
    }
  }, extensions = 'Buttons',
  options = list(
    pageLength = 15,
    scrollX = TRUE,
    dom = 'Bfrtip',
    buttons = list(
      list(extend = 'csv', filename = 'workspaces_ec2_details', text = 'Download CSV')
    )
  ))

  # Omics Tab Outputs
  output$has_omics_data <- reactive({
    nrow(aws_data$workspaces_omics) > 0
  })
  outputOptions(output, "has_omics_data", suspendWhenHidden = FALSE)

  output$omics_total_cost <- renderValueBox({
    # Check if daily omics data exists
    omics_daily_exists <- file.exists(file.path("verily_cost", "workspaces_omics_daily.csv"))

    if (omics_daily_exists && nrow(aws_data$workspaces_omics_daily) > 0) {
      date_range <- input$global_date_range
      total_cost <- aws_data$workspaces_omics_daily %>%
        dplyr::mutate(date = as.Date(date)) %>%
        dplyr::filter(date >= date_range[1], date <= date_range[2]) %>%
        dplyr::summarise(total_cost = sum(cost_usd, na.rm = TRUE)) %>%
        dplyr::pull(total_cost)
      subtitle_text <- "Omics Total Cost (Filtered)"
    } else {
      total_cost <- sum(aws_data$workspaces_omics$cost_usd, na.rm = TRUE)
      subtitle_text <- "Omics Total Cost (Aggregated)"
    }

    valueBox(
      value = paste0("$", format(round(total_cost, 0), big.mark = ",")),
      subtitle = subtitle_text,
      icon = icon("dna"),
      color = "blue"
    )
  })

  output$omics_count <- renderValueBox({
    count <- nrow(aws_data$workspaces_omics)
    valueBox(
      value = count,
      subtitle = "Omics Workspaces",
      icon = icon("flask"),
      color = "green"
    )
  })

  output$omics_avg_cost <- renderValueBox({
    avg_cost <- if (nrow(aws_data$workspaces_omics) > 0) {
      mean(aws_data$workspaces_omics$cost_usd, na.rm = TRUE)
    } else {
      0
    }
    valueBox(
      value = paste0("$", format(round(avg_cost, 2), nsmall = 2)),
      subtitle = "Avg Cost per Workspace",
      icon = icon("calculator"),
      color = "yellow"
    )
  })

  output$omics_cost_plot <- renderPlotly({
    omics_daily_exists <- file.exists(file.path("verily_cost", "workspaces_omics_daily.csv"))

    if (omics_daily_exists && nrow(aws_data$workspaces_omics_daily) > 0) {
      # Use daily data with date filtering
      date_range <- input$global_date_range
      omics_data <- aws_data$workspaces_omics_daily %>%
        dplyr::mutate(date = as.Date(date)) %>%
        dplyr::filter(date >= date_range[1], date <= date_range[2]) %>%
        dplyr::group_by(workspace_id) %>%
        dplyr::summarise(total_cost = sum(cost_usd, na.rm = TRUE), .groups = "drop") %>%
        dplyr::filter(total_cost > 0) %>%
        dplyr::arrange(desc(total_cost)) %>%
        dplyr::slice_head(n = 15)

      if (nrow(omics_data) > 0) {
        plot_ly(omics_data, x = ~total_cost, y = ~reorder(workspace_id, total_cost),
                type = 'bar', orientation = 'h') %>%
          layout(
            title = "Top Omics Workspaces by Cost (Daily Filtered)",
            xaxis = list(title = "Cost (USD)"),
            yaxis = list(title = "Workspace ID"),
            margin = list(l = 200)
          )
      } else {
        plot_ly() %>%
          add_text(x = 0.5, y = 0.5, text = "No Omics data for selected date range") %>%
          layout(xaxis = list(visible = FALSE), yaxis = list(visible = FALSE))
      }
    } else if (nrow(aws_data$workspaces_omics) > 0) {
      # Fall back to aggregated data
      top_omics <- aws_data$workspaces_omics %>%
        dplyr::group_by(WorkspaceId) %>%
        dplyr::summarise(total_cost = sum(cost_usd, na.rm = TRUE), .groups = "drop") %>%
        dplyr::arrange(desc(total_cost)) %>%
        dplyr::slice_head(n = 15)

      plot_ly(top_omics, x = ~total_cost, y = ~reorder(WorkspaceId, total_cost),
              type = 'bar', orientation = 'h') %>%
        layout(
          title = "Top Omics Workspaces by Cost (Aggregated - No Daily Data)",
          xaxis = list(title = "Cost (USD)"),
          yaxis = list(title = "Workspace ID"),
          margin = list(l = 200)
        )
    } else {
      plot_ly() %>%
        add_text(x = 0.5, y = 0.5, text = "No Omics workspace data available") %>%
        layout(xaxis = list(visible = FALSE), yaxis = list(visible = FALSE))
    }
  })

  output$omics_scatter_plot <- renderPlotly({
    if (nrow(aws_data$workspaces_omics) > 0) {
      plot_ly(aws_data$workspaces_omics, x = ~hours, y = ~cost_usd, type = 'scatter', mode = 'markers',
              text = ~WorkspaceId, hovertemplate = "Workspace: %{text}<br>Hours: %{x}<br>Cost: $%{y:.2f}<extra></extra>") %>%
        layout(
          title = "Omics Hours vs Cost",
          xaxis = list(title = "Hours"),
          yaxis = list(title = "Cost (USD)")
        )
    } else {
      plot_ly() %>%
        add_text(x = 0.5, y = 0.5, text = "No Omics workspace data available") %>%
        layout(xaxis = list(visible = FALSE), yaxis = list(visible = FALSE))
    }
  })

  output$omics_table <- DT::renderDataTable({
    omics_daily_exists <- file.exists(file.path("verily_cost", "workspaces_omics_daily.csv"))

    if (omics_daily_exists && nrow(aws_data$workspaces_omics_daily) > 0) {
      date_range <- input$global_date_range
      filtered_data <- aws_data$workspaces_omics_daily %>%
        dplyr::mutate(date = as.Date(date)) %>%
        dplyr::filter(date >= date_range[1], date <= date_range[2]) %>%
        dplyr::arrange(desc(cost_usd))

      if (nrow(filtered_data) > 0) {
        filtered_data
      } else {
        data.frame(Message = "No Omics data for selected date range")
      }
    } else {
      aws_data$workspaces_omics %>%
        dplyr::arrange(desc(cost_usd))
    }
  }, extensions = 'Buttons',
  options = list(
    pageLength = 15,
    scrollX = TRUE,
    dom = 'Bfrtip',
    buttons = list(
      list(extend = 'csv', filename = 'workspaces_omics_details', text = 'Download CSV')
    )
  ))
}

# Run the application
shinyApp(ui = ui, server = server)
