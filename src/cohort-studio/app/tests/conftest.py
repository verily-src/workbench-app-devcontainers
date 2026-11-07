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
# The suite covers the AI features; test_ai_features_hidden turns them off.
os.environ.setdefault("STUDIO_AI_FEATURES", "on")
os.environ.setdefault("STUDIO_LINEAGE_UI", "on")
os.environ.setdefault("STUDIO_PLINK_UI", "on")
# Scheduled extract refresh is driven by explicit ticks in its tests.
os.environ.setdefault("STUDIO_EXTRACT_SCHEDULER", "off")
# Keep test runs (and the e2e uvicorn they spawn) off the app's real
# discovery snapshot beside studio_config.json.
os.environ.setdefault("STUDIO_DISCOVERY_CACHE_PATH", os.path.join(
    tempfile.mkdtemp(prefix="studio-discovery-"), "discovery.json"))

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
    external_url = os.environ.get("STUDIO_TEST_DATABASE_URL")
    if external_url:
        yield {"dsn": external_url, "url": lambda _name: external_url}
        return
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
def fake_aurora(engine, monkeypatch):
    """Use the test PostgreSQL engine for Aurora SQL-path tests."""
    db.fetch_aurora_table.invalidate()
    monkeypatch.setattr(db, "get_engine_for_resource", lambda rid: engine)
    yield engine
    with engine.begin() as conn:
        conn.exec_driver_sql('DROP TABLE IF EXISTS public."samples"')
        conn.exec_driver_sql('DROP TABLE IF EXISTS public."visits"')


@pytest.fixture
def run_async():
    """Run a coroutine to completion on a private event loop.

    Playwright's sync API (its browser fixture is session-scoped) leaves an
    event loop running on the main thread once a frontend test has run, so a
    bare ``asyncio.run()`` in a later test fails. A worker thread has no
    running loop.
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    def run(coro):
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return run


_LIVE_SERVER_FIXTURES = {"app_url", "omop_app_url"}


def remount_mcp_if_started():
    """Mount a fresh MCP app when the current session manager has already run.

    The streamable-HTTP session manager can only be run once per instance.
    The mount keeps its original position among the app routes.
    """
    import mcp_server
    if mcp_server.AVAILABLE and getattr(
            mcp_server.mcp.session_manager, "_has_started", True):
        routes = main.app.router.routes
        index = next(i for i, route in enumerate(routes)
                     if getattr(route, "path", None) == "/mcp")
        main.app.mount("/mcp", mcp_server.http_app())
        routes[index] = routes.pop()


@pytest.fixture(autouse=True)
def _fresh_mcp_session_manager(request):
    """Give each test an MCP session manager that has not run yet.

    The streamable-HTTP session manager can only be run once per instance,
    but every ``with TestClient(main.app)`` enters the app lifespan, which
    runs it. Rebuild the mounted MCP app (and with it the manager) whenever a
    previous test has started it, keeping the mount at its original position.
    Tests served by a live uvicorn server keep the manager that server's
    lifespan started; swapping it would leave /mcp with a manager not running.
    """
    if _LIVE_SERVER_FIXTURES & set(request.fixturenames):
        yield
        return
    remount_mcp_if_started()
    yield
