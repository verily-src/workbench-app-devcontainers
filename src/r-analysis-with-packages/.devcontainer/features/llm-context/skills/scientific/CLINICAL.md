# Clinical Skills

**Trigger:** User asks about clinical trials, PubMed, literature search, survival analysis, or patient data.

---

## Quick Reference

| Task | Source | Access |
|------|--------|--------|
| Clinical trial data | ClinicalTrials.gov | REST API (v2) |
| Literature search | PubMed | E-utilities API |
| Survival analysis | lifelines | Python package |

---

## ClinicalTrials.gov

**Use for:** Finding trials by condition/drug, trial status, study design, recruiting locations.

### API v2 Queries

```python
import requests

BASE_URL = "https://clinicaltrials.gov/api/v2"

# Search studies
response = requests.get(f"{BASE_URL}/studies", params={
    "query.cond": "breast cancer",
    "query.intr": "pembrolizumab",
    "filter.overallStatus": "RECRUITING",
    "pageSize": 10
})
data = response.json()

for study in data['studies']:
    info = study['protocolSection']['identificationModule']
    status = study['protocolSection']['statusModule']
    print(f"{info['nctId']}: {info['briefTitle']}")
    print(f"  Status: {status['overallStatus']}")
```

### Get Study by NCT ID

```python
nct_id = "NCT04379596"
response = requests.get(f"{BASE_URL}/studies/{nct_id}")
study = response.json()

# Key sections
identification = study['protocolSection']['identificationModule']
status = study['protocolSection']['statusModule']
design = study['protocolSection']['designModule']
eligibility = study['protocolSection']['eligibilityModule']
outcomes = study['protocolSection'].get('outcomesModule', {})

print(f"Title: {identification['briefTitle']}")
print(f"Phase: {design.get('phases', ['N/A'])}")
print(f"Enrollment: {design.get('enrollmentInfo', {}).get('count', 'N/A')}")
```

### Search Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `query.cond` | Condition/disease | "lung cancer" |
| `query.intr` | Intervention/drug | "nivolumab" |
| `query.term` | General search | "checkpoint inhibitor" |
| `filter.overallStatus` | Trial status | "RECRUITING", "COMPLETED" |
| `filter.geo` | Location | "distance(39.0,-77.1,50mi)" |
| `filter.advanced` | Phase, age, etc. | "AREA[Phase]PHASE3" |

---

## PubMed (Literature Search)

**Use for:** Finding papers, abstracts, citation data.

### E-utilities API

```python
from Bio import Entrez

Entrez.email = "your.email@example.com"

# Search PubMed
handle = Entrez.esearch(
    db="pubmed",
    term="CRISPR cancer therapy[Title/Abstract] AND 2023[pdat]",
    retmax=20
)
record = Entrez.read(handle)
pmids = record['IdList']
print(f"Found {record['Count']} articles")

# Fetch abstracts
handle = Entrez.efetch(db="pubmed", id=pmids, rettype="abstract", retmode="text")
abstracts = handle.read()
print(abstracts)

# Fetch structured data
handle = Entrez.efetch(db="pubmed", id=pmids[:5], rettype="xml", retmode="xml")
from Bio import Medline
records = Medline.parse(handle)
for record in records:
    print(f"Title: {record.get('TI', 'N/A')}")
    print(f"Authors: {', '.join(record.get('AU', []))}")
    print(f"Journal: {record.get('JT', 'N/A')}")
    print()
```

### Search Syntax

| Syntax | Description | Example |
|--------|-------------|---------|
| `[Title]` | Search title only | "cancer[Title]" |
| `[Title/Abstract]` | Title or abstract | "EGFR[Title/Abstract]" |
| `[Author]` | Author name | "Smith J[Author]" |
| `[Journal]` | Journal name | "Nature[Journal]" |
| `[pdat]` | Publication date | "2023[pdat]" |
| `AND`, `OR`, `NOT` | Boolean operators | "cancer AND therapy" |
| `[MeSH Terms]` | MeSH vocabulary | "Neoplasms[MeSH Terms]" |

### REST API Alternative

```python
import requests

# E-utilities via REST
base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# Search
search_url = f"{base_url}/esearch.fcgi"
response = requests.get(search_url, params={
    "db": "pubmed",
    "term": "immunotherapy melanoma",
    "retmode": "json",
    "retmax": 10
})
pmids = response.json()['esearchresult']['idlist']

# Fetch summaries
summary_url = f"{base_url}/esummary.fcgi"
response = requests.get(summary_url, params={
    "db": "pubmed",
    "id": ",".join(pmids),
    "retmode": "json"
})
summaries = response.json()['result']
```

---

## Survival Analysis (Lifelines)

**Use for:** Kaplan-Meier curves, Cox regression, time-to-event analysis.

### Kaplan-Meier Estimator

```python
from lifelines import KaplanMeierFitter
import matplotlib.pyplot as plt

# Data format: duration (time), event (1=occurred, 0=censored)
durations = [5, 6, 6, 2.5, 4, 4, 1, 2, 3, 4, 5, 6]
events = [1, 0, 0, 1, 1, 1, 1, 1, 0, 1, 0, 1]

kmf = KaplanMeierFitter()
kmf.fit(durations, events, label='Overall Survival')

# Plot survival curve
kmf.plot_survival_function()
plt.xlabel('Time (months)')
plt.ylabel('Survival Probability')
plt.title('Kaplan-Meier Survival Curve')
plt.show()

# Median survival
print(f"Median survival: {kmf.median_survival_time_}")

# Survival at specific time
print(f"Survival at 12 months: {kmf.predict(12):.2%}")
```

### Compare Groups

```python
from lifelines.statistics import logrank_test

# Group 1
kmf1 = KaplanMeierFitter()
kmf1.fit(durations_group1, events_group1, label='Treatment')

# Group 2
kmf2 = KaplanMeierFitter()
kmf2.fit(durations_group2, events_group2, label='Control')

# Plot both
ax = kmf1.plot_survival_function()
kmf2.plot_survival_function(ax=ax)
plt.show()

# Log-rank test
results = logrank_test(durations_group1, durations_group2, events_group1, events_group2)
print(f"Log-rank p-value: {results.p_value:.4f}")
```

### Cox Proportional Hazards

```python
from lifelines import CoxPHFitter
import pandas as pd

# Data with covariates
df = pd.DataFrame({
    'duration': durations,
    'event': events,
    'age': [45, 50, 55, 60, 48, 52, 58, 62, 49, 51, 53, 57],
    'treatment': [1, 1, 0, 0, 1, 0, 1, 0, 1, 0, 1, 0]
})

cph = CoxPHFitter()
cph.fit(df, duration_col='duration', event_col='event')

# Summary with hazard ratios
cph.print_summary()

# Hazard ratios
print(f"\nHazard Ratios:")
print(cph.hazard_ratios_)

# Plot coefficients
cph.plot()
plt.show()
```

---

## Installation

```bash
pip install biopython requests lifelines matplotlib
```

---

## See Also

- For drug/target data → `DRUG_DISCOVERY.md`
- For visualization → `DATA_ANALYSIS.md`
