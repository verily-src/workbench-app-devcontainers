"""What the MCP tools do: resolve the locked cohort and the outcome, run Kumo, compare, select the highest risk.

Participant-level results stay on disk, owner-only, under ``<state>/runs``; what goes back to the
agent is counts and rates, masked below the small-cell threshold (``privacy``), and never a
person_id. A run is named by its run_id so the agent passes a short id between tools.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import cohort as cohort_mod
from . import dataset as dataset_mod
from . import destination as destination_mod
from . import outcome as outcome_mod
from . import privacy, schema, tables, views
from .dataset import TARGET

# An extra table to read beside the cohort's dataset: project.dataset.table.
EXTRA_TABLE = re.compile(r"^`?([a-z][a-z0-9-]{4,28}[a-z0-9])\.([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)`?$")

# The labeled histories are cut at yearly dates up to HISTORY_YEARS before as_of, and only those
# whose outcome window ends by as_of count, so a longer horizon leaves none to learn from.
HISTORY_YEARS = 5
MAX_HORIZON_DAYS = 365 * HISTORY_YEARS


class Service:
    def __init__(self, sessions_dir: Path, state_dir: Path, billing_project: str | None = None,
                 gpu_gb: float = 5.0, context: int = 3000, estimators: int = 2):
        self.sessions_dir, self.state = Path(sessions_dir), Path(state_dir)
        self.billing, self.gpu_gb = billing_project, gpu_gb
        self.context, self.estimators = int(context), int(estimators)
        for d in (self.state, self.state / "runs", self.state / "cache"):
            d.mkdir(parents=True, exist_ok=True)
            os.chmod(d, 0o700)
        self._lock = threading.Lock()
        # The graphs read, most recently used last: the cohort's dataset alone and with a genotype
        # table are both kept, so the steps of one demo do not read each other's out again.
        self._graphs: OrderedDict[tuple, tuple] = OrderedDict()
        self.max_graphs = max(1, int(os.environ.get("KUMO_FORECAST_GRAPHS", "2")))
        self._clients: dict[str | None, object] = {}

    # ---- plumbing ----------------------------------------------------------------------------
    def _client(self, project: str | None):
        from google.cloud import bigquery
        project = self.billing or project
        if project not in self._clients:
            self._clients[project] = bigquery.Client(project=project)
        return self._clients[project]

    @staticmethod
    def _cache_key(dataset, key, overrides, chosen):
        return (dataset, key, tuple(sorted((overrides or {}).items())), tuple(sorted(chosen)) if chosen else None)

    def graph(self, dataset: str, key: str, project: str | None = None, overrides: dict | None = None,
              chosen: list[str] | None = None):
        """``(Dataset, plan)`` for the chosen tables of a dataset keyed on ``key`` (default: every table
        with the key), read once. The model is built on first use. The ``max_graphs`` most recently
        used choices are kept; a run that needs an older one finds its choice in its own metadata
        and reads it again."""
        cache_key = self._cache_key(dataset, key, overrides, chosen)
        if cache_key in self._graphs:
            self._graphs.move_to_end(cache_key)
        else:
            client = self._client(project)
            schemas = tables.read_schemas(client, dataset)
            p = tables.plan(schemas, key, overrides, chosen)
            while len(self._graphs) >= self.max_graphs:
                self._graphs.popitem(last=False)
            raw = tables.load(client, dataset, p, self.state / "cache")
            vocab = tables.vocabulary(client, dataset, schemas)
            self._graphs[cache_key] = (dataset_mod.build(raw, schemas, key, p.time, vocab), p, [None])
        return self._graphs[cache_key][:2]

    def forecaster(self, dataset: str, key: str, project: str | None = None, overrides: dict | None = None,
                   chosen: list[str] | None = None):
        self.graph(dataset, key, project, overrides, chosen)
        entry = self._graphs[self._cache_key(dataset, key, overrides, chosen)]
        if entry[2][0] is None:
            from .model import Forecaster
            entry[2][0] = Forecaster(entry[0], gpu_gb=self.gpu_gb)
        return entry[2][0]

    def _with_extra(self, pop, chosen: list[str] | None, extra: list[str] | None) -> tuple[str, list[str] | None]:
        """The datasets to read (the cohort's, then each extra table's) and the tables to choose:
        ``chosen``, else every table of the cohort's own dataset with the key, then the extra
        tables, which must have the key too (``plan`` checks it)."""
        if not extra:
            return pop.dataset, chosen
        own = tables.datasets_of(pop.dataset)
        parsed = []
        for t in extra:
            m = EXTRA_TABLE.match(str(t).strip())
            if not m:
                raise ValueError(f"extra table {t!r} is not a project.dataset.table name")
            parsed.append(m.groups())
        dataset = ",".join(dict.fromkeys(own + [f"{p}.{d}" for p, d, _ in parsed]))
        schemas = tables.read_schemas(self._client(pop.billing_project), dataset)
        names = list(chosen) if chosen else [t for t in schema.tables_with_key(schemas, pop.key_data_column)
                                             if schemas[t].get("source") in own]
        for p, d, t in parsed:
            name = next((n for n, s in schemas.items() if s.get("source") == f"{p}.{d}" and s.get("table") == t), None)
            if name is None:
                raise ValueError(f"extra table {p}.{d}.{t} is not a table of {p}.{d}")
            names.append(name)
        return dataset, list(dict.fromkeys(names))

    def warm(self, extra_tables: list[str] | None = None) -> list[str]:
        """Read the newest locked cohort's dataset and build its model, then the same with each
        extra table (such as a genotype table; "dataset.table" is in the project BigQuery jobs run
        in, the workspace's), so no demo step waits on either. Returns what was warmed or why not;
        one that fails does not stop the others."""
        done = []
        with self._lock:
            pop = self._locked("latest", None)
            project = pop.billing_project or tables.datasets_of(pop.dataset)[0].split(".")[0]
            extra_tables = [t if t.count(".") == 2 else f"{project}.{t}" for t in (extra_tables or [])]
            for extra in [None] + [[t] for t in extra_tables]:
                what = pop.dataset if extra is None else f"{pop.dataset} with {extra[0]}"
                try:
                    dataset, chosen = self._with_extra(pop, None, extra)
                    fc = self.forecaster(dataset, pop.key_data_column, pop.billing_project, None, chosen)
                    primed = fc.prime() if hasattr(fc, "prime") else None
                    done.append(f"warmed {what}" + (f" (primed in {primed} s)" if primed is not None else ""))
                except Exception as err:  # noqa: BLE001 - warming is optional
                    done.append(f"not warmed {what} ({type(err).__name__}: {str(err)[:200]})")
        return done

    def _table_members(self, lc, table: str, key_type: str | None) -> pd.DataFrame:
        """The distinct keys of ``table`` (project.dataset.table, with the entity key column), as
        the population to score instead of the cohort's members."""
        m = EXTRA_TABLE.match(str(table).strip())
        if not m:
            raise ValueError(f"population_table {table!r} is not a project.dataset.table name")
        project, dataset, name = m.groups()
        key = lc.key_data_column
        sql = f"SELECT DISTINCT `{key}` FROM `{project}`.`{dataset}`.`{name}` WHERE `{key}` IS NOT NULL"
        try:
            df = self._client(lc.billing_project).query(sql).to_dataframe()
        except Exception as err:  # noqa: BLE001 - the BigQuery error says which: no table, no column, no access
            raise ValueError(f"population_table {project}.{dataset}.{name}: {str(err)[:300]}") from err
        return pd.DataFrame({key: _as_key(df[key], key_type)}).drop_duplicates(key)

    def _schemas(self, lc) -> dict[str, dict]:
        return tables.read_schemas(self._client(lc.billing_project), lc.dataset)

    def _locked(self, session_id: str, version: int | None):
        lc = cohort_mod.locked_cohort(cohort_mod.load_session(self.sessions_dir, session_id), version)
        if lc.key_data_column is None:
            lc = cohort_mod.resolve_key(lc, tables.read_schemas(self._client(lc.billing_project), lc.dataset))
        return lc

    def _frame(self, lc, ds_key_type: str | None) -> pd.DataFrame:
        df = self._client(lc.billing_project).query(lc.sql).to_dataframe()
        out = pd.DataFrame({lc.key_data_column: _as_key(df[lc.key_column], ds_key_type)})
        if lc.index_column and lc.index_column in df:
            out["index_date"] = pd.to_datetime(df[lc.index_column])
        return out.drop_duplicates(lc.key_data_column)

    def _outcome_dates(self, lc, o: outcome_mod.Outcome, key_type: str | None) -> pd.Series:
        """Each entity's first outcome date, from one parameterised query of the outcome's table."""
        from google.cloud import bigquery
        sql, params = outcome_mod.query(o, lc.key_data_column)
        qp = [bigquery.ArrayQueryParameter(n, t, v) if array else bigquery.ScalarQueryParameter(n, t, v)
              for n, t, v, array in params]
        df = self._client(lc.billing_project).query(
            sql, job_config=bigquery.QueryJobConfig(query_parameters=qp)).to_dataframe()
        dates = tables._naive(df["outcome_date"])
        return pd.Series(dates.to_numpy(), index=_as_key(df[lc.key_data_column], key_type).to_numpy())

    def _key_type(self, ds: dataset_mod.Dataset) -> str | None:
        return next((ty for t in ds.raw for n, ty in ds.schemas[t]["columns"] if n == ds.key), None)

    def _save(self, run_id: str, scores: pd.DataFrame, meta: dict) -> None:
        p, m = self.state / "runs" / f"{run_id}.parquet", self.state / "runs" / f"{run_id}.json"
        scores.to_parquet(p, index=False)
        m.write_text(json.dumps(meta, indent=1, default=str))
        for f in (p, m):
            os.chmod(f, 0o600)

    def _load(self, run_id: str) -> tuple[pd.DataFrame, dict]:
        if "/" in run_id or not run_id.startswith("run-"):
            raise ValueError(f"{run_id!r} is not a run id from forecast_risk")
        p = self.state / "runs" / f"{run_id}.parquet"
        if not p.exists():
            raise ValueError(f"no forecast run {run_id}; call forecast_risk first")
        return pd.read_parquet(p), json.loads((self.state / "runs" / f"{run_id}.json").read_text())

    # ---- tools ---------------------------------------------------------------------------------
    def cohort_info(self, session_id: str = "latest", version: int | None = None,
                    time_columns: dict | None = None) -> dict:
        with self._lock:
            lc = self._locked(session_id, version)
            schemas = tables.read_schemas(self._client(lc.billing_project), lc.dataset)
            keyed = tables.describe_keyed(schemas, lc.key_data_column, time_columns)
            key_type = next((ty for t in schemas.values() for n, ty in t["columns"]
                             if n == lc.key_data_column), None)
            # The data's end needs every keyed table read; where all of them together are refused
            # (too many rows, no date), the agent still gets the tables to choose from.
            try:
                ds, _ = self.graph(lc.dataset, lc.key_data_column, lc.billing_project, time_columns)
                data_end = str(ds.data_end.date())
            except schema.SchemaError as err:
                data_end = None
                note = (f"All of its tables together cannot be read: {err}. Choose tables from `tables` "
                        "for forecast_risk: ones with a time_column, whose rows add up to under the limit.")
            members = self._frame(lc, key_type)
            out = {"session_id": lc.session_id, "lock_version": lc.version, "locked_at": lc.locked_at,
                   "request": lc.question, "dataset": lc.dataset, "entity_key": lc.key_data_column,
                   "members": privacy.count(len(members)),
                   "tables": keyed}
            if data_end is None:
                out["note"] = note
            else:
                out["data_end"] = data_end
            if "index_date" in members and members.index_date.notna().any():
                out["index_dates"] = f"{members.index_date.min().date()} to {members.index_date.max().date()}"
            return out

    def forecast(self, outcome: dict | None = None, session_id: str = "latest", as_of: str | None = None,
                 horizon_days: int = 365, version: int | None = None, time_columns: dict | None = None,
                 tables: list[str] | None = None, extra_tables: list[str] | None = None,
                 population_table: str | None = None) -> dict:
        """Forecast ``outcome`` (``outcome_mod.parse``: rows of one of the dataset's tables, the
        first of which dates it) within ``horizon_days`` of ``as_of`` for the members of the locked
        cohort (or, with ``population_table``, everyone in that table, such as the people with a
        genome). Kumo learns from the whole dataset's history either way."""
        if outcome is None:
            raise ValueError('outcome is required: {"table": ..., "where": [{"column": ..., "op": ..., "value": ...}]}, '
                             "a table of the cohort's dataset (forecast_get_cohort_info lists them)")
        if not 30 <= int(horizon_days) <= MAX_HORIZON_DAYS:
            raise ValueError(f"horizon_days is between 30 and {MAX_HORIZON_DAYS}: the labeled histories "
                             f"come from up to {HISTORY_YEARS} years before as_of")
        with self._lock:
            pop = self._locked(session_id, version)
            key = pop.key_data_column
            o = outcome_mod.parse(outcome, self._schemas(pop), key)
            dataset, tables = self._with_extra(pop, tables, extra_tables)
            ds, p = self.graph(dataset, key, pop.billing_project, time_columns, tables)
            fc = self.forecaster(dataset, key, pop.billing_project, time_columns, tables)
            key_type = self._key_type(ds)
            members = (self._table_members(pop, population_table, key_type) if population_table
                       else self._frame(pop, key_type))
            first = self._outcome_dates(pop, o, key_type)
            if as_of is None:
                when, defaulted = (ds.data_end - pd.Timedelta(days=int(horizon_days))).normalize(), True
            else:
                when, defaulted = pd.Timestamp(as_of), False
            r = fc.run(first, members, when, int(horizon_days), context=self.context, history_years=HISTORY_YEARS,
                       estimators=self.estimators)
            run_id = "run-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            s = r["scores"]
            meta = {"run_id": run_id, "session_id": pop.session_id, "lock_version": pop.version,
                    "outcome": outcome, "population_table": population_table,
                    "dataset": dataset, "billing_project": pop.billing_project, "key": key,
                    "time_columns": time_columns or {}, "tables": list(tables) if tables else None, "as_of": str(when.date()),
                    "horizon_days": int(horizon_days), "labels_known": r["labels_known"]}
            pool = r["pool"]
            pool.to_parquet(self.state / "runs" / f"{run_id}.pool.parquet", index=False)
            os.chmod(self.state / "runs" / f"{run_id}.pool.parquet", 0o600)
            self._save(run_id, s, meta)
        from .profile import high_risk_profile
        profile = high_risk_profile(ds, s, when)
        out = {"run_id": run_id, "cohort": (f"everyone in {population_table}" if population_table
                                            else f"session {pop.session_id}, lock {pop.version}"),
               "outcome": f"{o.describe(ds.names)}, within {horizon_days} days of {when.date()}",
               "as_of": str(when.date()) + (f" (the default: the data end, {ds.data_end.date()}, less {int(horizon_days)} days)"
                                            if defaulted else ""),
               "model": "NVIDIA Kumo Relational (structured-data-models), in context, no training, no hand-built features",
               "cohort_members": privacy.count(int(members[key].nunique())),
               "members_at_risk": privacy.count(len(s)),
               "excluded": {k: privacy.count(v) for k, v in r["excluded"].items()},
               "learned_from": (f"{self.estimators} x {_number(privacy.count(r['context_rows']))} labeled histories "
                                f"({_number(privacy.count_of(r['context_positives'], r['context_rows']))} with the outcome) "
                                f"from the whole dataset before {when.date()}"),
               "risk_quartiles": _quartiles(s, r["labels_known"]),
               "high_risk_profile": profile,
               "scores_note": "Scores rank members by risk. The labeled histories are enriched with the outcome "
                              "(up to a quarter), so a score is not a calibrated probability; the observed rates are.",
               "tables_read": ds.tables_read(),
               "runtime": {"seconds": r["seconds"], "device": r["device"], "peak_gpu_gb": r["peak_gpu_gb"]}}
        if r["labels_known"]:
            y, sc = s[TARGET].astype(int).to_numpy(), s.risk.to_numpy()
            from .baselines import auroc
            out["observed"] = {"members_with_the_outcome": privacy.count_of(int(y.sum()), len(y)),
                               "rate": privacy.rate(int(y.sum()), len(y)), "auroc": auroc(y, sc)}
        else:
            out["observed"] = "not yet: the outcome window runs past the end of the data"
        return out

    def cohort_records(self, session_id: str = "latest", version: int | None = None, patients: int = 2) -> dict:
        """The tables a forecast reads and ``patients`` members as timelines, for synthetic data."""
        if not views.sample_records_allowed():
            raise ValueError("sample records are off on this server (KUMO_FORECAST_SAMPLE_RECORDS=1 turns them on, "
                             "for synthetic data only)")
        if not 1 <= int(patients) <= 5:
            raise ValueError("patients is 1 to 5")
        with self._lock:
            lc = self._locked(session_id, version)
            key = lc.key_data_column
            ds, p = self.graph(lc.dataset, key, lc.billing_project)
            members = self._frame(lc, self._key_type(ds))
            picked = views.pick_members(ds, members[key], int(patients))
            start = members.set_index(key).index_date if "index_date" in members else None
            people = []
            for i, entity in enumerate(picked, 1):
                person = {"label": f"Patient {i}"}
                if start is not None and pd.notna(start.get(entity)):
                    person["in_the_cohort_from"] = str(pd.Timestamp(start[entity]).date())
                people.append({**person, **views.timeline(ds, entity)})
            overview = views.table_overview(p.schemas, p.tables, key)
            mine = set(members[key])
            for t in overview:
                if t["table"] in ds.raw:
                    t["cohort_rows"] = int(ds.raw[t["table"]][key].isin(mine).sum())
            table = views.records_table(overview, people, int(len(ds.entities)), int(len(mine)))
            return {"table": table, "cohort": f"session {lc.session_id}, lock {lc.version}",
                    "members": int(members[key].nunique()),
                    "note": "The page shows this table under the tool's card. Reply with one short sentence; do "
                            "not repeat the table. Kumo learns from the records of everyone in the dataset (the "
                            "table's 'All' column) and forecasts for the cohort's members: say it that way. "
                            "The patients are a few members picked at random. Synthetic data; members are "
                            "Patient 1, 2, ...; no id is shown."}

    def genomes(self, manifest_table: str, vcf_url: str | None = None, regions: str | None = None,
                session_id: str = "latest", version: int | None = None) -> dict:
        """The cohort's genomes from a manifest table (counts, coverage, file sizes and the total),
        and a VCF's variants (per region, with a few PASS rows)."""
        m = EXTRA_TABLE.match(str(manifest_table).strip())
        if not m:
            raise ValueError(f"manifest_table {manifest_table!r} is not a project.dataset.table name")
        parsed = views.parse_regions(regions)
        if vcf_url is not None and not str(vcf_url).startswith("gs://"):
            raise ValueError("vcf_url is a gs:// URL of a VCF (.vcf or .vcf.gz)")
        with self._lock:
            lc = self._locked(session_id, version)
            key = lc.key_data_column
            ds, _ = self.graph(lc.dataset, key, lc.billing_project)
            key_type = self._key_type(ds)
            members = self._frame(lc, key_type)[key]
            project, dataset, name = m.groups()
            df = self._client(lc.billing_project).query(f"SELECT * FROM `{project}`.`{dataset}`.`{name}`").to_dataframe()
        if key not in df:
            raise ValueError(f"{manifest_table} has no {key} column to link genomes to the cohort's members")
        df[key] = _as_key(df[key], key_type)
        out = views.manifest_summary(df, key, members)
        reads = [str(u) for c in df.columns if c.endswith("_uri") for u in df[c].dropna()
                 if str(u).startswith("gs://") and str(u).endswith((".cram", ".bam"))]
        out["aligned_reads"] = views.size_estimate(_gcs_sizes(reads[:20]), int(len(df)))
        vcf = views.vcf_summary(_gcs_read(vcf_url), parsed) if vcf_url else None
        answer = {"table": views.genomes_table(out, vcf), "genomes": out["genomes"], "of_the_cohort": out["of_the_cohort"],
                  "note": "The page shows this table under the tool's card. Reply with one short sentence; do not "
                          "repeat the table."}
        staged = views.staged_genomes(df, key, members)
        if staged is not None:
            sheet = views.samplesheet(staged, key, self._sex(lc, staged[key].tolist()))
            answer["staged_genomes"] = int(len(staged))
            answer["samplesheet"] = sheet
            answer["note"] += (" samplesheet is the cohort's staged genomes as sarek's samplesheet (patient,sex,status,"
                               "sample,cram,crai; patient and sample are each genome's research_id): write it as it is.")
        return answer

    def _sex(self, lc, keys: list) -> dict:
        """Each key's sex as sarek reads it (XX, XY), from an OMOP person table's gender_concept_id;
        {} without one."""
        schemas = self._schemas(lc)
        person = next((s for n, s in schemas.items() if (s.get("table") or n) == "person"
                       and "gender_concept_id" in {c for c, _ in s["columns"]}), None)
        if person is None or not keys:
            return {}
        from google.cloud import bigquery
        source = person.get("source") or tables.datasets_of(lc.dataset)[0]
        project, dataset = source.split(".")
        k = lc.key_data_column
        job = self._client(lc.billing_project).query(
            f"SELECT `{k}` AS k, gender_concept_id AS g FROM `{project}`.`{dataset}`.`person` WHERE `{k}` IN UNNEST(@keys)",
            job_config=bigquery.QueryJobConfig(query_parameters=[bigquery.ArrayQueryParameter(
                "keys", "INT64" if all(isinstance(x, (int,)) or str(x).isdigit() for x in keys) else "STRING",
                [int(x) if str(x).isdigit() else str(x) for x in keys])]))
        return {r["k"]: views.SEX_BY_GENDER_CONCEPT.get(r["g"], "NA") for r in job.result()}

    def forecast_with_genotypes(self, genotype_table: str, outcome: dict | None = None, as_of: str | None = None,
                                horizon_days: int = 365, session_id: str = "latest",
                                version: int | None = None) -> dict:
        """``forecast`` for everyone in ``genotype_table`` twice, on the same people: from the health
        records alone, then with the genotype table read as well. Answered with both runs side by
        side (accuracy, the cases the highest-risk tenth holds, and how each genotype is shared in
        that tenth against the rest), as a ready table and as numbers."""
        alone = self.forecast(outcome, session_id, as_of, horizon_days, version, None, None, None, genotype_table)
        both = self.forecast(outcome, session_id, as_of, horizon_days, version, None, None,
                             [genotype_table], genotype_table)
        project, dataset, name = EXTRA_TABLE.match(str(genotype_table).strip()).groups()
        from .profile import high_risk_profile
        with self._lock:
            pop = self._locked(session_id, version)
            read, chosen = self._with_extra(pop, None, [genotype_table])
            built, _ = self.graph(read, pop.key_data_column, pop.billing_project, None, chosen)   # cached by the run
            columns = {c for s in built.schemas.values()
                       if s.get("source") == f"{project}.{dataset}" and s.get("table") == name for c, _ in s["columns"]}
            runs = {}
            for label, out in (("health_records_only", alone), ("with_genotypes", both)):
                scores, meta = self._load(out["run_id"])
                # Profiled on the graph with the genotype table, so the records-only run's highest-risk
                # tenth is described by the same genotype columns.
                profile = high_risk_profile(built, scores, pd.Timestamp(meta["as_of"]))
                runs[label] = {"run_id": out["run_id"], "observed": out["observed"],
                               "highest_risk_tenth": views.tenth_summary(scores, TARGET, meta["labels_known"]),
                               "genotypes": [r for r in profile if r["characteristic"].split(":")[0] in columns]}
        return {"table": views.genotype_comparison_table(both["cohort"], both["outcome"], both["members_at_risk"], runs),
                "population": both["cohort"], "outcome": both["outcome"], "as_of": both["as_of"],
                "members_at_risk": both["members_at_risk"], **runs, "model": both["model"],
                "note": "The page shows the table under the tool's card: both forecasts on the same people, the "
                        "first from the health records alone, the second with the genotype table read as one more "
                        "table. Reply in two short sentences on what the comparison shows, numbers unchanged; do "
                        "not repeat the table, and do not call a difference an improvement unless the table shows one."}

    def compare(self, run_id: str) -> dict:
        s, meta = self._load(run_id)
        if not meta["labels_known"]:
            return {"run_id": run_id, "comparison": "needs the outcome observed; forecast an earlier as_of to compare"}
        from .baselines import auroc, compare
        with self._lock:
            ds, _ = self.graph(meta["dataset"], meta["key"], meta["billing_project"], meta.get("time_columns") or None,
                               meta.get("tables"))
            pool = pd.read_parquet(self.state / "runs" / f"{run_id}.pool.parquet")
            both = compare(ds, pool, s[[meta["key"], "cutoff", TARGET, "risk"]])
        y = both[TARGET].astype(int).to_numpy()
        rows = {}
        for name, col in [("NVIDIA Kumo Relational (in context)", "risk"),
                          ("Logistic regression (trained)", "logistic_regression"),
                          ("Gradient-boosted trees (trained)", "gradient_boosting")]:
            top = both.nlargest(max(1, len(both) // 10), col)
            rows[name] = {"auroc": auroc(y, both[col].to_numpy()),
                          "top_10pct_observed_rate": privacy.rate(int(top[TARGET].astype(int).sum()), len(top))}
        return {"run_id": run_id, "members": privacy.count(len(both)),
                "base_rate": privacy.rate(int(y.sum()), len(y)), "models": rows,
                "note": "The baselines are trained on all labeled history with features built by rule from the "
                        "schema; Kumo reads a sample of the same history in context and the raw tables."}

    def select(self, run_id: str, destination: str, top_n: int = 16) -> dict:
        s, meta = self._load(run_id)
        if not 1 <= int(top_n) <= 200:
            raise ValueError("top_n is between 1 and 200")
        destination_mod.check_destination(destination, destination_mod.workspace_resources())
        key = meta["key"]
        pick = s.nlargest(int(top_n), "risk")
        fd, path = tempfile.mkstemp(suffix=".csv")    # owner-only; removed once copied
        try:
            with os.fdopen(fd, "w") as handle:
                pick[[key, "risk"]].to_csv(handle, index=False)
            destination_mod.copy_to_bucket(path, destination)
        finally:
            if os.path.exists(path):
                os.unlink(path)
        # top_n is the caller's own number, so it is shown as is; fewer members at risk than that is a
        # count of the data and is masked.
        selected = int(top_n) if len(pick) == int(top_n) else privacy.count(len(pick))
        out = {"run_id": run_id, "selected": selected, "rule": f"the {top_n} highest-risk members",
               "written_to": destination, "columns": [key, "risk"]}
        if meta["labels_known"] and len(pick):
            k = int(pick[TARGET].astype(int).sum())
            out["observed_outcome_among_selected"] = privacy.rate(k, len(pick))
            out["observed_outcome_among_all_at_risk"] = privacy.rate(int(s[TARGET].astype(int).sum()), len(s))
        return out


def _gcs_sizes(urls: list[str]) -> list[int]:
    """The sizes in bytes of these gs:// objects (those that exist), with gcloud as the server's user."""
    import subprocess
    if not urls:
        return []
    done = subprocess.run(["gcloud", "storage", "ls", "-l", *urls], capture_output=True, text=True, timeout=120)
    sizes = []
    for line in done.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0].isdigit() and parts[-1].startswith("gs://"):
            sizes.append(int(parts[0]))
    return sizes


def _gcs_read(url: str, limit: int = 200 * 1024 * 1024) -> bytes:
    """The bytes of one gs:// object (at most ``limit``), with gcloud as the server's user."""
    import subprocess
    done = subprocess.run(["gcloud", "storage", "cat", url], capture_output=True, timeout=300)
    if done.returncode != 0:
        raise ValueError(f"cannot read {url}: {done.stderr.decode(errors='replace').strip()[:300]}")
    if len(done.stdout) > limit:
        raise ValueError(f"{url} is larger than {limit // (1024 * 1024)} MB; give a VCF of a few regions")
    return done.stdout


def _number(n: int | str) -> str:
    """A count as ``privacy.count`` gives it, with thousands separators when it is shown."""
    return f"{n:,}" if isinstance(n, int) else n


def _as_key(values: pd.Series, key_type: str | None) -> pd.Series:
    """The cohort's key values as the dataset's key column holds them (integers or strings)."""
    if key_type in schema.INTEGER_TYPES:
        return pd.to_numeric(values).astype("int64")
    return values.astype(str)


def _quartiles(s: pd.DataFrame, known: bool) -> list[dict]:
    q = pd.qcut(s.risk.rank(method="first"), 4, labels=["Q1 (lowest)", "Q2", "Q3", "Q4 (highest)"])
    groups = [(str(label), grp) for label, grp in s.groupby(q, observed=True)]
    rows = [{"quartile": label, "members": privacy.count(len(grp)),
             "mean_score": round(float(grp.risk.mean()), 3)} for label, grp in groups]
    if known:
        rates = privacy.rates([(int(g[TARGET].astype(int).sum()), len(g)) for _, g in groups])
        for row, r in zip(rows, rates):
            row["observed_rate"] = r
    return rows
