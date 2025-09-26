# RAPIDS Jupyter (rapids)

A template to run RAPIDS-accelerated Jupyter environment on Workbench for GPU-accelerated data science workflows.

## Description

This template provides a containerized RAPIDS environment with Jupyter Lab, enabling GPU-accelerated data science libraries including:
- **cuDF**: GPU-accelerated DataFrames
- **cuML**: GPU-accelerated machine learning
- **cuGraph**: GPU-accelerated graph analytics  
- **cuSpatial**: GPU-accelerated spatial analytics
- **cuSignal**: GPU-accelerated signal processing
- **PyTorch**: Deep learning framework with GPU support

Based on the NVIDIA RAPIDS container image (`rapidsai/rapids:23.12-cuda11.8-runtime-ubuntu22.04-py3.10`).

## Prerequisites

- GPU-enabled virtual machine (NVIDIA GPU required)
- CUDA-compatible environment
- Docker with GPU runtime support

## Options

| Options Id | Description | Type | Default Value |
|-----|-----|-----|-----|
| cloud | VM cloud environment | string | gcp |
| login | Whether to log in to workbench CLI | string | false |

## Features

- **GPU Acceleration**: Leverages NVIDIA GPUs for data processing and machine learning
- **Complete RAPIDS Ecosystem**: All major RAPIDS libraries pre-installed
- **Jupyter Lab Interface**: Modern web-based interactive development environment
- **Volume Mounting**: Persistent workspace at `/workspace`
- **Port Forwarding**: Jupyter Lab accessible on port 8888
- **No Authentication**: Token-less access for development convenience

## Getting Started

1. Deploy this template on a GPU-enabled VM
2. Access Jupyter Lab at `http://localhost:8888`
3. Start building GPU-accelerated data science workflows!

## Example Usage

```python
import cudf
import cuml
import numpy as np

# Create a GPU DataFrame
df = cudf.DataFrame({'x': np.random.randn(1000000), 
                     'y': np.random.randn(1000000)})

# GPU-accelerated operations
result = df.x.mean()  # Computed on GPU
print(f"Mean: {result}")

# GPU-accelerated machine learning
from cuml.cluster import KMeans
kmeans = KMeans(n_clusters=5)
labels = kmeans.fit_predict(df[['x', 'y']])
```

## Customization

To add additional packages or modify the environment:

1. Uncomment and modify the `Dockerfile` 
2. Add your custom packages using `pip` or `conda`
3. Rebuild the container

## Performance Notes

- Ensure your VM has sufficient GPU memory for your workloads
- RAPIDS operations automatically use GPU when available
- For large datasets, consider data chunking and memory management

---

*Note: This template is optimized for NVIDIA GPU environments and requires CUDA-compatible hardware.*
