import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import patch

assert os.environ["DC_ACCESS_ENV"] == "test"
paths = [Path(sys.argv[1])] if len(sys.argv) == 2 else [Path("/app/app.py"), Path("/app/app/app.py"), Path("/workspace/app/app.py")]
path = next(path for path in paths if path.is_file())
with patch("google.cloud.bigquery.Client") as factory, patch("subprocess.run") as command:
    command.return_value.returncode = 1
    factory.return_value.query.return_value.result.return_value = []
    spec = importlib.util.spec_from_file_location("dependency_access_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.ENV == "test"
    client = module.app.test_client()
    assert client.get("/health").status_code == 200
    assert client.get("/").status_code == 200
    list(module._run_query("SELECT @fixture AS fixture", [], None))
    assert factory.return_value.query.called
print("dependency-workload-ok")
