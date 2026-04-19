# Cohort Multimodal Dashboard

Interactive dashboard for cohort-based multimodal analysis of BHS clinical and sensor data.

## Features

### 1. Cohort Selector
- Filter participants by clinical labels (sex, age, disease, medication)
- View cohort size and member list
- Export cohort as CSV

### 2. Device Data Visualization
- Cohort-aggregated sensor metrics over time (mean + stdev):
  - Step count
  - Sleep duration
  - Heart rate variability (HRV)
  - Walking bouts
  - Non-walking bouts
- Interactive Plotly charts with zoom/pan

### 3. Clinical Timeline
- Physician visit timeline for the cohort
- Aggregated clinical measurements:
  - Blood pressure (systolic/diastolic)
  - Heart rate
  - Visit dates and types
- Statistical overlays (mean, std ribbons)

## Architecture

```
React SPA (Vite + Tailwind + Plotly)  ──HTTPS──▶  Workbench proxy at :8080
                                                   │
                                                   ▼
                                      FastAPI + uvicorn
                                       │
                                       │   reads/writes
                                       ▼
                     wb-spotless-eggplant-4340.*
                     (BHS sensor + clinical tables)
```

- **Frontend**: React + TypeScript + Vite + TailwindCSS + Plotly.js
- **Backend**: FastAPI serving both API and built React SPA
- **Design**: Verily design system (colors, fonts, components)
- **Data**: BigQuery for clinical/sensor data

## Deploy as Workbench Custom App

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for complete deployment instructions.

**Quick Deploy**:
1. Push this repo to GitHub
2. Create Custom App in Workbench UI pointing to your GitHub repo
3. Access at: `https://workbench.verily.com/app/<APP_UUID>/proxy/8080/`

**Get your APP_UUID**:
```bash
wb app list --format=json | jq -r '.[] | select(.status == "RUNNING") | .id' | head -1
```

## Local Development

### Two-terminal dev mode (hot reload):

```bash
# Terminal 1: Backend
cd backend
python3.11 -m venv .venv
.venv/bin/pip install -e .[dev]
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload

# Terminal 2: Frontend
cd frontend
npm install
npm run dev   # Vite dev server on :5173, proxies /api to :8080
```

### Production-like local run:

```bash
cd frontend && npm run build && cd ..
cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080
# Access at http://localhost:8080
```

### Fully containerized (matches Workbench):

```bash
docker network create app-network
docker compose up --build
# Access at http://localhost:8080
```

## Project Structure

```
.
├── .devcontainer.json           Workbench devcontainer pointer
├── docker-compose.yaml          container_name: application-server
├── Dockerfile                   multi-stage: node build + python runtime
├── backend/                     FastAPI + BigQuery
│   ├── app/
│   │   ├── main.py              entrypoint; serves SPA + /api/*
│   │   ├── routers/             cohorts, device_data, clinical_data
│   │   ├── services/            bq.py (BigQuery service)
│   │   └── schemas/             Pydantic models
│   └── pyproject.toml
├── frontend/                    React + Vite + TS + Plotly + Tailwind
│   ├── src/
│   │   ├── pages/               CohortSelector · DeviceData · ClinicalTimeline
│   │   ├── components/          Reusable UI components
│   │   ├── api/                 typed clients + TanStack Query hooks
│   │   ├── App.tsx              Main app with navigation
│   │   └── main.tsx             React entry point
│   ├── package.json
│   └── vite.config.ts
└── README.md
```

## Data Sources

- **Clinical Labels**: `wb-spotless-eggplant-4340.analysis.DIAGNOSES`
- **Vital Signs**: `wb-spotless-eggplant-4340.crf.VS`
- **Sensor Data**: `wb-spotless-eggplant-4340.sensordata.*` (TBD)

## Tech Stack

- **Frontend**: React 19 + TypeScript + Vite + TailwindCSS + Plotly.js
- **Backend**: FastAPI + uvicorn
- **Data**: Google Cloud BigQuery
- **State Management**: TanStack Query
- **Styling**: Verily design system (teal primary, cream paper background)

## License

Internal. Confidential (BHS data).
