#!/usr/bin/env python3
"""Generates the TEST virtual-browser apps from the production ones.

The test apps (src/test-virtual-browser-*) are byte-for-byte copies of the
production virtual-browser apps plus an airlock-matrix runner used by the
Workbench e2e airlock canary. They must be copies, not references: the VM
bootstrap only substitutes ${templateOption:*} placeholders in the
.devcontainer.json and docker-compose.yaml that live inside the app's own
devcontainer folder, so compose files cannot be shared across folders.

Run from the repository root:

    python3 src/test-virtual-browser-common/generate.py          # regenerate
    python3 src/test-virtual-browser-common/generate.py --check  # CI drift check

--check exits non-zero if the checked-in test apps differ from what the
production apps generate, which means someone changed a virtual-browser app
without regenerating the test copies.
"""

import difflib
import json
import re
import sys
from pathlib import Path

REPO_SRC = Path(__file__).resolve().parent.parent
COMMON_DIR_NAME = "test-virtual-browser-common"

VARIANTS = {
    "jupyter": {
        "base": "virtual-browser-jupyter",
        "test": "test-virtual-browser-jupyter",
        "user": "jupyter",
    },
    "rstudio": {
        "base": "virtual-browser-rstudio",
        "test": "test-virtual-browser-rstudio",
        "user": "rstudio",
    },
}

GENERATED_FILES = [".devcontainer.json", "docker-compose.yaml", "docker-compose.build.yaml"]


def strip_jsonc_comments(text: str) -> str:
    """Removes // and /* */ comments without touching string contents."""
    out = []
    i = 0
    in_string = False
    while i < len(text):
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < len(text):
                out.append(text[i + 1])
                i += 1
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
            out.append(ch)
        elif text.startswith("//", i):
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = len(text) if end == -1 else end + 2
            continue
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def yaml_header(base_dir: str, file_name: str) -> str:
    return (
        f"# DO NOT EDIT: generated from ../{base_dir}/{file_name} by\n"
        f"# ../{COMMON_DIR_NAME}/generate.py. Regenerate with:\n"
        f"#   python3 src/{COMMON_DIR_NAME}/generate.py\n"
    )


def generate_devcontainer_json(variant: str, cfg: dict) -> str:
    base_text = (REPO_SRC / cfg["base"] / ".devcontainer.json").read_text()
    data = json.loads(strip_jsonc_comments(base_text))

    generated = {
        "_generated": (
            f"DO NOT EDIT: generated from ../{cfg['base']}/.devcontainer.json by "
            f"../{COMMON_DIR_NAME}/generate.py; regenerate with "
            f"python3 src/{COMMON_DIR_NAME}/generate.py"
        )
    }
    generated.update(data)
    generated["name"] = f"TEST {data['name']} (airlock canary)"
    generated["dockerComposeFile"] = list(data["dockerComposeFile"]) + [
        "docker-compose.test.yaml"
    ]
    # The runner backgrounds itself so the app start never blocks on it.
    generated["postStartCommand"] = dict(data["postStartCommand"])
    generated["postStartCommand"]["airlock-matrix"] = [
        "bash",
        "-c",
        f"nohup bash /opt/airlock-test/airlock-matrix-runner.sh {cfg['user']} {variant}"
        " >/tmp/airlock-matrix-runner.log 2>&1 &",
    ]
    return json.dumps(generated, indent=2) + "\n"


def generate_compose(cfg: dict) -> str:
    base = (REPO_SRC / cfg["base"] / "docker-compose.yaml").read_text()
    return yaml_header(cfg["base"], "docker-compose.yaml") + base


def generate_build_compose(cfg: dict) -> str:
    base = (REPO_SRC / cfg["base"] / "docker-compose.build.yaml").read_text()
    # The app image builds from the production app's folder (its Dockerfile is
    # not copied here); relative sibling contexts are unaffected.
    rewritten = re.sub(
        r"^(\s*context:\s*)\.\s*$",
        rf"\g<1>../{cfg['base']}",
        base,
        flags=re.MULTILINE,
    )
    return yaml_header(cfg["base"], "docker-compose.build.yaml") + rewritten


def generate(variant: str, cfg: dict) -> dict:
    return {
        ".devcontainer.json": generate_devcontainer_json(variant, cfg),
        "docker-compose.yaml": generate_compose(cfg),
        "docker-compose.build.yaml": generate_build_compose(cfg),
    }


def main() -> int:
    check = "--check" in sys.argv[1:]
    drift = False
    for variant, cfg in VARIANTS.items():
        test_dir = REPO_SRC / cfg["test"]
        test_dir.mkdir(parents=True, exist_ok=True)
        for file_name, content in generate(variant, cfg).items():
            target = test_dir / file_name
            if check:
                existing = target.read_text() if target.exists() else ""
                if existing != content:
                    drift = True
                    sys.stderr.write(f"DRIFT: {target} is out of date:\n")
                    sys.stderr.writelines(
                        difflib.unified_diff(
                            existing.splitlines(keepends=True),
                            content.splitlines(keepends=True),
                            fromfile=str(target),
                            tofile="regenerated",
                        )
                    )
            else:
                target.write_text(content)
                print(f"wrote {target}")
    if drift:
        sys.stderr.write(
            f"\nRegenerate with: python3 src/{COMMON_DIR_NAME}/generate.py\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
