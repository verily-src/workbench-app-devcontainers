"""The relational graph of a dataset, in pandas: the entity table, the static and the dated tables,
long tables split by code, who is at risk when. No model package is needed here; ``model.py`` turns
this into Kumo's tensors and ``baselines.py`` and ``profile.py`` read it too.

Vocabulary: the *entity key* is the column the cohort's members are keyed by (``person_id`` for
people). A *dated* table has a time column; a *static* table has none. The *entity table* is the
static table with one row per entity.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import schema

TARGET = "outcome_within_horizon"
ROW = "_row_number"
ENTITY = "entity"


@dataclass
class Dataset:
    key: str
    frames: dict[str, pd.DataFrame]       # the graph's tables: entity, static, dated and split tables
    splits: dict[str, pd.DataFrame]       # split table -> (key, time, value), for the statistics
    time: dict[str, str]                  # dated graph table -> its time column
    entity: str                           # the entity table's name
    pk: dict[str, str]                    # table -> the column that identifies a row
    split: dict[str, dict]                # split table -> {source, code_column, code, name}
    raw: dict[str, pd.DataFrame]          # the tables as read, before splitting
    raw_time: dict[str, str | None]       # table as read -> time column or None
    codes: dict[str, str]                 # dated table as read -> its code column
    schemas: dict[str, dict]
    first_seen: pd.Series                 # entity -> its first dated row
    observation: pd.DataFrame | None      # (key, start, end) rows, when the dataset has observation_period
    data_end: pd.Timestamp
    names: dict[str, str] = field(default_factory=dict)
    built_entity_table: bool = False
    entities: pd.DataFrame | None = None   # the entity keys, one row each

    @property
    def dated(self) -> list[str]:
        return [t for t in self.raw if self.raw_time[t] is not None]

    @property
    def static(self) -> list[str]:
        return [t for t in self.raw if self.raw_time[t] is None]

    def tables_read(self) -> dict:
        """What the forecast read, for the answer."""
        return {
            "entity_key": self.key,
            "entity_table": ("built from the distinct keys" if self.built_entity_table else self.entity),
            "tables": [{"table": t, "time_column": self.raw_time[t]} for t in self.raw],
            "split_by_code": {s["source"]: sorted({v["name"] for v in self.split.values() if v["source"] == s["source"]})
                              for s in self.split.values()},
        }


def _pick_code_column(df: pd.DataFrame, columns: list[tuple[str, str]], key: str, time: str | None) -> str | None:
    """The code column of a table: of the candidates with at most 5,000 distinct values, the one
    with the most (a table's own code, not its type or unit)."""
    best, best_n = None, 0
    for c in schema.code_columns(columns, key, time):
        if c not in df:
            continue
        n = int(df[c].nunique())
        if 0 < n <= schema.MAX_CODE_VALUES and n > best_n:
            best, best_n = c, n
    return best


def _observation_period(raw: dict[str, pd.DataFrame], time: dict, schemas: dict, key: str) -> pd.DataFrame | None:
    df = raw.get("observation_period")
    if df is None or time.get("observation_period") is None:
        return None
    start = time["observation_period"]
    ends = [n for n, ty in schemas["observation_period"]["columns"]
            if ty in schema.TIME_TYPES and "end" in n.lower() and n != start and n in df]
    if "start" not in start.lower() or not ends:
        return None
    out = df[[key, start, ends[0]]].copy()
    out.columns = [key, "start", "end"]
    return out.dropna()


def build(raw: dict[str, pd.DataFrame], schemas: dict[str, dict], key: str, time: dict[str, str | None],
          vocabulary: dict[str, str] | None = None, today: pd.Timestamp | None = None) -> Dataset:
    """The graph over the tables as read (``raw``), each with the entity key column."""
    vocabulary = vocabulary or {}
    raw = {n: (df if df[key].notna().all() else df[df[key].notna()]) for n, df in raw.items()}
    static = [n for n in raw if time[n] is None]
    everyone = pd.concat([df[key] for df in raw.values()]).drop_duplicates()
    # One row per entity: unique on the key, and holding every entity the tables mention.
    unique = {n: bool(raw[n][key].is_unique and len(raw[n]) == len(everyone)) for n in static}
    ent = schema.entity_table(static, unique, schemas)
    built = ent is None
    frames: dict[str, pd.DataFrame] = {}
    if built:
        ent = ENTITY
        while ent in raw:
            ent += "_"
        frames[ent] = pd.DataFrame({key: everyone.to_numpy()})
    pk: dict[str, str] = {ent: key}
    for name, df in raw.items():
        if name != ent:
            own = schema.primary_key(name, schemas[name]["columns"],
                                     df[f"{name}_id"].head(10_000).tolist() if f"{name}_id" in df else None)
            if own is None:
                df = df.assign(**{ROW: range(len(df))})   # a copy: ``raw`` is the caller's, and stays as read
                own = ROW
            pk[name] = own
        frames[name] = df
    dated_time = {n: time[n] for n in raw if time[n] is not None}
    codes: dict[str, str] = {}
    split: dict[str, dict] = {}
    for name in list(dated_time):
        cols = schemas[name]["columns"]
        code = _pick_code_column(raw[name], cols, key, time[name])
        if code is None:
            continue
        codes[name] = code
        if schema.value_column(cols, key, code) is None:
            continue
        df = frames[name]
        wanted = schema.frequent_codes(df[code].value_counts().to_dict())
        for c in wanted:
            sname = schema.split_name(name, c)
            frames[sname] = df[df[code] == c].drop(columns=[code])
            pk[sname], dated_time[sname] = pk[name], dated_time[name]
            split[sname] = {"source": name, "code_column": code, "code": c,
                            "name": schema.display_name(c, vocabulary)}
        if wanted:
            frames[name] = df[~df[code].isin(wanted)]
    # What the statistics (baselines, profile) read of a dated table: its key, time and code. The
    # model's columns stay in ``frames`` only until the model has them (``Forecaster``).
    splits = {s: f[[key, dated_time[s], schema.value_column(schemas[split[s]["source"]]["columns"], key,
                                                           split[s]["code_column"])]] for s, f in frames.items() if s in split}
    seen = [raw[n].groupby(key)[time[n]].min() for n in raw if time[n] is not None]
    first_seen = pd.concat(seen, axis=1).min(axis=1) if seen else pd.Series(dtype="datetime64[ns]")
    ends = [raw[n][time[n]].max() for n in raw if time[n] is not None and len(raw[n])]
    if not ends:
        raise schema.SchemaError("none of the tables read has a date column, so a forecast has no history to learn from")
    today = pd.Timestamp.today().normalize() if today is None else today
    entities = pd.DataFrame({key: everyone.to_numpy()})
    observation = _observation_period(raw, time, schemas, key)
    for n in list(raw):
        if time[n] is not None:
            raw[n] = raw[n][[key, time[n]] + ([codes[n]] if n in codes else [])]
    return Dataset(key=key, frames=frames, splits=splits, time=dated_time, entity=ent, pk=pk, split=split, raw=raw,
                   raw_time=dict(time), codes=codes, schemas=schemas, first_seen=first_seen,
                   observation=observation, data_end=min(max(ends), today),
                   names=vocabulary, built_entity_table=built, entities=entities)


def tasks(ds: Dataset, first: pd.Series, cutoff: pd.Timestamp, horizon: int, people: pd.Index | None = None) -> pd.DataFrame:
    """Rows (key, cutoff, label) for the entities at risk at the cutoff: with a dated row on or
    before it (or, with an observation_period table, in observation at it) and not yet through the
    outcome. ``first`` is each entity's outcome date."""
    key = ds.key
    if ds.observation is not None:
        o = ds.observation
        ids = o.loc[(o.start <= cutoff) & (o.end > cutoff), key].drop_duplicates()
    else:
        ids = pd.Series(ds.first_seen.index[ds.first_seen <= cutoff], name=key)
    if people is not None:
        ids = ids[ids.isin(people)]
    onset = ids.map(first)
    ids = ids[onset.isna() | (onset > cutoff)]
    rows = pd.DataFrame({key: ids.to_numpy(), "cutoff": cutoff})
    onset = rows[key].map(first)
    rows[TARGET] = ((onset > cutoff) & (onset <= cutoff + pd.Timedelta(days=horizon))).astype(int).astype(str)
    return rows
