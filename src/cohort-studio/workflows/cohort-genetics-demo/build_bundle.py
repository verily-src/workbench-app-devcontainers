from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

WORKFLOW_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[4]
REQUIREMENTS = WORKFLOW_DIR / "requirements.txt"
TARGET_PLATFORM = "x86_64-unknown-linux-gnu"
PYTHON_VERSION = "3.10"


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _archive(target: Path, destination: Path, force: bool) -> str:
    if destination.exists() and not force:
        raise ValueError(f"Archive already exists: {destination}; pass --force to replace it.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".vendor-", suffix=".zip",
                                    dir=destination.parent)
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        digest = hashlib.sha256()
        with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=9) as bundle:
            for source in sorted(target.rglob("*")):
                if source.is_symlink():
                    raise ValueError(f"Vendor package contains a symlink: {source}")
                if (not source.is_file() or source.name == ".lock"
                        or source.suffix == ".pyc" or "__pycache__" in source.parts):
                    continue
                relative = source.relative_to(target).as_posix()
                info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (0o100644 & 0xFFFF) << 16
                contents = source.read_bytes()
                bundle.writestr(info, contents, compress_type=zipfile.ZIP_DEFLATED,
                                compresslevel=9)
                digest.update(relative.encode("utf-8"))
                digest.update(b"\0")
                digest.update(contents)
        os.replace(tmp_path, destination)
    finally:
        tmp_path.unlink(missing_ok=True)
    return digest.hexdigest()


def build(args: argparse.Namespace) -> dict:
    destination = Path(args.output).expanduser().resolve() if args.output else WORKFLOW_DIR / "vendor.zip"
    if destination.exists() and not args.force:
        raise ValueError(f"Archive already exists: {destination}; pass --force to replace it.")
    target = (Path(args.target).expanduser().resolve() if args.target
              else Path(tempfile.mkdtemp(prefix="cohort-genetics-vendor-")))
    if _inside(target, REPO_ROOT):
        raise ValueError("Choose a vendor target outside the Git repository.")
    if target.exists() and any(target.iterdir()):
        raise ValueError(f"Vendor target is not empty: {target}")
    target.mkdir(parents=True, exist_ok=True)
    uv = shutil.which(args.uv)
    if not uv:
        raise ValueError(f"Could not find uv executable: {args.uv}")
    subprocess.run([
        uv, "pip", "install", "--target", str(target),
        "--python-version", PYTHON_VERSION,
        "--python-platform", TARGET_PLATFORM,
        "--only-binary", ":all:",
        "--no-compile", "-r", str(REQUIREMENTS),
    ], check=True)
    checksum = _archive(target, destination, args.force)
    return {
        "vendor_target": str(target),
        "archive": str(destination),
        "target_python": PYTHON_VERSION,
        "target_platform": TARGET_PLATFORM,
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "content_sha256": checksum,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a Linux Python 3.10 vendor archive for the workflow container.")
    parser.add_argument("--target", help="Empty install target outside this workflow; defaults to a new temp directory.")
    parser.add_argument("--output", help="Archive path; defaults to this workflow's vendor.zip.")
    parser.add_argument("--uv", default="uv", help="uv executable to use.")
    parser.add_argument("--force", action="store_true", help="Replace an existing archive.")
    args = parser.parse_args(argv)
    try:
        result = build(args)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"bundle build failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
