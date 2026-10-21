import os
import subprocess
import tarfile
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "self_update.sh"


def test_failed_frontend_build_keeps_live_app_and_sha(tmp_path):
    repo = tmp_path / "repo"
    source = repo / "src/cohort-studio"
    (source / "app").mkdir(parents=True)
    (source / "web").mkdir(parents=True)
    (source / "app/main.py").write_text("raise RuntimeError('new backend')\n")
    (source / "app/requirements.txt").write_text("new-dependency\n")
    (source / "web/package.json").write_text("{}\n")
    (source / "web/package-lock.json").write_text("{}\n")

    remote_sha = "a" * 40
    archive = tmp_path / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        output.add(repo, arcname=f"repo-{remote_sha}")

    stubs = tmp_path / "bin"
    stubs.mkdir()
    curl = stubs / "curl"
    curl.write_text("""#!/usr/bin/env python3
import json, os, shutil, sys
args = sys.argv[1:]
url = next(arg for arg in args if arg.startswith('https://'))
if 'api.github.com' in url:
    print(json.dumps({'sha': os.environ['TEST_REMOTE_SHA']}))
else:
    shutil.copyfile(os.environ['TEST_ARCHIVE'], args[args.index('-o') + 1])
""")
    curl.chmod(0o755)
    npm = stubs / "npm"
    npm.write_text("""#!/bin/sh
if [ "$1" = "run" ] && [ "$2" = "build" ]; then
  exit 23
fi
exit 0
""")
    npm.chmod(0o755)
    pip = stubs / "pip"
    pip.write_text("#!/bin/sh\necho called > \"$TEST_PIP_MARKER\"\nexit 0\n")
    pip.chmod(0o755)
    flock = stubs / "flock"
    flock.write_text("#!/bin/sh\nexit 0\n")
    flock.chmod(0o755)

    app = tmp_path / "live-app"
    (app / "static").mkdir(parents=True)
    (app / "main.py").write_text("old backend\n")
    (app / "requirements.txt").write_text("old dependency\n")
    (app / "static/index.html").write_text("old frontend\n")
    (app / "APP_SHA").write_text("old-sha\n")
    pip_marker = tmp_path / "pip-called"
    lock = tmp_path / "update.lock"

    env = os.environ.copy()
    env.update({
        "PATH": f"{stubs}:{env['PATH']}",
        "UPDATE_APP_ROOT": str(app),
        "UPDATE_LOCK_FILE": str(lock),
        "TEST_ARCHIVE": str(archive),
        "TEST_REMOTE_SHA": remote_sha,
        "TEST_PIP_MARKER": str(pip_marker),
    })
    result = subprocess.run(["bash", str(SCRIPT)], env=env, text=True,
                            capture_output=True, check=False)

    assert result.returncode != 0
    assert (app / "main.py").read_text() == "old backend\n"
    assert (app / "requirements.txt").read_text() == "old dependency\n"
    assert (app / "static/index.html").read_text() == "old frontend\n"
    assert (app / "APP_SHA").read_text() == "old-sha\n"
    assert not pip_marker.exists()


def test_successful_update_selects_archive_and_writes_sha(tmp_path):
    repo = tmp_path / "repo"
    source = repo / "src/cohort-studio"
    (source / "app").mkdir(parents=True)
    (source / "web").mkdir(parents=True)
    (source / "app/main.py").write_text("value = 'new backend'\n")
    (source / "app/requirements.txt").write_text("\n")
    (source / "web/package.json").write_text("{}\n")
    (source / "web/package-lock.json").write_text("{}\n")

    remote_sha = "b" * 40
    archive = tmp_path / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        output.add(repo, arcname=f"repo-{remote_sha}")

    stubs = tmp_path / "bin"
    stubs.mkdir()
    curl = stubs / "curl"
    curl.write_text("""#!/usr/bin/env python3
import json, os, shutil, sys
args = sys.argv[1:]
url = next(arg for arg in args if arg.startswith('https://'))
if 'api.github.com' in url:
    print(json.dumps({'sha': os.environ['TEST_REMOTE_SHA']}))
else:
    shutil.copyfile(os.environ['TEST_ARCHIVE'], args[args.index('-o') + 1])
""")
    curl.chmod(0o755)
    npm = stubs / "npm"
    npm.write_text("""#!/bin/sh
if [ "$1" = "run" ] && [ "$2" = "build" ]; then
  mkdir -p dist
  printf '<html>new frontend</html>\\n' > dist/index.html
fi
exit 0
""")
    npm.chmod(0o755)
    pip = stubs / "pip"
    pip.write_text("#!/bin/sh\nexit 0\n")
    pip.chmod(0o755)
    for command in ("flock", "pkill"):
        stub = stubs / command
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(0o755)

    app = tmp_path / "live-app"
    (app / "static").mkdir(parents=True)
    (app / "main.py").write_text("value = 'old backend'\n")
    (app / "requirements.txt").write_text("old dependency\n")
    (app / "static/index.html").write_text("old frontend\n")
    (app / "APP_SHA").write_text("old-sha\n")
    env = os.environ.copy()
    env.update({
        "PATH": f"{stubs}:{env['PATH']}",
        "UPDATE_APP_ROOT": str(app),
        "UPDATE_LOCK_FILE": str(tmp_path / "update.lock"),
        "TEST_ARCHIVE": str(archive),
        "TEST_REMOTE_SHA": remote_sha,
    })
    result = subprocess.run(["bash", str(SCRIPT)], env=env, text=True,
                            capture_output=True, check=False)

    assert result.returncode == 0, result.stderr + result.stdout
    assert (app / "main.py").read_text() == "value = 'new backend'\n"
    assert (app / "static/index.html").read_text() == "<html>new frontend</html>\n"
    assert (app / "APP_SHA").read_text() == f"{remote_sha}\n"
