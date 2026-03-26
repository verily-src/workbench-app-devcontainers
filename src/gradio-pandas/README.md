# Gradio Pandas JupyterLab

A JupyterLab environment with Gradio for building interactive data applications. Write Gradio code in Jupyter notebooks and publish shareable web apps accessible to others.

## What's Included

- **JupyterLab**: Full-featured notebook environment on port 8888
- **Gradio**: Build interactive ML/data apps on port 7860
- **Data Science Libraries**: pandas, matplotlib, seaborn, plotly
- **jupyter-server-proxy**: Seamlessly proxy Gradio apps through JupyterLab
- **Cloud Integration**: AWS and GCP CLI tools pre-installed

## Ports

- **8888**: JupyterLab interface
- **7860**: Gradio apps (default Gradio port)

## Quick Start

### 1. Create a Gradio App in JupyterLab

Open a new notebook in JupyterLab and create your first Gradio app:

```python
import gradio as gr
import pandas as pd

def analyze_data(file):
    """Simple CSV analyzer"""
    df = pd.read_csv(file.name)
    summary = df.describe().to_html()
    return f"<h3>Data Summary</h3>{summary}"

# Create Gradio interface
demo = gr.Interface(
    fn=analyze_data,
    inputs=gr.File(label="Upload CSV"),
    outputs=gr.HTML(label="Analysis Results"),
    title="Pandas Data Analyzer",
    description="Upload a CSV file to see statistical summary"
)

# Launch on port 7860 (accessible to others)
demo.launch(
    server_name="0.0.0.0",  # Allow external access
    server_port=7860,        # Use the exposed port
    share=False              # Not needed in Workbench
)
```

### 2. Access Your Gradio App

Once launched, your Gradio app will be accessible at:
- **From Workbench UI**: Click the "Open" button and append `/gradio` or access port 7860
- **Direct URL**: `https://your-workbench-url:7860`

### 3. Example: Interactive Data Dashboard

```python
import gradio as gr
import pandas as pd
import plotly.express as px

def create_plot(csv_file, x_col, y_col, chart_type):
    """Create interactive plots from CSV data"""
    df = pd.read_csv(csv_file.name)

    if chart_type == "Scatter":
        fig = px.scatter(df, x=x_col, y=y_col)
    elif chart_type == "Line":
        fig = px.line(df, x=x_col, y=y_col)
    elif chart_type == "Bar":
        fig = px.bar(df, x=x_col, y=y_col)

    return fig

# Get column names from uploaded file
def update_columns(file):
    if file is None:
        return [], []
    df = pd.read_csv(file.name)
    cols = df.columns.tolist()
    return gr.Dropdown(choices=cols), gr.Dropdown(choices=cols)

with gr.Blocks() as demo:
    gr.Markdown("# Interactive Data Dashboard")

    with gr.Row():
        file_input = gr.File(label="Upload CSV")
        chart_type = gr.Radio(
            choices=["Scatter", "Line", "Bar"],
            label="Chart Type",
            value="Scatter"
        )

    with gr.Row():
        x_axis = gr.Dropdown(label="X Axis", choices=[])
        y_axis = gr.Dropdown(label="Y Axis", choices=[])

    plot_output = gr.Plot(label="Visualization")

    # Update column dropdowns when file is uploaded
    file_input.change(
        fn=update_columns,
        inputs=[file_input],
        outputs=[x_axis, y_axis]
    )

    # Create plot when inputs change
    inputs = [file_input, x_axis, y_axis, chart_type]
    for inp in inputs:
        inp.change(fn=create_plot, inputs=inputs, outputs=plot_output)

demo.launch(server_name="0.0.0.0", server_port=7860)
```

## Using Multiple Gradio Apps

If you need to run multiple Gradio apps, you can:

1. **Use different paths** (recommended):
```python
# App 1
demo1.launch(server_name="0.0.0.0", server_port=7860, root_path="/app1")

# App 2
demo2.launch(server_name="0.0.0.0", server_port=7860, root_path="/app2")
```

2. **Use Gradio Blocks to combine multiple interfaces**:
```python
import gradio as gr

with gr.Blocks() as demo:
    with gr.Tab("Data Analysis"):
        # Your analysis interface here
        pass

    with gr.Tab("Visualization"):
        # Your visualization interface here
        pass

    with gr.Tab("Model Prediction"):
        # Your ML model interface here
        pass

demo.launch(server_name="0.0.0.0", server_port=7860)
```

## Best Practices

### 1. Always Use the Correct Server Settings
```python
demo.launch(
    server_name="0.0.0.0",  # Required for external access
    server_port=7860,        # Use the exposed port
    share=False              # share=True not needed in Workbench
)
```

### 2. Handle File Uploads Properly
```python
def process_file(file):
    # Access uploaded file using file.name
    df = pd.read_csv(file.name)
    return df.head().to_html()
```

### 3. Use Gradio's Built-in Examples
```python
demo = gr.Interface(
    fn=your_function,
    inputs=gr.Textbox(),
    outputs=gr.Textbox(),
    examples=[
        ["Example input 1"],
        ["Example input 2"]
    ]
)
```

## Troubleshooting

### Gradio App Not Accessible

1. Ensure you're using `server_name="0.0.0.0"`
2. Verify port 7860 is specified in launch
3. Check that the app is running (look for "Running on local URL" in output)

### Port Already in Use

If port 7860 is busy, stop the existing Gradio app:
```python
demo.close()  # Close existing demo
demo.launch(server_name="0.0.0.0", server_port=7860)
```

### Large File Uploads

For large file uploads, increase the limit:
```python
demo.launch(
    server_name="0.0.0.0",
    server_port=7860,
    max_file_size="100mb"  # Default is 100mb
)
```

## Options

| Option | Description | Type | Default |
|--------|-------------|------|---------|
| cloud | Cloud provider (gcp or aws) | string | gcp |
| login | Whether to log in to workbench CLI | string | false |

## Resources

- [Gradio Documentation](https://www.gradio.app/docs)
- [Gradio Guides](https://www.gradio.app/guides)
- [Pandas Documentation](https://pandas.pydata.org/docs/)
- [Plotly Documentation](https://plotly.com/python/)

## Example Use Cases

- **Data Exploration Tools**: Upload CSV files and perform interactive analysis
- **ML Model Demos**: Create interfaces for model inference
- **Data Visualization Dashboards**: Build interactive charts and graphs
- **Data Cleaning Tools**: Interactive data preprocessing interfaces
- **Report Generators**: Generate automated reports from uploaded data

---

*Note: This app is designed for Verily Workbench. For local development, see the main repository README.*
