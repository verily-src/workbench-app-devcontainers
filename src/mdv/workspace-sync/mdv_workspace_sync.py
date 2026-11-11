#!/usr/bin/env python3
"""Make Workbench workspace data available to MDV where MDV expects it.

MDV serves every project folder directly under its projects directory (/app/mdv). This script
fills that directory from workspace buckets, which startup bind-mounts read-only under
/mnt/mdv-workspace-ro (see start-workspace-sync.sh):

  <bucket>/mdv/projects/<name>/   ready-made MDV project -> linked in place (no data copy)
  <bucket>/mdv/data/<file>        .h5ad, .h5mu, .vcf(.gz), .csv/.tsv(.gz) -> converted to a local
                                  MDV project (see convert_file.py)

Files or projects anywhere in a bucket that a user opened from MDV's "Workspace data" browser
(workspace_ui.py) are recorded in <projects dir>/.workspace-imports.json and handled the same way.

If no bucket holds MDV data, built-in sample projects are linked instead, and removed again once
workspace data appears.

Linked projects are "overlays": the small metadata files MDV edits (views, state) are copied
locally so saving views works, directories are recreated locally, and data files are symlinks
into the read-only mount, so the bucket is never modified. Runs as the MDV user; standard
library only.
"""

import argparse
import fcntl
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

LOG = logging.getLogger("mdv-workspace-sync")

# Files MDV rewrites while a project is used; kept local so the source is never written.
LOCAL_COPY_FILES = ("datasources.json", "views.json", "state.json", "README.md")
SKIP_ENTRIES = ("lock",)
IMPORTS_FILE = ".workspace-imports.json"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from convert_file import kind_of, stem_of  # noqa: E402  (stdlib-only helpers)
SAMPLE_COMPLETE_MARKER = ".mdv-sample-complete"


def slugify(text):
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-.")
    return slug or "project"


class Sync:
    def __init__(self, args):
        self.args = args
        self.projects_dir = args.projects_dir
        self.state_path = os.path.join(self.projects_dir, ".workspace-sync-state.json")
        self.state = {"entries": {}, "retired_slugs": []}
        self.changed = False

    # ---- state -------------------------------------------------------------------------------

    def load_state(self):
        if os.path.exists(self.state_path):
            with open(self.state_path) as f:
                self.state = json.load(f)
        self.state.setdefault("entries", {})
        self.state.setdefault("retired_slugs", [])

    def save_state(self):
        tmp = self.state_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.state, f, indent=2, sort_keys=True)
        os.replace(tmp, self.state_path)

    def slug_for(self, key, base):
        entry = self.state["entries"].get(key)
        if entry:
            return entry["slug"]
        used = {e["slug"] for e in self.state["entries"].values()}
        used.update(self.state["retired_slugs"])
        used.update(os.listdir(self.projects_dir))
        slug, n = base, 2
        while slug in used:
            slug, n = f"{base}-{n}", n + 1
        return slug

    # ---- discovery ---------------------------------------------------------------------------

    def resources(self):
        """Mounted resources as (relative name, path). A missing list file means none mounted."""
        root = self.args.source_root
        if self.args.resources_file:
            if not os.path.exists(self.args.resources_file):
                return []
            with open(self.args.resources_file) as f:
                rels = [line.strip() for line in f if line.strip()]
        elif os.path.isdir(root):
            rels = sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
        else:
            rels = []
        return [(rel, os.path.join(root, rel)) for rel in rels
                if os.path.isdir(os.path.join(root, rel))]

    def discover_workspace(self):
        """Returns ({key: source}, set of mounted resource names)."""
        sources, mounted = {}, set()
        for rel, path in self.resources():
            mounted.add(rel)
            base = os.path.join(path, self.args.bucket_folder)
            try:
                if not os.path.isdir(base):
                    continue
                res_slug = slugify(rel.replace("/", "--"))
                sources.update(self.discover_projects(rel, res_slug, os.path.join(base, "projects")))
                if self.args.convert:
                    sources.update(self.discover_data(rel, res_slug, os.path.join(base, "data")))
            except OSError as e:
                LOG.warning("cannot read %s: %s", base, e)
        return sources, mounted

    @staticmethod
    def discover_projects(rel, res_slug, projects):
        found = {}
        if not os.path.isdir(projects):
            return found
        for name in sorted(os.listdir(projects)):
            src = os.path.join(projects, name)
            if name.startswith(".") or not os.path.isdir(src):
                continue
            if not os.path.exists(os.path.join(src, "datasources.json")):
                LOG.info("skipping %s: no datasources.json, so not an MDV project", src)
                continue
            found[f"ws:link:{rel}/{name}"] = {
                "kind": "link", "path": src, "resource": rel,
                "slug_base": f"{res_slug}--{slugify(name)}"}
        return found

    @staticmethod
    def discover_data(rel, res_slug, data):
        found = {}
        if not os.path.isdir(data):
            return found
        for name in sorted(os.listdir(data)):
            src = os.path.join(data, name)
            if kind_of(name) is None or not os.path.isfile(src):
                continue
            found[f"ws:convert:{rel}/{name}"] = {
                "kind": "convert", "path": src, "resource": rel,
                "slug_base": f"{res_slug}--{slugify(stem_of(name))}"}
        return found

    def discover_imports(self, mounted, taken_paths):
        """Sources a user opened from MDV's Workspace data browser. Returns {key: source} for
        imports whose bucket is mounted and whose source still exists."""
        path = os.path.join(self.projects_dir, IMPORTS_FILE)
        if not os.path.exists(path):
            return {}
        with open(path) as f:
            imports = json.load(f).get("imports", {})
        found = {}
        for key, item in imports.items():
            resource = item["resource"]
            src = os.path.join(self.args.source_root, resource, item["subpath"])
            if resource not in mounted or src in taken_paths or not os.path.exists(src):
                continue
            base = slugify(resource.replace("/", "--"))
            if item["kind"] == "link":
                found[key] = {"kind": "link", "path": src, "resource": resource,
                              "slug_base": f"{base}--{slugify(os.path.basename(src))}"}
            elif self.args.convert:
                found[key] = {"kind": "convert", "path": src, "resource": resource,
                              "slug_base": f"{base}--{slugify(stem_of(src))}"}
        return found

    def discover_samples(self):
        sources = {}
        for root in self.args.sample_dirs:
            if not os.path.isdir(root):
                continue
            for name in sorted(os.listdir(root)):
                src = os.path.join(root, name)
                if name.startswith(".") or not os.path.isdir(src):
                    continue
                if not os.path.exists(os.path.join(src, SAMPLE_COMPLETE_MARKER)):
                    continue
                sources[f"sample:{name}"] = {
                    "kind": "link", "path": src, "resource": None,
                    "slug_base": f"sample--{slugify(name)}"}
        return sources

    # ---- linking -----------------------------------------------------------------------------

    @staticmethod
    def signature(path):
        st = os.stat(path)
        return [st.st_size, int(st.st_mtime)]

    def link_project(self, key, src):
        slug = self.slug_for(key, src["slug_base"])
        dest = os.path.join(self.projects_dir, slug)
        if not os.path.isdir(dest):
            tmp = os.path.join(self.args.build_dir, f"link-{slug}")
            shutil.rmtree(tmp, ignore_errors=True)
            os.makedirs(tmp)
            self.populate_overlay(tmp, src["path"], previous=None)
            shutil.move(tmp, dest)
            self.changed = True
            LOG.info("linked %s -> %s", src["path"], dest)
        else:
            self.populate_overlay(dest, src["path"], previous=self.state["entries"].get(key, {}))
        self.state["entries"][key] = {
            "slug": slug, "kind": "link", "source": src["path"], "resource": src["resource"],
            "datasources_sig": self.signature(os.path.join(src["path"], "datasources.json"))}

    def populate_overlay(self, dest, source, previous):
        """Mirrors source into dest: top-level files MDV edits are copied, other files are
        symlinked, and directories are real local directories. MDV creates some directories
        (e.g. tracks/) when it loads a project, which fails on a dangling symlink, and MDV loads
        projects at startup before the buckets are mounted again."""
        for name in os.listdir(source):
            if name.startswith(".") or name in SKIP_ENTRIES:
                continue
            src_path, dest_path = os.path.join(source, name), os.path.join(dest, name)
            if name in LOCAL_COPY_FILES:
                # Keep the user's local views/state; refresh only the data description when
                # the source data changed, since it must match the linked data files.
                refresh = (name == "datasources.json" and previous is not None
                           and previous.get("datasources_sig") != self.signature(src_path))
                if refresh or not os.path.lexists(dest_path):
                    shutil.copyfile(src_path, dest_path)
                    if refresh:
                        LOG.info("source data changed; refreshed %s", dest_path)
            else:
                self.mirror(src_path, dest_path)
        self.prune(dest)

    def mirror(self, src_path, dest_path):
        if os.path.isdir(src_path):
            if os.path.islink(dest_path):
                os.unlink(dest_path)
            os.makedirs(dest_path, exist_ok=True)
            for name in os.listdir(src_path):
                if not name.startswith("."):
                    self.mirror(os.path.join(src_path, name), os.path.join(dest_path, name))
        elif not os.path.lexists(dest_path):
            os.symlink(src_path, dest_path)

    @staticmethod
    def prune(dest):
        """Removes links to files deleted from the source, and directories left empty."""
        for root, dirs, files in os.walk(dest, topdown=False):
            for name in files + dirs:
                path = os.path.join(root, name)
                if os.path.islink(path) and not os.path.exists(path):
                    os.unlink(path)
            if root != dest and not os.listdir(root) and \
                    os.path.basename(root) not in ("tracks", "images"):
                os.rmdir(root)

    # ---- conversion --------------------------------------------------------------------------

    def convert_file(self, key, src):
        sig = self.signature(src["path"])
        previous = self.state["entries"].get(key)
        if previous and previous.get("source_sig") == sig and \
                os.path.isdir(os.path.join(self.projects_dir, previous["slug"])):
            return
        slug = self.slug_for(key, src["slug_base"])
        tmp = os.path.join(self.args.build_dir, f"convert-{slug}")
        shutil.rmtree(tmp, ignore_errors=True)
        cmd = [self.args.python, "-W", "ignore",
               os.path.join(os.path.dirname(os.path.abspath(__file__)), "convert_file.py"),
               src["path"], tmp]
        LOG.info("converting %s (this can take a while)", src["path"])
        started = time.time()
        result = subprocess.run(cmd, cwd=self.args.build_dir, capture_output=True, text=True)
        if result.returncode != 0:
            LOG.error("conversion failed for %s:\n%s", src["path"], result.stderr[-4000:])
            shutil.rmtree(tmp, ignore_errors=True)
            return
        dest = os.path.join(self.projects_dir, slug)
        if os.path.isdir(dest):
            # Replace contents in place so the path MDV registered stays valid.
            for name in os.listdir(dest):
                path = os.path.join(dest, name)
                if os.path.isdir(path) and not os.path.islink(path):
                    shutil.rmtree(path)
                else:
                    os.unlink(path)
            for name in os.listdir(tmp):
                shutil.move(os.path.join(tmp, name), os.path.join(dest, name))
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            shutil.move(tmp, dest)
        self.changed = True
        self.state["entries"][key] = {
            "slug": slug, "kind": "convert", "source": src["path"], "resource": src["resource"],
            "source_sig": sig}
        LOG.info("converted %s -> %s in %.0f s", src["path"], dest, time.time() - started)

    # ---- MDV server --------------------------------------------------------------------------

    def mdv(self, path, method="GET", timeout=120):
        req = urllib.request.Request(self.args.mdv_url.rstrip("/") + path, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
        return json.loads(body) if body[:1] in (b"[", b"{") else body

    def wait_for_mdv(self):
        deadline = time.time() + self.args.mdv_wait_seconds
        while True:
            try:
                self.mdv("/projects", timeout=10)
                return True
            except (urllib.error.URLError, OSError, ValueError):
                if time.time() >= deadline:
                    return False
                time.sleep(3)

    def remove_entry(self, key):
        entry = self.state["entries"][key]
        slug, dest = entry["slug"], os.path.join(self.projects_dir, entry["slug"])
        try:
            ids = [p["id"] for p in self.mdv("/projects") if p.get("name") == slug]
        except (urllib.error.URLError, OSError, ValueError) as e:
            LOG.warning("cannot list MDV projects to remove %s: %s", slug, e)
            return
        if ids:
            try:
                self.mdv(f"/delete_project/{ids[0]}", method="DELETE")
            except (urllib.error.URLError, OSError) as e:
                LOG.warning("MDV refused to delete project %s (%s); keeping it", slug, e)
                return
        elif os.path.isdir(dest):
            # Renamed in MDV, or not registered yet. Deleting the folder while MDV still lists
            # the project makes MDV recreate it empty, so leave it for the user to delete.
            LOG.warning("source of %s is gone, but no MDV project is named %s; "
                        "delete it in MDV", dest, slug)
            return
        shutil.rmtree(dest, ignore_errors=True)
        self.state["retired_slugs"].append(slug)
        del self.state["entries"][key]
        LOG.info("removed %s (source no longer present)", slug)

    # ---- main --------------------------------------------------------------------------------

    def run(self):
        os.makedirs(self.args.build_dir, exist_ok=True)
        self.load_state()
        mdv_ready = self.wait_for_mdv()
        if not mdv_ready:
            LOG.warning("MDV not reachable at %s; new projects register at its next start",
                        self.args.mdv_url)

        workspace, mounted = self.discover_workspace()
        workspace.update(self.discover_imports(
            mounted, {src["path"] for src in workspace.values()}))
        samples = {}
        if self.args.samples == "always" or (self.args.samples == "auto" and not workspace):
            samples = self.discover_samples()
        if not self.args.only:
            LOG.info("%d workspace source(s) in %d mounted resource(s); %d sample(s) shown",
                     len(workspace), len(mounted), len(samples))
        self.state["workspace_sources"] = len(workspace)
        self.state["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")

        wanted = {**workspace, **samples}
        for key, src in wanted.items():
            if self.args.only and key != self.args.only:
                continue
            try:
                if src["kind"] == "link":
                    self.link_project(key, src)
                elif not self.args.link_only:
                    self.convert_file(key, src)
            except OSError as e:
                LOG.error("failed to add %s: %s", src["path"], e)
            self.save_state()

        if mdv_ready:
            # A single-item run (--only) still retires samples once real data exists.
            for key in [k for k in self.state["entries"] if k not in wanted
                        and (not self.args.only or k.startswith("sample:"))]:
                entry = self.state["entries"][key]
                # Never remove anything just because its bucket isn't mounted (yet).
                if entry.get("resource") and entry["resource"] not in mounted:
                    continue
                self.remove_entry(key)
                self.save_state()

        if self.changed and mdv_ready:
            try:
                self.mdv("/rescan_projects", timeout=600)
                LOG.info("registered new projects with MDV")
            except (urllib.error.URLError, OSError) as e:
                LOG.warning("rescan failed: %s", e)


def parse_args(argv):
    env = os.environ.get
    p = argparse.ArgumentParser(description="Make workspace data available to MDV.")
    p.add_argument("--source-root", default=env("MDV_WORKSPACE_RO_ROOT", "/mnt/mdv-workspace-ro"))
    p.add_argument("--resources-file", default=env(
        "MDV_WORKSPACE_RESOURCES_FILE", "/var/lib/mdv-workspace-sync/resources.txt"),
        help="list of mounted resources; empty string means every folder under --source-root")
    p.add_argument("--projects-dir", default=env("MDV_PROJECTS_DIR", "/app/mdv"))
    p.add_argument("--build-dir", default=env("MDV_SYNC_BUILD_DIR",
                                              "/var/lib/mdv-workspace-sync/build"))
    p.add_argument("--bucket-folder", default=env("MDV_WORKSPACE_FOLDER", "mdv"))
    p.add_argument("--sample-dirs", nargs="*", default=env(
        "MDV_SAMPLE_DIRS", "/opt/mdv-samples /var/lib/mdv-samples").split())
    p.add_argument("--samples", choices=["auto", "always", "never"],
                   default=env("MDV_SAMPLE_DATA", "auto"))
    p.add_argument("--convert", action=argparse.BooleanOptionalAction,
                   default=env("MDV_WORKSPACE_CONVERT", "true").lower() == "true")
    p.add_argument("--link-only", action="store_true", help="skip conversions (fast startup pass)")
    p.add_argument("--only", metavar="KEY",
                   help="process one source (used by the Workspace data browser); waits for a "
                        "running sync instead of skipping")
    p.add_argument("--mdv-url", default=env("MDV_INTERNAL_URL", "http://127.0.0.1:5056"))
    p.add_argument("--mdv-wait-seconds", type=int, default=180)
    p.add_argument("--python", default=env("MDV_PYTHON", "/app/python/.venv/bin/python"))
    args = p.parse_args(argv)
    args.resources_file = args.resources_file or None
    return args


def main(argv=None):
    os.umask(0o022)
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(message)s")
    state_dir = os.path.dirname(os.path.abspath(args.build_dir))
    os.makedirs(state_dir, exist_ok=True)
    with open(os.path.join(state_dir, "sync.lock"), "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | (0 if args.only else fcntl.LOCK_NB))
        except BlockingIOError:
            LOG.info("another sync is running; skipping")
            return 0
        Sync(args).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
