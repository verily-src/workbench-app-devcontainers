# Skill Index

**Read this file first to navigate available skills.**

---

## ⚡ Quick Navigation

| User Says... | Read This Skill |
|--------------|-----------------|
| "workflow failed" / "debug workflow" | `WORKFLOW_TROUBLESHOOT.md` |
| "create dashboard" / "visualize" / "Flask" | `DASHBOARD_BUILDER.md` |
| "create app" / "deploy app" | `CUSTOM_APP.md` |
| "single-cell" / "RNA-seq" / "scanpy" | `scientific/BIOINFORMATICS.md` |
| "molecule" / "drug" / "RDKit" / "ChEMBL" | `scientific/DRUG_DISCOVERY.md` |
| "gene" / "protein" / "variant" / "UniProt" | `scientific/GENOMICS_DATABASES.md` |
| "statistics" / "ML" / "plot" / "sklearn" | `scientific/DATA_ANALYSIS.md` |
| "clinical trial" / "PubMed" / "literature" | `scientific/CLINICAL.md` |

---

## Workbench Skills

Core skills for working within Verily Workbench:

| Skill | File | Description |
|-------|------|-------------|
| **Workflow Troubleshooting** | `WORKFLOW_TROUBLESHOOT.md` | Debug failed WDL/Nextflow workflows |
| **Dashboard Builder** | `DASHBOARD_BUILDER.md` | Create web apps, Flask, Streamlit |
| **Custom App** | `CUSTOM_APP.md` | Build deployable Workbench apps |

---

## Scientific Skills

Domain-specific skills for pharma/biotech research:

### 🧬 Bioinformatics (`scientific/BIOINFORMATICS.md`)
Single-cell analysis, differential expression, sequence analysis, RNA velocity.

**Packages:** scanpy, anndata, biopython, pydeseq2, scvelo

### 💊 Drug Discovery (`scientific/DRUG_DISCOVERY.md`)
Cheminformatics, molecular ML, bioactivity databases, target identification.

**Packages/APIs:** rdkit, deepchem, chembl, drugbank, opentargets

### 🔬 Genomics Databases (`scientific/GENOMICS_DATABASES.md`)
Gene annotations, protein data, variant interpretation, 3D structures.

**APIs:** ensembl, uniprot, clinvar, pdb

### 📊 Data Analysis (`scientific/DATA_ANALYSIS.md`)
Machine learning, statistics, visualization.

**Packages:** scikit-learn, statsmodels, plotly, seaborn

### 🏥 Clinical (`scientific/CLINICAL.md`)
Clinical trials, literature search, survival analysis.

**APIs:** clinicaltrials.gov, pubmed

---

## How to Use Skills

1. **Claude reads this index first** when you ask a scientific question
2. **Claude then reads the relevant domain index** (e.g., `BIOINFORMATICS.md`)
3. **Domain indexes link to detailed skill files** when needed

This hierarchy prevents context overload while ensuring Claude finds the right guidance.

---

## Adding New Skills

To add skills from [claude-scientific-skills](https://github.com/K-Dense-AI/claude-scientific-skills):

1. Copy the `SKILL.md` file to `scientific/<skill-name>.md`
2. Add an entry to the relevant domain index
3. Update this index if adding a new category
