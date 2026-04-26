"""
Configuration management for the Dataset Explorer Template.
Discovers datasets from Workbench environment variables and automounted resources.
"""
import os
from pathlib import Path
from typing import Dict, List, Optional
from pydantic import BaseModel


class WorkbenchResource(BaseModel):
    """Represents a Workbench resource discovered from environment variables"""
    name: str
    type: str  # 'bq-dataset', 'gcs-bucket', 'git-repo', etc.
    path: str  # gs:// path or project.dataset format
    is_controlled: bool = False  # True if workspace-created (read-write), False if referenced (read-only)
    mounted_path: Optional[Path] = None  # Path in $HOME/workspace/ if automounted


class DatasetDiscovery:
    """Discovers datasets from Workbench environment and filesystem"""

    def __init__(self):
        self.workspace_dir = Path.home() / "workspace"
        self.resources: Dict[str, WorkbenchResource] = {}
        self._discover_resources()

    def _discover_resources(self):
        """Scan environment variables for WORKBENCH_* resources"""
        for key, value in os.environ.items():
            if key.startswith("WORKBENCH_"):
                resource_name = key.replace("WORKBENCH_", "").lower()
                resource_type = self._infer_resource_type(value)

                # Check if resource is automounted
                mounted_path = None
                if self.workspace_dir.exists():
                    potential_mount = self.workspace_dir / resource_name
                    if potential_mount.exists():
                        mounted_path = potential_mount

                self.resources[resource_name] = WorkbenchResource(
                    name=resource_name,
                    type=resource_type,
                    path=value,
                    mounted_path=mounted_path
                )

    def _infer_resource_type(self, path: str) -> str:
        """Infer resource type from path format"""
        if path.startswith("gs://"):
            return "gcs-bucket"
        elif "." in path and not path.startswith("http"):
            # Format like project.dataset
            return "bq-dataset"
        elif path.startswith("git@") or path.startswith("https://"):
            return "git-repo"
        else:
            return "unknown"

    def get_bigquery_datasets(self) -> List[WorkbenchResource]:
        """Get all BigQuery datasets"""
        return [r for r in self.resources.values() if r.type == "bq-dataset"]

    def get_controlled_buckets(self) -> List[WorkbenchResource]:
        """Get controlled (workspace-created, read-write) GCS buckets"""
        # Controlled resources are typically prefixed with workspace ID
        return [r for r in self.resources.values()
                if r.type == "gcs-bucket" and r.is_controlled]

    def get_export_bucket(self, risk_tier: str = "standard") -> Optional[WorkbenchResource]:
        """Get appropriate export bucket based on risk tier"""
        # Look for tier-specific bucket first
        bucket_name = f"{risk_tier}_export"
        if bucket_name in self.resources:
            return self.resources[bucket_name]

        # Fall back to any controlled bucket
        controlled = self.get_controlled_buckets()
        return controlled[0] if controlled else None

    def scan_automounted_datasets(self) -> List[Path]:
        """Scan $HOME/workspace/ for automounted data directories"""
        if not self.workspace_dir.exists():
            return []

        datasets = []
        for item in self.workspace_dir.iterdir():
            if item.is_dir():
                # Check for common data file patterns
                has_data = any([
                    list(item.glob("*.csv")),
                    list(item.glob("*.parquet")),
                    list(item.glob("*.json")),
                    list(item.glob("*.tsv"))
                ])
                if has_data:
                    datasets.append(item)

        return datasets


class AppConfig(BaseModel):
    """Application configuration"""
    app_project: str  # Current Workbench project (for BigQuery client auth)
    discovery: DatasetDiscovery

    # Export configuration
    enable_exports: bool = True
    require_validation: bool = True  # Require validator approval before export

    # Compliance configuration
    run_compliance_checks: bool = True
    compliance_checks: List[str] = [
        "data_completeness",
        "sample_size_minimum",
        "demographic_representation"
    ]

    @classmethod
    def from_environment(cls):
        """Create config from Workbench environment"""
        # Get current project from gcloud or environment
        app_project = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")

        if not app_project:
            # Try to get from gcloud config
            import subprocess
            try:
                result = subprocess.run(
                    ["gcloud", "config", "get-value", "project"],
                    capture_output=True,
                    text=True
                )
                app_project = result.stdout.strip()
            except:
                app_project = "unknown-project"

        return cls(
            app_project=app_project,
            discovery=DatasetDiscovery()
        )


# Global configuration instance
config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """Get or create global configuration"""
    global config
    if config is None:
        config = AppConfig.from_environment()
    return config
