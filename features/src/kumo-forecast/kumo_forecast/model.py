"""NVIDIA Kumo Relational, in context, over the tables of a dataset (structured-data-models).

No features are built by hand. The model reads the tables as they are, linked to the entity table
by the entity key, and the sampler shows each task row only the rows dated on or before its cutoff
(``time_columns``), as in NVIDIA's RelBench example. One schema choice matters: the most frequent
codes of a long table get tables of their own (``dataset.build``). With one table of many codes,
the sampler's 16 rows per table per entity mostly miss the code that predicts the outcome; a table
per frequent code puts each in front of the model.

Labeled context rows are the population at yearly cutoffs before ``as_of`` whose outcome window
ends on or before ``as_of``, so no label the model sees comes from after the forecast date.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from . import privacy, schema
from .dataset import TARGET, Dataset, tasks

# The fewest labeled cases a forecast learns from.
MIN_CASES = 10


def pick_device(gpu_gb: float):
    """The CUDA device with the most free memory, capped at ``gpu_gb`` for this process; else CPU."""
    import torch
    if not torch.cuda.is_available():
        return torch.device("cpu"), None
    free = [(torch.cuda.mem_get_info(i)[0], i) for i in range(torch.cuda.device_count())]
    best_free, idx = max(free)
    total = torch.cuda.get_device_properties(idx).total_memory
    cap = min(gpu_gb * 1e9, best_free * 0.9)
    torch.cuda.set_per_process_memory_fraction(max(cap / total, 0.01), idx)
    return torch.device(f"cuda:{idx}"), cap / 1e9


class Forecaster:
    """Holds the relational graph of one dataset, built once, and answers forecasts on it."""

    def __init__(self, ds: Dataset, gpu_gb: float = 5.0):
        import sdm
        import torch
        self.sdm, self.torch = sdm, torch
        self.ds = ds
        self.device, self.cap_gb = pick_device(gpu_gb)
        key = ds.key
        tables = {}
        for name, df in ds.frames.items():
            # Codes are categories. Converted on a copy: a frame may be one ``raw`` holds too, and
            # the statistics read those as they are.
            df = df.assign(**{c: df[c].astype(str).astype("category") for c in schema.code_columns(
                [(c, "INTEGER") for c in df.columns], key, ds.time.get(name))})
            ov = {ds.pk[name]: "id", key: "id"}
            if name in ds.time:
                ov[ds.time[name]] = "datetime"
            tables[name] = sdm.TableTensor.from_pandas(
                df=df, stypes=sdm.infer_stypes(df.head(10_000), overrides=ov, text="drop", unsupported="drop"))
        self.data = sdm.RelationalData(tables=tables, relationships=[
            {"left_table": n, "left_column": key, "right_table": ds.entity, "right_column": key}
            for n in tables if n != ds.entity])
        self.sampler = self.data.sampler(time_columns=ds.time)
        self.model = sdm.models.KumoRelational(device=self.device)
        self.data_end = ds.data_end
        # The tensors hold the model's columns from here on. Dropped only now: a build that failed
        # (out of GPU memory, say) leaves the cached Dataset whole for the next attempt.
        ds.frames.clear()

    def run(self, first: pd.Series, members: pd.DataFrame, as_of: pd.Timestamp, horizon: int = 365,
            context: int = 3000, history_years: int = 5, seed: int = 0, estimators: int = 1,
            neighbors: int = 16) -> dict:
        """Scores for the members at risk at ``as_of`` (``members``: the key column, and optionally
        ``index_date``), and the labels where they are known. ``first`` is each entity's outcome date."""
        sdm, torch, ds = self.sdm, self.torch, self.ds
        key = ds.key
        t0 = time.time()
        pool = pd.concat([tasks(ds, first, as_of - pd.DateOffset(years=k), horizon)
                          for k in range(1, history_years + 1)], ignore_index=True)
        pool = pool[pool.cutoff + pd.Timedelta(days=horizon) <= as_of]
        cases = int((pool[TARGET] == "1").sum())
        if cases < MIN_CASES:
            raise ValueError(f"too few cases before {as_of.date()} to learn from ({privacy.count(cases)} in "
                             f"the population; at least {MIN_CASES} are needed)")
        people = pd.Index(members[key].unique())
        if "index_date" in members:
            started = members[members.index_date.isna() | (members.index_date <= as_of)][key]
            people = pd.Index(started.unique())
        query = tasks(ds, first, as_of, horizon, people)
        excluded = {"not_yet_in_the_cohort_on_as_of": int(members[key].nunique() - len(people)),
                    "not_at_risk_or_already_had_the_outcome": int(len(people) - len(query))}
        if query.empty:
            shown = {k: privacy.count(v) for k, v in excluded.items()}
            raise ValueError(f"none of the cohort's {privacy.count(members[key].nunique())} members is at risk on "
                             f"{as_of.date()}: {shown['not_yet_in_the_cohort_on_as_of']} join the cohort later and "
                             f"{shown['not_at_risk_or_already_had_the_outcome']} have no record by then or "
                             "already had the outcome. A cohort defined by the outcome cannot be forecast for it; "
                             "choose another outcome or a cohort without it.")
        rng = np.random.default_rng(seed)
        pos, neg = pool[pool[TARGET] == "1"], pool[pool[TARGET] == "0"]
        n_pos = min(len(pos), context // 4)
        ctx = pd.concat([pos.sample(n=n_pos, random_state=seed),
                         neg.sample(n=min(len(neg), context - n_pos), random_state=seed)])
        ctx = ctx.sample(frac=1, random_state=int(rng.integers(1 << 30))).reset_index(drop=True)
        st = {key: "id", "cutoff": "datetime", TARGET: "categorical"}
        context_t = sdm.TableTensor.from_pandas(df=ctx, stypes=st)
        query_t = sdm.TableTensor.from_pandas(df=query.reset_index(drop=True), stypes=st)
        kw = {"task_link": {"task_column": key, "table": ds.entity, "table_column": key},
              "num_neighbors": [neighbors, neighbors], "task_time_column": "cutoff"}
        torch.manual_seed(seed)
        if self.device.type == "cuda":
            torch.cuda.reset_peak_memory_stats(self.device)
        amp = self.device.type == "cuda"
        cs, rel = self.sampler(context_t, **kw).to(self.device)
        with torch.amp.autocast(self.device.type, torch.float16, enabled=amp):
            self.model.fit(x=cs.drop_columns(TARGET), y=cs[TARGET], related_tables=rel,
                           num_estimators=estimators)
        scores = []
        for b in query_t.split(1000, -2):
            with torch.amp.autocast(self.device.type, torch.float16, enabled=amp):
                out = self.model.predict(*self.sampler(b.drop_columns(TARGET), **kw).to(self.device))
            # The probability of the positive class, read by name (the output's columns are the
            # context's classes); a batch's own labels may hold no positive, or none be known yet.
            scores.append(torch.as_tensor(out.to_pandas()["1"].to_numpy(dtype="float32")))
        self.model.clear()
        query["risk"] = torch.cat(scores).numpy()
        known = as_of + pd.Timedelta(days=horizon) <= self.data_end
        return {"scores": query, "pool": pool, "excluded": excluded, "labels_known": bool(known),
                "context_rows": len(ctx), "context_positives": int(n_pos),
                "seconds": round(time.time() - t0, 1), "device": str(self.device),
                "peak_gpu_gb": round(torch.cuda.max_memory_allocated(self.device) / 1e9, 2) if amp else None}
