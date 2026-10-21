"""OMOP CDM support against a real throwaway Postgres 17 loaded with a
100-person Eunomia GiBleed subset (fixtures/omop, built by
make_fixture.py): detection, concept search, the cohort compiler checked
against pandas over the same CSVs, cohort/domain opens, endpoints, SQL
injection, timeouts, and joins on person_id."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pandas as pd
import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

import datasets
import db
import main
import omop
import omop_load

FIXTURE = Path(__file__).parent / "fixtures" / "omop"
GI_BLEED = 192671
GI_BLEED_ICD10 = 35208414          # non-standard K92.2
CELECOXIB, DICLOFENAC = 1118084, 1124300
ACETAMINOPHEN = 1125315            # no direct exposures, only its drugs
REPEATED = 40481087                # a condition recorded many times per person
MALE, FEMALE = 8507, 8532
# Eunomia has no measurement values; the fixture load gives this concept
# value_as_number = measurement_id % 100, and so does the pandas reference.
VALUED = 3006322
RID = "omopdb"


def _pg_bin() -> Path | None:
    dirs = [os.environ.get("STUDIO_PG_BIN"),
            os.path.dirname(shutil.which("pg_ctl") or ""),
            "/opt/homebrew/opt/postgresql@17/bin"]
    for d in filter(None, dirs):
        if (Path(d) / "pg_ctl").exists() and (Path(d) / "initdb").exists():
            return Path(d)
    return None


LEGACY_DDL = """
CREATE SCHEMA cdm53;
CREATE SCHEMA vocab;
CREATE TABLE cdm53.person (person_id integer, gender_concept_id integer,
  year_of_birth integer, race_concept_id integer, ethnicity_concept_id integer);
CREATE TABLE cdm53.observation_period (observation_period_id integer,
  person_id integer, observation_period_start_date date,
  observation_period_end_date date);
CREATE TABLE cdm53.visit_occurrence (visit_occurrence_id integer,
  person_id integer, visit_concept_id integer, visit_start_date date,
  admitting_source_concept_id integer);
CREATE TABLE cdm53.condition_occurrence (condition_occurrence_id integer,
  person_id integer, condition_concept_id integer, condition_start_date date);
CREATE TABLE vocab.concept (concept_id integer, concept_name text,
  domain_id text, vocabulary_id text, concept_class_id text,
  standard_concept text, concept_code text);
CREATE TABLE vocab.concept_ancestor (ancestor_concept_id integer,
  descendant_concept_id integer);
INSERT INTO cdm53.person VALUES (1, 8507, 1970, 0, 0), (2, 8532, 1980, 0, 0);
INSERT INTO cdm53.observation_period VALUES
  (1, 1, '2000-01-01', '2020-01-01'), (2, 2, '2000-01-01', '2020-01-01');
INSERT INTO cdm53.condition_occurrence VALUES (1, 1, 10, '2010-05-01'),
  (2, 2, 11, '2011-05-01');
INSERT INTO vocab.concept VALUES (10, 'Child', 'Condition', 'SNOMED', 'Clinical Finding', 'S', 'c10'),
  (11, 'Other child', 'Condition', 'SNOMED', 'Clinical Finding', 'S', 'c11'),
  (12, 'Parent', 'Condition', 'SNOMED', 'Clinical Finding', 'S', 'c12');
INSERT INTO vocab.concept_ancestor VALUES (12, 10), (12, 11), (10, 10), (11, 11), (12, 12);
"""


@pytest.fixture(scope="session")
def pg():
    """Throwaway Postgres on a unix socket in a temp dir, with databases
    omop (the fixture in schema cdm), legacy (5.3 names, split vocab
    schema) and empty."""
    bin_dir = _pg_bin()
    if bin_dir is None:
        pytest.skip("PostgreSQL binaries (initdb, pg_ctl) not found in PATH or "
                    "/opt/homebrew/opt/postgresql@17/bin; set STUDIO_PG_BIN")
    root = Path(tempfile.mkdtemp(prefix="studio-pg-", dir="/tmp"))
    data = root / "data"
    subprocess.run([bin_dir / "initdb", "-D", data, "-U", "postgres", "-A", "trust",
                    "--no-locale", "-E", "UTF8"], check=True, capture_output=True)
    subprocess.run([bin_dir / "pg_ctl", "-D", data, "-l", root / "log", "-w",
                    "-o", f"-p 5432 -k {root} -c listen_addresses=''", "start"],
                   check=True, capture_output=True)
    dsn = f"host={root} port=5432 user=postgres"
    try:
        with psycopg.connect(f"{dsn} dbname=postgres", autocommit=True) as conn:
            for name in ("omop", "legacy", "empty"):
                conn.execute(f"CREATE DATABASE {name}")
        with psycopg.connect(f"{dsn} dbname=omop") as conn:
            omop_load.load(conn, FIXTURE, "cdm", log=lambda *_: None)
            conn.execute("UPDATE cdm.measurement SET value_as_number = measurement_id %% 100 "
                         "WHERE measurement_concept_id = %s", (VALUED,))
        with psycopg.connect(f"{dsn} dbname=legacy") as conn:
            conn.execute(LEGACY_DDL)
        yield {"dsn": dsn, "url": lambda name: (
            f"postgresql+psycopg://postgres@/{name}?host={root}&port=5432")}
    finally:
        subprocess.run([bin_dir / "pg_ctl", "-D", data, "-m", "immediate", "stop"],
                       capture_output=True)
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(scope="session")
def engine(pg):
    eng = create_engine(pg["url"]("omop"))
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def info(engine):
    return omop.detect(engine)


@pytest.fixture
def client(engine, monkeypatch):
    monkeypatch.setattr(db, "list_aurora_resources", lambda: [{"id": RID}])
    monkeypatch.setattr(db, "get_engine_for_resource", lambda rid: engine)
    omop.invalidate()
    yield TestClient(main.app)
    omop.invalidate()


# --------------------------------------------------------- pandas reference

@pytest.fixture(scope="session")
def ref() -> dict[str, pd.DataFrame]:
    t = {p.name.removesuffix(".csv.gz"): pd.read_csv(p) for p in FIXTURE.glob("*.csv.gz")}
    m = t["measurement"]
    m.loc[m.measurement_concept_id == VALUED, "value_as_number"] = m.measurement_id % 100
    for df in t.values():
        for col in df.columns:
            if col.endswith("_date"):
                df[col] = pd.to_datetime(df[col])
    return t


def _events(ref, domain, ids, descendants=True, observation=True, start=None,
            end=None, vmin=None, vmax=None) -> pd.DataFrame:
    d = omop.DOMAINS[domain]
    ids = set(ids)
    if descendants:
        ca = ref["concept_ancestor"]
        ids |= set(ca[ca.ancestor_concept_id.isin(ids)].descendant_concept_id)
    ev = ref[d["table"]]
    ev = ev[ev[d["concept"]].isin(ids)]
    if vmin is not None:
        ev = ev[ev.value_as_number >= vmin]
    if vmax is not None:
        ev = ev[ev.value_as_number <= vmax]
    if start:
        ev = ev[ev[d["date"]] >= pd.Timestamp(start)]
    if end:
        ev = ev[ev[d["date"]] <= pd.Timestamp(end)]
    if observation:
        op = ref["observation_period"]
        both = ev.reset_index().merge(op, on="person_id")
        inside = both[(both[d["date"]] >= both.observation_period_start_date)
                      & (both[d["date"]] <= both.observation_period_end_date)]
        ev = ev.loc[sorted(set(inside["index"]))]
    return ev.rename(columns={d["date"]: "date"})


def _persons(ev: pd.DataFrame, min_count: int = 1) -> set:
    n = ev.groupby("person_id").size()
    return set(n[n >= min_count].index)


def _count(engine, info, spec) -> dict:
    return omop.count(engine, info, spec)


# --------------------------------------------------------------- detection

def test_detect_finds_schema_version_and_tables(info, ref):
    out = omop.public(info)
    assert (out["cdm"], out["cdm_schema"], out["vocab_schema"], out["version"]) == \
        (True, "cdm", "cdm", "5.4")
    tables = {t["name"]: t for t in out["tables"]}
    assert tables["person"]["rows"] == len(ref["person"]) == 100
    assert tables["condition_occurrence"] == {
        "name": "condition_occurrence", "schema": "cdm", "domain": "condition",
        "rows": len(ref["condition_occurrence"]), "approx": False}
    assert tables["concept"]["domain"] == "vocabulary"
    assert tables["death"]["rows"] == 0
    assert "columns" not in out


def test_detect_legacy_53_split_vocab_and_no_cdm(pg):
    legacy = omop.detect(create_engine(pg["url"]("legacy")))
    assert (legacy["cdm_schema"], legacy["vocab_schema"], legacy["version"]) == \
        ("cdm53", "vocab", "5.3")
    assert omop.detect(create_engine(pg["url"]("empty"))) is None
    assert omop.public(None) == {"cdm": False}


def test_legacy_split_vocab_expands_descendants(pg):
    eng = create_engine(pg["url"]("legacy"))
    info = omop.detect(eng)
    spec = {"criteria": [{"domain": "condition", "concept_ids": [12]}]}
    assert omop.count(eng, info, spec)["persons"] == 2
    spec["criteria"][0]["descendants"] = False
    assert omop.count(eng, info, spec)["persons"] == 0


def test_detect_resource_caches_and_feeds_the_hint(engine, monkeypatch):
    calls = []
    monkeypatch.setattr(db, "get_engine_for_resource",
                        lambda rid: calls.append(rid) or engine)
    omop.invalidate()
    assert omop.detect_resource(RID)["cdm_schema"] == "cdm"
    omop.detect_resource(RID)
    assert calls == [RID]
    assert omop.hint(RID) == {"cdm_schema": "cdm", "vocab_schema": "cdm",
                              "version": "5.4", "persons": 100}
    omop.invalidate()


# ---------------------------------------------------------- concept search

def test_search_by_name_ranks_ingredient_and_counts_persons(engine, info, ref):
    out = omop.search_concepts(engine, info, "Gastrointestinal hemorrhage")
    assert out[0]["concept_id"] == GI_BLEED
    assert out[0]["persons"] == len(_persons(_events(ref, "condition", [GI_BLEED],
                                                     observation=False))) == 40
    assert set(out[0]) == {"concept_id", "concept_name", "domain_id", "vocabulary_id",
                           "concept_class_id", "concept_code", "standard_concept",
                           "persons"}
    words = omop.search_concepts(engine, info, "oral celecoxib")
    assert words and all("celecoxib" in c["concept_name"].lower()
                         and "oral" in c["concept_name"].lower() for c in words)


def test_search_by_id_code_and_standard_filter(engine, info):
    assert omop.search_concepts(engine, info, str(GI_BLEED_ICD10)) == []
    by_id = omop.search_concepts(engine, info, str(GI_BLEED_ICD10), standard_only=False)
    assert by_id[0]["concept_name"] == "Gastrointestinal hemorrhage, unspecified"
    assert by_id[0]["standard_concept"] is None
    by_code = omop.search_concepts(engine, info, "K92.2", standard_only=False)
    assert by_code[0]["concept_id"] == GI_BLEED_ICD10
    assert omop.search_concepts(engine, info, str(CELECOXIB))[0]["concept_id"] == CELECOXIB


def test_search_domain_and_vocabulary_filters(engine, info):
    conds = omop.search_concepts(engine, info, "a", domain="condition", limit=200)
    assert conds and {c["domain_id"] for c in conds} == {"Condition"}
    rx = omop.search_concepts(engine, info, "celecoxib", vocabulary="RxNorm")
    assert rx and {c["vocabulary_id"] for c in rx} == {"RxNorm"}
    assert len(omop.search_concepts(engine, info, "", limit=7)) == 7


def test_search_text_is_bound_not_spliced(engine, info):
    for q in ("x'; DROP TABLE cdm.person; --", "%", "_", "\\", "' OR '1'='1"):
        assert omop.search_concepts(engine, info, q) == []
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM cdm.person")).scalar() == 100


# -------------------------------------------------------- cohort compiler

def test_descendants_expand_an_ingredient_to_its_drugs(engine, info, ref):
    spec = {"criteria": [{"domain": "drug", "concept_ids": [ACETAMINOPHEN]}]}
    expected = _persons(_events(ref, "drug", [ACETAMINOPHEN]))
    assert expected and _count(engine, info, spec)["persons"] == len(expected)
    spec["criteria"][0]["descendants"] = False
    assert _count(engine, info, spec)["persons"] == len(
        _persons(_events(ref, "drug", [ACETAMINOPHEN], descendants=False))) == 0


def test_attrition_matches_pandas(engine, info, ref):
    spec = {"criteria": [
        {"domain": "condition", "concept_ids": [GI_BLEED]},
        {"domain": "drug", "concept_ids": [DICLOFENAC]},
        {"domain": "drug", "concept_ids": [CELECOXIB], "exclude": True},
    ], "demographics": {"gender_concept_ids": [FEMALE]}}
    gi = _persons(_events(ref, "condition", [GI_BLEED]))
    dic = _persons(_events(ref, "drug", [DICLOFENAC]))
    cel = _persons(_events(ref, "drug", [CELECOXIB]))
    person = ref["person"].set_index("person_id")
    females = set(person.index[person.gender_concept_id == FEMALE])
    observed = set(ref["observation_period"].person_id)
    steps = [observed, observed & gi, observed & gi & dic,
             (observed & gi & dic) - cel, ((observed & gi & dic) - cel) & females]
    out = _count(engine, info, spec)
    assert out["total_persons"] == 100
    assert [a["persons"] for a in out["attrition"]] == [len(s) for s in steps]
    assert out["persons"] == len(steps[-1])
    assert [a["label"] for a in out["attrition"]] == [
        "With an observation period", "With Gastrointestinal hemorrhage",
        "With Diclofenac", "Without celecoxib", "Gender"]
    assert len(set(len(s) for s in steps)) > 2   # the steps really filter


def test_min_count(engine, info, ref):
    spec = {"criteria": [{"domain": "condition", "concept_ids": [REPEATED], "min_count": 3}]}
    expected = _persons(_events(ref, "condition", [REPEATED]), 3)
    assert 0 < len(expected) < len(_persons(_events(ref, "condition", [REPEATED])))
    assert _count(engine, info, spec)["persons"] == len(expected)


def test_measurement_value_range(engine, info, ref):
    spec = {"criteria": [{"domain": "measurement", "concept_ids": [VALUED],
                          "value_min": 20, "value_max": 40.5}]}
    expected = _persons(_events(ref, "measurement", [VALUED], vmin=20, vmax=40.5))
    assert 0 < len(expected) < len(_persons(_events(ref, "measurement", [VALUED])))
    assert _count(engine, info, spec)["persons"] == len(expected)


def test_date_window(engine, info, ref):
    spec = {"criteria": [{"domain": "condition", "concept_ids": [GI_BLEED],
                          "start": "2000-01-01", "end": "2010-12-31"}]}
    expected = _persons(_events(ref, "condition", [GI_BLEED], start="2000-01-01",
                                end="2010-12-31"))
    assert 0 < len(expected) < 40
    assert _count(engine, info, spec)["persons"] == len(expected)


def _index_ages(ref) -> pd.Series:
    first = _events(ref, "condition", [GI_BLEED]).groupby("person_id").date.min()
    yob = ref["person"].set_index("person_id").year_of_birth
    return first.dt.year - yob.loc[first.index]


def test_age_at_index_and_year_of_birth(engine, info, ref):
    ages = _index_ages(ref)
    spec = {"criteria": [{"domain": "condition", "concept_ids": [GI_BLEED]}],
            "demographics": {"age_min": 40, "age_max": 65}}
    expected = ages[(ages >= 40) & (ages <= 65)]
    assert 0 < len(expected) < len(ages)
    out = _count(engine, info, spec)
    assert out["persons"] == len(expected)
    assert out["attrition"][-1]["label"] == "Age 40–65 at index"
    person = ref["person"]
    spec = {"demographics": {"year_of_birth_min": 1950, "year_of_birth_max": 1970,
                             "gender_concept_ids": [MALE]}}
    expected = person[person.year_of_birth.between(1950, 1970)
                      & (person.gender_concept_id == MALE)]
    assert _count(engine, info, spec)["persons"] == len(expected) > 0


def test_index_relation_before_and_after(engine, info, ref):
    first = _events(ref, "condition", [GI_BLEED]).groupby("person_id").date.min()
    dic = _events(ref, "drug", [DICLOFENAC]).merge(first.rename("index"),
                                                   left_on="person_id", right_index=True)
    for rel, sel in (("before", dic.date < dic["index"]),
                     ("after", dic.date > dic["index"])):
        spec = {"criteria": [{"domain": "condition", "concept_ids": [GI_BLEED]},
                             {"domain": "drug", "concept_ids": [DICLOFENAC],
                              "index_relation": rel}]}
        assert _count(engine, info, spec)["persons"] == dic[sel].person_id.nunique()


def test_without_observation_requirement_counts_all_events(engine, info, ref):
    spec = {"require_observation": False,
            "criteria": [{"domain": "condition", "concept_ids": [GI_BLEED]}]}
    out = _count(engine, info, spec)
    assert out["persons"] == len(_persons(_events(ref, "condition", [GI_BLEED],
                                                  observation=False)))
    assert [a["label"] for a in out["attrition"]] == ["With Gastrointestinal hemorrhage"]


def test_empty_spec_is_everyone_observed(engine, info):
    out = _count(engine, info, {})
    assert out == {"persons": 100, "total_persons": 100, "attrition": [
        {"label": "With an observation period", "persons": 100}]}


@pytest.mark.parametrize("spec,match", [
    ({"criteria": [{"domain": "lab", "concept_ids": [1]}]}, "domain must be"),
    ({"criteria": [{"domain": "condition; DROP TABLE cdm.person", "concept_ids": [1]}]},
     "domain must be"),
    ({"criteria": [{"domain": "condition", "concept_ids": ["1) OR 1=1 --"]}]}, "integer"),
    ({"criteria": [{"domain": "condition", "concept_ids": [True]}]}, "integer"),
    ({"criteria": [{"domain": "condition", "concept_ids": []}]}, "at least one"),
    ({"criteria": [{"domain": "condition", "concept_ids": [1],
                    "start": "2020-01-01'; DROP TABLE cdm.person; --"}]}, "ISO date"),
    ({"criteria": [{"domain": "condition", "concept_ids": [1], "value_min": 1}]},
     "measurement only"),
    ({"criteria": [{"domain": "measurement", "concept_ids": [1], "value_min": "1"}]},
     "number"),
    ({"criteria": [{"domain": "condition", "concept_ids": [1], "min_count": 0}]},
     "at least 1"),
    ({"criteria": [{"domain": "condition", "concept_ids": [1], "sql": "x"}]},
     "unknown key"),
    ({"criteria; DROP TABLE cdm.person": []}, "Unknown cohort spec key"),
    ({"criteria": [{"domain": "condition", "concept_ids": [1],
                    "index_relation": "before"}]}, "defines the index"),
    ({"demographics": {"age_min": 50, "age_max": 10}}, "greater than"),
    ({"demographics": {"race": [1]}}, "Unknown demographics"),
])
def test_invalid_specs_are_rejected(engine, info, spec, match):
    with pytest.raises(ValueError, match=match):
        omop.count(engine, info, spec)


@pytest.mark.parametrize("spec", [
    {"criteria": ""}, {"criteria": 0}, {"criteria": False},
    {"demographics": []}, {"demographics": ""}, {"demographics": 0},
])
def test_falsey_spec_fields_must_have_the_expected_type(spec):
    with pytest.raises(ValueError):
        omop.parse_spec(spec)


@pytest.mark.parametrize("date", ["20200101", "2020-W01-1", "2020-1-01"])
def test_date_fields_require_calendar_date_format(date):
    with pytest.raises(ValueError, match="ISO date"):
        omop.parse_spec({"criteria": [{"domain": "condition", "concept_ids": [1],
                                       "start": date}]})


@pytest.mark.parametrize("number", [float("nan"), float("inf"), float("-inf")])
def test_numeric_filters_must_be_finite(number):
    with pytest.raises(ValueError, match="finite"):
        omop.parse_spec({"criteria": [{"domain": "measurement", "concept_ids": [1],
                                       "value_min": number}]})


def test_tables_used_reports_cohort_query_dependencies(info):
    spec = {"criteria": [{"domain": "condition", "concept_ids": [GI_BLEED]}]}
    assert omop.tables_used(info, spec) == [
        "cdm.person", "cdm.condition_occurrence", "cdm.observation_period",
        "cdm.concept", "cdm.concept_ancestor",
    ]


def test_death_without_concepts_and_empty_tables(engine, info):
    spec = {"criteria": [{"domain": "death"}]}
    assert omop.count(engine, info, spec)["persons"] == 0
    assert omop.count(engine, info, {"criteria": [{"domain": "death", "exclude": True}]}
                      )["persons"] == 100


# ------------------------------------------------------------------ opens

def test_open_cohort_columns_names_and_values(engine, info, ref):
    spec = {"criteria": [{"domain": "condition", "concept_ids": [GI_BLEED]},
                         {"domain": "drug", "concept_ids": [CELECOXIB, DICLOFENAC]},
                         {"domain": "drug", "concept_ids": [1177480], "exclude": True}]}
    df = omop.open_cohort(engine, info, spec)
    assert list(df.columns) == [
        "person_id", "gender", "race", "ethnicity", "year_of_birth", "age",
        "index_date", "observation_start", "observation_end",
        "Gastrointestinal hemorrhage events", "Gastrointestinal hemorrhage first",
        "celecoxib +1 events", "celecoxib +1 first"]
    assert len(df) == omop.count(engine, info, spec)["persons"] > 0
    assert set(df.gender) <= {"MALE", "FEMALE"}
    gi = _events(ref, "condition", [GI_BLEED]).groupby("person_id").date
    row = df.iloc[0]
    pid = row.person_id
    assert row["Gastrointestinal hemorrhage events"] == gi.size()[pid]
    assert row["Gastrointestinal hemorrhage first"] == gi.min()[pid] == row.index_date
    assert row.age == row.index_date.year - row.year_of_birth
    assert pd.api.types.is_datetime64_any_dtype(df.index_date)


def test_labels_are_short_and_unique(engine, info):
    spec = {"criteria": [{"domain": "condition", "concept_ids": [GI_BLEED]},
                         {"domain": "condition", "concept_ids": [GI_BLEED],
                          "min_count": 2}]}
    cols = list(omop.open_cohort(engine, info, spec).columns)
    assert "Gastrointestinal hemorrhage (2) events" in cols
    long = {"criteria": [{"domain": "drug", "concept_ids": [40162359]}]}
    label = omop.open_cohort(engine, info, long).columns[-1].removesuffix(" first")
    assert label.endswith("…") and len(label) == omop.LABEL_CHARS


def test_open_domain_names_concepts_and_restricts_to_cohort(engine, info, ref):
    spec = {"criteria": [{"domain": "condition", "concept_ids": [GI_BLEED]}]}
    df, origin = omop.open_domain(engine, info, "condition_occurrence", spec)
    gi = _persons(_events(ref, "condition", [GI_BLEED]))
    co = ref["condition_occurrence"]
    assert origin is None
    assert set(df.person_id) == gi
    assert len(df) == co.person_id.isin(gi).sum()
    cols = list(df.columns)
    assert cols[cols.index("condition_concept_id") + 1] == "condition_concept_name"
    assert "condition_type_concept_name" in cols
    names = ref["concept"].set_index("concept_id").concept_name
    sample = df[df.condition_concept_id == GI_BLEED].iloc[0]
    assert sample.condition_concept_name == names[GI_BLEED]


def test_open_domain_untouched_table_keeps_an_aurora_origin(engine, info, ref):
    df, origin = omop.open_domain(engine, info, "measurement", concept_names=False,
                                  resource_id=RID)
    assert origin == {"kind": "aurora", "resource_id": RID, "schema": "cdm",
                      "table": "measurement"}
    assert list(df.columns) == info["columns"]["measurement"]
    assert len(df) == len(ref["measurement"])
    _, enriched = omop.open_domain(engine, info, "measurement", resource_id=RID)
    assert enriched is None


@pytest.mark.parametrize("table", ["concept", "person; DROP TABLE cdm.person",
                                   "cdm_source", "nope"])
def test_open_domain_rejects_other_tables(engine, info, table):
    with pytest.raises(ValueError, match="person-level table"):
        omop.open_domain(engine, info, table)


def test_statement_timeout_raises_omop_timeout(engine):
    with pytest.raises(omop.OmopTimeout):
        with omop._session(engine, 50) as conn:
            conn.execute(text("SELECT pg_sleep(2)"))
    with pytest.raises(omop.OmopEngineError, match="Aurora:"):
        with omop._session(engine, 1000) as conn:
            conn.execute(text("SELECT * FROM cdm.no_such_table"))


# --------------------------------------------------------------- endpoints

def test_detect_endpoint(client, pg, monkeypatch):
    body = client.get(f"/api/omop/{RID}").json()
    assert (body["cdm"], body["cdm_schema"], body["version"]) == (True, "cdm", "5.4")
    empty = create_engine(pg["url"]("empty"))
    monkeypatch.setattr(db, "get_engine_for_resource", lambda rid: empty)
    assert client.get(f"/api/omop/{RID}?refresh=true").json() == {"cdm": False}
    assert client.get(f"/api/omop/{RID}/concepts?q=x").status_code == 404
    assert client.post(f"/api/omop/{RID}/cohort/count", json={}).status_code == 404


def test_unknown_resource_is_404(client, monkeypatch):
    monkeypatch.setattr(db, "list_aurora_resources", lambda wait=False: [{"id": "other"}])
    assert client.get(f"/api/omop/{RID}").status_code == 404


def test_concepts_endpoint(client):
    resp = client.get(f"/api/omop/{RID}/concepts",
                      params={"q": "hemorrhage", "domain": "condition"})
    assert resp.status_code == 200
    concepts = resp.json()["concepts"]
    assert concepts[0]["concept_id"] == GI_BLEED and concepts[0]["persons"] == 40
    resp = client.get(f"/api/omop/{RID}/concepts",
                      params={"q": "K92.2", "standard_only": "false"})
    assert resp.json()["concepts"][0]["concept_id"] == GI_BLEED_ICD10
    resp = client.get(f"/api/omop/{RID}/concepts", params={"q": "x" * 201})
    assert resp.status_code == 400


def test_count_endpoint_and_error_mapping(client, monkeypatch):
    spec = {"criteria": [{"domain": "condition", "concept_ids": [GI_BLEED]}]}
    resp = client.post(f"/api/omop/{RID}/cohort/count", json=spec)
    assert resp.status_code == 200 and resp.json()["persons"] == 40
    bad = {"criteria": [{"domain": "condition", "concept_ids": ["1 OR 1=1"]}]}
    assert client.post(f"/api/omop/{RID}/cohort/count", json=bad).status_code == 400

    def slow(*a, **k):
        raise omop.OmopTimeout("The query took longer than 15 s.")

    def broken(*a, **k):
        raise omop.OmopEngineError("Aurora: connection reset")

    monkeypatch.setattr(omop, "count", slow)
    assert client.post(f"/api/omop/{RID}/cohort/count", json=spec).status_code == 504
    monkeypatch.setattr(omop, "count", broken)
    assert client.post(f"/api/omop/{RID}/cohort/count", json=spec).status_code == 502


def test_real_timeout_maps_to_504(client, monkeypatch):
    monkeypatch.setattr(omop, "COUNT_TIMEOUT_MS", 1)
    real = omop._prepare

    def sleepy(conn, info, spec):
        conn.execute(text("SELECT pg_sleep(1)"))
        return real(conn, info, spec)

    monkeypatch.setattr(omop, "_prepare", sleepy)
    resp = client.post(f"/api/omop/{RID}/cohort/count", json={})
    assert resp.status_code == 504
    assert "longer than" in resp.json()["detail"]


def test_open_endpoints_and_join_on_person_id(client, engine, ref):
    spec = {"criteria": [{"domain": "condition", "concept_ids": [GI_BLEED]}]}
    cohort = client.post(f"/api/omop/{RID}/cohort/open",
                         json={"spec": spec, "name": "GI bleed"})
    assert cohort.status_code == 200
    cohort = cohort.json()
    assert set(cohort) == {"dataset_id", "source", "rows", "columns"}
    assert cohort["source"] == f"{RID} / GI bleed" and cohort["rows"] == 40
    assert datasets.get(cohort["dataset_id"])["origin"] is None
    cond = client.post(f"/api/omop/{RID}/domain/open",
                       json={"table": "condition_occurrence", "spec": spec}).json()
    assert cond["source"] == f"{RID} / cdm.condition_occurrence (cohort)"
    joined = client.post("/api/datasets/join", json={
        "left_id": cohort["dataset_id"], "right_id": cond["dataset_id"],
        "left_on": "person_id", "right_on": "person_id", "how": "inner"})
    assert joined.status_code == 200
    body = joined.json()
    assert body["join"]["engine"] == "duckdb"
    assert body["rows"] == cond["rows"]
    assert "cdm.condition_occurrence (cohort) → condition_concept_name" in \
        [c["name"] for c in body["columns"]]


def test_untouched_domain_tables_join_in_aurora(client, ref):
    person = client.post(f"/api/omop/{RID}/domain/open",
                         json={"table": "person", "concept_names": False}).json()
    visits = client.post(f"/api/omop/{RID}/domain/open",
                         json={"table": "visit_occurrence", "concept_names": False}).json()
    assert datasets.get(person["dataset_id"])["origin"]["schema"] == "cdm"
    body = client.post("/api/datasets/join", json={
        "left_id": person["dataset_id"], "right_id": visits["dataset_id"],
        "left_on": "person_id", "right_on": "person_id", "how": "semi"}).json()
    assert body["join"]["engine"] == "aurora"
    assert body["rows"] == ref["visit_occurrence"].person_id.nunique()


def test_open_endpoint_validation(client):
    resp = client.post(f"/api/omop/{RID}/domain/open", json={"table": "concept"})
    assert resp.status_code == 400
    resp = client.post(f"/api/omop/{RID}/cohort/open",
                       json={"spec": {"criteria": [{"domain": "nope"}]}})
    assert resp.status_code == 400


def test_datasources_carry_the_omop_hint(client, monkeypatch):
    monkeypatch.setattr(db, "resources_ready", lambda: True)
    monkeypatch.setattr(db, "retry_if_empty", lambda: None)
    monkeypatch.setattr(db, "list_aurora_resources", lambda wait=False: [{"id": RID}])
    monkeypatch.setattr(db, "list_s3_folders", lambda wait=False: [])
    monkeypatch.setattr(db, "list_bq_datasets", lambda wait=False: [])
    omop.detect_resource(RID)
    aurora = client.get("/api/datasources").json()["sources"][0]
    assert aurora["omop"] == {"cdm_schema": "cdm", "vocab_schema": "cdm",
                              "version": "5.4", "persons": 100}


def test_mcp_tools(client):
    import mcp_server
    if not mcp_server.AVAILABLE:
        pytest.skip("mcp not installed")
    found = json.loads(mcp_server.omop_search_concepts(RID, "hemorrhage", "condition"))
    assert found[0]["concept_id"] == GI_BLEED
    spec = json.dumps({"criteria": [{"domain": "condition", "concept_ids": [GI_BLEED]}]})
    assert json.loads(mcp_server.omop_count_cohort(RID, spec))["persons"] == 40
    opened = json.loads(mcp_server.omop_open_cohort(RID, spec, "gi"))
    assert opened["rows"] == 40


# ------------------------------------------------------------------ loader

def test_loader_is_idempotent_without_replace(pg):
    logged = []
    with psycopg.connect(f"{pg['dsn']} dbname=omop") as conn:
        counts = omop_load.load(conn, FIXTURE, "cdm", log=logged.append)
    assert "already has a CDM" in logged[0]
    assert counts["person"] == 100
    with pytest.raises(ValueError, match="Invalid schema"):
        omop_load.load(None, FIXTURE, 'cdm"; DROP')


def test_loader_ddl_matches_the_5_4_spec():
    ddl = omop_load.parse_ddl()
    assert len(ddl) == 39
    visit = [c for c, _ in ddl["visit_occurrence"]["columns"]]
    assert "admitted_from_concept_id" in visit and "admitting_source_concept_id" not in visit
    assert ("offset", False) in ddl["note_nlp"]["columns"]


@pytest.mark.parametrize("ready,status", [(False, 503), (True, 404)])
def test_empty_resource_listing_does_not_resolve_unknown_database(monkeypatch, ready, status):
    monkeypatch.setattr(db, "list_aurora_resources", lambda: [])
    monkeypatch.setattr(db, "resources_ready", lambda: ready)
    def unexpected_detection(*args):
        pytest.fail("An unknown resource must not start credential resolution")
    monkeypatch.setattr(omop, "detect_resource", unexpected_detection)
    response = TestClient(main.app).get("/api/omop/missing")
    assert response.status_code == status
