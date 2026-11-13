import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest

from .omop_fixture_data import OMOP_FIXTURE_STATEMENTS

sys.path.insert(0, str(Path(__file__).parent.parent))


def _find_postgres_program(name):
    """Return the full path of a Postgres program, or None if it is not installed.

    The PG_BIN environment variable (a folder) is looked at first, then the PATH.
    """
    folder = os.environ.get("PG_BIN")
    if folder:
        candidate = Path(folder) / name
        return str(candidate) if candidate.exists() else None
    return shutil.which(name)


def _pick_free_port():
    """Ask the operating system for a TCP port that nobody is using."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _run_postgres_program(program, *arguments):
    """Run a Postgres program and fail with its output if it exits with an error."""
    result = subprocess.run([program, *arguments], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{program} failed:\n{result.stdout}\n{result.stderr}")


@pytest.fixture(scope="session")
def postgres_server(tmp_path_factory):
    """Start a throwaway Postgres server in a temporary folder. Yield its connection string.

    The test is skipped, not failed, when the Postgres programs are not installed.
    The server listens on 127.0.0.1 only, and has no unix socket: a socket path in a long
    temporary folder can be longer than the operating system allows.
    """
    initdb = _find_postgres_program("initdb")
    pg_ctl = _find_postgres_program("pg_ctl")
    if initdb is None or pg_ctl is None:
        pytest.skip("Postgres programs (initdb, pg_ctl) not found. Set PG_BIN to run these tests.")

    data_folder = tmp_path_factory.mktemp("postgres") / "data"
    port = _pick_free_port()
    _run_postgres_program(
        initdb, "-D", str(data_folder), "-U", "postgres", "--auth=trust",
        "--encoding=UTF8", "--no-sync",
    )
    with open(data_folder / "postgresql.conf", "a") as config:
        config.write(
            f"\nlisten_addresses = '127.0.0.1'\nport = {port}\n"
            "unix_socket_directories = ''\nfsync = off\n"
        )

    _run_postgres_program(
        pg_ctl, "-D", str(data_folder), "-l", str(data_folder / "server.log"), "-w", "start"
    )
    try:
        yield f"postgresql://postgres@127.0.0.1:{port}/postgres"
    finally:
        _run_postgres_program(pg_ctl, "-D", str(data_folder), "-m", "immediate", "stop")


@pytest.fixture(scope="session")
def omop_database(postgres_server):
    """Fill the throwaway server with the OMOP test data. Yield the connection string."""
    with psycopg.connect(postgres_server, autocommit=True) as connection:
        for statement in OMOP_FIXTURE_STATEMENTS:
            connection.execute(statement)
    yield postgres_server
