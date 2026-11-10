"""
Shared pieces for the curated demo use cases: the spec types each use case is written in, and
the builders that turn a spec into rows for the generated tables.

A use case is a condition plus a hand-picked set of variants, written so every part of the
results page tells a coherent story for it. The variants are real: their GRCh38 positions,
alleles, transcripts, HGVS and ClinVar records were checked against ClinVar and Ensembl VEP when
they were written (see each use case file). Everything about the cohort -- allele counts, which
participants carry what, ancestry and age -- is synthetic.
"""

import random
import re
import zlib
from dataclasses import dataclass, field

AOU_POPULATIONS = ["afr", "amr", "eas", "eur", "mid", "oth", "sas"]
GNOMAD_POPULATIONS = ["afr", "amr", "asj", "eas", "fin", "nfe", "sas", "oth"]

# Typical allele numbers per population. Each variant's are these, shaved by up to 3% (as calls
# drop out at harder-to-sequence sites), so no two variants report identical denominators.
AOU_AN = {"eur": 238_000, "afr": 104_000, "amr": 86_000, "oth": 38_000,
          "eas": 14_600, "sas": 6_800, "mid": 2_600}
# gnomAD's are v4 genomes', the dataset the use cases' real gnomAD counts come from. (Its exomes
# are about ten times larger; the genomes are smaller than All of Us, as a demo would expect.)
GNOMAD_AN = {"nfe": 67_950, "afr": 41_528, "amr": 15_292, "asj": 3_470,
             "eas": 5_152, "fin": 10_578, "sas": 4_810, "oth": 2_114}

ANCESTRY_LABELS = ["EUR", "AFR", "AMR", "OTH", "EAS", "SAS", "MID"]
AGE_LABELS = ["18–29", "30–39", "40–49", "50–59", "60–69", "70+"]

# ClinVar review status -> gold stars.
STARS = {
    "practice guideline": 4,
    "reviewed by expert panel": 3,
    "criteria provided, multiple submitters, no conflicts": 2,
    "criteria provided, conflicting classifications": 1,
    "criteria provided, single submitter": 1,
    "no assertion criteria provided": 0,
}

# ClinVar's aggregate classification, as its API words it, -> the VAT's clinvar_classification
# terms. "Pathogenic/Likely pathogenic" is two terms in the VAT.
VAT_CLASSIFICATIONS = {
    "Pathogenic": ["Pathogenic"],
    "Likely pathogenic": ["Likely pathogenic"],
    "Pathogenic/Likely pathogenic": ["Pathogenic", "Likely pathogenic"],
    "Uncertain significance": ["Uncertain significance"],
    "Likely benign": ["Likely benign"],
    "Benign": ["Benign"],
    "Benign/Likely benign": ["Benign", "Likely benign"],
    "Conflicting classifications of pathogenicity": ["Conflicting interpretations"],
}

# SNVs and small indels, in VCF style: an indel carries the base before it on both alleles.
VID = re.compile(r"^(\d{1,2}|X|Y)-\d+-[ACGT]+-[ACGT]+$")

SPLICE_AI_KEYS = ("DS_AG", "DS_AL", "DS_DG", "DS_DL", "DP_AG", "DP_AL", "DP_DG", "DP_DL")


@dataclass(frozen=True)
class ClinVar:
    """A variant's ClinVar record, as of when the use case was written."""
    classification: str          # a key of VAT_CLASSIFICATIONS
    review_status: str           # a key of STARS
    last_evaluated: str          # YYYY-MM-DD
    rcvs: tuple[str, ...]
    # The conditions shown for it: ClinVar's own trait names, minus "not provided" and the like.
    conditions: tuple[str, ...]
    # Per-RCV classifications, parallel to rcvs. Needed only when submitters conflict; otherwise
    # every RCV gets the aggregate's terms in turn.
    rcv_classifications: tuple[str, ...] = ()


@dataclass(frozen=True)
class Matched:
    """
    The variant among the use case's phenotype-matched participants. AN is always twice the
    participant count (everyone called, two alleles each), so only the counts are given.
    """
    carriers_ac: int             # alternate alleles among the matched participants (can be 0)
    homozygotes: int = 0
    plp_in_trans: int = 0        # carriers with a ClinVar P/LP variant in trans


@dataclass(frozen=True)
class Variant:
    vid: str                     # chr-pos-ref-alt, GRCh38, as the VAT keys it
    gene: str
    gene_id: str                 # Ensembl gene
    transcript: str              # MANE Select, Ensembl ID
    mane: str                    # MANE Select, RefSeq ID
    hgvsc: str                   # on the MANE transcript, e.g. "c.1208G>A"
    hgvsp: str | None            # e.g. "p.Arg403Gln"; None for an intronic variant
    consequence: tuple[str, ...]  # VEP terms, most severe first
    exon: str | None             # "13/40"; None for an intronic (e.g. splice-site) variant
    rsid: str | None
    clinvar: ClinVar | None
    # Per population: an int is an allele count, a float an allele frequency, an (AC, AN) pair
    # both counts exactly (gnomAD's are real, from its API). None means the variant isn't in that
    # source at all -- for All of Us, that it's absent from the VAT.
    aou: dict | None
    gnomad: dict | None
    intron: str | None = None    # "5/34", for a variant in an intron instead of an exon
    revel: float | None = None
    # SpliceAI as VEP's plugin reports it: DS_* delta scores (acceptor/donor gain/loss) and DP_*
    # positions. None if it isn't scored.
    splice_ai: dict | None = None
    lof: str | None = None       # LOFTEE: "HC", "LC" or None
    lof_filter: tuple[str, ...] = ()
    lof_flags: tuple[str, ...] = ()
    # Not in All of Us means no phenotype-matched stats either; otherwise these override the
    # backend's randomly generated ones.
    matched: Matched | None = None


@dataclass(frozen=True)
class Condition:
    concept_id: int
    name: str
    est_count: int               # the cohort builder's participant estimate
    participants: int            # what condition_occurrence + concept_ancestor really match
    synonyms: tuple[str, ...] = ()
    # False for a condition the base condition fixture already defines (Tetralogy of Fallot),
    # whose participants and hierarchy that fixture owns.
    generate: bool = True


@dataclass(frozen=True)
class UseCase:
    key: str
    title: str                   # the label in the entry page's example menu
    description: str
    condition: Condition
    variants: tuple[Variant, ...]  # in the order the search enters them
    ancestry: dict[str, int] = field(default_factory=dict)  # label -> matched participants
    age: dict[str, int] = field(default_factory=dict)


def validate(case: UseCase) -> None:
    """Fails loudly on a use case that would render as contradictory numbers."""
    n = case.condition.participants

    def check(ok, message):
        if not ok:
            raise SystemExit(f"use case {case.key}: {message}")

    check(sum(case.ancestry.values()) == n, f"ancestry counts sum to {sum(case.ancestry.values())}, not {n}")
    check(sum(case.age.values()) == n, f"age counts sum to {sum(case.age.values())}, not {n}")
    check(set(case.ancestry) <= set(ANCESTRY_LABELS), f"unknown ancestry labels {set(case.ancestry) - set(ANCESTRY_LABELS)}")
    check(set(case.age) <= set(AGE_LABELS), f"unknown age labels {set(case.age) - set(AGE_LABELS)}")
    for v in case.variants:
        check(VID.match(v.vid) is not None, f"{v.vid}: not a chr-pos-ref-alt SNV or indel")
        check((v.exon is None) != (v.intron is None), f"{v.vid}: needs exactly one of exon and intron")
        check(v.splice_ai is None or set(v.splice_ai) == set(SPLICE_AI_KEYS), f"{v.vid}: SpliceAI needs all of {SPLICE_AI_KEYS}")
        if v.clinvar:
            check(v.clinvar.classification in VAT_CLASSIFICATIONS, f"{v.vid}: unknown classification")
            check(v.clinvar.review_status in STARS, f"{v.vid}: unknown review status")
            conflicting = v.clinvar.classification.startswith("Conflicting")
            check(not conflicting or len(v.clinvar.rcv_classifications) == len(v.clinvar.rcvs),
                  f"{v.vid}: conflicting records need a classification per RCV")
        if v.aou is None:
            check(v.matched is None, f"{v.vid}: not in All of Us, so it can't have matched stats")
            continue
        check(set(v.aou) <= set(AOU_POPULATIONS), f"{v.vid}: unknown All of Us populations")
        check(any(value > 0 for value in v.aou.values()), f"{v.vid}: in All of Us with no carriers")
        check(v.gnomad is None or any((value[0] if isinstance(value, tuple) else value) > 0 for value in v.gnomad.values()),
              f"{v.vid}: in gnomAD with no carriers")
        if v.gnomad is not None:
            check(set(v.gnomad) <= set(GNOMAD_POPULATIONS), f"{v.vid}: unknown gnomAD populations")
        if v.matched:
            m = v.matched
            # 0 is allowed: in All of Us, but carried by none of the matched participants.
            check(0 <= m.carriers_ac <= 2 * n, f"{v.vid}: matched AC outside 0..{2 * n}")
            check(2 * m.homozygotes <= m.carriers_ac, f"{v.vid}: more homozygotes than its AC allows")
            check(m.plp_in_trans <= m.carriers_ac - 2 * m.homozygotes, f"{v.vid}: P/LP-in-trans exceeds heterozygotes")


def _rng(vid: str, salt: str) -> random.Random:
    """Per-variant randomness that doesn't depend on generation order."""
    return random.Random(zlib.crc32(f"{vid}:{salt}".encode()))


def _frequency_block(vid, spec, populations, base_an, prefix, with_sc):
    """AC/AN/AF per population plus all_* and max_*, with the same invariants as the random rows."""
    rng = _rng(vid, prefix)
    out, per_pop_af = {}, {}
    total_ac = total_an = total_sc = 0
    for pop in populations:
        an = int(base_an[pop] * rng.uniform(0.97, 1.0))
        an -= an % 2
        value = spec.get(pop, 0)
        if isinstance(value, tuple):
            ac, an = value
        else:
            ac = value if isinstance(value, int) else round(value * an)
        af = ac / an
        out[f"{prefix}_{pop}_ac"], out[f"{prefix}_{pop}_an"], out[f"{prefix}_{pop}_af"] = ac, an, round(af, 8)
        per_pop_af[pop] = af
        total_ac += ac
        total_an += an
        if with_sc:
            # Carriers: every alt allele is in a heterozygote except the homozygotes' second copies,
            # with homozygotes at Hardy-Weinberg expectation.
            hom = min(round((an / 2) * af * af), ac // 2)
            out[f"{prefix}_{pop}_sc"] = ac - hom
            total_sc += ac - hom
    out[f"{prefix}_all_ac"], out[f"{prefix}_all_an"] = total_ac, total_an
    out[f"{prefix}_all_af"] = round(total_ac / total_an, 8)
    max_pop = max(populations, key=lambda p: per_pop_af[p])
    out[f"{prefix}_max_subpop"] = max_pop
    for suffix in ["ac", "an", "af"]:
        out[f"{prefix}_max_{suffix}"] = out[f"{prefix}_{max_pop}_{suffix}"]
    if with_sc:
        out[f"{prefix}_all_sc"] = total_sc
        out[f"{prefix}_max_sc"] = out[f"{prefix}_{max_pop}_sc"]
    return out


def _clinvar_fields(clinvar: ClinVar | None) -> dict:
    if clinvar is None:
        return {"clinvar_classification": [], "clinvar_last_updated": None, "clinvar_phenotype": [],
                "clinvar_rcv_ids": [], "clinvar_rcv_classifications": [], "clinvar_rcv_num_stars": []}
    terms = VAT_CLASSIFICATIONS[clinvar.classification]
    per_rcv = list(clinvar.rcv_classifications) or [terms[i % len(terms)] for i in range(len(clinvar.rcvs))]
    stars = STARS[clinvar.review_status]
    return {
        "clinvar_classification": terms,
        "clinvar_last_updated": clinvar.last_evaluated,
        "clinvar_phenotype": list(clinvar.conditions),
        "clinvar_rcv_ids": list(clinvar.rcvs),
        "clinvar_rcv_classifications": per_rcv,
        # Per-RCV review status isn't in the snapshot, so each record gets the variant's.
        "clinvar_rcv_num_stars": [stars] * len(clinvar.rcvs),
    }


def _variant_type(ref: str, alt: str) -> str:
    if len(ref) == len(alt) == 1:
        return "SNV"
    if len(alt) == 1 and ref[0] == alt:
        return "deletion"
    if len(ref) == 1 and alt[0] == ref:
        return "insertion"
    return "indel"


def vat_fields(v: Variant) -> dict:
    """The VAT columns a curated variant sets. Everything else comes from the random row it overlays."""
    chrom, pos, ref, alt = v.vid.split("-")
    fields = {
        "vid": v.vid,
        "contig": f"chr{chrom}",
        "position": int(pos),
        "ref_allele": ref,
        "alt_allele": alt,
        "variant_type": _variant_type(ref, alt),
        "genomic_location": f"chr{chrom}:{pos}",
        "gene_symbol": v.gene,
        "hgnc_symbol": v.gene,
        "gene_id": v.gene_id,
        "transcript": v.transcript,
        "transcript_source": "Ensembl",
        "is_canonical_transcript": True,
        "mane_select_name": v.mane,
        "mane_plus_clinical_name": None,
        "aa_change": v.hgvsp,
        "dna_change_in_transcript": v.hgvsc,
        "consequence": list(v.consequence),
        "exon_number": v.exon,
        "intron_number": v.intron,
        "dbsnp_rsid": [v.rsid] if v.rsid else [],
        "revel": v.revel,
        "LoF": v.lof,
        "LoF_filter": list(v.lof_filter),
        "LoF_flags": list(v.lof_flags),
        "LoF_info": [],
    }
    for site, s in [("acceptor", "A"), ("donor", "D")]:
        for event, e in [("gain", "G"), ("loss", "L")]:
            fields[f"splice_ai_{site}_{event}_score"] = v.splice_ai[f"DS_{s}{e}"] if v.splice_ai else None
            fields[f"splice_ai_{site}_{event}_distance"] = v.splice_ai[f"DP_{s}{e}"] if v.splice_ai else None

    fields.update(_frequency_block(v.vid, v.aou, AOU_POPULATIONS, AOU_AN, "gvs", with_sc=True))
    if v.gnomad is None:
        for key in ["all_af", "all_ac", "all_an", "failed_filter", "max_af", "max_ac", "max_an", "max_subpop"]:
            fields[f"gnomad_{key}"] = None
        for pop in GNOMAD_POPULATIONS:
            for suffix in ["ac", "an", "af"]:
                fields[f"gnomad_{pop}_{suffix}"] = None
    else:
        gnomad = _frequency_block(v.vid, v.gnomad, GNOMAD_POPULATIONS, GNOMAD_AN, "gnomad", with_sc=False)
        gnomad["gnomad_failed_filter"] = False
        fields.update(gnomad)

    fields.update(_clinvar_fields(v.clinvar))
    return fields


def phenotype_fixture(case: UseCase) -> dict:
    """The use case's entry in the backend's phenotype fixture."""
    return {
        "conceptId": case.condition.concept_id,
        "participants": case.condition.participants,
        "ancestry": [{"label": k, "count": case.ancestry[k]} for k in ANCESTRY_LABELS if case.ancestry.get(k)],
        "age": [{"label": k, "count": case.age[k]} for k in AGE_LABELS if case.age.get(k)],
        "variants": {
            v.vid: {"cohortAc": v.matched.carriers_ac, "homozygotes": v.matched.homozygotes,
                    "plpInTrans": v.matched.plp_in_trans}
            for v in case.variants if v.matched
        },
    }


def ui_example(case: UseCase) -> dict:
    """The use case's entry in the entry page's example menu."""
    return {
        "key": case.key,
        "title": case.title,
        "description": case.description,
        "variants": [v.vid for v in case.variants],
        # The shape the phenotype field takes a picked concept in (ConditionConcept).
        "condition": {"conceptId": case.condition.concept_id, "name": case.condition.name,
                      "estimatedParticipantCount": case.condition.est_count},
    }
