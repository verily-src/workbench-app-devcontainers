# Deployment Guide

## Quick Deploy to Workbench

### Option 1: Deploy from GitHub (Recommended)

1. **Push this repository to GitHub**:
   ```bash
   cd /home/jupyter/cohort-multimodal-dashboard
   git init
   git add .
   git commit -m "Initial commit: Cohort Multimodal Dashboard"
   git remote add origin <your-github-repo-url>
   git push -u origin main
   ```

2. **Create Custom App in Workbench**:
   - Navigate to your Workbench workspace
   - Click **Apps** → **Create Custom App**
   - Fill in:
     - **Name**: `Cohort Multimodal Dashboard`
     - **Repository URL**: `https://github.com/<your-org>/cohort-multimodal-dashboard.git`
     - **Branch**: `main`
     - **Folder path**: `.` (root)
     - **Machine type**: `n1-highmem-2` (recommended)
     - **Disk size**: 50 GB

3. **Wait for build** (first build takes ~5-10 minutes)

4. **Access your app**:
   ```bash
   # Get your app UUID
   wb app list --format=json | jq -r '.[] | select(.status == "RUNNING") | .id' | head -1
   
   # Access at:
   # https://workbench.verily.com/app/<APP_UUID>/proxy/8080/
   ```

### Option 2: Deploy from Local Directory

If you can't push to GitHub, you can copy this directory to a Git repository that Workbench can access, or use the Workbench Git repository feature.

## Local Testing Before Deploy

### Prerequisites
- Python 3.10+
- Node.js 18+
- Access to `wb-spotless-eggplant-4340` BigQuery project

### Setup

```bash
cd /home/jupyter/cohort-multimodal-dashboard

# Backend
cd backend
python3 -m venv .venv
.venv/bin/pip install -e .

# Frontend
cd ../frontend
npm install --legacy-peer-deps
npm run build

# Start server
cd ../backend
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Access at: `http://localhost:8080`

### Development Mode (Hot Reload)

**Terminal 1 - Backend**:
```bash
cd backend
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload
```

**Terminal 2 - Frontend**:
```bash
cd frontend
npm run dev  # Dev server on :5173, proxies /api to :8080
```

Access at: `http://localhost:5173`

## Docker Build Test (matches Workbench deployment)

```bash
cd /home/jupyter/cohort-multimodal-dashboard

# Create network
docker network create app-network

# Build and run
docker compose up --build

# Access at http://localhost:8080
```

## Troubleshooting

### App won't start
- Check Workbench app logs: `wb app logs <app-name>`
- Verify the repository branch is `main` and path is `.`
- Ensure Docker build succeeds locally first

### API errors
- Verify workspace has access to BigQuery datasets:
  - `wb-spotless-eggplant-4340.analysis.DIAGNOSES`
  - `wb-spotless-eggplant-4340.crf.VS`
  - `wb-spotless-eggplant-4340.sensordata.*`

### Frontend not loading
- Check browser console for errors
- Verify Workbench proxy URL format: `/app/<UUID>/proxy/8080/`
- Clear browser cache

### No data showing
- Ensure cohort filters match available data
- Check BigQuery permissions
- Review backend logs for query errors

## Environment Variables

Set these in `docker-compose.yaml` or Workbench app config:

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_ENV` | `dev` | Environment (`dev` or `prod`) |
| `USE_DEMO_TABLES` | `true` | Use demo tables |
| `BQ_MAX_BYTES_BILLED` | 2 TB | BigQuery cost guardrail |

## Data Requirements

The app expects these BigQuery tables:

### Clinical Data
- `{project}.analysis.DIAGNOSES` - Clinical labels, demographics, medications
  - Columns: `USUBJID`, `sex`, `age_at_enrollment`, `race`
  - Disease columns: `mh_*`, `der_hx_*`
  - Medication columns: `cm_acei`, `cm_arb`, `cm_bb`, `cm_ccb`, `cm_diuretics`

- `{project}.crf.VS` - Vital signs from physician visits
  - Columns: `USUBJID`, `VISITNUM`, `VISIT`, `study_day`
  - Vitals: `vs_sbp1_mmhg`, `vs_dbp1_mmhg`, `vs_pulse_bpm`

### Sensor Data
- `{project}.sensordata.STEP` - Step count data
- `{project}.sensordata.SLPMET` - Sleep metrics
- `{project}.sensordata.HEMET` - Heart rate variability
- `{project}.sensordata.AMCLASS` - Activity classification (walking bouts)

## Support

For issues:
- Workbench Support: support@workbench.verily.com
- Workbench Docs: https://support.workbench.verily.com
