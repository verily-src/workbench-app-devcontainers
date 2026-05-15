# Workbench App Templates

Pre-built application templates for Verily Workbench with workspace resource integration.

## Available Templates

| Template | Description | Port | Complexity |
|----------|-------------|------|------------|
| [flask-api](./flask-api/) | REST API with Flask for data processing | 8080 | Simple |
| [streamlit-dashboard](./streamlit-dashboard/) | Interactive data dashboard with Streamlit | 8501 | Simple |
| [rshiny-dashboard](./rshiny-dashboard/) | R-based interactive dashboard with Shiny | 3838 | Simple |
| [file-processor](./file-processor/) | File upload, validation, and GCS storage | 8080 | Simple |

## Features

All templates include:

- ✅ **Workspace Integration**: Auto-discovery of GCS buckets and BigQuery datasets
- ✅ **Environment Variables**: `WORKBENCH_<resource_name>` for all resources
- ✅ **LLM Context**: Compatible with `llm-context` feature for Claude/Gemini
- ✅ **Standard Structure**: Consistent devcontainer configuration
- ✅ **Documentation**: README with usage examples

## Quick Start

1. Choose a template that matches your use case
2. Copy the template folder to your repository
3. Customize the application code
4. Deploy to Workbench

## Template Structure

Each template follows this structure:

```
template-name/
├── manifest.yaml              # Template metadata & capabilities
├── devcontainer-template.json # Workbench UI registration
├── .devcontainer.json         # Devcontainer configuration
├── docker-compose.yaml        # Container setup
├── Dockerfile                 # Build instructions
├── app/                       # Application code
│   ├── main.py (or app.R)
│   └── requirements.txt
└── README.md                  # Usage documentation
```

## Workspace Resource Access

### Python

```python
import os

# Get all workspace resources
resources = {
    k.replace("WORKBENCH_", ""): v 
    for k, v in os.environ.items() 
    if k.startswith("WORKBENCH_")
}

# Access specific resource
bucket_path = os.environ.get("WORKBENCH_my_bucket")
```

### R

```r
# Get all workspace resources
resources <- Sys.getenv()
workbench_vars <- resources[grepl("^WORKBENCH_", names(resources))]

# Access specific resource
bucket_path <- Sys.getenv("WORKBENCH_my_bucket")
```

## Customization

1. **Add Dependencies**: Edit `requirements.txt` (Python) or `Dockerfile` (R packages)
2. **Change Port**: Update `docker-compose.yaml` and `.devcontainer.json`
3. **Add Features**: Include additional devcontainer features in `.devcontainer.json`

## Deployment

### Via Workbench UI

1. Push your customized template to a GitHub repository
2. In Workbench, create a new app → Custom App
3. Enter repository URL, branch, and folder path
4. Launch the app

### Template Manifest

Each template includes a `manifest.yaml` with:
- **capabilities**: What the template can do
- **inputs**: Configuration options
- **complexity**: Simple, Medium, or Advanced
- **port**: Default exposed port

This manifest can be used by LLMs to select appropriate templates based on user requirements.
