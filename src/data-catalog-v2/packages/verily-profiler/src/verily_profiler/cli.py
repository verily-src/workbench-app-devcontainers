"""
CLI entry point for verily-profiler.

Usage:
    verily-profiler discover <project>
    verily-profiler tech <project.dataset.table> [--billing-project ...] [--bucket ...]
    verily-profiler semantic <project.dataset.table> --model <model> [--billing-project ...] [--bucket ...]
    verily-profiler profile <project.dataset.table> --model <model> [--billing-project ...] [--bucket ...]
    verily-profiler profile-dataset <project.dataset> --model <model> [--billing-project ...] [--bucket ...]
"""

from __future__ import annotations

import json
import sys

import click


@click.group()
@click.version_option(package_name="verily-profiler")
def main():
    """BigQuery table profiling: technical stats + LLM-driven semantic metadata."""


@main.command()
@click.argument("project")
@click.option("--billing-project", default=None, help="Project for BQ billing (defaults to PROJECT)")
def discover(project: str, billing_project: str | None):
    """List datasets and tables in a BigQuery project."""
    from verily_profiler.discovery import discover_datasets, discover_tables

    datasets = discover_datasets(project, billing_project=billing_project)
    if not datasets:
        click.echo(f"No datasets found in {project}")
        return

    for ds in datasets:
        tables = discover_tables(project, ds, billing_project=billing_project)
        click.echo(f"\n{project}.{ds} ({len(tables)} tables):")
        for t in tables:
            rows = f"  {t.row_count:,} rows" if t.row_count is not None else ""
            click.echo(f"  {t.table_id}{rows}")


@main.command()
@click.argument("table")
@click.option("--billing-project", default=None, help="Project for BQ billing")
@click.option("--bucket", default=None, help="GCS bucket to write results")
def tech(table: str, billing_project: str | None, bucket: str | None):
    """Run technical profiling on a single table (project.dataset.table)."""
    from verily_profiler.storage import parse_fq_table, write_tech_profile as _write
    from verily_profiler.discovery import discover_tables
    from verily_profiler.technical import profile_technical

    project_id, dataset_id, table_id = parse_fq_table(table)
    bp = billing_project or project_id

    tables = discover_tables(project_id, dataset_id, billing_project=bp)
    match = next((t for t in tables if t.table_id == table_id), None)
    if not match:
        click.echo(f"Table {table} not found", err=True)
        sys.exit(1)

    result = profile_technical(match, billing_project=bp)
    click.echo(json.dumps(result.to_json_dict(), indent=2))

    if bucket:
        uri = _write(bucket, table, result, project_id=bp)
        click.echo(f"\nWritten to {uri}", err=True)


@main.command()
@click.argument("table")
@click.option("--model", required=True, help="Gemini model name")
@click.option("--billing-project", default=None, help="Project for Vertex AI & BQ billing")
@click.option("--bucket", default=None, help="GCS bucket (reads tech profile, writes semantic)")
def semantic(table: str, model: str, billing_project: str | None, bucket: str | None):
    """Run semantic profiling on a single table (requires tech profile)."""
    from verily_profiler.storage import parse_fq_table, read_tech_profile, write_sem_profile as _write
    from verily_profiler.models import TechTableProfile, TechColumnProfile
    from verily_profiler.semantic import profile_semantic

    project_id, dataset_id, table_id = parse_fq_table(table)
    bp = billing_project or project_id

    if bucket:
        tech_data = read_tech_profile(bucket, table, project_id=bp)
        if not tech_data:
            click.echo(f"No tech profile found in gs://{bucket} for {table}. Run `tech` first.", err=True)
            sys.exit(1)
    else:
        click.echo("--bucket is required for semantic profiling (to read tech profile)", err=True)
        sys.exit(1)

    tech = _reconstruct_tech_profile(tech_data)
    result = profile_semantic(tech, model=model, project_id=bp)
    click.echo(json.dumps(result.to_json_dict(), indent=2))

    uri = _write(bucket, table, result, project_id=bp)
    click.echo(f"\nWritten to {uri}", err=True)


@main.command()
@click.argument("table")
@click.option("--model", required=True, help="Gemini model name")
@click.option("--billing-project", default=None, help="Project for Vertex AI & BQ billing")
@click.option("--bucket", required=True, help="GCS bucket to write results")
def profile(table: str, model: str, billing_project: str | None, bucket: str):
    """Full pipeline: tech + semantic profiling for one table."""
    from verily_profiler.storage import parse_fq_table, write_tech_profile, write_sem_profile
    from verily_profiler.discovery import discover_tables
    from verily_profiler.technical import profile_technical
    from verily_profiler.semantic import profile_semantic

    project_id, dataset_id, table_id = parse_fq_table(table)
    bp = billing_project or project_id

    tables = discover_tables(project_id, dataset_id, billing_project=bp)
    match = next((t for t in tables if t.table_id == table_id), None)
    if not match:
        click.echo(f"Table {table} not found", err=True)
        sys.exit(1)

    click.echo(f"Technical profiling {table}...")
    tech = profile_technical(match, billing_project=bp)
    uri_t = write_tech_profile(bucket, table, tech, project_id=bp)
    click.echo(f"  -> {uri_t}")

    click.echo(f"Semantic profiling {table}...")
    sem = profile_semantic(tech, model=model, project_id=bp)
    uri_s = write_sem_profile(bucket, table, sem, project_id=bp)
    click.echo(f"  -> {uri_s}")

    click.echo(f"\nDone. Validation: {sem.validation.status}")
    if sem.validation.issues:
        for issue in sem.validation.issues:
            click.echo(f"  [issue] {issue}", err=True)
    if sem.validation.warnings:
        for w in sem.validation.warnings:
            click.echo(f"  [warning] {w}", err=True)


@main.command("profile-dataset")
@click.argument("dataset")
@click.option("--model", required=True, help="Gemini model name")
@click.option("--billing-project", default=None, help="Project for Vertex AI & BQ billing")
@click.option("--bucket", required=True, help="GCS bucket to write results")
def profile_dataset(dataset: str, model: str, billing_project: str | None, bucket: str):
    """Full pipeline for every table in a dataset (project.dataset)."""
    from verily_profiler.storage import write_tech_profile, write_sem_profile
    from verily_profiler.discovery import discover_tables
    from verily_profiler.technical import profile_technical
    from verily_profiler.semantic import profile_semantic

    parts = dataset.split(".", 1)
    if len(parts) != 2:
        click.echo("Expected format: project.dataset", err=True)
        sys.exit(1)
    project_id, dataset_id = parts
    bp = billing_project or project_id

    tables = discover_tables(project_id, dataset_id, billing_project=bp)
    if not tables:
        click.echo(f"No tables found in {dataset}")
        return

    click.echo(f"Found {len(tables)} tables in {dataset}")
    for i, tbl in enumerate(tables, 1):
        fq = tbl.fq_name
        click.echo(f"\n[{i}/{len(tables)}] {fq}")
        try:
            tech = profile_technical(tbl, billing_project=bp)
            write_tech_profile(bucket, fq, tech, project_id=bp)

            sem = profile_semantic(tech, model=model, project_id=bp)
            write_sem_profile(bucket, fq, sem, project_id=bp)

            click.echo(f"  OK ({sem.validation.status})")
        except Exception as e:
            click.echo(f"  FAILED: {e}", err=True)

    click.echo(f"\nDone — {len(tables)} tables profiled.")


def _reconstruct_tech_profile(data: dict) -> "TechTableProfile":
    """Rebuild a TechTableProfile dataclass from a GCS JSON dict."""
    from verily_profiler.models import TechTableProfile, TechColumnProfile, ValidationResult

    cols = []
    for c in data.get("columns", []):
        cols.append(TechColumnProfile(
            column_name=c.get("name", c.get("column_name", "")),
            data_type=c.get("data_type", ""),
            nullable=c.get("nullable", True),
            null_count=c.get("null_count", 0),
            null_percent=c.get("null_percent", 0.0),
            distinct_count=c.get("distinct_count", 0),
            top_values=c.get("top_values", []),
            value_counts=c.get("value_counts"),
            min_length=(c.get("string_stats") or {}).get("min_length"),
            max_length=(c.get("string_stats") or {}).get("max_length"),
            avg_length=(c.get("string_stats") or {}).get("avg_length"),
            min_value=(c.get("numeric_stats") or {}).get("min"),
            max_value=(c.get("numeric_stats") or {}).get("max"),
            median=(c.get("numeric_stats") or {}).get("median"),
            stddev=(c.get("numeric_stats") or {}).get("stddev"),
            detected_pattern=c.get("pattern"),
            anomalies=c.get("anomalies", []),
        ))

    v = data.get("validation", {})
    return TechTableProfile(
        table_name=data.get("table", ""),
        row_count=data.get("row_count", 0),
        size_bytes=data.get("size_bytes"),
        profiled_at=data.get("profiled_at", ""),
        columns=cols,
        validation=ValidationResult(
            status=v.get("status", "pass"),
            anomalies=v.get("anomalies", []),
            warnings=v.get("warnings", []),
        ),
    )


@main.command("reconcile")
@click.argument("project")
@click.option("--bucket", required=True, help="GCS bucket with profiling output")
@click.option("--model", default="gemini-2.5-flash", help="Gemini model name")
@click.option("--billing-project", default=None, help="Project for billing")
@click.option("--apply", "do_apply", is_flag=True, default=False, help="Apply reconciliation (default: dry-run)")
def reconcile_cmd(project: str, bucket: str, model: str, billing_project: str | None, do_apply: bool):
    """Reconcile terminology bindings across all profiled tables in a project."""
    from verily_profiler.storage import read_registry, write_registry, read_sem_profile, write_sem_profile, scan_profile_availability
    from verily_profiler.reconcile import reconcile, apply_reconciliation

    bp = billing_project or project
    click.echo(f"Loading registry for {project}...")
    registry = read_registry(bucket, project, billing_project_id=bp)
    click.echo(f"  Registry has {len(registry.entries)} entries")

    if len(registry.entries) < 2:
        click.echo("Not enough entries to reconcile.")
        return

    click.echo(f"Running reconciliation with {model}...")
    groups = reconcile(registry, model=model, project_id=bp)

    if not groups:
        click.echo("No duplicates found — registry is clean.")
        return

    click.echo(f"\nFound {len(groups)} reconciliation groups:\n")
    for i, g in enumerate(groups, 1):
        click.echo(f"  {i}. Canonical: [{g.canonical.system}] {g.canonical.code} — {g.canonical.display}")
        click.echo(f"     Rationale: {g.rationale}")
        for m in g.members:
            click.echo(f"     <- [{m.get('system','')}] {m.get('code','')} — {m.get('display','')}")
        click.echo()

    if not do_apply:
        click.echo("Dry run — use --apply to apply reconciliation.")
        return

    click.echo("Loading semantic profiles...")
    avail = scan_profile_availability(bucket, project, billing_project_id=bp)
    sem_profiles: dict[str, dict] = {}
    for fq, info in avail.items():
        if info.get("semantic"):
            s = read_sem_profile(bucket, fq, project_id=bp)
            if s:
                sem_profiles[fq] = s

    updated_reg, updated_profs = apply_reconciliation(registry, groups, sem_profiles)

    write_registry(bucket, project, updated_reg, billing_project_id=bp)
    click.echo(f"Registry updated: {len(updated_reg.entries)} entries")

    for fq, prof in updated_profs.items():
        write_sem_profile(bucket, fq, prof, project_id=bp)
    click.echo(f"Updated {len(updated_profs)} semantic profiles")
    click.echo("Reconciliation complete.")


if __name__ == "__main__":
    main()
