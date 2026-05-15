# Scientific Skills Index

**This file routes Claude to domain-specific scientific skills.**
Workbench skills (workflows, dashboards, custom apps) are handled directly by `CLAUDE.md`.

---

## ⚡ Quick Navigation

| User Says... | Read This Skill |
|--------------|-----------------|
| "single-cell" / "RNA-seq" / "scanpy" / "differential expression" | `scientific/BIOINFORMATICS.md` |
| "molecule" / "SMILES" / "drug" / "RDKit" / "ChEMBL" / "target" | `scientific/DRUG_DISCOVERY.md` |
| "gene" / "protein" / "variant" / "UniProt" / "Ensembl" / "PDB" | `scientific/GENOMICS_DATABASES.md` |
| "machine learning" / "sklearn" / "statistics" / "plot" | `scientific/DATA_ANALYSIS.md` |
| "clinical trial" / "PubMed" / "survival analysis" | `scientific/CLINICAL.md` |

---

## Domain Skills

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

## Adding New Skills

To add skills from [claude-scientific-skills](https://github.com/K-Dense-AI/claude-scientific-skills):

1. Copy the `SKILL.md` file to `scientific/<skill-name>.md`
2. Add a row to the Quick Navigation table above
3. Add a domain section below
