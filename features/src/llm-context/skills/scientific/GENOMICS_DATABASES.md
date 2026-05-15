# Genomics Databases Skills

**Trigger:** User asks about genes, proteins, variants, structures, annotations, Ensembl, UniProt, ClinVar, or PDB.

---

## Quick Reference

| Need | Database | API |
|------|----------|-----|
| Gene annotations, sequences | Ensembl | REST |
| Protein sequences, functions | UniProt | REST |
| Variant clinical significance | ClinVar | E-utilities |
| 3D protein structures | PDB/RCSB | REST |

---

## Ensembl (Gene Annotations)

**Use for:** Gene lookups, sequences, variant effect prediction (VEP), orthologs.

### REST API

```python
import requests

SERVER = "https://rest.ensembl.org"

def ensembl_get(endpoint, params=None):
    response = requests.get(f"{SERVER}{endpoint}", 
                           headers={"Content-Type": "application/json"},
                           params=params)
    return response.json()

# Lookup gene by symbol
gene = ensembl_get("/lookup/symbol/homo_sapiens/BRCA1", {"expand": 1})
print(f"Gene ID: {gene['id']}, Location: {gene['seq_region_name']}:{gene['start']}-{gene['end']}")

# Get gene sequence
seq = ensembl_get(f"/sequence/id/{gene['id']}", {"type": "genomic"})
print(f"Sequence length: {len(seq['seq'])} bp")

# Variant Effect Predictor (VEP)
vep_result = requests.post(
    f"{SERVER}/vep/human/region",
    headers={"Content-Type": "application/json"},
    json={"variants": ["17 41234451 . A G . . ."]}  # VCF format
).json()
```

### Common Endpoints
- `/lookup/symbol/{species}/{symbol}` - Gene by symbol
- `/lookup/id/{id}` - By Ensembl ID
- `/sequence/id/{id}` - Get sequence
- `/homology/id/{id}` - Orthologs/paralogs
- `/vep/{species}/region` - Variant effects

---

## UniProt (Protein Data)

**Use for:** Protein sequences, functions, domains, GO terms, cross-references.

### REST API

```python
import requests

BASE_URL = "https://rest.uniprot.org/uniprotkb"

# Search proteins
response = requests.get(f"{BASE_URL}/search", params={
    "query": "gene:TP53 AND organism_id:9606",
    "format": "json",
    "size": 5
})
results = response.json()['results']

for entry in results:
    print(f"{entry['primaryAccession']}: {entry['proteinDescription']['recommendedName']['fullName']['value']}")

# Get specific protein
protein = requests.get(f"{BASE_URL}/P04637.json").json()
print(f"Length: {protein['sequence']['length']} aa")

# Get FASTA sequence
fasta = requests.get(f"{BASE_URL}/P04637.fasta").text

# ID mapping (convert between databases)
mapping_response = requests.post(
    "https://rest.uniprot.org/idmapping/run",
    data={"from": "UniProtKB_AC-ID", "to": "Ensembl", "ids": "P04637"}
)
```

### Key Fields
- `primaryAccession` - UniProt ID (e.g., P04637)
- `proteinDescription` - Protein name
- `genes` - Gene names
- `sequence` - Amino acid sequence
- `features` - Domains, variants, modifications
- `uniProtKBCrossReferences` - Links to other databases

---

## ClinVar (Variant Clinical Significance)

**Use for:** Variant pathogenicity, clinical interpretations, disease associations.

### E-utilities API

```python
from Bio import Entrez
import xml.etree.ElementTree as ET

Entrez.email = "your.email@example.com"

# Search variants by gene
handle = Entrez.esearch(db="clinvar", term="BRCA1[gene] AND pathogenic[clinsig]", retmax=10)
record = Entrez.read(handle)
variant_ids = record['IdList']

# Get variant details
for vid in variant_ids[:3]:
    handle = Entrez.efetch(db="clinvar", id=vid, rettype="vcv", retmode="xml")
    # Parse XML response
    print(f"Variant ID: {vid}")
```

### Direct REST Query

```python
import requests

# Search by gene
response = requests.get(
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
    params={
        "db": "clinvar",
        "term": "BRCA1[gene]",
        "retmode": "json",
        "retmax": 100
    }
)
ids = response.json()['esearchresult']['idlist']
```

### Clinical Significance Categories
- Pathogenic
- Likely pathogenic
- Uncertain significance (VUS)
- Likely benign
- Benign

---

## PDB/RCSB (Protein Structures)

**Use for:** 3D structures, structural analysis, drug binding sites.

### REST API

```python
import requests

RCSB_URL = "https://data.rcsb.org/rest/v1/core"
SEARCH_URL = "https://search.rcsb.org/rcsbsearch/v2/query"

# Get structure metadata
pdb_id = "1TUP"  # p53 DNA-binding domain
structure = requests.get(f"{RCSB_URL}/entry/{pdb_id}").json()
print(f"Title: {structure['struct']['title']}")
print(f"Resolution: {structure['rcsb_entry_info'].get('resolution_combined', ['N/A'])} Å")

# Search structures
search_query = {
    "query": {
        "type": "terminal",
        "service": "full_text",
        "parameters": {"value": "kinase inhibitor"}
    },
    "return_type": "entry"
}
results = requests.post(SEARCH_URL, json=search_query).json()

# Download structure file
pdb_file = requests.get(f"https://files.rcsb.org/download/{pdb_id}.pdb").text
cif_file = requests.get(f"https://files.rcsb.org/download/{pdb_id}.cif").text
```

### Working with Structure Files

```python
from Bio.PDB import PDBParser

parser = PDBParser()
structure = parser.get_structure("protein", "1TUP.pdb")

for model in structure:
    for chain in model:
        print(f"Chain {chain.id}: {len(list(chain.get_residues()))} residues")
```

---

## Combined Workflow Example

```python
# Find drug targets for a disease, get protein info, check structures

import requests

# 1. Open Targets: Find targets for disease
disease_id = "EFO_0000311"  # Cancer
# ... (see DRUG_DISCOVERY.md)

# 2. UniProt: Get protein details
gene = "EGFR"
uniprot = requests.get(
    f"https://rest.uniprot.org/uniprotkb/search",
    params={"query": f"gene:{gene} AND organism_id:9606", "format": "json"}
).json()['results'][0]
uniprot_id = uniprot['primaryAccession']

# 3. PDB: Find structures
pdb_search = {
    "query": {
        "type": "terminal",
        "service": "text",
        "parameters": {"attribute": "rcsb_polymer_entity.pdbx_description", "value": gene}
    },
    "return_type": "entry"
}
structures = requests.post("https://search.rcsb.org/rcsbsearch/v2/query", json=pdb_search).json()
print(f"Found {structures['total_count']} structures for {gene}")
```

---

## Installation

```bash
pip install biopython requests
```

---

## See Also

- For sequence analysis → `BIOINFORMATICS.md` (Biopython)
- For drug-target data → `DRUG_DISCOVERY.md` (ChEMBL, Open Targets)
