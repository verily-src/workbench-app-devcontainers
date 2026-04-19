# Features Overview

## What This Dashboard Does

A cohort-based multimodal dashboard that combines **clinical labels** and **sensor data** to enable population-level analysis of BHS participants.

### Key Difference from DBM-Explorer

| DBM-Explorer (myoung) | Cohort Multimodal Dashboard (yours) |
|----------------------|-------------------------------------|
| Single-patient workflow | **Cohort-based workflow** |
| Signal → Feature → Cohort | **Cohort → Multimodal Analysis** |
| Individual time series | **Aggregated metrics (mean ± std)** |
| Interactive signal selection | **Clinical label filtering** |
| Save features & cohorts | **Export cohorts & visualizations** |

## Workflow

### 1. **Cohort Selector** (`/cohort`)

**Select participants** by filtering clinical labels:
- **Demographics**: Sex, Age range
- **Disease**: Hypertension, Diabetes, CVD, CKD, Afib, COPD
- **Medication**: ACE inhibitors, ARBs, Beta blockers, CCBs, Diuretics

**Output**:
- Cohort size
- Member list table
- Export to CSV
- Auto-saved to localStorage for other pages

**Example**: "Show all female participants aged 50-70 with hypertension on beta blockers"

---

### 2. **Device Data** (`/device`)

**View cohort-aggregated sensor metrics** over time:

#### Metrics Shown:
1. **Daily Step Count** - Average steps per day
2. **Sleep Duration** - Total sleep time (minutes)
3. **Heart Rate Variability (HRV)** - RMSSD metric (ms)
4. **Walking Bouts** - Ambulatory activity episodes
5. **Non-Walking Bouts** - Other activity episodes

#### Visualization:
- **Line charts** with mean values
- **Ribbon bands** showing ±1 standard deviation
- **Interactive Plotly** charts (zoom, pan, hover)
- **Study day timeline** (x-axis)

**Example Use**: "For my cohort of 50 hypertensive patients, how does average daily step count change over the study period?"

---

### 3. **Clinical Timeline** (`/clinical`)

**View physician visit data** aggregated across the cohort:

#### Metrics Shown:
1. **Blood Pressure Timeline**:
   - Systolic BP (mean ± std)
   - Diastolic BP (mean ± std)
   - Reference lines for normal/hypertensive ranges
2. **Heart Rate Timeline**:
   - Pulse/HR (mean ± std)
3. **Visit Summary Table**:
   - Visit name, study day, BP, HR, participant count

#### Visualization:
- **Dual BP lines** (systolic + diastolic) with std ribbons
- **Reference lines**: Normal (<120 SBP), Stage 1 HTN (≥140 SBP)
- **Visit markers** on x-axis
- **Summary table** with mean ± std statistics

**Example Use**: "Track how average blood pressure changes across physician visits for my diabetic cohort"

---

## Integration of Multimodal Data

This dashboard uniquely combines:

| Data Source | Type | Purpose |
|-------------|------|---------|
| `analysis.DIAGNOSES` | **Clinical labels** | Cohort filtering & demographics |
| `crf.VS` | **Clinical measurements** | Visit-based BP, HR timeline |
| `sensordata.STEP` | **Wearable sensor** | Daily activity levels |
| `sensordata.SLPMET` | **Wearable sensor** | Sleep patterns |
| `sensordata.HEMET` | **Wearable sensor** | Cardiovascular variability |
| `sensordata.AMCLASS` | **Wearable sensor** | Activity classification |

**Key Insight**: See how **device-measured behavior** (steps, sleep, HRV) correlates with **clinical outcomes** (BP control, visit patterns) for specific patient populations.

---

## Use Cases

### Research Questions This Dashboard Answers:

1. **Population characterization**: "What's the average step count for hypertensive patients on ACE inhibitors?"

2. **Temporal trends**: "Does sleep duration change over time for diabetic participants?"

3. **Clinical-device correlation**: "How does HRV vary across physician visits for CVD patients?"

4. **Cohort comparison**: Select different cohorts and compare their device data side-by-side

5. **Treatment monitoring**: "Do participants on different BP medications show different activity patterns?"

---

## Technical Features

### Backend
- **FastAPI** with auto-generated OpenAPI docs (`/docs`)
- **BigQuery** cost guardrails (2 TB limit)
- **Pandas** for data aggregation
- **Pydantic** schemas for type safety
- **Modular routers**: cohorts, device_data, clinical_data

### Frontend
- **React 18** with TypeScript
- **TanStack Query** for data fetching/caching
- **Plotly.js** for interactive charts
- **Tailwind CSS** with Verily design system
- **LocalStorage** for cohort persistence across pages

### Design
- **Verily brand colors**: Teal primary, cream paper background
- **Responsive layout**: Works on laptop/desktop screens
- **Accessible**: Semantic HTML, ARIA labels
- **Consistent**: Matches DBM-explorer visual language

---

## Data Flow

```
User selects filters (sex, age, disease, meds)
          ↓
Backend queries DIAGNOSES table
          ↓
Returns cohort member list (USUBJIDs)
          ↓
Stored in localStorage
          ↓
Device Data / Clinical Timeline pages load
          ↓
Backend queries sensor/VS tables for those USUBJIDs
          ↓
Aggregates by study_day or VISITNUM (mean, std, count)
          ↓
Returns time-series data
          ↓
Frontend renders Plotly charts with ribbons
```

---

## Extending This Dashboard

### Add New Metrics:
1. Add query to `backend/app/routers/device_data.py`
2. Add chart to `frontend/src/pages/DeviceData.tsx`

### Add New Filters:
1. Add disease/medication to `DISEASE_MAP` or `MEDICATION_MAP` in `cohorts.py`
2. Add option to `<select>` in `CohortSelector.tsx`

### Add New Pages:
1. Create `frontend/src/pages/NewPage.tsx`
2. Add route to `frontend/src/App.tsx`
3. Add nav link to `NAV` array

### Customize BigQuery Tables:
- Update `settings.bhs_project` in `backend/app/config.py`
- Modify table names in routers

---

## Performance Notes

- **Cohort queries**: Sub-second for <1000 participants
- **Device data**: 1-5 seconds depending on date range and cohort size
- **Clinical timeline**: <1 second (fewer data points)
- **BigQuery cost**: ~$0.01-0.10 per query (estimate)

**Optimization tips**:
- Use smaller cohorts for faster queries
- Limit study_day ranges in device data
- Enable BigQuery clustering on USUBJID for production tables
