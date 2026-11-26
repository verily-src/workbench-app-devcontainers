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

from . import schema

MOST_PER_TABLE = 6     # codes listed per table in a timeline
MOST_VALUES = 5        # lab-like values listed per member
SHOWN_COLUMNS = 6      # columns listed per table


def sample_records_allowed() -> bool:
    return os.environ.get("KUMO_FORECAST_SAMPLE_RECORDS", "0") == "1"


def table_overview(schemas: dict[str, dict], tables: list[str], key: str) -> list[dict]:
    """Each table read: rows, the column that dates it and its first columns after the key."""
    out = []
    for t in tables:
        cols = [n for n, _ in schemas[t]["columns"] if n != key]
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
