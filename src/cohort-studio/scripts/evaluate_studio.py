"""Run repeatable local contract evaluations with disposable PostgreSQL databases."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[1]
SUITES = {
    "agent": ["test_agent_runtime.py", "test_studio_agent.py", "test_studio_agent_api.py", "test_agent_artifacts.py",
              "test_agent_instructions.py", "test_provider_adapters.py", "test_knowledge.py",
              "test_prompt_guardrails.py", "test_agent_workflows.py", "test_agent_results.py"],
    "jev": ["test_join_discovery.py"],
    "engineering": ["test_grain_performance.py", "test_execution_contract.py", "test_data_jobs.py",
                    "test_export_jobs.py", "test_saved_snapshots.py", "test_group_count_filter.py",
                    "test_chart_axis_validation.py", "test_richer_calculations.py"],
    "demo": ["test_demo_roundtrip.py", "test_stage_storage.py", "test_join_s3_api.py"],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=["all", *SUITES], default="all")
    parser.add_argument("--repeat", type=int, choices=range(1, 11), default=2)
    parser.add_argument("--output", type=Path, default=ROOT / ".eval-results" / time.strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--nextflow", default=shutil.which("nextflow"))
    args = parser.parse_args()
    groups = list(SUITES) if args.suite == "all" else [args.suite]
    if "demo" in groups and (not args.nextflow or not Path(args.nextflow).is_file()):
        parser.error("The demo requires an installed Nextflow runtime; supply --nextflow PATH.")
    dsn = os.environ.get("STUDIO_EVAL_DB_DSN", "host=127.0.0.1 port=55433 dbname=postgres user=cohort_local password=cohort_local")
    details = conninfo_to_dict(dsn)
    if details.get("host") not in {"127.0.0.1", "localhost", "::1"} or details.get("hostaddr") not in {None, "127.0.0.1", "::1"}:
        parser.error("Evaluation databases must be on loopback. Cloud databases are not supported.")
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"suite": args.suite, "mode": "deterministic-contracts", "runs": [],
              "limits": ["Model and Jev responses are fixtures, not live quality scores.",
                         "S3/HealthOmics are file-backed adapters; Nextflow and PostgreSQL run locally."]}
    failures = False
    for iteration in range(1, args.repeat + 1):
        name = "studio_eval_" + uuid.uuid4().hex
        names = [name, name + "_legacy", name + "_empty"]
        created = []
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="studio-eval-") as temp:
            suite = Path(temp)
            for filename in dict.fromkeys(f for group in groups for f in SUITES[group]):
                content = (ROOT / "app/tests" / filename).read_text()
                content = content.replace("dbname=omop", "dbname=" + name)
                (suite / filename).write_text(content)
            (suite / "fixtures").symlink_to(ROOT / "app/tests/fixtures", target_is_directory=True)
            (suite / "conftest.py").write_text('''import os, sys
import pytest
from sqlalchemy import create_engine
sys.path.insert(0, os.environ["COHORT_TEST_APP"])
sys.path.insert(0, os.environ["COHORT_TEST_SCRIPTS"])
from tests.conftest import client, fake_aurora, info, ref
@pytest.fixture(scope="session")
def engine():
    engine = create_engine(os.environ["COHORT_TEST_DB_URL"])
    yield engine
    engine.dispose()
@pytest.fixture(scope="session")
def pg():
    return {"dsn": os.environ["COHORT_TEST_PG_DSN"], "url": lambda value: os.environ["COHORT_TEST_DB_URL"] if value == "omop" else os.environ["COHORT_TEST_DB_URL"] + "_" + value}
''')
            from sqlalchemy.engine import URL
            url = URL.create("postgresql+psycopg", username=details.get("user"), password=details.get("password"),
                             host=details["host"], port=int(details.get("port", 5432)), database=name).render_as_string(hide_password=False)
            env = {**os.environ, "COHORT_TEST_APP": str(ROOT / "app"), "COHORT_TEST_SCRIPTS": str(ROOT / "scripts"),
                   "COHORT_TEST_DB_URL": url, "COHORT_TEST_PG_DSN": dsn,
                   "STUDIO_OPERATIONS_PATH": str(suite / "operations.sqlite3"),
                   "STUDIO_KNOWLEDGE_PATH": str(suite / "knowledge.sqlite3"), "STUDIO_KB_EMBEDDINGS": "off"}
            if args.nextflow:
                env["STUDIO_EVAL_NEXTFLOW"] = str(Path(args.nextflow).resolve())
            xml = args.output / f"run-{iteration}.xml"
            log = args.output / f"run-{iteration}.log"
            try:
                with psycopg.connect(dsn, autocommit=True) as connection:
                    for database in names:
                        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
                        created.append(database)
                sys.path.insert(0, str(ROOT / "app"))
                import omop_load
                from tests.conftest import LEGACY_DDL
                with psycopg.connect(make_conninfo(dsn, dbname=name)) as connection:
                    omop_load.load(connection, ROOT / "app/tests/fixtures/omop", "cdm", log=lambda *_: None)
                    connection.execute("UPDATE cdm.measurement SET value_as_number = measurement_id %% 100 WHERE measurement_concept_id = %s", (3006322,))
                with psycopg.connect(make_conninfo(dsn, dbname=name + "_legacy")) as connection:
                    connection.execute(LEGACY_DDL)
                with log.open("w") as stream:
                    result = subprocess.run([sys.executable, "-m", "pytest", str(suite), "-q", "--tb=short",
                                             "-o", "junit_family=legacy", "--junitxml", str(xml)], env=env, cwd=ROOT, stdout=stream,
                                            stderr=subprocess.STDOUT, timeout=600)
                cases = []
                if xml.exists():
                    for case in ET.parse(xml).iter("testcase"):
                        status = next((kind for kind in ("failure", "error", "skipped") if case.find(kind) is not None), "passed")
                        cases.append({"name": case.get("name"), "status": status,
                                      "evidence": {item.get("name"): item.get("value")
                                                   for item in case.findall("./properties/property")}})
                passed = result.returncode == 0 and bool(cases) and all(c["status"] == "passed" for c in cases)
                failures |= not passed
                report["runs"].append({"iteration": iteration, "passed": passed, "cases": cases,
                                       "seconds": round(time.monotonic() - started, 2)})
                print(f"Run {iteration}: {'PASS' if passed else 'FAIL'} ({len(cases)} cases); {log}", flush=True)
            finally:
                with psycopg.connect(dsn, autocommit=True) as connection:
                    for database in created:
                        connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))
                (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return int(failures)


if __name__ == "__main__":
    raise SystemExit(main())
