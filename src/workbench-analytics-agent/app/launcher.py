"""Verily Product Analytics Agent: container entry point.

Workbench builds the image once, when the app is created, and never rebuilds
it. So that a stop and start is enough to pick up changes, this script
downloads the latest copy of the app from GitHub each time the container
starts and runs Streamlit from that copy. If that fails for any reason, it
runs the copy it started from instead.

The page's "Update" control runs this script again from the copy that is
already running, which fetches newer code without restarting the machine.

Settings (environment variables, set in docker-compose.yaml):
  ASK_WORKBENCH_REPO  GitHub repository, as "owner/name".
  ASK_WORKBENCH_REF   Branch, tag or commit to run, for example
                      "refs/heads/my-branch". Empty turns updates off.
  ASK_WORKBENCH_PATH  Folder in the repository that holds main.py.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath

# The copy of the app this script sits in: the image's copy on a normal
# start, or the copy already running when the page asks for an update.
BUILT_IN_DIR = Path(__file__).resolve().parent
LIVE_ROOT = Path(
    os.environ.get("ASK_WORKBENCH_LIVE_DIR") or Path.home() / ".ask-workbench" / "live"
)

DOWNLOAD_ATTEMPTS = 3
DOWNLOAD_TIMEOUT_SECONDS = 8
RETRY_WAIT_SECONDS = 2
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024
MAX_FILE_BYTES = 20 * 1024 * 1024

STREAMLIT_ARGS = ["--server.port=8501", "--server.address=0.0.0.0"]


class UpdateError(Exception):
    """Why the latest copy could not be used. The message is shown on the page."""


def log(message: str) -> None:
    print(f"[ask-workbench] {message}", flush=True)


def download(url: str, target: Path) -> None:
    """Save the archive at `url` to `target`, retrying briefly on network errors."""
    last_error: Exception | None = None
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "ask-workbench-launcher"}
            )
            with urllib.request.urlopen(
                request, timeout=DOWNLOAD_TIMEOUT_SECONDS
            ) as response, open(target, "wb") as out:
                total = 0
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES:
                        raise UpdateError("the download was larger than expected")
                    out.write(chunk)
            return
        except urllib.error.HTTPError as error:
            if error.code == 404:
                raise UpdateError("the branch was not found on GitHub") from error
            last_error = error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last_error = error
        if attempt < DOWNLOAD_ATTEMPTS:
            time.sleep(RETRY_WAIT_SECONDS)
    raise UpdateError("could not reach GitHub") from last_error


def unpack(archive: Path, subpath: str, target: Path) -> str:
    """Copy the files under `subpath` out of the archive into `target`.

    Returns the commit the archive was made from, or "" if it does not say.
    Only plain files and folders are copied, and only to paths inside `target`.
    """
    wanted = PurePosixPath(subpath)
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            # GitHub wraps everything in one top folder; drop it.
            parts = PurePosixPath(member.name).parts[1:]
            if not parts:
                continue
            try:
                inside = PurePosixPath(*parts).relative_to(wanted)
            except ValueError:
                continue
            if not inside.parts:
                continue
            if inside.is_absolute() or ".." in inside.parts:
                raise UpdateError("the download contained an unsafe path")
            destination = target.joinpath(*inside.parts)
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                continue  # links and special files are never copied
            if member.size > MAX_FILE_BYTES:
                raise UpdateError("the download contained an unexpectedly large file")
            destination.parent.mkdir(parents=True, exist_ok=True)
            source = tar.extractfile(member)
            if source is None:
                continue
            with source, open(destination, "wb") as out:
                shutil.copyfileobj(source, out)
        return tar.pax_headers.get("comment", "")


def requirement_lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    lines = (line.strip() for line in path.read_text().splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def install_packages_if_changed(app_dir: Path, installed: list[str]) -> None:
    """Install the app's packages when they differ from the `installed` list."""
    requirements = app_dir / "requirements.txt"
    if requirement_lines(requirements) == installed:
        return
    marker = app_dir / ".packages-installed"
    if marker.is_file():
        return
    log("the package list changed; installing packages")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-cache-dir",
            "--disable-pip-version-check",
            "-r",
            str(requirements),
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        log(result.stderr[-2000:])
        raise UpdateError("the new packages could not be installed")
    marker.touch()


def latest_app(repo: str, ref: str, subpath: str) -> tuple[Path, str]:
    """Download the app at `ref` and return its folder and commit."""
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo) or not re.fullmatch(r"[\w./-]+", ref):
        raise UpdateError("the update settings are not valid")
    url = f"https://codeload.github.com/{repo}/tar.gz/{ref}"
    # Read now: the copy this script started from may be removed further down.
    installed = requirement_lines(BUILT_IN_DIR / "requirements.txt")

    LIVE_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=LIVE_ROOT, prefix="download-") as work:
        archive = Path(work) / "app.tar.gz"
        download(url, archive)
        staging = Path(work) / "app"
        staging.mkdir()
        commit = unpack(archive, subpath.strip("/"), staging)
        if not (staging / "main.py").is_file():
            raise UpdateError("the download did not contain the app")

        final = LIVE_ROOT / (commit or "latest")
        if commit and final.is_dir():
            pass  # this commit is already unpacked; keep it and its packages marker
        else:
            shutil.rmtree(final, ignore_errors=True)
            os.replace(staging, final)

    # Packages first: if they cannot be installed, the copy this script
    # started from must still be there to fall back to.
    install_packages_if_changed(final, installed)

    for other in LIVE_ROOT.iterdir():
        if other != final:
            shutil.rmtree(other, ignore_errors=True)
    return final, commit


def fall_back(problem: str) -> tuple[Path, dict[str, str]]:
    """Run the copy this script started from, and tell the page why."""
    log(f"running the copy already here: {problem}")
    page_info = {"ASK_WORKBENCH_UPDATE_PROBLEM": problem}
    # A copy fetched earlier sits in a folder named after its commit.
    if BUILT_IN_DIR.parent == LIVE_ROOT and re.fullmatch(r"[0-9a-f]{40}", BUILT_IN_DIR.name):
        page_info["ASK_WORKBENCH_VERSION"] = BUILT_IN_DIR.name[:7]
    return BUILT_IN_DIR, page_info


def choose_app() -> tuple[Path, dict[str, str]]:
    """Decide which copy of the app to run and what to tell the page about it."""
    ref = os.environ.get("ASK_WORKBENCH_REF", "").strip()
    if not ref:
        return fall_back("updates are off")

    repo = os.environ.get("ASK_WORKBENCH_REPO", "").strip()
    subpath = os.environ.get("ASK_WORKBENCH_PATH", "").strip()
    try:
        app_dir, commit = latest_app(repo, ref, subpath)
    except UpdateError as error:
        return fall_back(str(error))
    except Exception as error:  # never let an update problem stop the app
        log(f"unexpected error: {error!r}")
        return fall_back("the update failed")

    version = commit[:7] if commit else "latest"
    log(f"running version {version} from {repo}")
    return app_dir, {"ASK_WORKBENCH_VERSION": version}


def main() -> None:
    app_dir, page_info = choose_app()
    os.environ.pop("ASK_WORKBENCH_VERSION", None)
    os.environ.pop("ASK_WORKBENCH_UPDATE_PROBLEM", None)
    os.environ.update(page_info)
    # Kept so the page's Update control can start this script the same way.
    os.environ["ASK_WORKBENCH_EXTRA_ARGS"] = json.dumps(sys.argv[1:])
    os.chdir(app_dir)
    # Arguments after the script name are passed on, so a local run can
    # override the port or address.
    command = [sys.executable, "-m", "streamlit", "run", "main.py"]
    os.execv(sys.executable, command + STREAMLIT_ARGS + sys.argv[1:])


if __name__ == "__main__":
    main()
