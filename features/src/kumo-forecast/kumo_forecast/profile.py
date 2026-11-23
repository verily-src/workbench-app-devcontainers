"""What the highest-risk entities have in common: the top 10% of a forecast against the rest of the
entities at risk, in aggregates only (masked counts and rates, medians), as of the forecast date.

Built by rule from the schema, for any dataset: for each static categorical column, the shares of
its three most common values; for each split table, the median last value (None when fewer entities
than the small-cell threshold have one); for each dated table with a code column, the eight codes
most over-represented in the top 10%, as shares.
"""
from __future__ import annotations

import pandas as pd

from . import privacy, schema
from .dataset import Dataset

COMMON_VALUES = 3
OVER_REPRESENTED = 8
MAX_DISTINCT = 50


def _share(mask: pd.Series) -> str:
    return privacy.rate(int(mask.sum()), len(mask))


def _median(values: pd.Series) -> float | None:
    """The median of the values held, or None when fewer entities than the small-cell threshold
    hold one: the median of a handful is one of their values."""
    held = values.dropna()
    if held.empty or len(held) < privacy.threshold():
        return None
    return round(float(held.median()), 1)


def high_risk_profile(ds: Dataset, scores: pd.DataFrame, as_of: pd.Timestamp,
                      codes: int = OVER_REPRESENTED) -> list[dict]:
    """Rows of (characteristic, top 10%, rest) for the entities scored."""
    key = ds.key
    s = scores.sort_values("risk", ascending=False)
    k = max(1, len(s) // 10)
    top, rest = pd.Index(s.head(k)[key]), pd.Index(s.iloc[k:][key])
    names = ds.names
    rows: list[dict] = [{"characteristic": "people" if key == "person_id" else "entities",
                         "top_10pct": privacy.count_of(len(top), len(s)),
                         "rest": privacy.count_of(len(rest), len(s))}]

    def both(label, fn):
        rows.append({"characteristic": label, "top_10pct": fn(top), "rest": fn(rest)})

    for name in ds.static:
        df = ds.raw[name].drop_duplicates(key).set_index(key)
        for c, ty in ds.schemas[name]["columns"]:
            if c == key or c not in df:
                continue
            if not (ty == "STRING" or (ty in schema.INTEGER_TYPES and schema.CODE_NAME.search(c.lower()))):
                continue
            if df[c].nunique() > MAX_DISTINCT:
                continue    # free text or an identifier, not a characteristic
            counts = df.loc[df.index.isin(s[key]), c].value_counts()
            # A value held by fewer entities than the small-cell threshold would name them.
            for v in counts[counts >= max(privacy.threshold(), 1)].head(COMMON_VALUES).index:
                both(f"{c}: {schema.display_name(v, names) if ty != 'STRING' else v}",
                     lambda ids, c=c, v=v: _share(df[c].reindex(ids) == v))
    for sname, info in ds.split.items():
        value = schema.value_column(ds.schemas[info["source"]]["columns"], key, info["code_column"])
        d = ds.splits[sname]
        last = d[d[ds.time[sname]] <= as_of].sort_values(ds.time[sname]).groupby(key)[value].last()
        both(f"median latest {info['name']} ({info['source']})", lambda ids, last=last: _median(last.reindex(ids)))
    for name, code in ds.codes.items():
        d = ds.raw[name]
        d = d[(d[ds.raw_time[name]] <= as_of) & d[key].isin(s[key])].drop_duplicates([key, code])
        top_share = d[d[key].isin(top)][code].value_counts() / max(len(top), 1)
        rest_share = d[d[key].isin(rest)][code].value_counts() / max(len(rest), 1)
        lift = (top_share - rest_share.reindex(top_share.index).fillna(0)).sort_values(ascending=False)
        held = d[code].value_counts()
        lift = lift[lift.index.map(lambda c: held.get(c, 0) >= max(privacy.threshold(), 1))]
        for c in lift.head(codes).index:
            had = set(d.loc[d[code] == c, key])
            both(f"{name}.{code}: {schema.display_name(c, names)}", lambda ids, h=had: _share(ids.isin(h)))
    return rows
