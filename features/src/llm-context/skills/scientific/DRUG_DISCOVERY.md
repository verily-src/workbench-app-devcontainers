# Drug Discovery Skills

**Trigger:** User asks about molecules, compounds, drugs, SMILES, fingerprints, ADMET, targets, or bioactivity.

---

## Quick Reference

| Task | Tool | Quick Access |
|------|------|--------------|
| Molecular structure/properties | `rdkit` | `from rdkit import Chem` |
| ADMET/property prediction | `deepchem` | `import deepchem as dc` |
| Bioactivity data (IC50, Ki) | ChEMBL | REST API |
| Drug info & interactions | DrugBank | REST API |
| Target-disease associations | Open Targets | GraphQL API |

---

## RDKit (Cheminformatics)

**Use for:** SMILES parsing, molecular descriptors, fingerprints, substructure search, similarity.

### Basic Operations

```python
from rdkit import Chem
from rdkit.Chem import Descriptors, AllChem, Draw

# Parse SMILES
mol = Chem.MolFromSmiles('CC(=O)OC1=CC=CC=C1C(=O)O')  # Aspirin
if mol is None:
    print("Invalid SMILES")

# Calculate properties
mw = Descriptors.MolWt(mol)
logp = Descriptors.MolLogP(mol)
hbd = Descriptors.NumHDonors(mol)
hba = Descriptors.NumHAcceptors(mol)
tpsa = Descriptors.TPSA(mol)
rotatable = Descriptors.NumRotatableBonds(mol)

print(f"MW: {mw:.2f}, LogP: {logp:.2f}, HBD: {hbd}, HBA: {hba}, TPSA: {tpsa:.2f}")

# Lipinski's Rule of 5
lipinski_pass = mw <= 500 and logp <= 5 and hbd <= 5 and hba <= 10
```

### Fingerprints & Similarity

```python
from rdkit import DataStructs
from rdkit.Chem import AllChem

mol1 = Chem.MolFromSmiles('CCO')
mol2 = Chem.MolFromSmiles('CCCO')

# Morgan fingerprint (ECFP-like)
fp1 = AllChem.GetMorganFingerprintAsBitVect(mol1, radius=2, nBits=2048)
fp2 = AllChem.GetMorganFingerprintAsBitVect(mol2, radius=2, nBits=2048)

# Tanimoto similarity
similarity = DataStructs.TanimotoSimilarity(fp1, fp2)
print(f"Similarity: {similarity:.3f}")
```

### Substructure Search

```python
# Define substructure pattern
pattern = Chem.MolFromSmarts('c1ccccc1')  # benzene ring

# Check if molecule contains pattern
has_benzene = mol.HasSubstructMatch(pattern)

# Find all matches
matches = mol.GetSubstructMatches(pattern)
```

---

## DeepChem (Molecular ML)

**Use for:** Property prediction, ADMET, toxicity, binding affinity.

```python
import deepchem as dc

# Load MoleculeNet dataset
tasks, datasets, transformers = dc.molnet.load_delaney(featurizer='ECFP')
train, valid, test = datasets

# Quick model training
model = dc.models.MultitaskClassifier(n_tasks=1, n_features=1024)
model.fit(train, nb_epoch=10)

# Predict on new molecules
smiles = ['CCO', 'CC(=O)O', 'c1ccccc1']
featurizer = dc.feat.CircularFingerprint(size=1024)
features = featurizer.featurize(smiles)
predictions = model.predict_on_batch(features)
```

### Pre-trained Models

```python
# Load pre-trained toxicity model
tox21_tasks, tox21_datasets, tox21_transformers = dc.molnet.load_tox21()

# ADMET prediction
# Use relevant MoleculeNet datasets: BBBP, ClinTox, SIDER, etc.
```

---

## ChEMBL Database

**Use for:** Bioactivity data, IC50/Ki values, target information.

### REST API Queries

```python
import requests

BASE_URL = "https://www.ebi.ac.uk/chembl/api/data"

# Search compound by name
response = requests.get(f"{BASE_URL}/molecule/search.json?q=aspirin")
results = response.json()['molecules']

# Get bioactivity for a target (e.g., COX-2)
target_id = "CHEMBL230"  # COX-2
response = requests.get(f"{BASE_URL}/activity.json?target_chembl_id={target_id}&limit=100")
activities = response.json()['activities']

for act in activities[:5]:
    print(f"{act['molecule_chembl_id']}: {act['standard_type']} = {act['standard_value']} {act['standard_units']}")
```

### Using chembl_webresource_client

```python
from chembl_webresource_client.new_client import new_client

# Search molecules
molecule = new_client.molecule
aspirin = molecule.filter(pref_name__iexact='aspirin')[0]

# Get activities for target
activity = new_client.activity
target_activities = activity.filter(target_chembl_id='CHEMBL230', pchembl_value__gte=6)

# Search by SMILES similarity
similarity = new_client.similarity
similar_mols = similarity.filter(smiles='CC(=O)Oc1ccccc1C(=O)O', similarity=70)
```

---

## DrugBank

**Use for:** Approved drug information, drug-drug interactions, mechanisms.

```python
import requests

# Note: DrugBank API requires authentication for full access
# Free tier available at https://go.drugbank.com/

# Example: Search drug by name (requires API key)
headers = {'Authorization': 'Bearer YOUR_API_KEY'}
response = requests.get(
    'https://api.drugbank.com/v1/drugs',
    params={'q': 'metformin'},
    headers=headers
)
```

### DrugBank Data Fields
- Drug name, description, indication
- Mechanism of action
- Drug-drug interactions
- Targets and enzymes
- ADMET properties
- Chemical structure (SMILES, InChI)

---

## Open Targets

**Use for:** Target-disease associations, genetic evidence, known drugs.

### GraphQL API

```python
import requests

ENDPOINT = "https://api.platform.opentargets.org/api/v4/graphql"

# Query target-disease associations
query = """
query targetAssociations($ensemblId: String!) {
  target(ensemblId: $ensemblId) {
    id
    approvedSymbol
    associatedDiseases {
      rows {
        disease { id name }
        score
      }
    }
  }
}
"""

response = requests.post(ENDPOINT, json={
    'query': query,
    'variables': {'ensemblId': 'ENSG00000157764'}  # BRAF
})
data = response.json()['data']['target']

for assoc in data['associatedDiseases']['rows'][:5]:
    print(f"{assoc['disease']['name']}: {assoc['score']:.3f}")
```

### Common Queries
- Target tractability and safety
- Known drugs for a disease
- Genetic associations (GWAS)
- Pathway information

---

## Installation

```bash
pip install rdkit deepchem chembl_webresource_client requests
```

---

## See Also

- For protein structures → `GENOMICS_DATABASES.md` (PDB, UniProt)
- For clinical trials → `CLINICAL.md`
