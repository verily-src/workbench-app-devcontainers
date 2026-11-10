#!/usr/bin/env python3
"""Build the large MDV sample project when the workspace has no MDV data.

Uses the example from MDV's backend tools tutorial
(https://mdv.ndm.ox.ac.uk/docs/tutorials/backend-tools-tutorial): 1000 Genomes phase 3
chromosome 1 variants, converted with `mdvtools convert-vcf`. Only the 8 site columns are kept
(not the 2,504 per-sample genotype columns). The number of variants is limited by the VM's
memory, up to the whole chromosome (~6.5 million variants), so the sample is as large as the VM
can convert safely.

The result goes to /var/lib/mdv-samples/<name>/ with a completion marker; mdv_workspace_sync.py
then links it into MDV. Runs as the MDV user; standard library only.
"""

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time

LOG = logging.getLogger("mdv-samples")

VCF_URL = ("https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/release/20130502/"
           "ALL.chr1.phase3_shapeit2_mvncall_integrated_v5b.20130502.genotypes.vcf.gz")
SAMPLE_NAME = "1000genomes-chr1-variants"
COMPLETE_MARKER = ".mdv-sample-complete"
FAILURE_FILE = ".last-failure.json"
# Measured: converting 500,000 variants peaks at ~560 MB; allow 1.2 GB per million.
MB_PER_MILLION_SITES = 1200
RETRY_AFTER_SECONDS = 6 * 3600


def mem_available_mb():
    """Available memory, respecting the container's cgroup limit."""
    with open("/proc/meminfo") as f:
        meminfo = dict(line.split(":", 1) for line in f)
    available = int(meminfo["MemAvailable"].split()[0]) // 1024
    for path in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            with open(path) as f:
                limit = f.read().strip()
            if limit.isdigit():
                used_path = path.replace("memory.max", "memory.current").replace(
                    "limit_in_bytes", "usage_in_bytes")
                with open(used_path) as f:
                    used = int(f.read().strip())
                available = min(available, (int(limit) - used) // (1024 * 1024))
        except OSError:
            continue
    return available


def site_limit(requested):
    if requested > 0:
        return requested
    budget_mb = mem_available_mb() // 2
    return max(250_000, budget_mb * 1_000_000 // MB_PER_MILLION_SITES)


def download(url, dest, attempts=5):
    """Downloads url to dest with curl, resuming partial downloads."""
    for attempt in range(1, attempts + 1):
        result = subprocess.run(
            ["curl", "-fsSL", "--retry", "10", "--retry-all-errors", "--connect-timeout", "30",
             "--speed-limit", "10000", "--speed-time", "120", "-C", "-", "-o", dest, url],
            capture_output=True, text=True)
        if result.returncode == 0:
            return
        LOG.warning("download attempt %d failed: %s", attempt, result.stderr.strip()[-300:])
        time.sleep(min(60, 10 * attempt))
    raise RuntimeError(f"could not download {url}")


def extract_sites(vcf_gz, dest, max_sites):
    """Writes the VCF headers and the first 8 columns of up to max_sites variants."""
    # zcat stops early with SIGPIPE when awk exits, so only awk's status matters.
    script = (
        'zcat "$1" 2>/dev/null | cut -f1-8 | '
        'awk -v max="$2" \'/^#/ {print; next} {print; if (++n >= max) exit}\' > "$3"; '
        'exit ${PIPESTATUS[2]}')
    result = subprocess.run(["bash", "-c", script, "extract", vcf_gz, str(max_sites), dest],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"extracting variants failed: {result.stderr[-500:]}")
    with open(dest, "rb") as f:
        return sum(1 for line in f if not line.startswith(b"#"))


def build(args):
    final = os.path.join(args.samples_dir, SAMPLE_NAME)
    if os.path.exists(os.path.join(final, COMPLETE_MARKER)):
        LOG.info("sample %s already built", SAMPLE_NAME)
        return 0
    failure = os.path.join(args.samples_dir, FAILURE_FILE)
    if os.path.exists(failure) and not args.force:
        with open(failure) as f:
            last = json.load(f)
        if time.time() - last.get("time", 0) < RETRY_AFTER_SECONDS:
            LOG.info("previous sample build failed (%s); retrying later", last.get("error"))
            return 0

    work = os.path.join(args.samples_dir, ".build")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    try:
        max_sites = site_limit(args.max_sites)
        LOG.info("building sample %s with up to %d variants (%d MB memory available)",
                 SAMPLE_NAME, max_sites, mem_available_mb())
        vcf_gz = os.path.join(work, "source.vcf.gz")
        vcf = os.path.join(work, "1000genomes_chr1.vcf")
        started = time.time()
        download(args.url, vcf_gz)
        LOG.info("downloaded %s in %.0f s", args.url, time.time() - started)
        started = time.time()
        sites = extract_sites(vcf_gz, vcf, max_sites)
        os.remove(vcf_gz)
        LOG.info("extracted %d variants in %.0f s", sites, time.time() - started)

        project = os.path.join(work, "project")
        started = time.time()
        result = subprocess.run(
            [args.python, "-W", "ignore", "-m", "mdvtools.cli", "convert-vcf", project, vcf],
            cwd=work, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"convert-vcf failed: {result.stderr[-2000:]}")
        LOG.info("converted in %.0f s", time.time() - started)
        os.remove(vcf)

        with open(os.path.join(project, "README.md"), "w") as f:
            f.write(
                "# Sample: 1000 Genomes chromosome 1 variants\n\n"
                f"{sites:,} variant sites from 1000 Genomes phase 3 chromosome 1 (site columns "
                "only), converted with `mdvtools convert-vcf` as in MDV's backend tools "
                "tutorial.\n\nThis sample is shown because no workspace bucket has an `mdv/` "
                "folder. Add your data to `<bucket>/mdv/projects/` or `<bucket>/mdv/data/` and "
                "it replaces the samples automatically.\n\nSource: " + args.url + "\n")
        open(os.path.join(project, COMPLETE_MARKER), "w").close()
        shutil.rmtree(final, ignore_errors=True)
        os.replace(project, final)
        if os.path.exists(failure):
            os.remove(failure)
        LOG.info("sample ready at %s", final)
        return 0
    except Exception as e:  # report and retry later rather than crash the sync loop
        LOG.error("sample build failed: %s", e)
        with open(failure, "w") as f:
            json.dump({"time": time.time(), "error": str(e)[:500]}, f)
        return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv=None):
    os.umask(0o022)
    env = os.environ.get
    p = argparse.ArgumentParser(description="Build the large MDV sample project.")
    p.add_argument("--samples-dir", default=env("MDV_LARGE_SAMPLE_DIR", "/var/lib/mdv-samples"))
    p.add_argument("--url", default=env("MDV_SAMPLE_VCF_URL", VCF_URL))
    p.add_argument("--max-sites", type=int, default=int(env("MDV_SAMPLE_VCF_MAX_SITES", "0")),
                   help="0 = as many as the VM's memory allows, up to the whole chromosome")
    p.add_argument("--python", default=env("MDV_PYTHON", "/app/python/.venv/bin/python"))
    p.add_argument("--force", action="store_true", help="ignore a recent failure")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(message)s")
    os.makedirs(args.samples_dir, exist_ok=True)
    return build(args)


if __name__ == "__main__":
    sys.exit(main())
