# Setup Guide: Data Profiling Custom App in Workbench

## Overview

This custom app is a **JupyterLab-based application** that automatically:
1. **Reads data** from your Workbench data collection (GCS bucket)
2. **Loads the data** into a pandas DataFrame
3. **Generates a comprehensive data profiling report** using the `ydata-profiling` library

The app works with **any CSV file structure** - no hardcoded column names required!

---

## How to Set Up the Custom App in Workbench

### Prerequisites
- A Workbench workspace
- Access to a data collection (GCS bucket) with your data file
- Your forked repository: `https://github.com/SIVerilyDP/workbench-app-devcontainers`

### Step-by-Step Setup

#### 1. **Fork the Repository** (Already Done ✅)
   - Your fork: `https://github.com/SIVerilyDP/workbench-app-devcontainers`
   - The app template is located in: `src/lab-results-analyzer-dev/`

#### 2. **Create Custom App in Workbench UI**

   a. **Navigate to Workbench Apps**
      - Go to your Workbench workspace
      - Click on "Apps" or "Cloud Apps" in the navigation
      - Click "Create App" or "Add Custom App"

   b. **Select Dev Container Method**
      - Choose "Custom App" or "Dev Container" option
      - Select "From Git Repository"

   c. **Configure the App**
      - **Repository URL**: `https://github.com/SIVerilyDP/workbench-app-devcontainers`
      - **Branch**: `master` (or your preferred branch)
      - **Template Path**: `src/lab-results-analyzer-dev`
      - **Template Name**: `lab-results-analyzer-dev` (should auto-detect from `devcontainer-template.json`)

   d. **Set Template Options** (if prompted)
      - **Cloud**: `gcp` (or `aws` if using AWS)
      - **Login**: `false` (unless you need CLI login)

   e. **Create the App**
      - Click "Create" or "Deploy"
      - Wait for the app to build and start (this may take a few minutes)

#### 3. **Access Your App**

   - Once the app is running, click "Open" or access it via the app URL
   - You'll see JupyterLab interface with:
     - `Lab_Results_Analysis.ipynb` - The main notebook
     - `run_data_profiling.py` - The Python script (alternative to notebook)
     - `README.md` - Documentation

---

## What the Custom App Does

### Architecture

The app uses:
- **Docker Container**: `jupyter/scipy-notebook` (includes Python, pandas, numpy, matplotlib, seaborn)
- **Port**: 8888 (JupyterLab web interface)
- **User**: `jovyan` (Jupyter user)
- **Network**: `app-network` (Workbench requirement)

### Data Flow

```
┌─────────────────────┐
│  GCS Bucket         │
│  (Data Collection)  │
│                     │
│  MUP_DPR_RY25...csv │
└──────────┬──────────┘
           │
           │ google-cloud-storage client
           │
           ▼
┌─────────────────────┐
│  Python Script/     │
│  Jupyter Notebook   │
│                     │
│  1. Load from GCS    │
│  2. Parse CSV       │
│  3. Create DataFrame│
└──────────┬──────────┘
           │
           │ pandas DataFrame
           │
           ▼
┌─────────────────────┐
│  ydata-profiling    │
│  Library            │
│                     │
│  Generate Report    │
└──────────┬──────────┘
           │
           │ HTML Report
           │
           ▼
┌─────────────────────┐
│  data_profile_      │
│  report.html        │
│                     │
│  Comprehensive      │
│  Data Analysis      │
└─────────────────────┘
```

### Key Features

#### 1. **Automatic GCS Access**
   - Uses Google Cloud Storage client library
   - Authenticates using Workbench's default credentials
   - Downloads data directly from your data collection bucket
   - No manual file uploads needed!

#### 2. **Generic Data Analysis**
   - Works with **any CSV structure** - no hardcoded columns
   - Automatically detects:
     - Data types (numeric, categorical, dates, etc.)
     - Missing values
     - Statistical distributions
     - Correlations between variables

#### 3. **Comprehensive Profiling Report**
   The `ydata-profiling` library generates a detailed HTML report including:

   **Overview Section:**
   - Dataset statistics (rows, columns, memory usage)
   - Variable types summary
   - Warnings and alerts

   **Variable Analysis** (for each column):
   - **Numeric columns**: Mean, median, std dev, min, max, quartiles, histograms, box plots
   - **Categorical columns**: Value counts, frequency tables, bar charts
   - **Date columns**: Range, frequency distributions
   - **Missing values**: Count and percentage

   **Interactions:**
   - Correlation matrix (heatmap)
   - Scatter plots for correlated variables
   - Missing values pattern analysis

   **Sample Data:**
   - First and last rows
   - Duplicate rows detection

#### 4. **Automatic Dependency Installation**
   - Installs `google-cloud-storage` if missing
   - Installs `ydata-profiling` if missing
   - Patches numpy compatibility issues automatically

---

## Configuration

### Current Settings

The app is pre-configured with your data:

```python
GCS_BUCKET = "my-gcs-experimentation-bucker-wb-steady-parsnip-7109"
FILE_NAME = "MUP_DPR_RY25_P04_V10_DY23_Geo.csv"
FILE_FORMAT = "csv"
```

### To Change the Data Source

Edit either:
- **Notebook**: `Lab_Results_Analysis.ipynb` (Cell 8 - Configuration section)
- **Script**: `run_data_profiling.py` (Lines 18-20)

Change the values:
```python
GCS_BUCKET = "your-bucket-name"
FILE_NAME = "your-file.csv"
FILE_FORMAT = "csv"  # or "parquet", "json", "excel"
```

---

## Usage

### Option 1: Use the Notebook (Recommended)

1. Open `Lab_Results_Analysis.ipynb` in JupyterLab
2. Click **"Run All"** from the menu (or press `Shift+Enter` on each cell)
3. Wait for the report to generate (may take 1-5 minutes depending on data size)
4. The report will:
   - Display inline in the notebook (if supported)
   - Save as `data_profile_report.html` in the current directory
5. Download and open `data_profile_report.html` in your browser for the full interactive report

### Option 2: Use the Python Script

1. Open a terminal in JupyterLab
2. Run:
   ```bash
   python run_data_profiling.py
   ```
3. The script will:
   - Download data from GCS
   - Generate the profiling report
   - Save it as `data_profile_report.html`
   - Attempt to open it in your browser

---

## Technical Details

### Files Structure

```
lab-results-analyzer-dev/
├── .devcontainer.json          # Dev container configuration
├── docker-compose.yaml         # Docker Compose setup
├── devcontainer-template.json  # Template metadata for Workbench
├── Lab_Results_Analysis.ipynb  # Main Jupyter notebook
├── run_data_profiling.py       # Standalone Python script
├── README.md                   # App documentation
└── archived/                   # Archived files (LLM attempts, etc.)
```

### Docker Configuration

- **Image**: `jupyter/scipy-notebook`
- **Container Name**: `application-server` (Workbench requirement)
- **Network**: `app-network` (external, created by Workbench)
- **Port**: `8888` (JupyterLab)
- **Volumes**: 
  - `.` → `/workspace` (app code)
  - `work` → `/home/jovyan/work` (persistent storage)

### Required Workbench Settings

The `docker-compose.yaml` includes Workbench-specific requirements:
- `cap_add: SYS_ADMIN` - For mounting workspace resources
- `devices: /dev/fuse` - For gcsfuse (if needed)
- `security_opt: apparmor:unconfined` - For file system access

---

## Troubleshooting

### Issue: "ModuleNotFoundError: No module named 'google.cloud'"
**Solution**: The app auto-installs this. If it fails, run manually:
```bash
pip install google-cloud-storage
```

### Issue: "ModuleNotFoundError: No module named 'ydata_profiling'"
**Solution**: The app auto-installs this. If it fails, run manually:
```bash
pip install ydata-profiling
```

### Issue: "TypeError: asarray() got an unexpected keyword argument 'copy'"
**Solution**: The app includes a numpy compatibility patch. This should be automatic.

### Issue: Data not loading from GCS
**Check**:
1. Bucket name is correct
2. File name is correct
3. You have read permissions on the data collection
4. The data collection is in the same GCP project as your Workbench workspace

### Issue: Report generation is slow
**Solution**: For large datasets (>100k rows), edit the notebook/script and set:
```python
profile = ProfileReport(df, minimal=True, ...)  # Faster, less detailed
```

---

## Next Steps

- **Customize the analysis**: Add your own analysis cells to the notebook
- **Change data source**: Update the GCS bucket and file name
- **Add visualizations**: Use matplotlib/seaborn for custom charts
- **Export results**: Save the report or export specific statistics

---

## Support

For issues or questions:
- Check the `README.md` in the app directory
- Review Workbench documentation on custom apps
- Check the main repository: https://github.com/verily-src/workbench-app-devcontainers

