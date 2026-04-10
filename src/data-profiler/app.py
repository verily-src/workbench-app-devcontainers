"""
WB Data Profiler — Technical (C2a) and Semantic (C2b) profiling for BigQuery datasets.

3-tab Gradio app:
  Tab 1: Setup — project/dataset/table selection + optional context upload
  Tab 2: Technical Profile (C2a) — schema stats, validation, review, export, GCS deliver
  Tab 3: Semantic Profile (C2b) — LLM definitions/bindings/PHI, review, export, GCS deliver
"""

from __future__ import annotations

import argparse
import io
import json
import os
import tempfile
import zipfile
from typing import Optional

import gradio as gr
import pandas as pd

from bq_discovery import discover_bq_datasets, discover_bq_tables
from gcs_utils import discover_gcs_buckets, discover_gcs_folders, upload_multiple_jsons
from models import BQTableInfo, CombinedProfile, TechTableProfile, SemanticTableProfile
from prompt_engine import detect_available_model
from semantic_profiler import profile_table_semantic, revalidate_semantic
from tech_profiler import profile_table

# ── Global State ──────────────────────────────────────────────────────────────

_billing_project: Optional[str] = None
_data_projects: list[str] = []
_output_bucket: Optional[str] = None
_gemini_model: Optional[str] = None

_discovered_tables: dict[str, BQTableInfo] = {}       # fq_name -> BQTableInfo
_selected_table_names: list[str] = []

_tech_profiles: dict[str, TechTableProfile] = {}      # fq_name -> profile
_sem_profiles: dict[str, SemanticTableProfile] = {}    # fq_name -> profile


# ── CLI Args ──────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="WB Data Profiler")
    p.add_argument("--project", type=str,
                   default=os.environ.get("GCP_PROJECT_ID"),
                   help="Billing project for BQ/Vertex AI")
    p.add_argument("--data-project", type=str, nargs="+",
                   default=(os.environ.get("DATA_PROJECT_IDS", "").split()
                            if os.environ.get("DATA_PROJECT_IDS") else None),
                   help="GCP project(s) where data lives")
    p.add_argument("--output-bucket", type=str,
                   default=os.environ.get("OUTPUT_GCS_BUCKET"),
                   help="Default GCS bucket for output")
    p.add_argument("--model", type=str,
                   default=os.environ.get("GEMINI_MODEL"),
                   help="Gemini model override (default: auto-detect)")
    p.add_argument("--port", type=int,
                   default=int(os.environ.get("GRADIO_PORT", "7860")),
                   help="Gradio port")
    return p.parse_args()


# ── Tab 1: Setup Handlers ────────────────────────────────────────────────────

def _get_data_projects() -> list[str]:
    projects = list(_data_projects)
    if _billing_project and _billing_project not in projects:
        projects.insert(0, _billing_project)
    return projects


def on_refresh_datasets(data_project: str):
    """Load datasets for a project."""
    if not data_project:
        return gr.update(choices=[], value=None)
    datasets = discover_bq_datasets(data_project, _billing_project)
    return gr.update(choices=datasets, value=datasets[0] if datasets else None)


def on_refresh_tables(data_project: str, dataset: str):
    """Load tables for a dataset and return a selection checklist."""
    global _discovered_tables
    if not data_project or not dataset:
        return gr.update(choices=[], value=[])

    tables = discover_bq_tables(data_project, dataset, _billing_project)
    _discovered_tables = {}
    choices = []
    for t in tables:
        label = f"{t.table_id}  ({t.row_count:,} rows, {len(t.columns)} cols)" if t.row_count else t.table_id
        _discovered_tables[t.fq_name] = t
        choices.append((label, t.fq_name))

    return gr.update(choices=choices, value=[])


def on_select_tables(selected_fq_names: list[str]):
    """Store selected tables."""
    global _selected_table_names
    _selected_table_names = selected_fq_names
    if not selected_fq_names:
        return "No tables selected."
    return f"Selected {len(selected_fq_names)} table(s): {', '.join(t.split('.')[-1] for t in selected_fq_names)}"


# ── Tab 2: Technical Profiling Handlers ───────────────────────────────────────

def on_run_tech_profiling():
    """Run C2a technical profiling on all selected tables."""
    global _tech_profiles
    if not _selected_table_names:
        return (
            pd.DataFrame(),
            "No tables selected. Go to Setup tab and select tables first.",
            "{}",
        )

    all_rows = []
    all_validation_lines = []

    for fq_name in _selected_table_names:
        table_info = _discovered_tables.get(fq_name)
        if not table_info:
            all_validation_lines.append(f"**{fq_name}**: table info not found")
            continue

        profile = profile_table(table_info, _billing_project)
        _tech_profiles[fq_name] = profile

        for cp in profile.columns:
            row = cp.to_review_row()
            row["Table"] = fq_name.split(".")[-1]
            all_rows.append(row)

        v = profile.validation
        header = f"**{fq_name.split('.')[-1]}** — {v.status.upper()}"
        if v.anomalies:
            header += f"\n  Anomalies: " + "; ".join(v.anomalies)
        if v.warnings:
            header += f"\n  Warnings: " + "; ".join(v.warnings)
        all_validation_lines.append(header)

    cols_order = ["Table", "Column", "Type", "Nullable", "Nulls", "Distinct",
                  "Top Values", "Stats", "Pattern", "Anomalies"]
    df = pd.DataFrame(all_rows, columns=cols_order) if all_rows else pd.DataFrame()
    validation_md = "\n\n".join(all_validation_lines) if all_validation_lines else "No results."

    json_preview = _build_tech_json_preview()

    return df, validation_md, json_preview


def _build_tech_json_preview() -> str:
    if not _tech_profiles:
        return "{}"
    if len(_tech_profiles) == 1:
        return next(iter(_tech_profiles.values())).to_json_string()
    combined = {name: p.to_json_dict() for name, p in _tech_profiles.items()}
    return json.dumps(combined, indent=2)


def on_export_tech_json():
    """Export technical profiles as a downloadable JSON file."""
    if not _tech_profiles:
        return None
    if len(_tech_profiles) == 1:
        name, profile = next(iter(_tech_profiles.items()))
        filename = f"tech_profile_{name.split('.')[-1]}.json"
        path = os.path.join(tempfile.gettempdir(), filename)
        with open(path, "w") as f:
            f.write(profile.to_json_string())
        return path

    path = os.path.join(tempfile.gettempdir(), "tech_profiles.zip")
    with zipfile.ZipFile(path, "w") as zf:
        for name, profile in _tech_profiles.items():
            fname = f"tech_profile_{name.replace('.', '_')}.json"
            zf.writestr(fname, profile.to_json_string())
    return path


def on_export_tech_csv():
    """Export technical profiles as CSV."""
    if not _tech_profiles:
        return None
    all_rows = []
    for fq_name, profile in _tech_profiles.items():
        for cp in profile.columns:
            row = cp.to_review_row()
            row["Table"] = fq_name
            all_rows.append(row)
    if not all_rows:
        return None
    df = pd.DataFrame(all_rows)
    path = os.path.join(tempfile.gettempdir(), "tech_profiles.csv")
    df.to_csv(path, index=False)
    return path


def on_tech_gcs_refresh_buckets():
    project = _billing_project or (_data_projects[0] if _data_projects else "")
    if not project:
        return gr.update(choices=[], value=None)
    buckets = discover_gcs_buckets(project)
    return gr.update(choices=buckets, value=buckets[0] if buckets else None)


def on_tech_gcs_refresh_folders(bucket: str):
    if not bucket:
        return gr.update(choices=[], value=None)
    folders = discover_gcs_folders(bucket)
    choices = ["(root)"] + list(folders)
    return gr.update(choices=choices, value="(root)")


def on_tech_gcs_upload(bucket: str, folder: str):
    if not _tech_profiles:
        return "No technical profiles to upload."
    if not bucket:
        return "Select a GCS bucket first."
    base_path = "" if folder == "(root)" else folder
    files = {}
    for name, profile in _tech_profiles.items():
        fname = f"tech_profile_{name.replace('.', '_')}.json"
        files[fname] = profile.to_json_dict()

    project = _billing_project or (_data_projects[0] if _data_projects else None)
    try:
        uris = upload_multiple_jsons(bucket, base_path, files, project)
        return f"Uploaded {len(uris)} file(s):\n" + "\n".join(f"  {u}" for u in uris)
    except Exception as e:
        return f"Upload failed: {e}"


# ── Tab 3: Semantic Profiling Handlers ────────────────────────────────────────

def on_run_semantic_profiling():
    """Run C2b semantic profiling on all tables that have C2a results."""
    global _sem_profiles
    if not _tech_profiles:
        return (
            pd.DataFrame(),
            "Run Technical Profiling (Tab 2) first.",
            "{}",
        )

    model = _gemini_model
    if not model:
        model = detect_available_model(_billing_project)

    all_rows = []
    all_validation_lines = []

    for fq_name, tech_prof in _tech_profiles.items():
        sem_prof = profile_table_semantic(
            tech_profile=tech_prof,
            model_name=model,
            project_id=_billing_project,
        )
        _sem_profiles[fq_name] = sem_prof

        for sc in sem_prof.columns:
            row = sc.to_review_row()
            row["Table"] = fq_name.split(".")[-1]
            all_rows.append(row)

        v = sem_prof.validation
        header = f"**{fq_name.split('.')[-1]}** — {v.status.upper()}"
        if v.issues:
            header += "\n  Issues: " + "; ".join(v.issues)
        all_validation_lines.append(header)

    cols_order = ["Table", "Column", "Definition", "Terminology Bindings",
                  "Sensitivity", "Join Paths", "Confidence"]
    df = pd.DataFrame(all_rows, columns=cols_order) if all_rows else pd.DataFrame()
    validation_md = "\n\n".join(all_validation_lines) if all_validation_lines else "No results."
    json_preview = _build_sem_json_preview()

    return df, validation_md, json_preview


def _build_sem_json_preview() -> str:
    if not _sem_profiles:
        return "{}"
    if len(_sem_profiles) == 1:
        return next(iter(_sem_profiles.values())).to_json_string()
    combined = {name: p.to_json_dict() for name, p in _sem_profiles.items()}
    return json.dumps(combined, indent=2)


def on_run_revalidation():
    """Re-run LLM-as-Judge on semantic profiles."""
    if not _sem_profiles or not _tech_profiles:
        return "No profiles to validate."

    model = _gemini_model or detect_available_model(_billing_project)
    lines = []
    for fq_name, sem_prof in _sem_profiles.items():
        tech_prof = _tech_profiles.get(fq_name)
        if not tech_prof:
            continue
        result = revalidate_semantic(sem_prof, tech_prof, model, _billing_project)
        sem_prof.validation = result
        header = f"**{fq_name.split('.')[-1]}** — {result.status.upper()}"
        if result.issues:
            header += "\n  Issues: " + "; ".join(result.issues)
        lines.append(header)

    return "\n\n".join(lines) if lines else "Validation complete — no issues."


def on_export_sem_json():
    if not _sem_profiles:
        return None
    if len(_sem_profiles) == 1:
        name, profile = next(iter(_sem_profiles.items()))
        filename = f"semantic_profile_{name.split('.')[-1]}.json"
        path = os.path.join(tempfile.gettempdir(), filename)
        with open(path, "w") as f:
            f.write(profile.to_json_string())
        return path

    path = os.path.join(tempfile.gettempdir(), "semantic_profiles.zip")
    with zipfile.ZipFile(path, "w") as zf:
        for name, profile in _sem_profiles.items():
            fname = f"semantic_profile_{name.replace('.', '_')}.json"
            zf.writestr(fname, profile.to_json_string())
    return path


def on_export_sem_csv():
    if not _sem_profiles:
        return None
    all_rows = []
    for fq_name, profile in _sem_profiles.items():
        for sc in profile.columns:
            row = sc.to_review_row()
            row["Table"] = fq_name
            all_rows.append(row)
    if not all_rows:
        return None
    df = pd.DataFrame(all_rows)
    path = os.path.join(tempfile.gettempdir(), "semantic_profiles.csv")
    df.to_csv(path, index=False)
    return path


def on_sem_gcs_refresh_buckets():
    project = _billing_project or (_data_projects[0] if _data_projects else "")
    if not project:
        return gr.update(choices=[], value=None)
    buckets = discover_gcs_buckets(project)
    return gr.update(choices=buckets, value=buckets[0] if buckets else None)


def on_sem_gcs_refresh_folders(bucket: str):
    if not bucket:
        return gr.update(choices=[], value=None)
    folders = discover_gcs_folders(bucket)
    choices = ["(root)"] + list(folders)
    return gr.update(choices=choices, value="(root)")


def on_sem_gcs_upload(bucket: str, folder: str):
    if not _sem_profiles:
        return "No semantic profiles to upload."
    if not bucket:
        return "Select a GCS bucket first."
    base_path = "" if folder == "(root)" else folder
    files = {}
    for name, profile in _sem_profiles.items():
        fname = f"semantic_profile_{name.replace('.', '_')}.json"
        files[fname] = profile.to_json_dict()

    project = _billing_project or (_data_projects[0] if _data_projects else None)
    try:
        uris = upload_multiple_jsons(bucket, base_path, files, project)
        return f"Uploaded {len(uris)} file(s):\n" + "\n".join(f"  {u}" for u in uris)
    except Exception as e:
        return f"Upload failed: {e}"


# ── UI Builder ────────────────────────────────────────────────────────────────

def build_ui():
    data_projects = _get_data_projects()

    with gr.Blocks(title="WB Data Profiler") as app:
        gr.Markdown("# WB Data Profiler\nTechnical (C2a) and Semantic (C2b) profiling for BigQuery datasets.")

        # ── Tab 1: Setup ──────────────────────────────────────────────
        with gr.Tab("Setup"):
            gr.Markdown("### Select Data Source")
            with gr.Row():
                dd_project = gr.Dropdown(
                    choices=data_projects,
                    value=data_projects[0] if data_projects else None,
                    label="Data Project",
                    interactive=True,
                )
                dd_dataset = gr.Dropdown(choices=[], label="Dataset", interactive=True)
                btn_refresh_ds = gr.Button("Refresh Datasets", size="sm")

            btn_refresh_ds.click(on_refresh_datasets, inputs=[dd_project], outputs=[dd_dataset])

            btn_refresh_tables = gr.Button("Load Tables")
            cbg_tables = gr.CheckboxGroup(choices=[], label="Select Tables to Profile")
            txt_selection = gr.Markdown("No tables selected.")

            btn_refresh_tables.click(
                on_refresh_tables, inputs=[dd_project, dd_dataset], outputs=[cbg_tables]
            )
            cbg_tables.change(on_select_tables, inputs=[cbg_tables], outputs=[txt_selection])

            gr.Markdown("### Optional Context for Semantic Profiling")
            file_context = gr.File(
                label="Upload context files (data dictionary, schema.yml, study protocol)",
                file_types=[".csv", ".yml", ".yaml", ".txt", ".md", ".json"],
                file_count="multiple",
            )

        # ── Tab 2: Technical Profile ──────────────────────────────────
        with gr.Tab("Technical Profile (C2a)"):
            gr.Markdown("### Run Technical Profiling")
            gr.Markdown(
                "Schema introspection, column stats (NULL %, distinct counts, distributions), "
                "coded-value detection, pattern recognition, and structural validation. No LLM."
            )
            btn_run_tech = gr.Button("Run Technical Profiling", variant="primary")

            gr.Markdown("---\n### Review")
            tech_df = gr.Dataframe(
                label="Column Profiles",
                interactive=True,
                wrap=True,
            )
            tech_validation_md = gr.Markdown("*Run profiling to see results.*")

            gr.Markdown("### JSON Preview")
            tech_json_preview = gr.Code(language="json", label="Technical Profile JSON", interactive=False)

            btn_run_tech.click(
                on_run_tech_profiling,
                outputs=[tech_df, tech_validation_md, tech_json_preview],
            )

            gr.Markdown("---\n### Export")
            with gr.Row():
                btn_export_tech_json = gr.Button("Export JSON")
                btn_export_tech_csv = gr.Button("Export CSV")
            tech_download = gr.File(label="Download", interactive=False)

            btn_export_tech_json.click(on_export_tech_json, outputs=[tech_download])
            btn_export_tech_csv.click(on_export_tech_csv, outputs=[tech_download])

            gr.Markdown("---\n### Deliver to GCS")
            with gr.Row():
                tech_gcs_bucket = gr.Dropdown(choices=[], label="GCS Bucket", interactive=True)
                btn_tech_gcs_refresh = gr.Button("Refresh Buckets", size="sm")
            tech_gcs_folder = gr.Dropdown(choices=["(root)"], label="Folder", interactive=True)
            btn_tech_gcs_upload = gr.Button("Upload to GCS")
            tech_gcs_status = gr.Markdown("")

            btn_tech_gcs_refresh.click(on_tech_gcs_refresh_buckets, outputs=[tech_gcs_bucket])
            tech_gcs_bucket.change(on_tech_gcs_refresh_folders, inputs=[tech_gcs_bucket], outputs=[tech_gcs_folder])
            btn_tech_gcs_upload.click(
                on_tech_gcs_upload, inputs=[tech_gcs_bucket, tech_gcs_folder], outputs=[tech_gcs_status]
            )

        # ── Tab 3: Semantic Profile ───────────────────────────────────
        with gr.Tab("Semantic Profile (C2b)"):
            gr.Markdown("### Run Semantic Profiling")
            gr.Markdown(
                "LLM-driven: field definitions, terminology bindings (LOINC/ICD-10/SNOMED CT), "
                "PHI/PII classification, join path suggestions, and per-field confidence scores. "
                "Requires Technical Profiling (Tab 2) to be run first."
            )
            btn_run_sem = gr.Button("Run Semantic Profiling", variant="primary")

            gr.Markdown("---\n### Review")
            sem_df = gr.Dataframe(
                label="Semantic Profiles",
                interactive=True,
                wrap=True,
            )
            sem_validation_md = gr.Markdown("*Run profiling to see results.*")

            btn_revalidate = gr.Button("Re-validate (LLM-as-Judge)")
            btn_revalidate.click(on_run_revalidation, outputs=[sem_validation_md])

            gr.Markdown("### JSON Preview")
            sem_json_preview = gr.Code(language="json", label="Semantic Profile JSON", interactive=False)

            btn_run_sem.click(
                on_run_semantic_profiling,
                outputs=[sem_df, sem_validation_md, sem_json_preview],
            )

            gr.Markdown("---\n### Export")
            with gr.Row():
                btn_export_sem_json = gr.Button("Export JSON")
                btn_export_sem_csv = gr.Button("Export CSV")
            sem_download = gr.File(label="Download", interactive=False)

            btn_export_sem_json.click(on_export_sem_json, outputs=[sem_download])
            btn_export_sem_csv.click(on_export_sem_csv, outputs=[sem_download])

            gr.Markdown("---\n### Deliver to GCS")
            with gr.Row():
                sem_gcs_bucket = gr.Dropdown(choices=[], label="GCS Bucket", interactive=True)
                btn_sem_gcs_refresh = gr.Button("Refresh Buckets", size="sm")
            sem_gcs_folder = gr.Dropdown(choices=["(root)"], label="Folder", interactive=True)
            btn_sem_gcs_upload = gr.Button("Upload to GCS")
            sem_gcs_status = gr.Markdown("")

            btn_sem_gcs_refresh.click(on_sem_gcs_refresh_buckets, outputs=[sem_gcs_bucket])
            sem_gcs_bucket.change(on_sem_gcs_refresh_folders, inputs=[sem_gcs_bucket], outputs=[sem_gcs_folder])
            btn_sem_gcs_upload.click(
                on_sem_gcs_upload, inputs=[sem_gcs_bucket, sem_gcs_folder], outputs=[sem_gcs_status]
            )

    return app


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = parse_args()

    _billing_project = args.project
    _data_projects = args.data_project or []
    _output_bucket = args.output_bucket
    _gemini_model = args.model

    print(f"  Billing project: {_billing_project}")
    print(f"  Data projects:   {_data_projects}")
    print(f"  Output bucket:   {_output_bucket}")
    print(f"  Gemini model:    {_gemini_model or '<auto-detect>'}")

    app = build_ui()
    app.launch(
        server_name="0.0.0.0",
        server_port=args.port,
        show_error=True,
        theme=gr.themes.Soft(),
    )
