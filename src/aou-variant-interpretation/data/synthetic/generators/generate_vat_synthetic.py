#!/usr/bin/env python3
"""
Generate synthetic data conforming to the All of Us Variant Annotation Table
(VAT) BigQuery schema.

Output is newline-delimited JSON (NDJSON), which is the correct format for
loading into BigQuery when the schema contains REPEATED (ARRAY) fields.
CSV cannot represent arrays.

Most rows are random. The curated demo use cases' variants (see use_cases/) are appended to them:
each is a random row with every column the app shows overwritten from its spec, so those
variants look real while the columns nobody reads stay filled in.

Usage:
    python3 data/synthetic/generators/generate_vat_synthetic.py

Defaults assume it's run from the repo root; every path can be overridden.
"""

import argparse
import json
import os
import random

from use_cases import USE_CASES
from use_cases.common import vat_fields

# ---------------------------------------------------------------------------
# Controlled vocabularies (realistic values, not real variant data)
# ---------------------------------------------------------------------------

CONTIGS = [f"chr{i}" for i in range(1, 23)] + ["chrX", "chrY"]
BASES = ["A", "C", "G", "T"]

GVS_SUBPOPS = ["afr", "amr", "eas", "eur", "mid", "oth", "sas"]
GNOMAD_SUBPOPS = ["afr", "amr", "asj", "eas", "fin", "nfe", "sas", "oth"]

CONSEQUENCES = [
    "missense_variant", "synonymous_variant", "intron_variant",
    "stop_gained", "frameshift_variant", "splice_donor_variant",
    "splice_acceptor_variant", "5_prime_UTR_variant", "3_prime_UTR_variant",
    "upstream_gene_variant", "downstream_gene_variant",
    "inframe_deletion", "inframe_insertion", "start_lost",
    "non_coding_transcript_exon_variant",
]

VARIANT_TYPES = ["SNV", "insertion", "deletion", "indel"]
TRANSCRIPT_SOURCES = ["Ensembl", "RefSeq"]

CLINVAR_CLASSES = [
    "Benign", "Likely benign", "Uncertain significance",
    "Likely pathogenic", "Pathogenic", "Conflicting interpretations",
    "not provided",
]

PHENOTYPES = [
    "Hereditary breast and ovarian cancer syndrome",
    "Cystic fibrosis",
    "Long QT syndrome",
    "Familial hypercholesterolemia",
    "Lynch syndrome",
    "Marfan syndrome",
    "Dilated cardiomyopathy",
    "Retinitis pigmentosa",
    "Hypertrophic cardiomyopathy",
    "Noonan syndrome",
]

GENE_SYMBOLS = [
    "BRCA1", "BRCA2", "CFTR", "TP53", "APOE", "LDLR", "MYH7", "TTN",
    "KCNQ1", "SCN5A", "MLH1", "MSH2", "FBN1", "RYR2", "PKD1", "DMD",
    "NF1", "PTEN", "RB1", "VHL", "ATM", "CHEK2", "PALB2", "MUTYH",
]

LOF_VALUES = ["HC", "LC", None]
LOF_FILTERS = ["END_TRUNC", "INCOMPLETE_CDS", "NON_CAN_SPLICE",
               "ANC_ALLELE", "NON_DONOR_DISRUPTING"]
LOF_FLAGS = ["SINGLE_EXON", "NAGNAG_SITE", "PHYLOCSF_WEAK",
             "PHYLOCSF_UNLIKELY_ORF", "NON_CAN_SPLICE_SURR"]

# Total allele number pools, loosely mimicking cohort sizes
GVS_AN_POOL = 490_000      # ~245k diploid samples
GNOMAD_AN_POOL = 152_000   # ~76k diploid samples


def maybe(value, p=0.85):
    """Return value with probability p, else None (exercises NULL handling)."""
    return value if random.random() < p else None


def make_allele_pair():
    """Return (ref, alt, variant_type) with plausible indel representation."""
    vtype = random.choices(
        VARIANT_TYPES, weights=[0.86, 0.05, 0.06, 0.03]
    )[0]
    if vtype == "SNV":
        ref = random.choice(BASES)
        alt = random.choice([b for b in BASES if b != ref])
    elif vtype == "insertion":
        ref = random.choice(BASES)
        alt = ref + "".join(random.choices(BASES, k=random.randint(1, 8)))
    elif vtype == "deletion":
        alt = random.choice(BASES)
        ref = alt + "".join(random.choices(BASES, k=random.randint(1, 8)))
    else:  # indel
        ref = "".join(random.choices(BASES, k=random.randint(2, 5)))
        alt = "".join(random.choices(BASES, k=random.randint(2, 5)))
    return ref, alt, vtype


def allele_freq_block(subpops, an_pool, with_sc):
    """
    Build a consistent AC/AN/AF (and optional sample-count) block.

    Guarantees:
      - per-subpop AF == AC / AN
      - all_ac == sum(subpop ac), all_an == sum(subpop an)
      - max_* fields point at the subpop with the highest AF
      - sc (sample count) <= ac, since a hom-alt sample carries 2 alleles
    """
    # Draw a global frequency; most variants are rare.
    global_af = random.choices(
        [random.uniform(1e-5, 1e-3),
         random.uniform(1e-3, 0.01),
         random.uniform(0.01, 0.5)],
        weights=[0.6, 0.25, 0.15],
    )[0]

    out = {}
    total_ac = total_an = total_sc = 0
    per_pop = {}

    # Split the allele-number pool unevenly across subpopulations.
    weights = [random.uniform(0.5, 3.0) for _ in subpops]
    wsum = sum(weights)

    for pop, w in zip(subpops, weights):
        an = int(an_pool * (w / wsum))
        an -= an % 2  # allele number is even for diploid autosomal calls
        # Let each subpop drift around the global frequency.
        pop_af = min(1.0, max(0.0, global_af * random.lognormvariate(0, 0.6)))
        ac = min(an, int(round(pop_af * an)))
        af = (ac / an) if an else 0.0

        out[f"{pop}_ac"] = ac
        out[f"{pop}_an"] = an
        out[f"{pop}_af"] = round(af, 8)
        per_pop[pop] = af
        total_ac += ac
        total_an += an

        if with_sc:
            # Sample count: between ceil(ac/2) and ac.
            sc = random.randint((ac + 1) // 2, ac) if ac else 0
            out[f"{pop}_sc"] = sc
            total_sc += sc

    out["all_ac"] = total_ac
    out["all_an"] = total_an
    out["all_af"] = round(total_ac / total_an, 8) if total_an else 0.0
    if with_sc:
        out["all_sc"] = total_sc

    # max_* derived from the highest-frequency subpopulation
    max_pop = max(per_pop, key=per_pop.get)
    out["max_subpop"] = max_pop
    out["max_ac"] = out[f"{max_pop}_ac"]
    out["max_an"] = out[f"{max_pop}_an"]
    out["max_af"] = out[f"{max_pop}_af"]
    if with_sc:
        out["max_sc"] = out[f"{max_pop}_sc"]

    return out


def splice_ai_pair():
    """SpliceAI delta score + distance; scores are 0-1, distances -50..50."""
    return round(random.betavariate(0.6, 8), 4), random.randint(-50, 50)


def make_row():
    contig = random.choice(CONTIGS)
    position = random.randint(10_000, 248_000_000)
    ref, alt, vtype = make_allele_pair()
    gene = random.choice(GENE_SYMBOLS)
    is_coding = random.random() < 0.55

    row = {}

    # --- variant identity -------------------------------------------------
    row["vid"] = f"{contig.removeprefix('chr')}-{position}-{ref}-{alt}"
    row["transcript"] = maybe(
        f"ENST{random.randint(0, 99999999):011d}.{random.randint(1, 12)}", 0.92
    )
    row["contig"] = contig
    row["position"] = position
    row["ref_allele"] = ref
    row["alt_allele"] = alt

    # --- GVS (All of Us cohort) frequencies -------------------------------
    gvs = allele_freq_block(GVS_SUBPOPS, GVS_AN_POOL, with_sc=True)
    for key in ["all_ac", "all_an", "all_af", "all_sc",
                "max_af", "max_ac", "max_an", "max_sc", "max_subpop"]:
        row[f"gvs_{key}"] = gvs[key]
    for pop in GVS_SUBPOPS:
        for suffix in ["ac", "an", "af", "sc"]:
            row[f"gvs_{pop}_{suffix}"] = gvs[f"{pop}_{suffix}"]

    # --- transcript / consequence annotation ------------------------------
    row["gene_symbol"] = maybe(gene, 0.95)
    row["transcript_source"] = maybe(random.choice(TRANSCRIPT_SOURCES), 0.92)
    row["aa_change"] = maybe(
        f"p.{random.choice(['Ala','Gly','Ser','Arg','Leu','Val','Glu','Lys'])}"
        f"{random.randint(1, 2200)}"
        f"{random.choice(['Val','Thr','Asp','Cys','Trp','Pro','Ter'])}",
        0.5 if is_coding else 0.02,
    )
    row["consequence"] = random.sample(
        CONSEQUENCES, k=random.randint(1, 3)
    )
    row["dna_change_in_transcript"] = maybe(
        f"c.{random.randint(1, 6600)}{ref}>{alt}", 0.7
    )
    row["variant_type"] = vtype
    # Exon/intron numbers are "N/total" strings, and are mutually exclusive.
    if is_coding:
        total_exons = random.randint(2, 60)
        row["exon_number"] = f"{random.randint(1, total_exons)}/{total_exons}"
        row["intron_number"] = None
    else:
        total_introns = random.randint(2, 59)
        row["exon_number"] = None
        row["intron_number"] = f"{random.randint(1, total_introns)}/{total_introns}"
    row["genomic_location"] = f"{contig}:{position}"
    row["dbsnp_rsid"] = (
        [f"rs{random.randint(1000, 999999999)}"
         for _ in range(random.randint(1, 2))]
        if random.random() < 0.75 else []
    )
    row["gene_id"] = maybe(f"ENSG{random.randint(0, 99999999):011d}", 0.95)
    row["gene_omim_id"] = maybe(random.randint(100000, 620000), 0.6)
    row["is_canonical_transcript"] = random.random() < 0.35

    # --- gnomAD frequencies -----------------------------------------------
    has_gnomad = random.random() < 0.8
    if has_gnomad:
        gn = allele_freq_block(GNOMAD_SUBPOPS, GNOMAD_AN_POOL, with_sc=False)
        row["gnomad_all_af"] = gn["all_af"]
        row["gnomad_all_ac"] = gn["all_ac"]
        row["gnomad_all_an"] = gn["all_an"]
        row["gnomad_failed_filter"] = random.random() < 0.08
        row["gnomad_max_af"] = gn["max_af"]
        row["gnomad_max_ac"] = gn["max_ac"]
        row["gnomad_max_an"] = gn["max_an"]
        row["gnomad_max_subpop"] = gn["max_subpop"]
        for pop in GNOMAD_SUBPOPS:
            for suffix in ["ac", "an", "af"]:
                row[f"gnomad_{pop}_{suffix}"] = gn[f"{pop}_{suffix}"]
    else:
        # Variant absent from gnomAD -> all frequency fields NULL.
        for key in ["all_af", "all_ac", "all_an", "failed_filter",
                    "max_af", "max_ac", "max_an", "max_subpop"]:
            row[f"gnomad_{key}"] = None
        for pop in GNOMAD_SUBPOPS:
            for suffix in ["ac", "an", "af"]:
                row[f"gnomad_{pop}_{suffix}"] = None

    # --- in-silico predictors ---------------------------------------------
    # REVEL is only defined for missense variants.
    row["revel"] = (
        round(random.betavariate(1.5, 2.5), 4)
        if "missense_variant" in row["consequence"] and random.random() < 0.9
        else None
    )

    for site in ["acceptor", "donor"]:
        for event in ["gain", "loss"]:
            score, dist = splice_ai_pair()
            present = random.random() < 0.7
            row[f"splice_ai_{site}_{event}_score"] = score if present else None
            row[f"splice_ai_{site}_{event}_distance"] = dist if present else None

    # --- OMIM -------------------------------------------------------------
    if random.random() < 0.3:
        n = random.randint(1, 3)
        names = random.sample(PHENOTYPES, k=n)
        row["omim_phenotypes_id"] = [random.randint(100000, 620000)
                                     for _ in range(n)]
        row["omim_phenotypes_name"] = names
    else:
        row["omim_phenotypes_id"] = []
        row["omim_phenotypes_name"] = []

    # --- ClinVar ----------------------------------------------------------
    if random.random() < 0.25:
        n_rcv = random.randint(1, 4)
        row["clinvar_classification"] = random.sample(
            CLINVAR_CLASSES, k=random.randint(1, 2)
        )
        row["clinvar_last_updated"] = (
            f"{random.randint(2016, 2025)}-"
            f"{random.randint(1, 12):02d}-{random.randint(1, 28):02d}"
        )
        row["clinvar_phenotype"] = random.sample(
            PHENOTYPES, k=random.randint(1, 3)
        )
        # These four arrays are parallel: index i describes the same RCV record.
        row["clinvar_rcv_ids"] = [
            f"RCV{random.randint(0, 9999999):09d}" for _ in range(n_rcv)
        ]
        row["clinvar_rcv_classifications"] = [
            random.choice(CLINVAR_CLASSES) for _ in range(n_rcv)
        ]
        row["clinvar_rcv_num_stars"] = [
            random.randint(0, 4) for _ in range(n_rcv)
        ]
    else:
        row["clinvar_classification"] = []
        row["clinvar_last_updated"] = None
        row["clinvar_phenotype"] = []
        row["clinvar_rcv_ids"] = []
        row["clinvar_rcv_classifications"] = []
        row["clinvar_rcv_num_stars"] = []

    # --- MANE / HGNC ------------------------------------------------------
    row["mane_select_name"] = maybe(
        f"NM_{random.randint(0, 999999):06d}.{random.randint(1, 6)}", 0.45
    )
    row["mane_plus_clinical_name"] = maybe(
        f"NM_{random.randint(0, 999999):06d}.{random.randint(1, 6)}", 0.08
    )
    row["hgnc_symbol"] = maybe(gene, 0.9)
    row["hgnc_id"] = maybe(random.randint(1, 55000), 0.9)

    # --- LOFTEE -----------------------------------------------------------
    lof_relevant = any(
        c in row["consequence"]
        for c in ["stop_gained", "frameshift_variant",
                  "splice_donor_variant", "splice_acceptor_variant"]
    )
    if lof_relevant:
        row["LoF"] = random.choice(LOF_VALUES)
        row["LoF_filter"] = (random.sample(LOF_FILTERS, k=random.randint(1, 2))
                             if row["LoF"] == "LC" else [])
        row["LoF_flags"] = (random.sample(LOF_FLAGS, k=random.randint(1, 2))
                            if random.random() < 0.4 else [])
        row["LoF_info"] = [
            f"{k}:{round(random.uniform(0, 1), 3)}"
            for k in random.sample(
                ["PERCENTILE", "GERP_DIST", "BP_DIST", "DIST_FROM_LAST_EXON"],
                k=random.randint(1, 3),
            )
        ]
    else:
        row["LoF"] = None
        row["LoF_filter"] = []
        row["LoF_flags"] = []
        row["LoF_info"] = []

    # GERP is REPEATED in this schema (one score per overlapping element).
    row["GERP"] = (
        [round(random.uniform(-12.0, 6.2), 3)
         for _ in range(random.randint(1, 3))]
        if random.random() < 0.8 else []
    )

    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=1000)
    ap.add_argument("--out", default="data/synthetic/tables/synthetic_foxtrot_vat.ndjson")
    ap.add_argument("--schema",
                    default="data/synthetic/schemas/foxtrot_v4_2025_07_29_vat_v9_r2_p2_schema.json",
                    help="BQ schema JSON to validate generated fields against. "
                         "Pass an empty string to skip validation.")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    random.seed(args.seed)

    rows = [make_row() for _ in range(args.rows)]

    # After the random rows, so adding a use case doesn't reshuffle them.
    curated = [
        {**make_row(), **vat_fields(variant)}
        for case in USE_CASES
        for variant in case.variants
        if variant.aou is not None  # not in All of Us means not in the VAT
    ]
    random_vids = {r["vid"] for r in rows}
    clashes = [r["vid"] for r in curated if r["vid"] in random_vids]
    if clashes:
        raise SystemExit(f"ERROR: curated variants collide with random rows: {clashes}")
    rows += curated

    # Sort by contig/position so the output looks like a real variant table.
    contig_order = {c: i for i, c in enumerate(CONTIGS)}
    rows.sort(key=lambda r: (contig_order[r["contig"]], r["position"]))

    if args.schema:
        with open(args.schema) as fh:
            schema = json.load(fh)
        expected = {f["name"] for f in schema}
        produced = set(rows[0].keys())
        missing = expected - produced
        extra = produced - expected
        if missing:
            raise SystemExit(f"ERROR: schema fields not generated: {sorted(missing)}")
        if extra:
            raise SystemExit(f"ERROR: generated fields not in schema: {sorted(extra)}")
        # Reorder keys to match schema order (cosmetic, but easier to eyeball).
        order = [f["name"] for f in schema]
        rows = [{k: r[k] for k in order} for r in rows]
        print(f"Validated all {len(expected)} schema fields are present.")

    parent = os.path.dirname(args.out)
    if parent:
        os.makedirs(parent, exist_ok=True)

    with open(args.out, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")

    print(f"Wrote {len(rows)} rows to {args.out} ({len(curated)} from the use cases)")


if __name__ == "__main__":
    main()
