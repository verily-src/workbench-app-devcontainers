#!/usr/bin/env python3
"""
Curation helper for the demo use cases (use_cases/): looks up real variants and prints a
Variant(...) spec for each, ready to paste into a use case file, with every fact checked against
the public sources the use cases are built from:

    ClinVar (NCBI E-utilities)  classification, review status, date, RCVs, conditions
    Ensembl VEP (MANE Select)   consequence, HGVS, exon/intron, rsID, and from VEP's plugins
                                SpliceAI, REVEL and LOFTEE
    gnomAD API (v4 genomes)     per-population allele counts

What it can't know -- All of Us counts and the phenotype-matched carriers, which are synthetic --
it drafts from gnomAD for a common variant, and leaves as marked TODOs for a rare one. Review the
output before pasting it.

Usage (from the repo root; needs network access):

    python3 data/synthetic/generators/curate_use_case_variant.py 14-23429278-C-T
    python3 data/synthetic/generators/curate_use_case_variant.py MYH7:R403Q LDLR:C681*
    python3 data/synthetic/generators/curate_use_case_variant.py 19-11120205-T-C --participants 391

    # Re-check every variant already in the use cases against the live sources:
    python3 data/synthetic/generators/curate_use_case_variant.py --verify

Variants are GRCh38 chr-pos-ref-alt IDs (VCF-style, so indels include the preceding base), or
GENE:CHANGE with ClinVar's one-letter protein change (quote ones with a *, like LDLR:C681*).
ClinVar allows 3 requests a second; set NCBI_API_KEY for 10.
"""

import argparse
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

from use_cases.common import AOU_AN, STARS, VAT_CLASSIFICATIONS

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
ENSEMBL = "https://rest.ensembl.org"
GNOMAD = "https://gnomad.broadinstitute.org/api"
NCBI_API_KEY = os.environ.get("NCBI_API_KEY")
REFSEQ_CHROM = {f"NC_0000{n:02d}": str(n) for n in range(1, 23)} | {"NC_000023": "X", "NC_000024": "Y"}
# gnomAD's population IDs -> the VAT's gnomAD columns. The VAT has no Middle Eastern column.
GNOMAD_POPS = {"afr": "afr", "amr": "amr", "asj": "asj", "eas": "eas", "fin": "fin", "nfe": "nfe",
               "sas": "sas", "remaining": "oth"}
# ClinVar trait names that say nothing about the condition.
UNINFORMATIVE_TRAITS = {"not provided", "not specified", "Cardiovascular phenotype", "Inborn genetic diseases"}
# At or above this gnomAD frequency a variant counts as common enough to draft its All of Us
# frequencies from gnomAD's; below it, its All of Us counts are the use case author's call.
COMMON_AF = 1e-4


# --- HTTP -----------------------------------------------------------------------------------

def fetch_json(url, body=None, pause=0.0, attempts=8):
    """GET (or POST, with a body) JSON, retrying with backoff: all three services rate-limit."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json", "Accept": "application/json"} if data else {}
    for attempt in range(attempts):
        time.sleep(pause)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=90) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError) as e:
            if isinstance(e, urllib.error.HTTPError) and e.code == 400:
                raise
            time.sleep(min(60, 3 * (attempt + 1)))
    raise SystemExit(f"ERROR: gave up on {url}")


def eutils(endpoint, **params):
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
    return fetch_json(f"{EUTILS}/{endpoint}.fcgi?db=clinvar&retmode=json&{urllib.parse.urlencode(params)}",
                      pause=0.12 if NCBI_API_KEY else 0.4)


# --- Variant IDs ----------------------------------------------------------------------------

def reference_base(chrom, pos):
    return fetch_json(f"{ENSEMBL}/sequence/region/human/{chrom}:{pos}..{pos}:1?content-type=application/json",
                      pause=0.1)["seq"].upper()


def spdi_to_vid(spdi):
    """ClinVar's SPDI (0-based, unanchored) -> the VAT's chr-pos-ref-alt (VCF-style, left-aligned)."""
    parts = spdi.split(":")
    chrom = REFSEQ_CHROM.get(parts[0].split(".")[0]) if len(parts) == 4 else None
    if not chrom:
        return None
    pos0, deleted, inserted = int(parts[1]), parts[2], parts[3]
    if len(deleted) == 1 and len(inserted) == 1:
        return f"{chrom}-{pos0 + 1}-{deleted}-{inserted}"
    # An indel: anchor it on the base before (at 1-based pos0), then trim to its minimal form.
    anchor = reference_base(chrom, pos0)
    ref, alt = anchor + deleted, anchor + inserted
    while len(ref) > 1 and len(alt) > 1 and ref[-1] == alt[-1]:
        ref, alt = ref[:-1], alt[:-1]
    return f"{chrom}-{pos0}-{ref}-{alt}"


# --- ClinVar --------------------------------------------------------------------------------

def clinvar_summaries(term):
    ids = eutils("esearch", term=term, retmax=40)["esearchresult"]["idlist"]
    if not ids:
        return []
    result = eutils("esummary", id=",".join(ids))["result"]
    return [result[uid] for uid in result["uids"]]


def clinvar_record(summary):
    gc = summary.get("germline_classification", {})
    conditions = []
    for trait in gc.get("trait_set", []):
        name = trait.get("trait_name")
        if name and name not in UNINFORMATIVE_TRAITS and name not in conditions:
            conditions.append(name)
    return {
        "classification": (gc.get("description") or "").split(";")[0],
        "review_status": gc.get("review_status"),
        "last_evaluated": (gc.get("last_evaluated") or "")[:10].replace("/", "-"),
        "rcvs": summary.get("supporting_submissions", {}).get("rcv", [])[:6],
        "conditions": conditions[:3],
        "genes": [g.get("symbol") for g in summary.get("genes", [])],
        "title": summary.get("title"),
    }


def clinvar_by_vid(vid):
    """
    The ClinVar record for exactly this variant, or None. A position can carry more than one --
    e.g. a haplotype record that includes this variant alongside another -- so this takes the
    variant's own main record: the one with the most RCVs.
    """
    chrom, pos, ref, _ = vid.split("-")
    start = int(pos) + (1 if len(ref) > 1 else 0)  # an indel's anchor base isn't part of it
    matches = []
    for summary in clinvar_summaries(f"{chrom}[chr] AND {start}[chrpos38]"):
        spdi = summary["variation_set"][0].get("canonical_spdi", "")
        if spdi and spdi_to_vid(spdi) == vid:
            matches.append(summary)
    if not matches:
        return None
    return clinvar_record(max(matches, key=lambda s: len(s.get("supporting_submissions", {}).get("rcv", []))))


def clinvar_by_protein_change(gene, change):
    """GENE + ClinVar one-letter change (R403Q, C681*) -> (vid, record) of its best-supported record."""
    hits = []
    for summary in clinvar_summaries(f'{gene}[gene] AND "{change}"[Protein change]'):
        changes = [c.strip() for c in (summary.get("protein_change") or "").split(",")]
        spdi = summary["variation_set"][0].get("canonical_spdi", "")
        if change in changes and gene in (summary.get("title") or "") and spdi:
            hits.append((len(summary.get("supporting_submissions", {}).get("rcv", [])), spdi, summary))
    if not hits:
        return None, None
    _, spdi, summary = max(hits, key=lambda h: h[0])
    return spdi_to_vid(spdi), clinvar_record(summary)


# --- Ensembl VEP and gnomAD -----------------------------------------------------------------

def vep(vid, gene):
    """VEP on the gene's MANE Select transcript, with the SpliceAI, REVEL and LOFTEE plugins."""
    chrom, pos, ref, alt = vid.split("-")
    url = f"{ENSEMBL}/vep/human/region?mane=1&hgvs=1&numbers=1&SpliceAI=2&REVEL=1&LoF=1"
    result = fetch_json(url, body={"variants": [f"{chrom} {pos} . {ref} {alt} . . ."]}, pause=0.1)[0]
    transcripts = [t for t in result.get("transcript_consequences", []) if t.get("mane_select")]
    t = next((t for t in transcripts if t.get("gene_symbol") == gene), transcripts[0] if transcripts else None)
    if t is None:
        return None
    hgvsp = t["hgvsp"].split(":")[1].replace("%3D", "=") if t.get("hgvsp") else None
    if hgvsp:
        # Frameshifts in HGVS's short form, so the table stays narrow: p.Ala262ArgfsTer32 -> p.Ala262fs.
        hgvsp = re.sub(r"^(p\.[A-Z][a-z]{2}\d+)[A-Z][a-z]{2}fsTer\d+$", r"\1fs", hgvsp)
    splice = t.get("spliceai")
    keys = ("DS_AG", "DS_AL", "DS_DG", "DS_DL", "DP_AG", "DP_AL", "DP_DG", "DP_DL")
    return {
        "gene": t["gene_symbol"], "gene_id": t["gene_id"], "transcript": t["transcript_id"], "mane": t["mane_select"],
        "hgvsc": t["hgvsc"].split(":")[1], "hgvsp": hgvsp, "consequence": tuple(t["consequence_terms"]),
        "exon": t.get("exon"), "intron": t.get("intron"),
        "rsid": next((c["id"] for c in result.get("colocated_variants", []) if c["id"].startswith("rs")), None),
        "revel": t.get("revel"),
        "splice_ai": {k: splice[k] for k in keys} if splice else None,
        "lof": t.get("lof"),
        "lof_filter": tuple(str(t["lof_filter"]).split(",")) if t.get("lof_filter") else (),
        "lof_flags": tuple(str(t["lof_flags"]).split(",")) if t.get("lof_flags") else (),
    }


GNOMAD_QUERY = """query($id: String!) { variant(variantId: $id, dataset: gnomad_r4) {
  genome { ac an populations { id ac an } } } }"""


def gnomad_genomes(vid):
    """Per-population (AC, AN) in gnomAD v4 genomes, or None if it has no carriers there."""
    try:
        data = fetch_json(GNOMAD, body={"query": GNOMAD_QUERY, "variables": {"id": vid}}, pause=1.1)
    except urllib.error.HTTPError:
        return None
    genome = ((data.get("data") or {}).get("variant") or {}).get("genome")
    if not genome or not genome["ac"]:
        return None
    return {GNOMAD_POPS[p["id"]]: (p["ac"], p["an"]) for p in genome["populations"] if p["id"] in GNOMAD_POPS}


# --- Drafting the synthetic parts -----------------------------------------------------------

def gnomad_af(pops):
    return sum(ac for ac, _ in pops.values()) / sum(an for _, an in pops.values())


def aou_from_gnomad(vid, pops):
    """All of Us frequencies drafted from gnomAD's, per population, give or take 12%."""
    def af(p):
        ac, an = pops.get(p, (0, 0))
        return ac / an if an else 0
    draft = {"eur": 0.93 * af("nfe") + 0.03 * af("fin") + 0.04 * af("asj"), "afr": af("afr"), "amr": af("amr"),
             "eas": af("eas"), "sas": af("sas"), "mid": af("nfe"), "oth": af("oth")}
    jitter = lambda p: random.Random(zlib.crc32(f"{vid}:aou:{p}".encode())).uniform(0.88, 1.12)  # noqa: E731
    return {p: float(f"{v * jitter(p):.2g}") for p, v in draft.items() if v > 0}


def aou_af(spec):
    return sum(v * AOU_AN[p] if isinstance(v, float) else v for p, v in spec.items()) / sum(AOU_AN.values())


# --- Output ---------------------------------------------------------------------------------

def tup(items):
    items = list(items)
    return "(" + ", ".join(repr(x) for x in items) + ("," if len(items) == 1 else "") + ")"


def dict_literal(d, value=repr):
    return "{" + ", ".join(f'"{k}": {value(v)}' for k, v in d.items()) + "}"


def variant_spec(vid, v, cv, gnomad, participants, ratio):
    """The Variant(...) block, formatted as in the use case files."""
    lines = []
    if gnomad and gnomad_af(gnomad) >= COMMON_AF:
        aou = aou_from_gnomad(vid, gnomad)
        aou_line = f"            aou={dict_literal(aou)},"
        if participants:
            ac = min(round(ratio * aou_af(aou) * 2 * participants), 2 * participants)
            hom = min(round(participants * (ac / (2 * participants)) ** 2), ac // 2)
            matched = f"Matched(carriers_ac={ac}" + (f", homozygotes={hom}" if hom else "") + ")"
            matched_line = f"            matched={matched},  # {ratio:g}x the All of Us frequency"
        else:
            matched_line = "            matched=Matched(carriers_ac=0),  # TODO: pass --participants to draft this"
    else:
        aou_line = '            aou={"eur": 1},  # TODO: All of Us allele counts per population (rare: set by hand)'
        matched_line = "            matched=Matched(carriers_ac=1),  # TODO: carriers among the matched participants"

    lines.append("        Variant(")
    lines.append(f'            vid="{vid}", gene="{v["gene"]}", gene_id="{v["gene_id"]}",')
    lines.append(f'            transcript="{v["transcript"]}", mane="{v["mane"]}", hgvsc="{v["hgvsc"]}", hgvsp={v["hgvsp"]!r},')
    where = f'exon="{v["exon"]}"' if v["exon"] else f'exon=None, intron="{v["intron"]}"'
    lines.append(f"            consequence={tup(v['consequence'])}, {where}, rsid={v['rsid']!r},")
    if cv:
        lines.append("            clinvar=ClinVar(")
        lines.append(f'                classification="{cv["classification"]}",')
        lines.append(f'                review_status="{cv["review_status"]}", last_evaluated="{cv["last_evaluated"]}",')
        lines.append(f"                rcvs={tup(cv['rcvs'])},")
        if cv["classification"].startswith("Conflicting"):
            lines.append(f"                rcv_classifications={tup(['Uncertain significance'] * len(cv['rcvs']))},"
                         "  # TODO: each RCV's own classification")
        lines.append(f"                conditions={tup(cv['conditions'])},")
        lines.append("            ),")
    else:
        lines.append("            clinvar=None,")
    lines.append(aou_line)
    gnomad_value = dict_literal(gnomad, value=lambda x: f"({x[0]}, {x[1]})") if gnomad else None
    lines.append(f"            gnomad={gnomad_value},")
    if v["revel"] is not None:
        lines.append(f"            revel={v['revel']},")
    if v["splice_ai"]:
        lines.append(f"            splice_ai={dict_literal(v['splice_ai'])},")
    if v["lof"]:
        lines.append(f'            lof="{v["lof"]}",')
    if v["lof_filter"]:
        lines.append(f"            lof_filter={tup(v['lof_filter'])},")
    if v["lof_flags"]:
        lines.append(f"            lof_flags={tup(v['lof_flags'])},")
    lines.append(matched_line)
    lines.append("        ),")
    return "\n".join(lines)


def summary_line(vid, v, cv, gnomad):
    splice = max(v["splice_ai"][k] or 0 for k in ("DS_AG", "DS_AL", "DS_DG", "DS_DL")) if v["splice_ai"] else None
    gnomad_text = f"{gnomad_af(gnomad):.2g} ({sum(ac for ac, _ in gnomad.values())} alleles)" if gnomad else "not in gnomAD genomes"
    return (f"# {v['gene']} {v['hgvsp'] or v['hgvsc']} ({vid}): {v['consequence'][0]}; "
            f"ClinVar {cv['classification'] if cv else 'none'}; gnomAD {gnomad_text}; "
            f"SpliceAI {'—' if splice is None else f'{splice:.2f}'}; LOFTEE {v['lof'] or '—'}")


def warnings_for(cv):
    out = []
    if cv and cv["classification"] not in VAT_CLASSIFICATIONS:
        out.append(f"ClinVar classification {cv['classification']!r} has no VAT equivalent in use_cases/common.py")
    if cv and cv["review_status"] not in STARS:
        out.append(f"review status {cv['review_status']!r} isn't in STARS in use_cases/common.py")
    return out


# --- Modes ----------------------------------------------------------------------------------

VID = re.compile(r"^(\d{1,2}|X|Y)-\d+-[ACGT]+-[ACGT]+$")


def curate(queries, participants, ratio):
    for query in queries:
        if VID.match(query):
            vid, cv = query, clinvar_by_vid(query)
            gene = cv["genes"][0] if cv and cv["genes"] else None
        elif ":" in query:
            gene, change = query.split(":", 1)
            vid, cv = clinvar_by_protein_change(gene, change.removeprefix("p."))
            if not vid:
                print(f"# {query}: no ClinVar record with that exact protein change\n", file=sys.stderr)
                continue
        else:
            raise SystemExit(f"ERROR: {query!r} is neither chr-pos-ref-alt nor GENE:CHANGE")
        v = vep(vid, gene)
        if v is None:
            print(f"# {query} ({vid}): VEP found no MANE Select transcript\n", file=sys.stderr)
            continue
        gnomad = gnomad_genomes(vid)
        print(summary_line(vid, v, cv, gnomad))
        for warning in warnings_for(cv):
            print(f"# WARNING: {warning}")
        print(variant_spec(vid, v, cv, gnomad, participants, ratio))
        print()


def verify():
    """Re-check every use case variant's recorded facts against the live sources."""
    from use_cases import USE_CASES

    drifted = 0
    for case in USE_CASES:
        for variant in case.variants:
            v = vep(variant.vid, variant.gene)
            cv = clinvar_by_vid(variant.vid)
            gnomad = gnomad_genomes(variant.vid)
            live = {
                "gene_id": v and v["gene_id"], "transcript": v and v["transcript"], "mane": v and v["mane"],
                "hgvsc": v and v["hgvsc"], "hgvsp": v and v["hgvsp"], "consequence": v and v["consequence"],
                "exon": v and v["exon"], "intron": v and v["intron"], "rsid": v and v["rsid"],
                "clinvar.classification": cv and cv["classification"],
                "clinvar.review_status": cv and cv["review_status"],
                "clinvar.last_evaluated": cv and cv["last_evaluated"],
                # As a set: ClinVar doesn't return a variant's RCVs in a stable order.
                "clinvar.rcvs": cv and frozenset(cv["rcvs"]),
                "gnomad": gnomad,
            }
            recorded = {
                "gene_id": variant.gene_id, "transcript": variant.transcript, "mane": variant.mane,
                "hgvsc": variant.hgvsc, "hgvsp": variant.hgvsp, "consequence": variant.consequence,
                "exon": variant.exon, "intron": variant.intron, "rsid": variant.rsid,
                "clinvar.classification": variant.clinvar and variant.clinvar.classification,
                "clinvar.review_status": variant.clinvar and variant.clinvar.review_status,
                "clinvar.last_evaluated": variant.clinvar and variant.clinvar.last_evaluated,
                "clinvar.rcvs": variant.clinvar and frozenset(variant.clinvar.rcvs),
                "gnomad": variant.gnomad,
            }
            differences = [k for k in recorded if recorded[k] != live[k]]
            label = f"{case.key}: {variant.gene} {variant.hgvsp or variant.hgvsc} ({variant.vid})"
            if differences:
                drifted += 1
                print(f"DRIFTED  {label}")
                for k in differences:
                    print(f"    {k}: recorded {recorded[k]!r}, now {live[k]!r}")
            else:
                print(f"ok       {label}")
    total = sum(len(case.variants) for case in USE_CASES)
    print(f"\n{total - drifted} of {total} variants match the live sources; {drifted} have drifted.")
    return drifted == 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("variants", nargs="*", help="chr-pos-ref-alt IDs or GENE:CHANGE (e.g. MYH7:R403Q)")
    ap.add_argument("--participants", type=int,
                    help="the use case's matched participant count, to draft a common variant's matched carriers")
    ap.add_argument("--ratio", type=float, default=1.0,
                    help="the enrichment to draft a common variant's matched carriers at (default 1.0: background)")
    ap.add_argument("--verify", action="store_true", help="re-check every use case variant against the live sources")
    args = ap.parse_args()
    if args.verify:
        sys.exit(0 if verify() else 1)
    if not args.variants:
        ap.error("give at least one variant, or --verify")
    curate(args.variants, args.participants, args.ratio)


if __name__ == "__main__":
    main()
