import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

APP_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(APP_DIR))

FIXTURES = Path(__file__).parent / "fixtures"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def app_url():
    """Serve the real app once for the whole E2E session."""
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "panel", "serve", "main.py",
         "--port", str(port), "--allow-websocket-origin", "*", "--liveness"],
        cwd=APP_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"{url}/liveness", timeout=1)
            break
        except Exception:
            if proc.poll() is not None:
                out = proc.stdout.read().decode(errors="replace")
                raise RuntimeError(f"panel serve exited early:\n{out}")
            time.sleep(0.3)
    else:
        proc.kill()
        raise RuntimeError("panel serve did not become live within 30s")
    yield f"{url}/main"
    proc.terminate()
    proc.wait(timeout=10)
