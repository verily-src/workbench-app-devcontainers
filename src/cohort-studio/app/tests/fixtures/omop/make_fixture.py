













import gzip
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[2]))

import omop_load

GI_BLEED = 192671
DICLOFENAC = 1124300
VOCAB = {"concept", "vocabulary", "domain", "concept_class", "concept_relationship",
         "relationship", "concept_synonym", "cdm_source"}


def _read(sources: dict, table: str) -> pd.DataFrame:
    with sources[table]() as f:
        df = pd.read_csv(f, dtype=str, keep_default_na=False)
    df.columns = df.columns.str.lower()
    return df


def main(zip_path: Path):
    sources = omop_load.open_sources(zip_path)
    tables = {t: _read(sources, t) for t in sources}
    person = tables["person"]
    cond = tables["condition_occurrence"]
    drug = tables["drug_exposure"]
    ca = tables["concept_ancestor"]
    diclofenac_ids = set(ca[ca.ancestor_concept_id == str(DICLOFENAC)].descendant_concept_id)
    gi = set(cond[cond.condition_concept_id == str(GI_BLEED)].person_id)
    diclofenac = set(drug[drug.drug_concept_id.isin(diclofenac_ids)].person_id) - gi
    other = set(person.person_id) - gi - diclofenac

    def pick(ids: set, n: int) -> list:
        return sorted(ids, key=int)[::max(1, len(ids) // n)][:n]

    keep = set(pick(gi, 40) + pick(diclofenac, 40) + pick(other, 20))
    out = {}
    for table, df in tables.items():
        if table in VOCAB:
            out[table] = df
        elif "person_id" in df.columns:
            out[table] = df[df.person_id.isin(keep)]
    used = set()
    for df in out.values():
        for col in df.columns:
            if col.endswith("_concept_id"):
                used |= set(df[col])
    known = set(tables["concept"].concept_id)
    out["concept_ancestor"] = ca[ca.descendant_concept_id.isin(used)
                                 & ca.ancestor_concept_id.isin(known)]
    total = 0
    for table, df in sorted(out.items()):
        if df.empty:
            continue
        path = HERE / f"{table}.csv.gz"
        with open(path, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
            gz.write(df.to_csv(index=False).encode())
        total += path.stat().st_size
        print(f"{table:<24} {len(df):>6} rows  {path.stat().st_size:>7} bytes")
    print(f"{len(keep)} persons, {total:,} bytes")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else omop_load.fetch())
