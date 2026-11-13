#!/usr/bin/env python3
"""Backend for the "Workspace data" browser shown inside MDV (see workspace-ui.js).

Lets users browse the workspace buckets mounted in the app and open a file or MDV project in MDV
with one click. The data never goes through the browser: the server links or converts it straight
from the read-only bucket mount (mdv_workspace_sync.py), then MDV opens the new project.

Listens on 127.0.0.1 only; nginx routes /_workspace/ here, behind Workbench's authentication.
Runs as the MDV user; standard library only.

  GET  /ui.js                 the browser script injected into MDV's pages
  GET  /api/list?path=<path>  mounted buckets (empty path) or a folder's entries
  POST /api/import            {"path": "<bucket>/<path>"} -> {"job": id, ...}
  GET  /api/jobs/<id>         job status, and the MDV project to open when done
"""

import json
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from convert_file import kind_of  # noqa: E402  (stdlib-only helper)

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = os.environ.get
RO_ROOT = os.path.realpath(ENV("MDV_WORKSPACE_RO_ROOT", "/mnt/mdv-workspace-ro"))
RESOURCES_FILE = ENV("MDV_WORKSPACE_RESOURCES_FILE", "/var/lib/mdv-workspace-sync/resources.txt")
META_DIR = os.path.dirname(RESOURCES_FILE)
STEWARDSHIP = {"CONTROLLED": "Controlled", "REFERENCED": "Referenced"}
RESOURCE_TYPES = {"GCS_BUCKET": "Cloud Storage bucket", "GCS_OBJECT": "Cloud Storage object",
                  "AWS_S3_STORAGE_FOLDER": "S3 Storage Folder"}
PROJECTS_DIR = ENV("MDV_PROJECTS_DIR", "/app/mdv")
STATE_FILE = os.path.join(PROJECTS_DIR, ".workspace-sync-state.json")
IMPORTS_FILE = os.path.join(PROJECTS_DIR, ".workspace-imports.json")
LOG_FILE = ENV("MDV_SYNC_LOG", "/var/lib/mdv-workspace-sync/sync.log")
MDV_URL = ENV("MDV_INTERNAL_URL", "http://127.0.0.1:5056")
FOLDER = ENV("MDV_WORKSPACE_FOLDER", "mdv")
PORT = int(ENV("MDV_WORKSPACE_UI_PORT", "5057"))
MAX_ENTRIES = 2000
PROJECT_CHECK_LIMIT = 300

LOG = logging.getLogger("mdv-workspace-ui")
JOBS = {}
JOBS_LOCK = threading.Lock()
IMPORTS_LOCK = threading.Lock()


class BadRequest(Exception):
    pass


def mounted_resources():
    if not os.path.exists(RESOURCES_FILE):
        return []
    with open(RESOURCES_FILE) as f:
        return [line.strip() for line in f if line.strip()]


def resolve(path):
    """Maps "<resource>/<subpath>" to (resource, subpath, absolute path) inside the mounts."""
    path = path.strip("/")
    parts = path.split("/")
    if not path or any(p in ("", ".", "..") for p in parts):
        raise BadRequest("invalid path")
    resource = max((r for r in mounted_resources() if path == r or path.startswith(r + "/")),
                   key=len, default=None)
    if resource is None:
        raise BadRequest("not in a mounted workspace bucket")
    subpath = path[len(resource):].strip("/")
    absolute = os.path.join(RO_ROOT, resource, subpath)
    if not os.path.realpath(absolute).startswith(RO_ROOT + os.sep):
        raise BadRequest("invalid path")
    return resource, subpath, absolute


def workspace_name():
    data = read_json(os.path.join(META_DIR, "workspace.json"), {})
    return data.get("name") or data.get("id") or ""


def resource_details():
    """Workbench resource metadata by resource name, from `wb resource list` at app start."""
    data = read_json(os.path.join(META_DIR, "resources.json"), [])
    return {r.get("id"): r for r in data if isinstance(r, dict) and r.get("id")}


def resource_entry(rel, details):
    meta = details.get(rel.rsplit("/", 1)[-1], {})
    kind = RESOURCE_TYPES.get(meta.get("resourceType"), "Cloud Storage bucket")
    labels = [kind]
    if meta.get("stewardshipType") in STEWARDSHIP:
        labels.append(STEWARDSHIP[meta["stewardshipType"]])
    return {"name": rel.rsplit("/", 1)[-1], "path": rel, "type": "bucket",
            "label": " · ".join(labels), "description": meta.get("description") or ""}


def list_virtual(path):
    """Workbench folders and the resources in them, above the bucket level."""
    prefix = f"{path}/" if path else ""
    details, folders, entries = resource_details(), set(), []
    for rel in mounted_resources():
        if not rel.startswith(prefix):
            continue
        rest = rel[len(prefix):]
        if "/" in rest:
            folders.add(rest.split("/", 1)[0])
        else:
            entries.append(resource_entry(rel, details))
    entries += [{"name": f, "path": prefix + f, "type": "wbfolder"} for f in folders]
    order = {"wbfolder": 0, "bucket": 1}
    entries.sort(key=lambda e: (order[e["type"]], e["name"].lower()))
    return {"path": path, "workspace": workspace_name(), "entries": entries, "truncated": False}


def is_project(directory):
    return os.path.isfile(os.path.join(directory, "datasources.json"))


def list_path(path):
    path = path.strip("/")
    resources = mounted_resources()
    if not path or (path not in resources and
                    not any(path.startswith(r + "/") for r in resources)):
        if path and not any(r.startswith(path + "/") for r in resources):
            raise BadRequest("not in a mounted workspace bucket")
        return list_virtual(path)
    _, _, absolute = resolve(path)
    if not os.path.isdir(absolute):
        raise BadRequest("not a folder")
    entries, checked = [], 0
    with os.scandir(absolute) as it:
        for entry in it:
            if entry.name.startswith("."):
                continue
            rel = f"{path}/{entry.name}"
            if entry.is_dir(follow_symlinks=False):
                project = checked < PROJECT_CHECK_LIMIT and is_project(entry.path)
                checked += 1
                entries.append({"name": entry.name, "path": rel,
                                "type": "project" if project else "folder"})
            elif entry.is_file(follow_symlinks=False):
                st = entry.stat()
                entries.append({"name": entry.name, "path": rel, "type": "file",
                                "size": st.st_size, "modified": int(st.st_mtime),
                                "kind": kind_of(entry.name),
                                "importable": kind_of(entry.name) is not None})
            if len(entries) >= MAX_ENTRIES:
                break
    order = {"project": 0, "folder": 1, "file": 2}
    entries.sort(key=lambda e: (order[e["type"]], e["name"].lower()))
    return {"path": path, "workspace": workspace_name(), "entries": entries,
            "truncated": len(entries) >= MAX_ENTRIES}


def read_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def mdv_projects():
    with urllib.request.urlopen(MDV_URL.rstrip("/") + "/projects", timeout=30) as resp:
        return json.load(resp)


def project_for(source):
    """The MDV project (id, name) already made from this source, if any."""
    for entry in read_json(STATE_FILE, {}).get("entries", {}).values():
        if entry.get("source") == source and \
                os.path.isdir(os.path.join(PROJECTS_DIR, entry["slug"])):
            for project in mdv_projects():
                if project.get("name") == entry["slug"]:
                    return project["id"], entry["slug"]
    return None


def sync_key(resource, subpath, kind):
    """The key the sync uses for this source; files in the bucket's mdv/ folder already have one."""
    parts = subpath.split("/")
    if kind == "link" and len(parts) == 3 and parts[:2] == [FOLDER, "projects"]:
        return f"ws:link:{resource}/{parts[2]}"
    if kind == "convert" and len(parts) == 3 and parts[:2] == [FOLDER, "data"]:
        return f"ws:convert:{resource}/{parts[2]}"
    return f"ui:{kind}:{resource}/{subpath}"


def record_import(key, resource, subpath, kind):
    if not key.startswith("ui:"):
        return
    with IMPORTS_LOCK:
        data = read_json(IMPORTS_FILE, {"imports": {}})
        data.setdefault("imports", {})[key] = {
            "resource": resource, "subpath": subpath, "kind": kind,
            "added": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        tmp = IMPORTS_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp, IMPORTS_FILE)


def start_import(path):
    resource, subpath, absolute = resolve(path)
    if os.path.isdir(absolute) and is_project(absolute):
        kind = "link"
    elif os.path.isfile(absolute) and kind_of(absolute) is not None:
        kind = "convert"
    else:
        raise BadRequest("only MDV projects and .h5ad, .h5mu, .vcf, .csv or .tsv files can be "
                         "opened")
    job = {"id": uuid.uuid4().hex[:12], "path": path, "kind": kind, "state": "running",
           "started": time.time(), "log": []}
    existing = project_for(absolute)
    if existing:
        job.update(state="done", project_id=existing[0], project_name=existing[1],
                   message="Already in MDV")
    else:
        key = sync_key(resource, subpath, kind)
        record_import(key, resource, subpath, kind)
        threading.Thread(target=run_job, args=(job, key, absolute), daemon=True).start()
    with JOBS_LOCK:
        JOBS[job["id"]] = job
    return job


def run_job(job, key, absolute):
    cmd = [sys.executable, os.path.join(HERE, "mdv_workspace_sync.py"), "--only", key]
    try:
        with open(LOG_FILE, "a") as log, subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as proc:
            for line in proc.stdout:
                log.write(line)
                log.flush()
                job["log"] = (job["log"] + [line.rstrip()])[-20:]
        if proc.returncode != 0:
            raise RuntimeError(f"import failed (exit {proc.returncode})")
        project = project_for(absolute)
        if not project:
            raise RuntimeError("the project wasn't created; see the details below")
        job.update(state="done", project_id=project[0], project_name=project[1])
    except Exception as e:  # report to the browser rather than lose the job
        LOG.exception("import of %s failed", job["path"])
        job.update(state="failed", message=str(e))


def job_status(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if job is None:
        raise BadRequest("unknown job")
    out = {k: v for k, v in job.items() if k != "started"}
    out["elapsed"] = int(time.time() - job["started"])
    return out


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_errors(self, fn):
        try:
            self.send_json(200, fn())
        except BadRequest as e:
            self.send_json(400, {"error": str(e)})
        except FileNotFoundError:
            self.send_json(404, {"error": "not found"})
        except PermissionError:
            self.send_json(403, {"error": "permission denied"})
        except Exception as e:
            LOG.exception("request failed")
            self.send_json(500, {"error": str(e)})

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/ui.js":
            with open(os.path.join(HERE, "workspace-ui.js"), "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/javascript; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif url.path == "/api/list":
            self.handle_errors(lambda: list_path(parse_qs(url.query).get("path", [""])[0]))
        elif url.path.startswith("/api/jobs/"):
            self.handle_errors(lambda: job_status(url.path.rsplit("/", 1)[-1]))
        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self):
        if urlparse(self.path).path != "/api/import":
            self.send_json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length > 10_000:
            self.send_json(413, {"error": "request too large"})
            return

        def go():
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                raise BadRequest("invalid JSON")
            return start_import(str(body.get("path", "")))
        self.handle_errors(go)

    def log_message(self, fmt, *args):
        LOG.info("%s %s", self.address_string(), fmt % args)


def main():
    os.umask(0o022)
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(message)s")
    LOG.info("workspace data browser listening on 127.0.0.1:%d", PORT)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
