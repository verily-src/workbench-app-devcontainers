import sys
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pandas as pd
import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).parent.parent))

import db
import main
import omop
import omop_load

FIXTURE = Path(__file__).parent / "fixtures" / "omop"
VALUED = 3006322
RID = "omopdb"

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


def _pg_bin():
    dirs = [os.environ.get("STUDIO_PG_BIN"),
            os.path.dirname(shutil.which("pg_ctl") or ""),
            "/opt/homebrew/opt/postgresql@17/bin"]
    return next((Path(d) for d in filter(None, dirs)
                 if (Path(d) / "pg_ctl").exists()
                 and (Path(d) / "initdb").exists()), None)


@pytest.fixture(scope="session")
def pg():
    bin_dir = _pg_bin()
    if bin_dir is None:
        pytest.skip("PostgreSQL binaries not found; set STUDIO_PG_BIN")
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


@pytest.fixture(scope="session")
def ref():
    tables = {p.name.removesuffix(".csv.gz"): pd.read_csv(p)
              for p in FIXTURE.glob("*.csv.gz")}
    measurements = tables["measurement"]
    measurements.loc[measurements.measurement_concept_id == VALUED,
                     "value_as_number"] = measurements.measurement_id % 100
    for frame in tables.values():
        for col in frame.columns:
            if col.endswith("_date"):
                frame[col] = pd.to_datetime(frame[col])
    return tables


@pytest.fixture
def fake_aurora(tmp_path, monkeypatch):



    from sqlalchemy import create_engine, event

    import db
    engine = create_engine(f"sqlite:///{tmp_path / 'main.db'}")
    public = tmp_path / "public.db"

    @event.listens_for(engine, "connect")
    def _attach(dbapi_conn, _record):
        dbapi_conn.execute(f"ATTACH DATABASE '{public}' AS public")

    monkeypatch.setattr(db, "get_engine_for_resource", lambda rid: engine)
    return engine
