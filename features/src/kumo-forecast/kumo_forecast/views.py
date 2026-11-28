"""Short, ready answers for showing the data a forecast reads: the cohort's records (tables and a
few members' timelines, from the graph already loaded), its genomes (a manifest table) and a VCF.

They exist so the agent does not write and debug its own queries for these views. Sample records
are shown only when the server allows it (``KUMO_FORECAST_SAMPLE_RECORDS=1``, for synthetic data)
and never with an id: members are "Patient 1", "Patient 2" and so on.
"""
from __future__ import annotations

import gzip
import io
import os
import re

import pandas as pd

from . import privacy, schema

MOST_PER_TABLE = 6     # codes listed per table in a timeline
MOST_VALUES = 5        # lab-like values listed per member
SHOWN_COLUMNS = 6      # columns listed per table


def sample_records_allowed() -> bool:
    return os.environ.get("KUMO_FORECAST_SAMPLE_RECORDS", "0") == "1"


def table_overview(schemas: dict[str, dict], tables: list[str], key: str) -> list[dict]:
    """Each table read: rows, the column that dates it and its first columns after the key."""
    from .profile import SENSITIVE
    out = []
    for t in tables:
        cols = [n for n, _ in schemas[t]["columns"] if n != key and not SENSITIVE.search(n)]
        out.append({"table": t, "rows": int(schemas[t].get("num_rows", 0)),
                    "dated_by": schema.time_column(schemas[t]["columns"]),
                    "columns": cols[:SHOWN_COLUMNS] + (["..."] if len(cols) > SHOWN_COLUMNS else [])})
    return out


def _day(t) -> str:
    return str(pd.Timestamp(t).date())


def timeline(ds, entity) -> dict:
    """One member's history from the graph: for each dated table with a code column, its codes by
    name with the first and last date and how often; then the member's most recorded values
    (labs, vitals) as first and last value."""
    key, names = ds.key, ds.names
    out: dict = {}
    for name, code in ds.codes.items():
        d = ds.raw[name]
        rows = d[d[key] == entity]
        if rows.empty:
            continue
        time = ds.raw_time[name]
        g = rows.groupby(code)[time].agg(["min", "max", "count"]).sort_values("min")
        out[name] = [{"what": schema.display_name(c, names), "first": _day(r["min"]), "last": _day(r["max"]),
                      "times": int(r["count"])} for c, r in g.head(MOST_PER_TABLE).iterrows()]
        if len(g) > MOST_PER_TABLE:
            out[name].append({"more": int(len(g) - MOST_PER_TABLE)})
    values = []
    for sname, info in ds.split.items():
        d = ds.splits[sname]
        rows = d[d[key] == entity]
        if rows.empty:
            continue
        time, value = rows.columns[1], rows.columns[2]
        rows = rows.dropna(subset=[value]).sort_values(time)
        if rows.empty:
            continue
        values.append({"what": info["name"], "first": f"{rows[value].iloc[0]:g} on {_day(rows[time].iloc[0])}",
                       "last": f"{rows[value].iloc[-1]:g} on {_day(rows[time].iloc[-1])}", "times": int(len(rows))})
    if values:
        out["values"] = sorted(values, key=lambda v: -v["times"])[:MOST_VALUES]
    return out


def pick_members(ds, members: pd.Series, n: int, seed: int = 7) -> list:
    """``n`` members with a history in the graph (dated rows in at least two tables), the same
    ones every time for the same cohort."""
    key = ds.key
    held = set()
    for name in ds.codes:
        held |= set(ds.raw[name][key].unique())
    pool = pd.Series(sorted(set(members) & held))
    if pool.empty:
        return []
    return pool.sample(n=min(n, len(pool)), random_state=seed).tolist()


# ---- genomes ------------------------------------------------------------------------------------

_REGION = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*=\s*(chr[0-9XYMT]+|[0-9XYMT]+):([0-9,]+)-([0-9,]+)\s*$")


def parse_regions(text: str | None) -> list[tuple[str, str, int, int]]:
    """``"APOL1=chr22:36245000-36275000; PCSK9=chr1:55030000-55070000"`` as (name, chrom, start, end)."""
    out = []
    for part in [p for p in re.split(r"[;\n]", text or "") if p.strip()]:
        m = _REGION.match(part)
        if not m:
            raise ValueError(f"region {part.strip()!r} is not NAME=chrom:start-end (such as APOL1=chr22:36245000-36275000)")
        name, chrom, start, end = m.groups()
        out.append((name, chrom, int(start.replace(",", "")), int(end.replace(",", ""))))
    return out


def manifest_summary(df: pd.DataFrame, key: str, members: pd.Series) -> dict:
    """Genomes in all and in the cohort, and the columns with few values (coverage, processing,
    build, staged), counted over the cohort's genomes."""
    mine = df[df[key].isin(set(members))]
    described = {}
    for c in df.columns:
        if c == key or c.endswith("_uri") or c.endswith("_id"):
            continue
        values = mine[c].dropna()
        if values.empty or values.nunique() > 4:
            continue
        described[c] = {str(v): int(n) for v, n in values.value_counts().items()}
    return {"genomes": int(len(df)), "of_the_cohort": int(len(mine)), "cohort_genomes": described}


def size_estimate(sizes: list[int], genomes: int) -> dict:
    """One genome's aligned reads and what all would add up to, from the files that are present."""
    if not sizes:
        return {"note": "no aligned-reads file of the manifest is in a bucket"}
    each = sum(sizes) / len(sizes)
    return {"files_present": len(sizes), "one_genome_gb": round(each / 1e9, 1),
            "all_genomes_tb_estimated": round(each * genomes / 1e12, 1)}


SEX_BY_GENDER_CONCEPT = {8532: "XX", 8507: "XY"}   # OMOP gender concepts as sarek's sex
SAMPLESHEET_COLUMNS = ("research_id", "cram_uri", "crai_uri", "is_staged")


def staged_genomes(df: pd.DataFrame, key: str, members: pd.Series) -> pd.DataFrame | None:
    """The cohort's genomes whose files are in a bucket (is_staged), or None for a manifest without
    the columns a samplesheet needs."""
    if not all(c in df for c in SAMPLESHEET_COLUMNS):
        return None
    staged = df[df[key].isin(set(members)) & df["is_staged"].fillna(False).astype(bool)]
    return staged[staged.cram_uri.notna() & staged.crai_uri.notna()].sort_values("research_id")


def samplesheet(staged: pd.DataFrame, key: str, sex: dict) -> str:
    """sarek's samplesheet for aligned reads: patient,sex,status,sample,cram,crai, with each genome's
    research_id as patient and sample (never the numeric key), status 0 and sex XX, XY or NA."""
    lines = ["patient,sex,status,sample,cram,crai"]
    for _, r in staged.iterrows():
        rid = str(r["research_id"])
        lines.append(f"{rid},{sex.get(r[key], 'NA')},0,{rid},{r['cram_uri']},{r['crai_uri']}")
    return "\n".join(lines) + "\n"


VCF_COLUMNS = {
    "CHROM": "the chromosome",
    "POS": "the position on it (1-based)",
    "REF": "the base(s) the reference genome has there",
    "ALT": "the base(s) this genome has instead",
    "QUAL": "how confident the call is (Phred scale: 30 means 1 in 1,000 wrong)",
    "GT": "the genotype: 0/1 one copy of ALT, 1/1 two copies, 0/0 none",
}


def vcf_summary(data: bytes, regions: list[tuple[str, str, int, int]], rows: int = 5) -> dict:
    """A VCF's counts (records, PASS, SNPs, indels), its variants per region, and ``rows`` PASS
    rows from the first region (or from anywhere, without regions)."""
    text = gzip.open(io.BytesIO(data), "rt") if data[:2] == b"\x1f\x8b" else io.StringIO(data.decode())
    records = passed = snps = indels = 0
    per_region = {name: 0 for name, *_ in regions}
    sample_name, shown = None, []
    for line in text:
        if line.startswith("##"):
            continue
        f = line.rstrip("\n").split("\t")
        if line.startswith("#"):
            sample_name = f[9] if len(f) > 9 else None
            continue
        records += 1
        chrom, pos, ref, alt, qual, flt = f[0], int(f[1]), f[3], f[4], f[5], f[6]
        ok = flt == "PASS"
        passed += ok
        if ok:
            if len(ref) == 1 and all(len(a) == 1 for a in alt.split(",")):
                snps += 1
            else:
                indels += 1
        inside = None
        for name, rc, start, end in regions:
            if chrom.removeprefix("chr") == rc.removeprefix("chr") and start <= pos <= end:
                per_region[name] += ok   # a variant: a PASS call (RefCall rows confirm the reference)
                inside = inside or name
        first = regions[0][0] if regions else None
        if ok and len(shown) < rows and (first is None or inside == first):
            gt = f[9].split(":")[0] if len(f) > 9 else ""
            shown.append({"CHROM": chrom, "POS": pos, "REF": ref, "ALT": alt, "QUAL": qual, "GT": gt})
    out = {"sample": sample_name, "records": records, "passed": passed, "passed_snps": snps,
           "passed_indels": indels, "rows": shown, "columns": VCF_COLUMNS}
    if regions:
        out["variants_per_region"] = {name: n for name, n in per_region.items()}
        out["regions"] = {name: f"{c}:{s:,}-{e:,}" for name, c, s, e in regions}
    return out


# ---- tables ---------------------------------------------------------------------------------------
# The views answer as Markdown tables, built here, so what the page shows does not depend on how a
# model words it: the assistant page draws a tool answer's "table" under the tool's card.

PATIENT_TABLES = ("condition_occurrence", "drug_exposure", "procedure_occurrence")

# What an OMOP table holds, in a visitor's words. A table not named here shows by its own name.
TABLE_NAMES = {
    "measurement": "Lab results and vitals",
    "visit_occurrence": "Visits",
    "drug_exposure": "Prescriptions",
    "observation": "Other observations",
    "condition_occurrence": "Diagnoses",
    "procedure_occurrence": "Procedures",
    "person": "People",
    "death": "Deaths",
    "device_exposure": "Devices",
    "observation_period": "Periods of care",
    "wgs_sample_manifest": "Genome list",
}
# Bookkeeping tables: counted in the total, never listed by name.
BACKGROUND_TABLES = {"cb_search_person", "observation_period", "wgs_sample_manifest"}
# Lab names as a clinician says them, after short_name.
LAB_NAMES = {"Glomerular filtration rate": "eGFR", "Hemoglobin A1c (Glycated)": "HbA1c",
             "Hemoglobin A1c": "HbA1c", "Creatinine serum/plasma": "Creatinine",
             "Albumin/Creatinine": "Urine albumin/creatinine"}
SHOWN_TABLES = 6       # tables listed by name; the rest are summed in one row
SHOWN_CODES = 5        # diagnoses (or other codes) per patient
SHOWN_DRUGS = 3        # medicines per patient
SHOWN_VALUES = 3       # lab values per patient


def _cell(text) -> str:
    return str(text).replace("|", "/").replace("\n", " ")


def short_name(name: str, most: int = 40) -> str:
    """A concept's name without its bracketed detail, at most ``most`` characters
    ("Glomerular filtration rate/1.73 sq M.predicted [Volume Rate/Area] ..." -> "Glomerular filtration rate")."""
    name = re.split(r" \[|/[0-9]", str(name))[0].strip()
    return name if len(name) <= most else name[: most - 1].rstrip() + "…"


def lab_name(name: str) -> str:
    short = short_name(name)
    return LAB_NAMES.get(short, short)


def _fmt(n) -> str:
    return f"{n:,}" if isinstance(n, int) else str(n)


def _about(n: int) -> str:
    """4,567,890 -> "4.6 million"; smaller counts as they are."""
    return f"{n / 1e6:.1f} million" if n >= 1_000_000 else _fmt(n)


def _year(day: str) -> str:
    return str(day)[:4]


def records_table(overview: list[dict], people: list[dict], everyone: int | None = None,
                  members: int | None = None) -> str:
    """A headline (what Kumo learns from and whom it forecasts for), the largest tables by what they
    hold with their rows for everyone and for the cohort's members, then a few members picked at
    random: when they joined the cohort, their first diagnoses and medicines by year, and their most
    recorded lab values first to last. ``everyone``: the people in the data; ``members``: the
    cohort's; each overview row may hold ``cohort_rows``."""
    total = sum(int(t["rows"]) for t in overview)
    biggest = sorted(overview, key=lambda t: (t["table"] in BACKGROUND_TABLES, -int(t["rows"])))
    whom = f" for {_fmt(everyone)} people" if everyone else ""
    head = (f"**Kumo learns from the whole dataset, {len(overview)} tables with {_about(total)} rows of health "
            f"records{whom}, with no hand-built features"
            + (f", and forecasts for this cohort's {_fmt(members)} members.**" if members else ".**"))
    split = members is not None and all("cohort_rows" in t for t in overview)
    cols = ["Records", f"All {_fmt(everyone)} people" if everyone else "Rows"] + (
        [f"This cohort's {_fmt(members)}"] if split else [])
    lines = [head, "", "| " + " | ".join(cols) + " |", "|---|" + "---:|" * (len(cols) - 1)]

    def row(name, rows, cohort):
        return f"| {_cell(name)} | {_fmt(rows)} |" + (f" {_fmt(cohort)} |" if split else "")
    shown = [t for t in biggest if t["table"] not in BACKGROUND_TABLES][:SHOWN_TABLES]
    for t in shown:
        lines.append(row(TABLE_NAMES.get(t["table"], t["table"]), int(t["rows"]), t.get("cohort_rows")))
    rest = [t for t in biggest if t not in shown]
    if rest:
        lines.append(row(f"{len(rest)} more tables", sum(int(t["rows"]) for t in rest),
                         sum(int(t.get("cohort_rows", 0)) for t in rest)))
    if not people:
        return "\n".join(lines)
    tables = [t for t in PATIENT_TABLES[:2] if any(t in p for p in people)]
    if not tables:   # not OMOP: the first two event tables the patients have
        seen = [k for p in people for k in p if k not in ("label", "in_the_cohort_from", "values")]
        tables = list(dict.fromkeys(seen))[:2]
    most = {t: SHOWN_DRUGS if t == "drug_exposure" else SHOWN_CODES for t in tables}
    some = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five"}.get(len(people), str(len(people)))
    lines += ["", f"*{some} of the cohort's {_fmt(members) + ' ' if members else ''}members, picked at random, "
                  "as examples of what a record holds (synthetic patients; no names or ids):*"]
    head_row = ["Patient", "In the cohort since"] + [TABLE_NAMES.get(t, t.replace("_", " ")) for t in tables] + ["Labs (first → last)"]
    lines += ["", "| " + " | ".join(head_row) + " |", "|" + "---|" * len(head_row)]
    for p in people:
        cells = [p["label"], _year(p.get("in_the_cohort_from", "-"))]
        for t in tables:
            items = [i for i in p.get(t, []) if "what" in i][: most[t]]
            cells.append(_cell(", ".join(f"{short_name(i['what'])} ({_year(i['first'])})" for i in items) or "-"))
        cells.append(_cell("; ".join(f"{lab_name(v['what'])}: {v['first'].split(' on ')[0]} → {v['last'].split(' on ')[0]}"
                                     for v in p.get("values", [])[:SHOWN_VALUES]) or "-"))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _copies(gt: str) -> str:
    """A genotype as copies of the variant: 0/1 -> 1, 1/1 -> 2."""
    alleles = re.split(r"[/|]", gt or "")
    n = sum(a not in ("0", ".") for a in alleles)
    return str(n) if gt else "-"


def genomes_table(summary: dict, vcf: dict | None) -> str:
    """A headline (genomes in all and of the cohort), their size, what Parabricks found in one
    genome per gene, then a few of its variants in plain words."""
    lines = [f"**{_fmt(summary['genomes'])} whole genomes, {_fmt(summary['of_the_cohort'])} of them from this "
             "cohort's members.**", "", "| | |", "|---|---|"]
    coverage = summary.get("cohort_genomes", {}).get("nominal_coverage")
    reads = summary.get("aligned_reads", {})
    each = "Whole genome" + (f", {next(iter(coverage))}x coverage" if coverage and len(coverage) == 1 else "")
    if "one_genome_gb" in reads:
        each += f": about {reads['one_genome_gb']} GB of sequencing reads"
        lines.append(f"| One genome | {_cell(each)} |")
        lines.append(f"| All of them | about {reads['all_genomes_tb_estimated']} TB |")
    else:
        lines.append(f"| One genome | {_cell(each)} |")
    rows = vcf.get("rows", []) if vcf else []
    if vcf:
        per = vcf.get("variants_per_region", {})
        found = (", ".join(f"{n} in {name}" for name, n in per.items()) if per
                 else f"{_fmt(vcf['passed'])} variants")
        lines.append(f"| Parabricks found, in one genome | {_cell(found)} |")
    if rows:
        gene = next(iter(vcf.get("variants_per_region", {})), "")
        lines += ["", "| Gene | Position | Reference → this genome | Copies |", "|---|---|---|---:|"]
        for r in rows[:3]:
            lines.append(f"| {_cell(gene or '-')} | {_cell(r['CHROM'])}:{_fmt(r['POS'])} | "
                         f"{_cell(r['REF'])} → {_cell(r['ALT'])} | {_copies(r['GT'])} |")
    return "\n".join(lines)


def tenth_summary(scores: pd.DataFrame, target: str, labels_known: bool) -> dict:
    """The highest-risk tenth of a forecast's scores: how many of the cases it holds and its rate
    against the rest's, where the outcome is known."""
    s = scores.sort_values("risk", ascending=False)
    k = max(1, int(round(len(s) * 0.1)))
    if not labels_known:
        return {"people": k}
    y = s[target].astype(int)
    top, rest = y.iloc[:k], y.iloc[k:]
    return {"people": k, "cases_in_it": privacy.count(int(top.sum())), "cases": privacy.count(int(y.sum())),
            "rate": privacy.rate(int(top.sum()), len(top)),
            "rate_in_the_rest": privacy.rate(int(rest.sum()), len(rest)) if len(rest) else "-"}


def genotype_comparison_table(population: str, outcome: str, at_risk, runs: dict) -> str:
    """Two forecasts on the same people side by side: from the health records alone and with a
    genotype table too."""
    a, b = runs["health_records_only"], runs["with_genotypes"]
    lines = [f"**The same {_fmt(at_risk)} people, forecast twice: {_cell(outcome)}.**", "",
             "| | Health records only | Health records + genotypes |", "|---|---|---|"]

    def auroc(r):
        o = r["observed"]
        return f"{o['auroc']:.3f}" if isinstance(o, dict) and o.get("auroc") is not None else "-"
    lines.append(f"| Accuracy (AUROC) | {auroc(a)} | {auroc(b)} |")
    ta, tb = a["highest_risk_tenth"], b["highest_risk_tenth"]
    if "cases" in ta and "cases" in tb:
        lines.append(f"| Cases in the highest-risk tenth | {ta['cases_in_it']} of {ta['cases']} | {tb['cases_in_it']} of {tb['cases']} |")
        lines.append(f"| Rate in the highest-risk tenth vs the rest | {ta['rate']} vs {ta['rate_in_the_rest']} | "
                     f"{tb['rate']} vs {tb['rate_in_the_rest']} |")
    rows_b = {r["characteristic"]: r for r in b["genotypes"]}
    for r in a["genotypes"]:
        other = rows_b.get(r["characteristic"])
        label = r["characteristic"].split(": ", 1)[-1]
        label = label[:1].upper() + label[1:]
        lines.append(f"| {_cell(label)}: highest-risk tenth vs the rest | {r['top_10pct']} vs {r['rest']} | "
                     + (f"{other['top_10pct']} vs {other['rest']} |" if other else "- |"))
    return "\n".join(lines)
