# Bioinformatics Skills

**Trigger:** User asks about single-cell analysis, RNA-seq, sequences, differential expression, or trajectory analysis.

---

## Quick Reference

| Task | Package | Quick Command |
|------|---------|---------------|
| Single-cell workflow | `scanpy` | `import scanpy as sc; adata = sc.read_h5ad('data.h5ad')` |
| Differential expression | `pydeseq2` | `from pydeseq2 import DeseqDataSet` |
| Sequence analysis | `biopython` | `from Bio import SeqIO` |
| RNA velocity | `scvelo` | `import scvelo as scv` |

---

## Scanpy (Single-Cell Analysis)

**Use for:** QC, normalization, PCA/UMAP, clustering, marker genes, cell type annotation.

### Standard Workflow

```python
import scanpy as sc

# Load data
adata = sc.read_h5ad('data.h5ad')  # or sc.read_10x_mtx('filtered_feature_bc_matrix/')

# QC
sc.pp.calculate_qc_metrics(adata, percent_top=None, log1p=False, inplace=True)
adata = adata[adata.obs['total_counts'] > 500]
adata = adata[adata.obs['pct_counts_mt'] < 20]

# Normalize & log transform
sc.pp.normalize_total(adata, target_sum=1e4)
sc.pp.log1p(adata)

# Find variable genes
sc.pp.highly_variable_genes(adata, n_top_genes=2000)
adata = adata[:, adata.var.highly_variable]

# PCA, neighbors, UMAP, clustering
sc.tl.pca(adata)
sc.pp.neighbors(adata, n_pcs=30)
sc.tl.umap(adata)
sc.tl.leiden(adata, resolution=0.5)

# Marker genes
sc.tl.rank_genes_groups(adata, 'leiden', method='wilcoxon')
sc.pl.rank_genes_groups(adata, n_genes=10)

# Visualization
sc.pl.umap(adata, color=['leiden', 'gene_of_interest'])
```

### Common File Formats
- `.h5ad` - AnnData format (standard)
- 10X Genomics: `filtered_feature_bc_matrix/`
- CSV: `sc.read_csv('counts.csv')`

---

## AnnData (Data Structure)

**Use for:** Creating, manipulating, and saving single-cell datasets.

```python
import anndata as ad
import pandas as pd
import numpy as np

# Create from scratch
adata = ad.AnnData(
    X=count_matrix,           # cells x genes
    obs=cell_metadata_df,     # cell annotations
    var=gene_metadata_df      # gene annotations
)

# Key attributes
adata.X                       # Expression matrix
adata.obs                     # Cell metadata (DataFrame)
adata.var                     # Gene metadata (DataFrame)
adata.obsm['X_umap']          # Embeddings
adata.uns                     # Unstructured data

# Subset
adata_subset = adata[adata.obs['cell_type'] == 'T cell', :]
adata_subset = adata[:, adata.var['highly_variable']]

# Save/load
adata.write('output.h5ad')
adata = ad.read_h5ad('output.h5ad')

# Concatenate datasets
adata_combined = ad.concat([adata1, adata2], join='outer')
```

---

## PyDESeq2 (Differential Expression)

**Use for:** Bulk RNA-seq differential expression analysis.

```python
import pandas as pd
from pydeseq2.dds import DeseqDataSet
from pydeseq2.ds import DeseqStats

# Load count matrix (genes x samples) and metadata
counts = pd.read_csv('counts.csv', index_col=0)
metadata = pd.read_csv('metadata.csv', index_col=0)

# Ensure sample order matches
counts = counts[metadata.index]

# Create DESeq dataset
dds = DeseqDataSet(
    counts=counts.T,  # samples x genes
    metadata=metadata,
    design_factors='condition'  # column in metadata
)

# Run DESeq
dds.deseq2()

# Get results
stat_res = DeseqStats(dds, contrast=['condition', 'treated', 'control'])
stat_res.summary()
results_df = stat_res.results_df

# Filter significant genes
sig_genes = results_df[(results_df['padj'] < 0.05) & (abs(results_df['log2FoldChange']) > 1)]
```

---

## Biopython (Sequence Analysis)

**Use for:** FASTA/GenBank parsing, BLAST, sequence manipulation, NCBI access.

```python
from Bio import SeqIO, Entrez
from Bio.Seq import Seq

# Parse FASTA
for record in SeqIO.parse('sequences.fasta', 'fasta'):
    print(f"{record.id}: {len(record.seq)} bp")

# Sequence manipulation
seq = Seq("ATGCGATCGATCG")
print(seq.complement())
print(seq.reverse_complement())
print(seq.translate())

# NCBI Entrez (always set email)
Entrez.email = "your.email@example.com"
handle = Entrez.efetch(db="nucleotide", id="NM_001301717", rettype="fasta", retmode="text")
record = SeqIO.read(handle, "fasta")

# BLAST
from Bio.Blast import NCBIWWW, NCBIXML
result_handle = NCBIWWW.qblast("blastn", "nt", seq)
blast_records = NCBIXML.parse(result_handle)
```

---

## scVelo (RNA Velocity)

**Use for:** Inferring cell state transitions and trajectory directions.

```python
import scvelo as scv

# Load data with spliced/unspliced counts
adata = scv.read('data.h5ad')  # or from loom file

# Preprocessing
scv.pp.filter_and_normalize(adata, min_shared_counts=20)
scv.pp.moments(adata, n_pcs=30, n_neighbors=30)

# Velocity estimation
scv.tl.velocity(adata)
scv.tl.velocity_graph(adata)

# Visualization
scv.pl.velocity_embedding_stream(adata, basis='umap')
scv.pl.velocity_embedding(adata, basis='umap', arrow_length=3)

# Latent time
scv.tl.latent_time(adata)
scv.pl.scatter(adata, color='latent_time', cmap='viridis')

# Driver genes
scv.tl.rank_velocity_genes(adata, groupby='clusters')
```

---

## Installation

```bash
pip install scanpy anndata pydeseq2 biopython scvelo
```

---

## See Also

- For interactive visualization → `DATA_ANALYSIS.md` (plotly, seaborn)
- For gene/protein databases → `GENOMICS_DATABASES.md`
